"""
ABSTRACTION DU BACKEND LLM — Ollama local ou cloud (Together), au choix via
config.LLM_BACKEND, sans toucher au reste du pipeline.
================================================================================
Contexte (2026-08-07, checklist.md) : Ollama en local sur CPU dégrade sous
charge soutenue (~17 -> <7 tok/s après ~50 appels séquentiels, cause non
identifiée) et Pass 3 de deep_analysis timeout régulièrement — bloquant pour
une démo live devant la banque (25 août). Exception explicite accordée au
sprint "pas de nouveau modèle / pas de fix perf avant le 25" pour ce
chantier précis.

Une seule fonction publique : call_llm(). Les deux appelants (llm_confirm.py,
deep_analysis.py) avaient chacun leur propre appel HTTP direct à Ollama
(dupliqué) — ce module centralise l'appel réseau, pas la logique métier
(cache disque, parsing, message de repli) qui reste dans chaque module
appelant, inchangée sur ce point.

CHOIX: call_llm() retourne None en cas d'échec (jamais d'exception) — pas
"" comme envisagé initialement — pour matcher le contrat déjà établi de
l'ex-deep_analysis._call_ollama (None = distinct d'une réponse vide
confirmée). Fail-open partout : timeout, clé API manquante/invalide,
rate-limit, backend down -> log un warning, retourne None. Chaque appelant
définit son propre repli (confirm_risk -> True, summarize_passage -> extrait
tronqué, etc.), ce module ne décide pas du fallback métier.

CHOIX: LLM_BACKEND par défaut "ollama" (voir config.py) — le backend cloud
est opt-in via variable d'environnement, pas un nouveau défaut silencieux
pour tous les déploiements existants.
"""

import logging
import threading
import time

import requests

import config

logger = logging.getLogger(__name__)

_rate_lock = threading.Lock()
_last_call_time = 0.0

# Backends qui passent par une API compatible OpenAI (/v1/chat/completions).
# "ollama" n'y figure pas : appel direct à /api/generate, format propre à
# Ollama, déjà existant avant ce chantier.
_CLOUD_BACKENDS = {
    "together": {"base_url": "https://api.together.xyz/v1", "api_key_attr": "TOGETHER_API_KEY"},
}


def _rate_limit():
    """Espace les appels aux backends cloud pour rester sous
    config.LLM_RATE_LIMIT req/s. Ollama local n'a pas de rate limit externe
    à respecter — seuls les backends de _CLOUD_BACKENDS passent par ici."""
    global _last_call_time
    min_interval = 1.0 / config.LLM_RATE_LIMIT if config.LLM_RATE_LIMIT > 0 else 0
    with _rate_lock:
        elapsed = time.time() - _last_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_call_time = time.time()


def _resolve_options(config_key, temperature):
    """Traduit config.OLLAMA_CONFIGS[config_key] (num_predict/num_ctx) en
    paramètres neutres (max_tokens/num_ctx). config_key=None -> AUCUN
    plafond de longueur de réponse (max_tokens=None) — obligatoire pour la
    Pass 2 de deep_analysis.py, qui appelle call_llm() sans config_key
    précisément pour ne jamais plafonner num_predict (cf. son commentaire
    Tier 0 : le modèle se répète avant de conclure, un plafond tronquerait
    la réponse avant la dernière répétition et ferait régresser ce bug déjà
    corrigé)."""
    if config_key is None:
        return {"temperature": temperature, "max_tokens": None, "num_ctx": None}
    cfg = config.OLLAMA_CONFIGS[config_key]
    return {"temperature": temperature, "max_tokens": cfg["num_predict"], "num_ctx": cfg["num_ctx"]}


