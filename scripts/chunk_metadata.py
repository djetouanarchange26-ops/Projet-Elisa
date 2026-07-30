"""
CHANTIER 1 (PROMPT_CLAUDE_CODE_ESG_V2) — Métadonnées enrichies des chunks
===========================================================================
Fonctions pures (pas d'I/O) utilisées par `ingest.py` (nouveaux documents)
et `backfill_chunk_metadata.py` (rétro-remplissage des chunks déjà dans
`chunks.csv`) pour peupler 4 champs jusqu'ici vides ou inexistants :

  - doc_date          : date du document (niveau DOCUMENT, pas chunk — voir
                        extract_doc_date, appelée une fois par document)
  - section_type      : environmental | social | governance | general
  - chunk_type        : metric | commitment | incident | narrative
  - specificity_score : float 0-1 — concret vs vague (signal ESG en soi)

FRAGILE (important) : `search.chunk_text()` reste inchangé et n'appelle
RIEN de ce module — ces métadonnées ne s'appliquent QU'AU CORPUS
(ingestion + backfill), jamais au découpage d'une requête live analyze()/
app.py, sous peine de casser la cohérence train/serve (cf.
AUDIT_ESG.md §1.2 et l'avertissement du prompt V2, Chantier 1).

Conventions commentaires (comme le reste du projet) :
  CHOIX / ALT / SEUIL / FRAGILE
"""

import re
from datetime import datetime


# ============================================================================
# 1. doc_date — niveau DOCUMENT (appelé une fois par document, pas par chunk)
# ============================================================================

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# "Dated: 14 June 2011" / "Date: June 14, 2011"
_DATE_LABELED_DMY_RE = re.compile(
    r"\b(?:date[d]?|issued|published)\s*:?\s*(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})\b", re.IGNORECASE)
