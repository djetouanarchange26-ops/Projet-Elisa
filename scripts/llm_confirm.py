"""
UTILITAIRES LLM — confirmation de polarité + résumé de passages
========================================================================
Deux fonctions, même infra Ollama/cache/fail-open :
  - confirm_risk()      : filtre les faux positifs de flag_scores/detected_signals
  - summarize_passage()  : résumé court d'un passage historique (Historical
                            Similar Cases, app.py) à la place d'un extrait
                            brut tronqué en plein milieu de phrase

CONFIRMATION LLM DE POLARITÉ — filtre les faux positifs de flag_scores
========================================================================
Constat (2026-07-25, voir checklist.md "Chantier ouvert") : un chunk qui
MENTIONNE un sujet à risque (ESAP, biodiversité, communauté...) matche les
mêmes passages historiques FAISS que ce sujet soit traité comme un problème
("ESAP action plan shows delays") ou comme résolu/positif ("ESAP actions
completed ahead of schedule") — la similarité d'embedding ne capture pas la
polarité, seulement le sujet. Vérifié en reproduisant le même écart avec
deux modèles d'embedding différents (MiniLM et mpnet) : ce n'est pas une
limite de capacité d'un modèle en particulier.

Ce module comble ce trou pour les chunks du document interrogé (pas ceux du
corpus historique, déjà nettoyés par annote.py) : pour un chunk où
signals.flags_mentioned_in_text() repère un flag candidat (mot-clé), on
demande à un LLM local (Ollama) de confirmer si le chunk décrit vraiment un
risque, avant de le laisser contribuer au score de ce flag.

CHOIX: un appel LLM par (chunk, flag candidat) — pas systématique sur tous
les chunks — signals.py sert de filtre regex bon marché en amont pour ne
solliciter le LLM que sur les cas topicalement pertinents.
CHOIX: qwen3:4b-instruct sur Ollama, pas qwen3:4b — la variante "hybride" de
Qwen3 insiste pour produire des centaines de tokens de raisonnement interne
même avec think:false ou le suffixe /no_think dans le prompt (mesuré :
25-95s/appel contre ~2s/appel à chaud pour -instruct, qui répond directement
en 1 mot).
Le backend LLM (Ollama local ou cloud) et le modèle actif sont résolus par
llm_backend.py via config.LLM_BACKEND/config.LLM_MODEL — voir ce module pour
le détail. Fail-open partout : si le backend est injoignable, confirm_risk()
retombe sur True — comportement identique à avant l'ajout du filtre — plutôt
que de faire planter l'analyse.
"""

import hashlib
import json
import logging
import threading
from pathlib import Path

import config
import llm_backend

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent.parent
CACHE_PATH = BASE / "models" / "llm_confirm_cache.json"

FLAG_LABELS = {
    1: "community opposition, involuntary displacement, or stakeholder/indigenous rights issues",
    2: "pollution, contamination, spills, or environmental monitoring exceedances",
    3: "biodiversity threats or non-compliance with IFC Performance Standards / ESAP delays",
}

_cache = None
_cache_lock = threading.Lock()
_llm_unreachable_warned = False


def _warn_llm_unreachable(usage):
    """N'affiche le warning qu'une fois par process (évite de noyer la
    console sur un run avec ~50-80 appels LLM si le backend est down)."""
    global _llm_unreachable_warned
    if not _llm_unreachable_warned:
        logger.warning(f"LLM {usage} injoignable — repli fail-open.")
        _llm_unreachable_warned = True


def _load_cache():
    global _cache
    if _cache is not None:
        return _cache
    if CACHE_PATH.exists():
        _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    else:
        _cache = {}
    return _cache


