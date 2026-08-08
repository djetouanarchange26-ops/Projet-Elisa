"""
CHANTIER 3 (PROMPT_CLAUDE_CODE_ESG_V2) — Pipeline d'analyse LLM multi-pass
==============================================================================
Fait passer l'outil de « matcher de similarité » à « analyste ESG » via 3
passes LLM courtes et TRÈS CADRÉES (voir AUDIT_ESG.md §1.3 : avant ce
chantier, le LLM local ne faisait que 3 micro-tâches ponctuelles — filtre
de polarité, résumé, recommandation en 1 phrase — jamais d'extraction
structurée ni de détection d'omission).

Adapté à un LLM 4B (qwen3:4b-instruct — pas un « vrai » LLM cloud), cf.
PROMPT_CLAUDE_CODE_ESG_V2.md, Chantier 3 :
  - format de réponse EN LIGNES (pas de JSON — plus fiable avec un petit
    modèle, parsé avec de simples splits)
  - une question à la fois par passe, jamais cinq
  - PAS de Pass 4 (scénarios contrefactuels/impact financier chiffré) —
    un 4B inventerait des chiffres non fiables ; on ne le fait pas plutôt
    que de le faire mal (ça viendra avec un vrai LLM, cf. le prompt)

Ce module NE MODIFIE PAS llm_confirm.py, qui reste le filtre de polarité
utilisé par search.py/analyze.py — deep_analysis.py est une couche
complémentaire, pas un remplacement.

Feature flag : config.DEEP_ANALYSIS_ENABLED — analyze.py doit fonctionner
sans (résultat existant : flag_scores + recommandation simple par
llm_confirm.generate_recommendation).

Fail gracefully : si une passe échoue (Ollama injoignable) ou produit un
résultat non parsable (attendu avec un 4B), la fonction log un avertissement
et retourne un résultat partiel/vide pour cette passe plutôt que de lever
une exception — run_deep_analysis() ne plante jamais, cf. son docstring.
"""

import hashlib
import json
import logging
import re
import threading
from pathlib import Path

import config
import llm_backend
from chunk_metadata import classify_section_type
from search import chunk_text

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent.parent
CACHE_PATH = BASE / "models" / "deep_analysis_cache.json"

# SEUIL: borne le nombre de chunks soumis à la Pass 1 — un gros document
# (100+ pages) déclencherait sinon autant d'appels LLM séquentiels que de
# chunks (~2-4s/appel mesuré, cf. checklist.md), largement hors budget démo.
# Les chunks au-delà de cette limite ne sont juste pas passés en Pass 1 (pas
# tronqués/résumés) — limite assumée, pas un bug.
MAX_CHUNKS_PASS1 = 20

_cache = None
_cache_lock = threading.Lock()
_llm_unreachable_warned = False