_DATE_LABELED_MDY_RE = re.compile(
    r"\b(?:date[d]?|issued|published)\s*:?\s*([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE)
# "Dated: March 2020" / "June 2011" (mois + année, sans jour) — labellisée
_DATE_LABELED_MY_RE = re.compile(
    r"\b(?:date[d]?|issued|published)\s*:?\s*([A-Za-z]+)\.?\s+(\d{4})\b", re.IGNORECASE)
# Repli non labellisé : "March 2011" quelque part dans les 1ères lignes
_MONTH_YEAR_RE = re.compile(r"\b([A-Za-z]+)\.?\s+(\d{4})\b")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# SEUIL: ne cherche que dans le début du document — une date trouvée en
# page 40 n'est presque jamais la date d'émission du rapport.
_HEADER_WINDOW_CHARS = 2000


def _month_num(name):
    return _MONTHS.get(name.lower().rstrip("."))


def extract_doc_date(full_text, ifc_board_dates=None, project_id=""):
    """Devine la date d'émission d'un document (niveau DOCUMENT — à
    appeler UNE FOIS par document, pas par chunk, cf. docstring du module).

    Ordre d'essai :
      1. Motif labellisé "Date(d): DD Month YYYY" / "Month DD, YYYY" /
         "Month YYYY" dans les ~2000 premiers caractères.
      2. Repli : premier motif "Month YYYY" (non labellisé) dans la même
         fenêtre.
      3. Repli : `ifc_board_dates` (dict numéro IFC -> date ISO), si le
         numéro de projet est identifiable dans `project_id` (cf.
         `ifc_board_dates.IFC_BOARD_DATES` — date d'approbation, pas la
         date d'émission du document, mais meilleur proxy que rien).
      4. `None` si tout échoue — PAS de date inventée (cf. AUDIT_ESG.md,
         "Chantier 0" : on ne fabrique pas de date non vérifiée).

    Retourne une chaîne ISO (YYYY-MM-DD) ou None. Quand seul mois+année
    sont connus (pas de jour), le jour est fixé au 1er du mois — convention
    documentée ici, pas une vraie date d'émission précise au jour près.
    """
    header = (full_text or "")[:_HEADER_WINDOW_CHARS]

    m = _DATE_LABELED_DMY_RE.search(header)
    if m:
        day, month_name, year = m.groups()
        month = _month_num(month_name)
        if month:
            try:
                return datetime(int(year), month, int(day)).strftime("%Y-%m-%d")
            except ValueError:
                pass

    m = _DATE_LABELED_MDY_RE.search(header)
    if m:
        month_name, day, year = m.groups()
        month = _month_num(month_name)
        if month:
            try:
                return datetime(int(year), month, int(day)).strftime("%Y-%m-%d")
            except ValueError:
                pass

    m = _DATE_LABELED_MY_RE.search(header)
    if m:
        month_name, year = m.groups()
        month = _month_num(month_name)
        if month:
            return f"{year}-{month:02d}-01"

    m = _MONTH_YEAR_RE.search(header)
    if m:
        month_name, year = m.groups()
        month = _month_num(month_name)
        if month and 1900 <= int(year) <= 2100:
            return f"{year}-{month:02d}-01"

    if ifc_board_dates:
        nums = re.findall(r"\d{4,}", project_id or "")
        for n in nums:
            if n in ifc_board_dates:
                return ifc_board_dates[n]

    return None


# ============================================================================
# 2. section_type — par CHUNK
# ============================================================================

# CHOIX: dictionnaire de mots-clés pondérés, construit à partir de
# signals.SIGNAL_KEYWORDS (déjà partagé analyze.py/annote.py/app.py) +
# vocabulaire ESG/IFC Performance Standards additionnel classique. Pas de
# LLM ici (le prompt le demande explicitement) — juste des heuristiques
# bon marché, cohérentes avec le reste du pipeline de classification.
SECTION_KEYWORDS = {
    "environmental": {
        "emission": 2, "ghg": 2, "greenhouse gas": 2, "carbon": 1.5, "co2": 2,
        "biodiversity": 2, "habitat": 2, "critical habitat": 2.5, "species": 1,
        "water": 1, "effluent": 2, "discharge": 1.5, "pollut": 2, "contaminat": 2,
        "waste": 1.5, "hazardous material": 2, "spill": 2, "air quality": 1.5,
        "noise": 1, "energy efficiency": 1.5, "climate": 1.5, "deforestation": 2,
        "wastewater": 2, "soil": 1, "groundwater": 1.5, "ps3": 2, "ps6": 2.5,
    },
    "social": {
        "community": 2, "communities": 2, "resettlement": 2.5, "involuntary": 2,
        "livelihood": 2, "indigenous": 2.5, "land acquisition": 2, "labor": 1.5,
        "labour": 1.5, "working conditions": 2, "health and safety": 2,
        "occupational health": 2, "grievance": 1.5, "stakeholder": 1,
        "consultation": 1, "gender": 1.5, "child labor": 2.5, "forced labor": 2.5,
        "cultural heritage": 2, "vulnerable": 1.5, "affected people": 2,
        "ps1": 1, "ps2": 2, "ps4": 2, "ps5": 2.5, "ps7": 2.5, "ps8": 2,
    },
    "governance": {
        "compliance": 2, "non-compliance": 2.5, "esap": 2, "action plan": 1,
        "monitoring report": 1.5, "audit": 2, "board": 1.5, "transparency": 2,
        "disclosure": 1.5, "grievance mechanism": 2, "anti-corruption": 2.5,
        "whistleblower": 2.5, "regulatory": 1.5, "performance standard": 1,
        "supervision": 1, "review and management": 1, "policy": 1,
        "management system": 1.5, "oversight": 1.5, "reporting requirement": 2,
    },
}
# ALT: catégories supplémentaires si besoin (ex: "economic") — pas demandé
# par le prompt V2, volontairement laissé à 3 catégories + "general".

_SECTION_PATTERNS = {
    section: {kw: re.compile(re.escape(kw), re.IGNORECASE) for kw in kws}
    for section, kws in SECTION_KEYWORDS.items()
}

# SEUIL: en dessous de ce score total (toutes catégories confondues), le
# chunk est trop générique/administratif pour être classé — "general".
_SECTION_MIN_SCORE = 1.5


def classify_section_type(text):
    """Classe un chunk dans environmental / social / governance / general
    par somme de poids de mots-clés (pas de ML, cf. consigne du prompt).
    "general" si aucune catégorie ne dépasse un score minimal (intro,
    conclusion, contexte non spécifique, texte administratif)."""
    scores = {}
    for section, patterns in _SECTION_PATTERNS.items():
        scores[section] = sum(weight * len(patterns[kw].findall(text))
                               for kw, weight in SECTION_KEYWORDS[section].items()
                               for _ in [patterns[kw]])
    best_section = max(scores, key=scores.get)
    if scores[best_section] < _SECTION_MIN_SCORE:
        return "general"
    return best_section


# ============================================================================
# 3. chunk_type — par CHUNK (type rhétorique)
# ============================================================================

# Unités de mesure/quantités concrètes -> signal "metric"
_METRIC_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|mw|kw|gwh|mwh|km2?|ha|hectares?|"
    r"tons?|tonnes?|kg|m3|m³|usd|\$|eur|€|db|ppm|mg/l|µg|ug)\b", re.IGNORECASE)
_NUMBER_DENSE_RE = re.compile(r"\d+(?:[.,]\d+)?")

