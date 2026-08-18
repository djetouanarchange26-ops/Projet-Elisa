"""Détection des sections structurelles des documents IFC/ESRS.

CHOIX: module séparé de search.py — la détection de sections est
spécifique aux documents IFC et à la Grille V3, pas au pipeline
de recherche vectorielle existant.

ALT: intégrer dans chunk_metadata.py (qui fait déjà classify_section_type).
Rejeté : chunk_metadata.py est utilisé pour le corpus offline, pas pour
le document uploadé — les deux n'ont pas le même cycle de vie.

FRAGILE: les titres de section sont standardisés dans les ESRS IFC
mais peuvent varier légèrement d'un dossier à l'autre. Les patterns
ci-dessous sont calibrés sur CBG et devront être validés sur Mundra.

CONTEXTE (directive CC-09, confirmée telle quelle par CC-V4-04) : deux
sources de faux positifs systématiques repérées au niveau parseur, avant
le LLM :
  - ESAP (Environmental & Social Action Plan) : items à l'impératif
    (Prepare, Finalize, Complete...) qui sont des obligations NON ENCORE
    REMPLIES, pas des mitigations prouvées.
  - "Information on E&S Complaints and Grievance Mechanisms" : texte type
    reproduit à l'identique en fin de tous les ESRS IFC, faux positifs
    identiques sur 100% du corpus.

CHANTIER CC-V4-04 (addition V4, bonus non bloquant) : marquage BEST-EFFORT
des couches temporelles pour les documents Type 3 (rapport de monitoring
multiannuel par auditeur indépendant, cf. grid_questions.DOCUMENT_TYPES et
R8) — un même rapport peut couvrir plusieurs périodes de monitoring
("First/Second/Third Monitoring Period"), et savoir à quelle période un
verbatim appartient aide le LLM à ne pas mélanger un constat ancien et
résolu avec l'état actuel. Cf. _detect_temporal_layers : indépendant de
l'exclusion ESAP/plaintes IFC ci-dessus, n'exclut RIEN — informatif
uniquement, pour le prompt (R8), pas pour le scoring.
"""

import logging
import re

logger = logging.getLogger(__name__)

# --- Patterns de détection ESAP (déclenchent le DÉBUT de la section) ---
# CHOIX: regex sur les titres de section, pas sur le contenu.
# Les titres ESAP sont très standardisés dans les ESRS IFC.
ESAP_TITLE_PATTERNS = [
    r"environmental\s+(?:and|&)\s+social\s+action\s+plan",
    r"\bESAP\b",
    r"action\s+plan\s+(?:item|table|matrix)",
]

# --- Patterns de détection section plaintes IFC (déclenchent le DÉBUT) ---
COMPLAINTS_SECTION_PATTERNS = [
    r"information\s+on\s+e\s*&\s*s\s+complaints?\s+and\s+grievance",
    r"information\s+on\s+environmental\s+(?:and|&)\s+social\s+complaints",
    r"compliance\s+advisor\s*[/]?\s*ombudsman\s*\(?\s*cao\s*\)?",
]

# CHOIX: en plus du titre, un pattern de CONTINUATION par section — la
# note de cadrage suppose une détection "jusqu'au prochain titre de même
# niveau", mais un chunk isolé (découpage ~175 mots) ne porte quasiment
# jamais de titre de section suivant de façon fiable. On utilise à la
# place le vocabulaire propre à chaque section : tant qu'un chunk qui
# suit un titre détecté contient ce vocabulaire, il reste dans la
# section ; dès qu'un chunk ne le contient plus, la section se termine.
# Cette heuristique est délibérément conservatrice (mieux vaut sous-tagger
# un item ESAP que sur-tagger un chunk hors sujet).
ESAP_CONTINUATION_PATTERNS = [
    r"\bitem\s+\d+\b",
    r"\b(?:prepare|finalize|complete|repair|employ|implement|establish|"
    r"submit|conduct|develop|ensure)\b",
]

COMPLAINTS_CONTINUATION_PATTERNS = [
    r"\bcomplaints?\b",
    r"\bgrievances?\b",
    r"\bombudsman\b",
    r"\bcao\b",
    r"\badversely\s+affected\b",
    r"\bharm\b",
]