# ============================================================================
# INFRASTRUCTURE — cache disque + appel Ollama (même pattern que llm_confirm.py)
# ============================================================================

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
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(_cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _cache_key(pass_name, text):
    # CHANTIER LLM BACKEND (2026-08-07) : inclut backend+modèle actifs — une
    # réponse Together/Qwen3.5-9B ne doit jamais être servie comme si elle
    # venait d'Ollama/qwen3:4b-instruct (ou l'inverse), même logique que le
    # cache de llm_confirm.py.
    return hashlib.sha256(f"{config.LLM_BACKEND}:{config.LLM_MODEL}:{pass_name}:{text}".encode("utf-8")).hexdigest()


# DIRECTIVE_CLAUDE_CODE_ESG_V3, Tier 0 — Pass 1 (extraction courte, 3 lignes
# attendues) et Pass 3 (synthèse) ont une longueur de réponse prévisible, donc
# plafonnées via config.OLLAMA_CONFIGS. Pass 2 est délibérément EXCLUE de ce
# plafond (num_predict) : run_pass2() ne fonctionne correctement que parce que
# le modèle "se répète" plusieurs fois avant de conclure (mesuré : jusqu'à 29
# lignes/6 sujets, cf. run_pass2 et checklist.md Chantier 3) — seul le DERNIER
# bloc est retenu. Un num_predict trop bas tronquerait la réponse avant cette
# dernière répétition et ferait régresser ce bug déjà corrigé.
_CONFIG_KEY_BY_PASS = {"pass1": "deep_extract", "pass3": "deep_synthesize"}


def _call_llm(prompt, pass_name, cache_input, temperature=0.0, timeout=60):
    """Appel LLM générique avec cache disque — retourne le texte de réponse
    brut, ou None si le backend est injoignable/répond vide (fail-open, même
    logique que llm_confirm.confirm_risk). Le backend actif (Ollama local ou
    cloud) est résolu par llm_backend.py via config.LLM_BACKEND.

    config_key=None pour pass_name="pass2" (absent de _CONFIG_KEY_BY_PASS) :
    volontaire, voir le commentaire Tier 0 au-dessus de _CONFIG_KEY_BY_PASS —
    Pass 2 ne doit jamais avoir de plafond de longueur de réponse."""
    global _llm_unreachable_warned
    key = _cache_key(pass_name, cache_input)
    with _cache_lock:
        cache = _load_cache()
        if key in cache:
            return cache[key]

    config_key = _CONFIG_KEY_BY_PASS.get(pass_name)
    text = llm_backend.call_llm(prompt, config_key=config_key, temperature=temperature, timeout=timeout)
    if not text:
        if not _llm_unreachable_warned:
            logger.warning("deep_analysis: LLM injoignable — passe(s) ignorée(s) (fail-open).")
            _llm_unreachable_warned = True
        return None

    with _cache_lock:
        cache[key] = text
        _save_cache()
    return text


# ============================================================================
# PASS 1 — Extraction de faits (chunk par chunk)
# ============================================================================

_PASS1_PROMPT_TEMPLATE = """Tu lis un extrait d'un rapport de projet. Réponds UNIQUEMENT au format demandé.

Extrait :
"{chunk_text}"

Questions :
1. Ce passage contient-il un engagement chiffré ? (OUI/NON)
   Si OUI : quel engagement ? quelle cible ? quel horizon ?
2. Ce passage mentionne-t-il un incident ou un problème ? (OUI/NON)
   Si OUI : lequel, en une phrase ?
3. Ce passage est-il vague ou évasif ? (OUI/NON)
   Si OUI : quelle formulation est évasive ?

Réponds EXACTEMENT dans ce format :
ENGAGEMENT: OUI/NON | [description courte] | [cible] | [horizon]
INCIDENT: OUI/NON | [description courte]
EVASIF: OUI/NON | [formulation identifiée]"""

_PASS1_LINE_RE = {
    "engagement": re.compile(r"ENGAGEMENT\s*:\s*(OUI|NON)\s*(?:\|(.*))?", re.IGNORECASE),
    "incident":   re.compile(r"INCIDENT\s*:\s*(OUI|NON)\s*(?:\|(.*))?", re.IGNORECASE),
    "evasif":     re.compile(r"EVASIF\s*:\s*(OUI|NON)\s*(?:\|(.*))?", re.IGNORECASE),
}


def _parse_pass1_response(response_text):
    """Parse le format ligne-par-ligne de la Pass 1 — bien plus tolérant
    qu'un parseur JSON face aux imperfections d'un modèle 4B (cf. docstring
    du module). Un champ absent/mal formé -> "présent": False plutôt que de
    lever une exception (fail gracefully, ce chunk contribue juste moins).

    BUG CORRIGÉ (2026-08-06, checklist.md) : le défaut était `None` (pas
    encore `{"present": False}`) pour une ligne jamais matchée — si la
    réponse du LLM était coupée avant la 3e ligne (EVASIF, souvent tronquée
    par num_predict trop bas) ou ne respectait pas exactement le format
    demandé, `result[key]` restait `None`. `run_pass3` fait ensuite
    `f.get("incident", {}).get("present")` — `.get(..., {})` ne sert à rien
    quand la clé EXISTE avec la valeur `None` (le défaut de `.get()` ne
    s'applique que si la clé est ABSENTE) → `None.get(...)` →
    `AttributeError`, Pass 3 échouait silencieusement (fail-open, mais la
    synthèse ne se générait alors jamais). Mesuré sur un document réel de
    171 chunks (checklist.md, audit du 2026-08-06).
    """
    result = {"engagement": {"present": False}, "incident": {"present": False}, "evasif": {"present": False}}
    for line in response_text.splitlines():
        for key, pattern in _PASS1_LINE_RE.items():
            m = pattern.search(line)
            if not m:
                continue
            present = m.group(1).strip().upper() == "OUI"
            fields = [f.strip() for f in (m.group(2) or "").split("|")]
            fields = [f for f in fields if f]
            if key == "engagement":
                result[key] = {
                    "present": present,
                    "description": fields[0] if len(fields) > 0 else "",
                    "cible":       fields[1] if len(fields) > 1 else "",
                    "horizon":     fields[2] if len(fields) > 2 else "",
                } if present else {"present": False}
            else:
                result[key] = {
                    "present": present,
                    "description": fields[0] if fields else "",
                } if present else {"present": False}
    return result


def run_pass1(chunks):
    """Extraction de faits, un appel LLM par chunk (borné à
    MAX_CHUNKS_PASS1). Retourne une liste de dicts, un par chunk traité :
    {"chunk_index", "engagement", "incident", "evasif"} — les champs
    valent {"present": False} si absents/non détectés/passe échouée pour
    ce chunk (jamais d'exception propagée)."""
    findings = []
    for i, chunk in enumerate(chunks[:MAX_CHUNKS_PASS1]):
        prompt = _PASS1_PROMPT_TEMPLATE.format(chunk_text=chunk)
        response = _call_llm(prompt, "pass1", chunk, temperature=0.0)
        if response is None:
            continue  # LLM injoignable — ce chunk ne contribue pas, pas d'exception
        parsed = _parse_pass1_response(response)
        parsed["chunk_index"] = i
        findings.append(parsed)
    return findings


# ============================================================================
# PASS 2 — Détection d'omissions (une fois, sur l'ensemble du document)
# ============================================================================

_CRITICAL_TOPICS = [
    "Impact sur les communautés locales et réinstallation",
    "Pollution et gestion des déchets",
    "Biodiversité et habitats naturels",
    "Conditions de travail et santé-sécurité",
    "Consultation des parties prenantes",
    "Mécanisme de plainte et recours",
]
N_CRITICAL_TOPICS = len(_CRITICAL_TOPICS)  # exposé pour app.py (score d'omission du radar chart, Chantier 4)

_SECTION_LABELS_FR = {
    "environmental": "Environnement (émissions, biodiversité, eau, déchets, pollution)",
    "social":        "Social (communautés, droits humains, travail, réinstallation)",
    "governance":    "Gouvernance (conformité, consultation, mécanismes de plainte)",
}

# CHOIX: heuristique légère par mots-clés — aucune vraie taxonomie de secteur
# n'existe dans le codebase (cf. AUDIT_ESG.md §1.1, pas de champ project_type).
# Suffisant pour donner du contexte au prompt Pass 2, pas une classification
# rigoureuse.
_PROJECT_TYPE_KEYWORDS = [
    (r"\bhydro\w*|\bdam\b|\breservoir\b", "projet hydroélectrique"),
    (r"\bwind farm\b|\bwind power\b|\bturbine", "projet éolien"),
    (r"\bsolar\b|\bphotovoltaic\b|\bPV\b", "projet solaire"),
    (r"\bmin(e|ing)\b|\bmineral\b|\bore\b", "projet minier"),
    (r"\boil\b|\bgas\b|\bpetroleum\b|\bpipeline\b", "projet pétrole & gaz"),
    (r"\bport\b|\bterminal\b|\bshipping\b", "projet portuaire/logistique"),
    (r"\bairport\b|\baviation\b", "projet aéroportuaire"),
    (r"\broad\b|\bhighway\b|\bmotorway\b", "projet routier"),
    (r"\bmicrofinance\b|\bfinancial institution\b|\bbank\b", "institution financière"),
]
# FRAGILE: motifs testés manuellement pour éviter les faux positifs sur des
# mots courants du corpus — ex. "PV\b" sans \b initial matchait "SPV"
# (special purpose vehicle, très fréquent en project finance) ; "ore\b" sans
# \b initial matchait "explore". Vérifier tout nouveau mot-clé court de la
# même façon avant de l'ajouter.


def guess_project_type(text):
    """Devine un type de projet générique à partir de mots-clés sectoriels
    — contexte pour la Pass 2, pas une vraie classification (cf. CHOIX
    ci-dessus). Défaut : description générique IFC/bailleur de développement."""
    for pattern, label in _PROJECT_TYPE_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return "projet d'infrastructure/énergie financé par une institution de développement"


_PASS2_PROMPT_TEMPLATE = """Tu es un analyste de risque. Voici les sujets couverts dans un rapport de projet :
{themes}

Voici les sujets ESG critiques pour un {project_type} :
- Impact sur les communautés locales et réinstallation
- Pollution et gestion des déchets
- Biodiversité et habitats naturels
- Conditions de travail et santé-sécurité
- Consultation des parties prenantes
- Mécanisme de plainte et recours

Quels sujets critiques sont ABSENTS ou insuffisamment couverts dans ce rapport ?
Liste uniquement les sujets manquants, un par ligne. Si tout est couvert, écris "AUCUNE OMISSION"."""


def run_pass2(chunks, project_type):
    """Détection d'omissions — un seul appel LLM, sur les section_type
    détectés dans les chunks du document (Chantier 1 : classify_section_type,
    réutilisé ici en lecture seule pour construire le prompt — n'affecte pas
    le chunking/scoring FAISS, cf. la mise en garde de chunk_metadata.py).

    Retourne une liste de sujets manquants — au plus N_CRITICAL_TOPICS (6),
    toujours des libellés exacts de _CRITICAL_TOPICS, jamais du texte libre
    du modèle (cf. FRAGILE ci-dessous). Vide si tout est couvert. `None` si
    la passe échoue (Ollama injoignable) — distinct de [] confirmé."""
    section_types = {classify_section_type(c) for c in chunks} - {"general"}
    themes = "\n".join(f"- {_SECTION_LABELS_FR.get(s, s)}" for s in sorted(section_types))
    if not themes:
        themes = "(aucun thème ESG spécifique détecté)"

    prompt = _PASS2_PROMPT_TEMPLATE.format(themes=themes, project_type=project_type)
    cache_input = f"{project_type}:{themes}"
    response = _call_llm(prompt, "pass2", cache_input, temperature=0.0)
    if response is None:
        return None  # échec de la passe — distinct de [] ("AUCUNE OMISSION" confirmée)

    # FRAGILE: un 4B ne respecte pas toujours "un sujet par ligne, rien
    # d'autre" — mesuré : jusqu'à 29 lignes en réponse pour 6 sujets
    # possibles. Structure observée : le modèle rappelle d'abord la liste
    # complète des 6 sujets (écho du prompt), raisonne à voix haute sur ce
    # qui est couvert ou non, puis répète 2-3 fois une liste affinée avant
    # de conclure. La DERNIÈRE répétition est systématiquement la plus
    # propre (mesuré : 3 répétitions identiques du bon sous-ensemble, la
    # toute première étant le rappel complet à ignorer). On découpe donc la
    # réponse en blocs (séparés par une ligne vide) et on ne garde QUE le
    # dernier bloc qui matche au moins un sujet connu — pas toute la
    # réponse — pour éviter de compter le rappel de la liste complète comme
    # des omissions.
    blocks = [b for b in response.split("\n\n") if b.strip()]
    last_matching_topics = []
    for block in blocks:
        topics = _topics_matched_in_block(block)
        if topics:
            last_matching_topics = topics
    return last_matching_topics


def _topics_matched_in_block(block):
    """Sujets canoniques de _CRITICAL_TOPICS (dédupliqués, ordre d'apparition)
    matchés par les lignes de `block` — correspondance souple (sous-chaîne
    dans un sens ou l'autre, insensible à la casse), jamais une ligne de
    prose arbitraire acceptée telle quelle comme sujet."""
    found = []
    for line in block.splitlines():
        line_clean = line.strip("-•* ").strip().lower()
        if not line_clean:
            continue
        for topic in _CRITICAL_TOPICS:
            if topic not in found and (topic.lower() in line_clean or line_clean in topic.lower()):
                found.append(topic)
    return found


# ============================================================================
# PASS 3 — Synthèse d'alerte (une fois, sur les findings agrégés)
# ============================================================================

_PASS3_PROMPT_TEMPLATE = """Tu rédiges une alerte de risque ESG pour un comité de crédit bancaire.

Voici les éléments détectés dans le rapport du projet "{project_name}" :
- Incidents identifiés : {incidents}
- Engagements sans cible chiffrée : {vague_commitments}
- Formulations évasives détectées : {evasive_phrases}
- Sujets ESG critiques non couverts : {omissions}
- Score de risque du modèle : {risk_grade} ({probability_12m:.0%} à 12 mois)
- Signaux détectés : {detected_signals}

Rédige en 3-5 phrases :
1. Le niveau de risque global et pourquoi
2. Le signal le plus préoccupant et ce qu'il implique
3. Ce qui manque dans ce rapport et pourquoi c'est un problème"""


def _format_list_for_prompt(items, empty_label):
    return "; ".join(items) if items else empty_label


def run_pass3(project_name, pass1_findings, omissions, risk_grade, probability_12m, detected_signals):
    """Synthèse d'alerte — un seul appel LLM sur les findings déjà agrégés
    (Pass 1 + Pass 2 + la prédiction Cox existante). Retourne une chaîne
    (3-5 phrases) ou None si la passe échoue (Ollama injoignable/réponse
    vide) — l'appelant retombe alors sur le "recommendation" existant
    (llm_confirm.generate_recommendation), cf. run_deep_analysis."""
    incidents = [f["incident"]["description"] for f in pass1_findings
                 if f.get("incident", {}).get("present") and f["incident"]["description"]]
    vague_commitments = [f["engagement"]["description"] for f in pass1_findings
                          if f.get("engagement", {}).get("present") and not f["engagement"].get("cible")
                          and f["engagement"]["description"]]
    evasive = [f["evasif"]["description"] for f in pass1_findings
               if f.get("evasif", {}).get("present") and f["evasif"]["description"]]
    signal_names = sorted({s["signal"] for s in detected_signals})[:6]

    prompt = _PASS3_PROMPT_TEMPLATE.format(
        project_name=project_name,
        incidents=_format_list_for_prompt(incidents, "aucun"),
        vague_commitments=_format_list_for_prompt(vague_commitments, "aucun"),
        evasive_phrases=_format_list_for_prompt(evasive, "aucune"),
        omissions=_format_list_for_prompt(omissions or [], "aucune"),
        risk_grade=risk_grade,
        probability_12m=probability_12m,
        detected_signals=_format_list_for_prompt(signal_names, "aucun signal spécifique"),
    )
    cache_input = json.dumps({
        "p": project_name, "i": incidents, "v": vague_commitments, "e": evasive,
        "o": omissions, "g": risk_grade, "pr": round(probability_12m, 3), "s": signal_names,
    }, sort_keys=True)
    # BUG CORRIGÉ (2026-08-06, audit perf checklist.md) : deep_synthesize
    # (num_predict=450, cf. config.py) peut légitimement approcher ou
    # dépasser le timeout par défaut de _call_llm (60s) sur Ollama en CPU
    # (~7-10 tokens/s mesuré sous charge) — mesuré : timeout réel atteint sur
    # cette passe précise après un run à froid avec ~50 appels LLM déjà
    # enchaînés. Le num_predict a été augmenté (fix troncature de la veille)
    # sans augmenter ce timeout en conséquence — corrigé ici. Conservé tel
    # quel après le passage à llm_backend.py (2026-08-07) : un backend cloud
    # plus rapide n'en a pas besoin, mais ne pas le réduire ne coûte rien et
    # garde une marge si LLM_FALLBACK retombe sur Ollama.
    return _call_llm(prompt, "pass3", cache_input, temperature=0.2, timeout=150)


# ============================================================================
# ORCHESTRATEUR
# ============================================================================

def run_deep_analysis(pdf_text, project_name, risk_grade, probability_12m, detected_signals):
    """Pipeline complète Pass 1 -> Pass 2 -> Pass 3.

    Ne lève JAMAIS d'exception : chaque passe peut échouer indépendamment
    (Ollama injoignable, réponse non parsable) sans empêcher les autres de
    s'exécuter ni de produire un résultat. Si config.DEEP_ANALYSIS_ENABLED
    est désactivé, retourne un résultat vide immédiatement (analyze.py doit
    fonctionner identiquement à avant ce chantier dans ce cas).

    Retourne :
      {
        "enabled":     bool,
        "pass1_findings": [...],       # cf. run_pass1 — [] si désactivé/échoué
        "omissions":      [...] | None, # None = passe échouée (pas "aucune omission")
        "synthesis":      str | None,   # None = passe échouée ou désactivée
        "project_type":   str,
      }
    """
    if not config.DEEP_ANALYSIS_ENABLED:
        return {"enabled": False, "pass1_findings": [], "omissions": None,
                "synthesis": None, "project_type": None}

    chunks = chunk_text(pdf_text) or [pdf_text]
    project_type = guess_project_type(pdf_text)

    try:
        pass1_findings = run_pass1(chunks)
    except Exception as e:
        print(f"  [WARN] deep_analysis Pass 1 : erreur inattendue ({e}) — résultat vide pour cette passe.")
        pass1_findings = []

    try:
        omissions = run_pass2(chunks, project_type)
    except Exception as e:
        print(f"  [WARN] deep_analysis Pass 2 : erreur inattendue ({e}) — résultat vide pour cette passe.")
        omissions = None

    try:
        synthesis = run_pass3(project_name, pass1_findings, omissions, risk_grade,
                               probability_12m, detected_signals)
    except Exception as e:
        print(f"  [WARN] deep_analysis Pass 3 : erreur inattendue ({e}) — résultat vide pour cette passe.")
        synthesis = None

    return {
        "enabled": True,
        "pass1_findings": pass1_findings,
        "omissions": omissions,
        "synthesis": synthesis,
        "project_type": project_type,
    }


if __name__ == "__main__":
    test_text = """
    The project has faced significant community opposition. Local communities
    have filed grievances regarding involuntary resettlement and inadequate
    consultation processes. The ESAP action plan shows delays in implementing
    corrective measures, with reasonable efforts to be made where feasible.
    The company aims to explore emission reduction opportunities in due course.
    """
    result = run_deep_analysis(
        test_text, "Test Project", risk_grade="B", probability_12m=0.42,
        detected_signals=[{"signal": "community opposition"}, {"signal": "ESAP delays"}],
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