# Engagements/promesses -> signal "commitment"
_COMMITMENT_RE = re.compile(
    r"\b(?:will\s+\w+|commit(?:s|ted|ment)?\s+to|plans?\s+to|"
    r"intends?\s+to|aims?\s+to|targets?\s+(?:of|to)|by\s+20\d{2}|"
    r"is\s+expected\s+to|shall\s+\w+)\b", re.IGNORECASE)

# Incidents/problèmes -> signal "incident" (recoupe signals.py volontairement :
# un incident réel utilise souvent le même vocabulaire que les flags de risque)
_INCIDENT_RE = re.compile(
    r"\b(?:complaint|grievance|incident|accident|spill|violation|breach|"
    r"non-?compliance|exceed(?:ance|ed|s)?|protest|opposition|damage|"
    r"injury|fatality|leak(?:age)?|contamination\s+(?:event|occurred)|"
    r"reported\s+(?:an?\s+)?(?:incident|issue|problem))\b", re.IGNORECASE)

_CHUNK_TYPE_MIN_SCORE = 2  # SEUIL: en dessous, "narrative" par défaut


def classify_chunk_type(text):
    """Classe le type rhétorique d'un chunk : metric / commitment /
    incident / narrative (repli si aucun signal ne dépasse le seuil).
    Priorité : incident > metric > commitment — un chunk qui décrit un
    incident AVEC des chiffres (ex: "200 liters spilled") est d'abord un
    signal d'incident, pas juste une métrique neutre."""
    incident_score = len(_INCIDENT_RE.findall(text))
    metric_score = len(_METRIC_RE.findall(text)) * 2 + len(_NUMBER_DENSE_RE.findall(text)) * 0.3
    commitment_score = len(_COMMITMENT_RE.findall(text))

    if incident_score * 2 >= _CHUNK_TYPE_MIN_SCORE:  # pondéré plus fort : signal rare mais très informatif
        return "incident"
    scores = {"metric": metric_score, "commitment": commitment_score}
    best = max(scores, key=scores.get)
    if scores[best] < _CHUNK_TYPE_MIN_SCORE:
        return "narrative"
    return best


# ============================================================================
# 4. specificity_score — par CHUNK (float 0-1)
# ============================================================================

# Formulations évasives/hedging — pénalisent le score. Recoupe en partie le
# vocabulaire Pass 2/3 du prompt V2 (Chantier 3, "formulations évasives").
_HEDGING_RE = re.compile(
    r"\b(?:may|might|could|as\s+appropriate|where\s+possible|where\s+feasible|"
    r"in\s+due\s+course|aims?\s+to|aspires?\s+to|strive[sd]?\s+to|"
    r"reasonable\s+efforts?|best\s+efforts?|to\s+the\s+extent\s+possible|"
    r"as\s+needed|if\s+necessary|endeavou?rs?\s+to|is\s+committed\s+to\s+"
    r"exploring|will\s+consider|subject\s+to\s+(?:availability|feasibility))\b",
    re.IGNORECASE)

# Marqueurs concrets : chiffres/unités (cf. _METRIC_RE), années/dates précises,
# entités nommées approximées par séquences de mots capitalisés hors début de
# phrase (heuristique simple, pas de vrai NER — cf. consigne "pas besoin de ML").
_YEAR_TOKEN_RE = re.compile(r"\b(19|20)\d{2}\b")
_CAPITALIZED_SEQ_RE = re.compile(r"(?<!^)(?<![.!?]\s)\b[A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,}){0,2}\b")

# SEUILS: coefficients de mise à l'échelle — ratio (marqueurs / mots) est
# petit par nature (rarement >20% des mots d'un chunk), donc amplifié avant
# clamp à [0,1]. Choix empirique, pas statistiquement calibré (corpus trop
# petit pour ça, cf. AUDIT_ESG.md §1.4) — mais monotone et reproductible.
_CONCRETE_WEIGHT = 18.0
_HEDGING_WEIGHT = 22.0


def compute_specificity_score(text):
    """Score 0-1 : à quel point un chunk est concret (chiffres précis,
    dates, unités de mesure, entités nommées) vs vague (formulations
    évasives, absence de métrique). CE SCORE EST UN SIGNAL ESG EN SOI —
    voir prompt V2, Chantier 1 : un rapport plein de chunks à faible
    spécificité est un red flag de greenwashing.
    """
    words = text.split()
    word_count = max(len(words), 1)

    concrete = (
        len(_METRIC_RE.findall(text)) * 2
        + len(_YEAR_TOKEN_RE.findall(text))
        + len(_CAPITALIZED_SEQ_RE.findall(text)) * 0.5
    )
    hedging = len(_HEDGING_RE.findall(text))

    raw = (concrete / word_count) * _CONCRETE_WEIGHT - (hedging / word_count) * _HEDGING_WEIGHT
    return round(max(0.0, min(1.0, raw)), 3)
