"""
GRILLE ESG V4 — détection automatique du type de document (R11)
=====================================================================
R11 (grid_questions.DOCUMENT_TYPES) conditionne le mode de lecture, les
formes de preuve admises (grid_prompts.py) et la règle de silence R5/R8 —
il doit donc être résolu AVANT l'annotation/le scoring de chaque question,
pas après. Avant ce module, document_type était saisi manuellement dans
l'UI (sélecteur Streamlit, défaut index 0 = Type 1) : un analyste qui ne
changeait pas la sélection par défaut se retrouvait avec un Type 1
("Instruction / due diligence pré-closing") pour n'importe quel document,
y compris un rapport de monitoring multiannuel (Type 3) — cf. le
diagnostic sur le rapport CGPL Mundra, classé Type 1 par défaut alors
qu'il s'agit d'un Type 3.

CHOIX: un appel LLM dédié, séparé des 12 appels question-par-question
(grid_prompts.py) — la détection de type est une tâche de classification
globale du document, pas une question de la grille. Un seul appel par
analyse (pas par question).

CHOIX: indices lexicaux (regex) calculés en amont et transmis au LLM
comme AIDE ("indices détectés"), jamais comme décision automatique — la
classification finale reste un jugement du LLM sur le contenu réel, pas
un simple pattern-matching sur des mots-clés (même logique que R10 dans
grid_prompts.py : pas de filtre lexical qui déciderait à la place du
LLM). Générique, pas calibré sur un dossier en particulier (Mundra ne
doit jamais apparaître dans ce fichier) — les indices ciblent le
vocabulaire structurel des 4 types (CAO, AMR, ESRS, période de
monitoring...), pas un projet précis.

Fail-open (ADR-002) : si le LLM est injoignable ou répond dans un format
inexploitable, repli sur une heuristique lexicale déterministe (pas un
Type 1 muet) — et le champ "confidence"/"source" du résultat l'indique
explicitement, pour que l'analyste (boucle humaine, Note de Cadrage
décision 2) voie que la détection n'est pas fiable plutôt que de laisser
un type par défaut masquer une détection ratée.
"""

import logging
import re

import grid_questions
import llm_backend

logger = logging.getLogger(__name__)

# --- Indices lexicaux par type (aide au LLM + heuristique de repli) ---
# CHOIX: patterns génériques sur le vocabulaire structurel IFC/CAO, pas sur
# un dossier précis — cf. docstring du module, "Ce qu'il ne faut PAS faire"
# (pas de patch par nom de projet).
_HINTS = {
    1: [
        (r"\bESIA\b", "ESIA (Environmental and Social Impact Assessment)"),
        (r"environmental\s+and\s+social\s+review\s+summary", "Environmental and Social Review Summary (ESRS)"),
        (r"\bESRS\b", "ESRS"),
        (r"credit\s+memo|memo(?:randum)?\s+de\s+cr[ée]dit", "mémo de crédit"),
        (r"due\s+diligence", "due diligence"),
        (r"\bpre[- ]closing\b|avant\s+cl[ôo]ture", "pré-closing"),
    ],
    2: [
        (r"annual\s+monitoring\s+report|\bAMR\b", "Annual Monitoring Report (AMR)"),
        (r"rapport\s+annuel\s+de\s+suivi", "rapport annuel de suivi"),
        (r"prepared\s+by\s+the\s+(?:client|sponsor|company)", "rapport préparé par le client/sponsor lui-même"),
    ],
    3: [
        (r"compliance\s+advisor\s*[/]?\s*ombudsman|\bCAO\b", "Compliance Advisor Ombudsman (CAO)"),
        (r"compliance\s+(?:review\s+)?panel", "panel de conformité"),
        (r"(?:first|second|third|1st|2nd|3rd)\s+monitoring\s+period|monitoring\s+period\s+(?:no\.?\s*)?\d",
         "structuration en périodes de monitoring successives"),
        (r"independent\s+(?:audit|auditor|assessment)", "audit/évaluation indépendant"),
    ],
    4: [
        (r"biodiversity\s+action\s+plan|\bBAP\b", "rapport biodiversité (BAP)"),
        (r"air\s+quality\s+(?:monitoring\s+)?report", "rapport qualité de l'air"),
        (r"grievance\s+mechanism\s+report", "rapport mécanisme de griefs"),
        (r"thematic\s+(?:review|report|assessment)", "revue thématique"),
    ],
}

_TYPE_RE = {t: [re.compile(p, re.IGNORECASE) for p, _ in pats] for t, pats in _HINTS.items()}
_EXCERPT_CHARS = 4000