# --- Patterns de détection des couches temporelles (CC-V4-04, bonus) ---
# CHOIX: titres de type "First/Second/Third Monitoring Period" — calibré
# sur le vocabulaire IFC observé (cf. FRAGILE module). Pas de pattern de
# continuation ici (contrairement à ESAP/plaintes) : une section de
# période de monitoring n'a pas de vocabulaire propre, son contenu est la
# narration normale du document — cf. _detect_temporal_layers.
TEMPORAL_LAYER_PATTERNS = {
    1: [
        r"first\s+monitoring\s+period",
        r"1st\s+monitoring\s+period",
        r"monitoring\s+period\s+(?:no\.?\s*)?1\b",
    ],
    2: [
        r"second\s+monitoring\s+period",
        r"2nd\s+monitoring\s+period",
        r"monitoring\s+period\s+(?:no\.?\s*)?2\b",
    ],
    3: [
        r"third\s+monitoring\s+period",
        r"3rd\s+monitoring\s+period",
        r"monitoring\s+period\s+(?:no\.?\s*)?3\b",
    ],
}


def _compile(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_ESAP_TITLE_RE = _compile(ESAP_TITLE_PATTERNS)
_COMPLAINTS_TITLE_RE = _compile(COMPLAINTS_SECTION_PATTERNS)
_ESAP_CONTINUATION_RE = _compile(ESAP_CONTINUATION_PATTERNS)
_COMPLAINTS_CONTINUATION_RE = _compile(COMPLAINTS_CONTINUATION_PATTERNS)
_TEMPORAL_LAYER_RE = {layer: _compile(pats) for layer, pats in TEMPORAL_LAYER_PATTERNS.items()}


def _matches_any(text, compiled_patterns):
    return any(p.search(text) for p in compiled_patterns)


def classify_chunks(chunks):
    """Marque chaque chunk avec sa section structurelle.

    CHOIX: on ne supprime pas les chunks — on les MARQUE. Le pipeline
    décide ensuite quoi en faire (exclure de la mitigation, exclure
    complètement, etc.).

    chunks : list of dicts, chaque dict a au minimum "text" (str).
    Retourne : une NOUVELLE liste de dicts (chunks originaux non modifiés)
    avec un champ "section_tag" ajouté :
      - "esap" : chunk situé dans la section ESAP
      - "ifc_complaints" : chunk situé dans la section plaintes IFC
      - "temporal_layer_1"/"_2"/"_3" : chunk situé dans une section de
        période de monitoring identifiée (CC-V4-04, bonus best-effort,
        documents Type 3) — n'exclut rien, informatif pour le prompt (R8)
      - None : chunk normal (aucune exclusion)

    CHOIX: l'exclusion ESAP/plaintes IFC (CC-09) est TOUJOURS prioritaire
    sur le marquage temporel (CC-V4-04) — un chunk n'a qu'un seul
    section_tag ; le marquage temporel ne s'applique qu'aux chunks que
    l'exclusion ESAP/plaintes laisse à None.
    """
    tags = _detect_section_boundaries(chunks)
    temporal_tags = _detect_temporal_layers(chunks)
    final_tags = [tag if tag is not None else temporal_tags[i] for i, tag in enumerate(tags)]

    n_esap = sum(1 for t in tags if t == "esap")
    n_complaints = sum(1 for t in tags if t == "ifc_complaints")
    if n_esap or n_complaints:
        logger.info(
            "grid_sections: %d chunk(s) ESAP, %d chunk(s) plaintes IFC exclus sur %d chunks",
            n_esap, n_complaints, len(chunks),
        )

    n_temporal = sum(1 for t in final_tags if t and t.startswith("temporal_layer_"))
    if n_temporal:
        logger.info("grid_sections: %d chunk(s) marqués par couche temporelle sur %d chunks",
                     n_temporal, len(chunks))

    return [dict(chunk, section_tag=tag) for chunk, tag in zip(chunks, final_tags)]


def _detect_section_boundaries(chunks):
    """Identifie, pour chaque chunk, la section structurelle à laquelle
    il appartient ("esap", "ifc_complaints" ou None).

    FRAGILE: la détection repose sur l'hypothèse que les sections sont
    contiguës et que le titre apparaît dans un chunk identifiable. Si un
    document a une structure non standard, les chunks ne seront pas
    marqués et passeront normalement dans le pipeline (fail-open).

    Stratégie :
    1. Scanner les chunks dans l'ordre. Un titre ESAP/complaints détecté
       dans un chunk (re)démarre la section correspondante à partir de
       ce chunk (prioritaire sur toute section en cours).
    2. Tant qu'une section est active, les chunks suivants restent
       marqués tant qu'ils contiennent le vocabulaire de continuation de
       cette section (cf. ESAP_CONTINUATION_PATTERNS /
       COMPLAINTS_CONTINUATION_PATTERNS).
    3. Dès qu'un chunk ne matche ni un titre ni le vocabulaire de
       continuation de la section active, la section se termine
       (le chunk courant redevient None).
    """
    tags = [None] * len(chunks)
    active = None

    for i, chunk in enumerate(chunks):
        text = chunk.get("text", "") or ""

        if _matches_any(text, _ESAP_TITLE_RE):
            active = "esap"
            tags[i] = active
            continue

        if _matches_any(text, _COMPLAINTS_TITLE_RE):
            active = "ifc_complaints"
            tags[i] = active
            continue

        if active == "esap" and _matches_any(text, _ESAP_CONTINUATION_RE):
            tags[i] = active
            continue

        if active == "ifc_complaints" and _matches_any(text, _COMPLAINTS_CONTINUATION_RE):
            tags[i] = active
            continue

        active = None
        tags[i] = None

    return tags


def _detect_temporal_layers(chunks):
    """Marquage BEST-EFFORT des couches temporelles (CC-V4-04, bonus,
    documents Type 3 à monitoring multiannuel — cf. R8) : "temporal_layer_1"
    / "_2" / "_3", ou None.

    CHOIX: contrairement à ESAP/plaintes IFC, une section "Third Monitoring
    Period" n'a pas de vocabulaire de continuation propre — son contenu
    est la narration normale du document. Une fois un titre de couche
    détecté, la couche reste donc active pour TOUS les chunks suivants
    jusqu'au prochain titre détecté (couche différente, ou re-détection du
    même titre — sans effet), pas seulement tant qu'un vocabulaire
    persiste. Simpliste par construction (cf. "bonus non bloquant" dans la
    directive CC-V4-04) — si aucun titre n'est détecté dans le document
    (structure non standard, vocabulaire différent), tous les chunks
    restent None et le LLM gère les couches via le prompt (R8), fail-open.
    """
    tags = [None] * len(chunks)
    active = None

    for i, chunk in enumerate(chunks):
        text = chunk.get("text", "") or ""

        for layer, patterns in _TEMPORAL_LAYER_RE.items():
            if _matches_any(text, patterns):
                active = layer
                break

        tags[i] = f"temporal_layer_{active}" if active is not None else None

    return tags


def get_chunks_for_question(chunks, question_code, for_mitigation=False):
    """Retourne les chunks utilisables pour une question donnée.

    CHOIX: la logique de filtrage par section est centralisée ici.

    chunks : list classifiée par classify_chunks (chaque chunk a
        "section_tag").
    question_code : str, ex. "B.2.1" — conservé pour traçabilité/logging,
        la distinction R/A est portée par `for_mitigation`, pas déduite
        du code ici (l'appelant sait déjà s'il évalue R ou A).
    for_mitigation : bool
      - False (défaut) : évaluation du risque (R) — exclut
        "ifc_complaints", garde "esap" (un item ESAP renseigne le risque).
      - True : évaluation de la mitigation (A) — exclut "ifc_complaints"
        ET "esap" (un item ESAP est une obligation non remplie, jamais
        une preuve d'atténuation).
    """
    excluded_tags = {"ifc_complaints"}
    if for_mitigation:
        excluded_tags.add("esap")

    return [c for c in chunks if c.get("section_tag") not in excluded_tags]