def _save_cache():
    # FRAGILE: appelé sous _cache_lock — json.dumps(_cache) prend un snapshot
    # cohérent même si un autre thread modifie _cache juste après le dump.
    CACHE_PATH.write_text(json.dumps(_cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _cache_key(chunk_text, flag_num):
    # FRAGILE: la clé inclut FLAG_LABELS[flag_num] — si la définition d'un
    # flag change, le cache s'invalide automatiquement pour ce flag au lieu
    # de servir un jugement basé sur une ancienne définition.
    # CHANTIER LLM BACKEND (2026-08-07) : inclut aussi backend+modèle actifs
    # — une réponse Together/Qwen3.5-9B ne doit jamais être servie comme si
    # elle venait d'Ollama/qwen3:4b-instruct (ou l'inverse). Même logique
    # d'invalidation que pour la définition du flag ci-dessus.
    raw = f"{config.LLM_BACKEND}:{config.LLM_MODEL}:{flag_num}:{FLAG_LABELS[flag_num]}:{chunk_text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def flush_cache():
    """Force l'écriture du cache sur disque. À appeler explicitement quand
    confirm_risk(..., save=False) a été utilisé (voir warm_llm_cache.py)."""
    with _cache_lock:
        _save_cache()


def confirm_risk(chunk_text, flag_num, timeout=60, save=True):
    """
    Retourne True si le LLM confirme que `chunk_text` décrit un risque réel
    pour `flag_num` (1/2/3), False s'il décrit une situation conforme,
    résolue ou positive sur ce même sujet.

    Fail-open : si Ollama est injoignable ou répond de façon inattendue,
    retourne True (comportement identique à avant l'ajout de ce filtre)
    plutôt que de faire planter l'analyse. Le warning ne s'affiche qu'une
    fois par process pour ne pas noyer la console.

    Thread-safe : voir warm_llm_cache.py, qui appelle cette fonction depuis
    plusieurs threads pour préchauffer le cache en parallèle. FRAGILE:
    limiter à ~4 threads — mesuré empiriquement qu'au-delà (16 threads
    testés), le débit se dégrade progressivement sur une charge soutenue
    (RAM/contexte limités sur ce CPU) jusqu'à dépasser `timeout`, faisant
    échouer silencieusement les appels (fail-open) sans jamais remplir le
    cache. Voir checklist.md pour le détail de cette régression.

    save : si False, le résultat est mis en cache en mémoire mais PAS
    persisté sur disque immédiatement — l'appelant doit appeler
    flush_cache() périodiquement (voir warm_llm_cache.py). Évite qu'une
    réécriture du fichier JSON entier sous _cache_lock à CHAQUE appel ne
    devienne un point de contention entre threads sur un run massif.
    """
    key = _cache_key(chunk_text, flag_num)
    with _cache_lock:
        cache = _load_cache()
        if key in cache:
            return cache[key]

    prompt = (
        "Passage from an ESG/environmental-social due diligence document:\n"
        f"\"{chunk_text}\"\n\n"
        f"Does this passage describe an ACTUAL problem related to "
        f"{FLAG_LABELS[flag_num]}, or does it describe compliance, a "
        f"resolved issue, or a positive status on that same topic?\n"
        "Answer with exactly one word: RISK or CLEAN."
    )

    response = llm_backend.call_llm(prompt, config_key="confirm_risk", temperature=0, timeout=timeout)
    if response is None:
        _warn_llm_unreachable("de confirmation — filtre polarité désactivé")
        return True
    result = response.strip().upper().startswith("RISK")

    with _cache_lock:
        cache[key] = result
        if save:
            _save_cache()
    return result


def summarize_passage(text, max_words=30, timeout=60, save=True):
    """
    Résume `text` (un passage historique du corpus, ~175 mots) en une phrase
    courte et factuelle — remplace l'extrait brut affiché dans "Historical
    Similar Cases" (app.py), aujourd'hui tronqué à 220 caractères en plein
    milieu de phrase, pas toujours lisible.

    Fail-open : si Ollama est injoignable, retourne `text` tronqué à 220
    caractères (comportement d'avant l'ajout du résumé) plutôt que de
    planter l'affichage.

    CHOIX: cache séparé de celui de confirm_risk (clé construite localement,
    pas via _cache_key) — même fichier disque (models/llm_confirm_cache.json),
    préfixe "summarize:" pour éviter toute collision avec les clés de
    confirm_risk (qui n'ont jamais ce préfixe). Préfixe aussi backend+modèle,
    même raison que dans _cache_key (2026-08-07, cf. plus haut dans le fichier).
    """
    key = hashlib.sha256(f"{config.LLM_BACKEND}:{config.LLM_MODEL}:summarize:{text}".encode("utf-8")).hexdigest()
    with _cache_lock:
        cache = _load_cache()
        if key in cache:
            return cache[key]

    fallback = text[:220].strip() + "…"
    prompt = (
        "Summarize the following passage from an ESG/environmental-social "
        f"due diligence document in ONE short factual sentence (max {max_words} "
        "words) describing what it specifically covers. No generic filler, "
        "no preamble like \"This passage describes\" — go straight to the content.\n\n"
        f"Passage:\n\"{text}\"\n\nSummary:"
    )

    response = llm_backend.call_llm(prompt, config_key="summarize", temperature=0.2, timeout=timeout)
    summary = response.strip().strip('"') if response else ""
    if not summary:
        _warn_llm_unreachable("de résumé — repli sur extrait brut")
        return fallback

    with _cache_lock:
        cache[key] = summary
        if save:
            _save_cache()
    return summary


def generate_recommendation(risk_grade, detected_signals, timeout=60, save=True):
    """
    Recommandation credit committee en 1 phrase, basée sur les signaux
    RÉELLEMENT détectés dans le document (pas un template fixe par grade,
    voir RECOMMENDATION_BY_GRADE dans app.py — ancien comportement).

    CHANTIER SIMPLIFICATION PIPELINE (2026-08-08) : signature adaptée pour
    ne plus prendre probability_12m — le Cox est retiré (model.py), analyze.py
    ne calcule plus de probabilité d'événement, juste un risk_grade par
    règle. Ce module n'est pas concerné par le retrait du Cox/reranker en
    lui-même (aucun lien), mais cette fonction dépendait directement de
    probability_12m dans son prompt — sans cet ajustement, l'appel depuis
    analyze.py planterait (`None:.0%`).

    Retourne None si le backend LLM est injoignable ou répond vide —
    l'appelant (analyze.py/app.py) retombe alors sur le template par grade
    (fail-open), plutôt qu'un texte LLM à moitié fiable.
    """
    signal_names = sorted({s["signal"] for s in detected_signals})[:6]  # borne le prompt
    cache_input = f"{risk_grade}:{signal_names}"
    key = hashlib.sha256(f"{config.LLM_BACKEND}:{config.LLM_MODEL}:recommend:{cache_input}".encode("utf-8")).hexdigest()
    with _cache_lock:
        cache = _load_cache()
        if key in cache:
            return cache[key]

    signals_desc = ", ".join(signal_names) if signal_names else "no specific signal detected"
    prompt = (
        "You are writing a one-sentence recommendation for a credit committee "
        "reviewing an ESG risk assessment of a project finance transaction.\n"
        f"Risk grade: {risk_grade}\n"
        f"Specific risk signals detected in the document: {signals_desc}\n\n"
        "Write ONE concise, actionable sentence (max 35 words) recommending a "
        "specific next step, referencing the actual signals above rather than "
        "generic language. No preamble, no quotes."
    )

    response = llm_backend.call_llm(prompt, config_key="recommend", temperature=0.3, timeout=timeout)
    text = response.strip().strip('"') if response else ""
    if not text:
        _warn_llm_unreachable("de recommandation — repli sur template par grade")
        return None

    with _cache_lock:
        cache[key] = text
        if save:
            _save_cache()
    return text


if __name__ == "__main__":
    tests = [
        ("The project has faced significant community opposition. Local populations "
         "report involuntary displacement without adequate compensation.", 1, True),
        ("Community feedback mechanisms are active with positive stakeholder sentiment.", 1, False),
        ("The ESAP action plan shows delays in implementation of corrective measures.", 3, True),
        ("ESAP actions completed ahead of schedule. Biodiversity offset program is on track.", 3, False),
    ]
    for text, flag_num, expected in tests:
        result = confirm_risk(text, flag_num)
        status = "OK" if result == expected else "MISMATCH"
        print(f"[{status}] flag{flag_num} attendu={'RISK' if expected else 'CLEAN'} "
              f"obtenu={'RISK' if result else 'CLEAN'} — {text[:60]}...")

    print()
    sample = (
        "The quarterly discharge monitoring report for Q2 was not submitted within "
        "the required timeframe. Water quality parameters at the downstream sampling "
        "point exceeded IFC EHS guideline thresholds for total suspended solids."
    )
    print(f"[summarize] {summarize_passage(sample)}")