_PROMPT_TEMPLATE = """Tu es un analyste ESG. Détermine le TYPE du document ci-dessous parmi les 4 catégories de la Grille ESG V4 (R11).

TYPE 1 — Instruction / due diligence pré-closing :
ESRS, ESIA, mémo de crédit. Produit AVANT ou AU MOMENT du financement.
Décrit des risques anticipés et des mesures PLANIFIÉES (obligation de
planification), pas d'historique d'exploitation réel.

TYPE 2 — Rapport annuel de suivi opérateur :
AMR (Annual Monitoring Report), rapport E&S annuel produit PAR
L'OPÉRATEUR/LE CLIENT lui-même sur SA propre performance (pas un tiers
indépendant). Obligation de résultat sur une période d'environ 12 mois.

TYPE 3 — Rapport de monitoring multiannuel par auditeur indépendant :
Rapport CAO (Compliance Advisor Ombudsman), panel de conformité, ou tout
audit produit par un TIERS INDÉPENDANT DE L'OPÉRATEUR (pas le client, pas
le prêteur), couvrant PLUSIEURS périodes de monitoring successives
(souvent structuré en "First/Second/Third Monitoring Period").

TYPE 4 — Rapport de suivi thématique ou sectoriel :
Limité à UN SEUL thème (biodiversité, qualité de l'air, mécanisme de
griefs...), périmètre étroit, pas une revue E&S complète du projet.

INDICES DÉTECTÉS AUTOMATIQUEMENT DANS LE TEXTE (aide à la décision,
NE DÉCIDE PAS À TA PLACE — juge sur le contenu réel) :
{lexical_hints}

EXTRAIT DU DOCUMENT (début) :
{excerpt}

RÉPONDS EXACTEMENT DANS CE FORMAT :
TYPE: 1 ou 2 ou 3 ou 4
CONFIANCE: haute ou moyenne ou faible
EVIDENCE: [passage ou éléments du texte qui justifient ce choix]
"""

_LINE_PATTERNS = {
    "type":       re.compile(r"^TYPE\s*:[ \t]*([1-4])\b", re.IGNORECASE | re.MULTILINE),
    "confidence": re.compile(r"^CONFIANCE\s*:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE),
    "evidence":   re.compile(r"^EVIDENCE\s*:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE),
}

_VALID_CONFIDENCE = ("haute", "moyenne", "faible")


def _collect_hints(text):
    """Retourne {type: [libellés d'indices trouvés]} — pur repérage
    lexical, aucune décision prise ici (cf. docstring du module)."""
    found = {}
    for doc_type, patterns in _TYPE_RE.items():
        labels = [label for (pattern, (_, label)) in zip(patterns, _HINTS[doc_type]) if pattern.search(text)]
        if labels:
            found[doc_type] = labels
    return found


def _format_hints(hints):
    if not hints:
        return "(aucun indice lexical détecté)"
    return "\n".join(
        f"- Type {t} : {', '.join(labels)}" for t, labels in sorted(hints.items())
    )


def _heuristic_fallback(hints):
    """Repli déterministe si le LLM est injoignable ou mal formé — PAS un
    Type 1 muet (cf. docstring du module, "ne pas masquer une détection
    ratée"). Générique : le type avec le plus d'indices distincts
    l'emporte ; égalité ou aucun indice -> Type 1 (le plus prudent, seul
    type qui n'impose ni couches temporelles R8 ni hiérarchie de sources
    R9), mais avec confidence="faible" et source explicite pour que
    l'analyste sache qu'il doit vérifier."""
    if not hints:
        return {
            "document_type": 1,
            "confidence": "faible",
            "evidence": None,
            "source": "fallback_heuristique_aucun_indice",
        }
    best_type = max(hints, key=lambda t: len(hints[t]))
    return {
        "document_type": best_type,
        "confidence": "faible",
        "evidence": "Indices lexicaux : " + ", ".join(hints[best_type]),
        "source": "fallback_heuristique_lexicale",
    }


def parse_response(raw_response):
    """Parse la réponse LLM. Retourne None si le format est inexploitable
    (pas de ligne TYPE valide) — fail-open géré par l'appelant."""
    if not raw_response:
        return None

    match = _LINE_PATTERNS["type"].search(raw_response)
    if not match:
        logger.warning("grid_doctype: aucune ligne TYPE exploitable — parsing échoué.")
        return None

    def _field(key):
        m = _LINE_PATTERNS[key].search(raw_response)
        return m.group(1).strip() if m else ""

    confidence = _field("confidence").lower() or "faible"
    if confidence not in _VALID_CONFIDENCE:
        confidence = "faible"

    return {
        "document_type": int(match.group(1)),
        "confidence": confidence,
        "evidence": _field("evidence") or None,
    }


def detect_document_type(text):
    """Détecte le type de document (R11) à partir de son texte intégral.

    Retourne un dict {"document_type": int (clé de
    grid_questions.DOCUMENT_TYPES), "confidence": "haute"|"moyenne"|"faible",
    "evidence": str|None, "source": "llm"|"fallback_heuristique_lexicale"|
    "fallback_heuristique_aucun_indice"}.

    CHOIX: ne lève jamais d'exception (fail-open, ADR-002) — un texte vide
    ou un LLM injoignable retombent sur l'heuristique lexicale, jamais sur
    un crash ni sur un Type 1 silencieux non distingué d'une vraie
    détection (cf. champ "source"/"confidence").
    """
    text = text or ""
    hints = _collect_hints(text[: _EXCERPT_CHARS * 3])  # scan un peu plus large que l'extrait envoyé au LLM

    prompt = _PROMPT_TEMPLATE.format(
        lexical_hints=_format_hints(hints),
        excerpt=text[:_EXCERPT_CHARS] or "(document vide)",
    )

    raw = llm_backend.call_llm(prompt, config_key="detect_doctype", temperature=0.0)
    parsed = parse_response(raw) if raw else None

    if parsed is None:
        logger.warning("grid_doctype: LLM injoignable ou réponse inexploitable — repli sur heuristique lexicale.")
        return _heuristic_fallback(hints)

    if parsed["document_type"] not in grid_questions.DOCUMENT_TYPES:
        logger.warning("grid_doctype: type hors bornes (%r) — repli sur heuristique lexicale.", parsed["document_type"])
        return _heuristic_fallback(hints)

    return {
        "document_type": parsed["document_type"],
        "confidence": parsed["confidence"],
        "evidence": parsed["evidence"],
        "source": "llm",
    }