def _call_ollama(prompt, model, options, timeout):
    ollama_options = {"temperature": options["temperature"]}
    if options["max_tokens"] is not None:
        ollama_options["num_predict"] = options["max_tokens"]
    if options["num_ctx"] is not None:
        ollama_options["num_ctx"] = options["num_ctx"]

    resp = requests.post(
        f"{config.OLLAMA_HOST}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": ollama_options,
            "keep_alive": -1,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def _call_openai_compatible(prompt, model, base_url, api_key, options, timeout):
    # Import local : openai n'est requis que si un backend cloud est utilisé
    # (cf. requirements.txt) — un déploiement 100% Ollama n'a pas besoin de
    # cette dépendance installée pour fonctionner.
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    kwargs = {"temperature": options["temperature"]}
    if options["max_tokens"] is not None:
        kwargs["max_tokens"] = options["max_tokens"]

    # BUG CORRIGÉ (2026-08-08, smoke test réel Together/Qwen3.5-9B) : Qwen3
    # raisonne par défaut même sur ce modèle "9B" sans badge "deep thinking"
    # dans le dashboard Together — mesuré : finish_reason="length" à 300
    # tokens sans jamais atteindre le contenu final, tout dans
    # response.choices[0].message.reasoning_content, content="" (message.content
    # vide). Avec confirm_risk (max_tokens=5), ça donnait 100% de réponses
    # vides -> fail-open permanent (True partout), silencieux car pas
    # d'exception. chat_template_kwargs.enable_thinking=False (convention
    # vLLM/Qwen3, pas un standard OpenAI) supprime le raisonnement : mesuré
    # ensuite content="RISK", 3 tokens, 1.6s. Gate sur "qwen" dans le nom du
    # modèle — ce paramètre n'a pas de sens pour un modèle d'une autre
    # famille (Gemma, GPT-OSS) et il n'est pas garanti qu'il soit inoffensif
    # de l'envoyer quand même.
    if "qwen" in model.lower():
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        timeout=timeout,
        **kwargs,
    )
    return (response.choices[0].message.content or "").strip()


def _dispatch(backend, prompt, model, options, timeout):
    """Route l'appel vers le bon adaptateur. Lève une exception en cas
    d'échec (réseau, clé manquante, HTTP non-2xx, ...) — c'est call_llm() qui
    attrape et transforme ça en fail-open, pas cette fonction."""
    if backend == "ollama":
        return _call_ollama(prompt, model, options, timeout)
    if backend in _CLOUD_BACKENDS:
        spec = _CLOUD_BACKENDS[backend]
        api_key = getattr(config, spec["api_key_attr"], "")
        if not api_key:
            raise RuntimeError(f"{spec['api_key_attr']} manquante pour LLM_BACKEND={backend!r}")
        _rate_limit()
        return _call_openai_compatible(prompt, model, spec["base_url"], api_key, options, timeout)
    raise ValueError(f"LLM_BACKEND inconnu : {backend!r}")


def call_llm(prompt, config_key=None, temperature=0.0, timeout=60.0):
    """
    Envoie `prompt` au backend LLM actif (config.LLM_BACKEND) et retourne le
    texte de réponse (stripped), ou None en cas d'échec — jamais d'exception,
    fail-open (cf. docstring du module).

    config_key : une clé de config.OLLAMA_CONFIGS ("confirm_risk",
    "summarize", "recommend", "deep_extract", "deep_synthesize") pour
    appliquer le plafond de longueur de réponse associé, ou None pour ne
    PAS plafonner.
    """
    options = _resolve_options(config_key, temperature)
    backend = config.LLM_BACKEND

    try:
        return _dispatch(backend, prompt, config.LLM_MODEL, options, timeout)
    except Exception as e:
        logger.warning(f"llm_backend: backend [{backend}] injoignable (config_key={config_key!r}) : {e}")

    fallback = config.LLM_FALLBACK
    if fallback and fallback != backend:
        fallback_model = config.LLM_MODEL_BY_BACKEND.get(fallback, config.LLM_MODEL)
        try:
            return _dispatch(fallback, prompt, fallback_model, options, timeout)
        except Exception as e:
            logger.warning(f"llm_backend: fallback [{fallback}] injoignable aussi (config_key={config_key!r}) : {e}")

    return None
