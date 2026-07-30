"""
CHANTIER 2 (PROMPT_CLAUDE_CODE_ESG_V2) — Re-ranking cross-encoder post-FAISS
================================================================================
FAISS remonte les chunks les plus proches par similarité cosine (lexico-
sémantique) — pas nécessairement les plus pertinents ANALYTIQUEMENT (cf.
AUDIT_ESG.md §1.2). Ce module re-score un lot de candidats FAISS avec un
cross-encoder (attention croisée requête/candidat — plus précis mais plus
lent qu'un simple produit scalaire) puis combine ce score avec les
métadonnées de chunk_metadata.py (Chantier 1) : récence du document,
spécificité, type rhétorique.

CHOIX: cross-encoder/ms-marco-MiniLM-L-6-v2 (pas le L-12, plus lourd) —
mesuré sur cette machine : ~0.07s pour re-scorer 7 paires en batch, largement
sous le budget "<2s pour 30 candidats" du prompt.

FRAGILE: les logits bruts de ce cross-encoder ne sont PAS bornés à [0,1] et
leur échelle varie fortement d'une requête à l'autre (mesuré : de -9 à +5.6
selon la requête) — une sigmoïde fixe écraserait quasiment tous les scores
près de 0 et rendrait le poids ALPHA_CROSS_ENCODER inopérant. On normalise
donc en min-max PAR LOT (les scores d'un même appel rerank(), pas globalement)
— le meilleur candidat du lot vaut ~1.0, le pire ~0.0, ce qui est cohérent
avec l'usage (comparer des candidats entre eux, pas une probabilité absolue).

Feature flag : config.RERANKER_ENABLED — désactivable sans casser
search.py (repli sur l'ordre FAISS brut d'origine, comportement
pré-Chantier 2).
"""

from datetime import datetime

from sentence_transformers import CrossEncoder

import config

_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_model = None

# --- Score composite (SEUIL: poids ajustables, cf. prompt V2 Chantier 2) ---
ALPHA_CROSS_ENCODER = 0.5   # pertinence sémantique profonde (cross-encoder)
BETA_SPECIFICITY = 0.2      # les chunks concrets pèsent plus (Chantier 1)
GAMMA_RECENCY = 0.2         # les documents récents pèsent plus (doc_date)
DELTA_CHUNK_TYPE = 0.1      # bonus/malus selon le type rhétorique du chunk

RECENCY_HALF_LIFE_YEARS = 3.0  # SEUIL: demi-vie de la décroissance de récence

CHUNK_TYPE_BOOST = {"metric": 0.2, "incident": 0.2, "commitment": 0.0, "narrative": -0.1}
# ALT: chunk_type absent (candidat pré-Chantier 1 ou métadonnée manquante) -> 0.0 (neutre)


def _ensure_loaded():
    global _model
    if _model is None:
        _model = CrossEncoder(_CROSS_ENCODER_MODEL)
    return _model


def _safe_float(val, default):
    """`val` peut être None, NaN (pandas), ou une vraie valeur — repli
    neutre plutôt que de planter sur un candidat aux métadonnées
    incomplètes (ex: chunk du corpus avant le backfill Chantier 1)."""
    try:
        f = float(val)
        return default if f != f else f  # f != f <=> NaN
    except (TypeError, ValueError):
        return default


def _recency_score(doc_date_str):
    """Décroissance exponentielle, demi-vie ~3 ans. 0.5 (neutre) si
    doc_date absent ou illisible — pas de pénalité injuste pour un
    document sans date connue."""
    if not doc_date_str or not isinstance(doc_date_str, str):
        return 0.5
    try:
        doc_date = datetime.strptime(doc_date_str[:10], "%Y-%m-%d")
    except ValueError:
        return 0.5
    age_years = max((datetime.now() - doc_date).days / 365.25, 0)
    return 0.5 ** (age_years / RECENCY_HALF_LIFE_YEARS)


def _normalize_cross_scores(raw_scores):
    """Min-max PAR LOT — voir FRAGILE dans la docstring du module pour le
    pourquoi (pas une sigmoïde fixe)."""
    lo, hi = min(raw_scores), max(raw_scores)
    if hi - lo < 1e-9:  # tous identiques (lot de taille 1, ou cas dégénéré)
        return [0.5 for _ in raw_scores]
    return [(s - lo) / (hi - lo) for s in raw_scores]


def rerank(query_text, candidates, top_k=10):
    """
    Re-score `candidates` (issus d'un retrieval FAISS élargi, cf. search.py)
    par pertinence analytique vis-à-vis de `query_text`, puis garde les
    `top_k` meilleurs selon le score composite.

    `candidates` : liste de dicts portant au moins "text" — "doc_date"/
    "chunk_type"/"specificity_score" sont utilisés s'ils sont présents
    (Chantier 1), sinon valeurs neutres (cf. _safe_float/_recency_score/
    CHUNK_TYPE_BOOST.get(..., 0.0)) — un candidat sans ces métadonnées
    n'est donc pas pénalisé, juste moins différencié.

    Retourne les candidats triés par "rerank_score" décroissant (champ
    ajouté à chaque dict) — "score" (similarité FAISS d'origine) reste
    inchangé, pour comparaison/débogage.
    """
    if not config.RERANKER_ENABLED or not candidates:
        return candidates[:top_k]

    model = _ensure_loaded()
    pairs = [(query_text, c["text"]) for c in candidates]
    raw_scores = model.predict(pairs)
    cross_scores = _normalize_cross_scores(raw_scores)

    for c, cross_score in zip(candidates, cross_scores):
        specificity = _safe_float(c.get("specificity_score"), 0.5)
        recency = _recency_score(c.get("doc_date"))
        chunk_boost = CHUNK_TYPE_BOOST.get(c.get("chunk_type"), 0.0)

        raw = (
            ALPHA_CROSS_ENCODER * cross_score
            + BETA_SPECIFICITY * specificity
            + GAMMA_RECENCY * recency
            + DELTA_CHUNK_TYPE * chunk_boost
        )
        # CHOIX: clampé à [0,1] — flag_scores (search.py) multiplie ce score
        # par 100 pour l'échelle 0-100 attendue par le modèle Cox/l'UI ; sans
        # ça DELTA_CHUNK_TYPE négatif ou une somme > 1.0 produirait un score
        # hors bornes (ex: 105/100).
        c["rerank_score"] = max(0.0, min(1.0, raw))

    candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
    return candidates[:top_k]
