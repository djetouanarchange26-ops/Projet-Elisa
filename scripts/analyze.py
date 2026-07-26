"""
BLOC 2.5 — Pipeline complète analyze()
=======================================
Orchestre tout : PDF text → flag scores → Cox → résultat.

Usage depuis app.py :
    from scripts.analyze import analyze
    result = analyze(pdf_text)
"""

import re
import time
import numpy as np
from pathlib import Path
from collections import defaultdict

import search
import llm_confirm
from model import load_cox_model
from signals import SIGNAL_KEYWORDS, SIGNAL_PATTERNS as _SIGNAL_PATTERNS


# --- Lazy loading (chargé une seule fois, pas à chaque appel) ---
# CHOIX: variables globales au module, chargées au 1er appel
# ALT:   classe AnalyzeEngine avec __init__ → plus propre mais plus verbeux
#        ex: engine = AnalyzeEngine(); result = engine.analyze(text)
_model    = None
_index    = None
_metadata = None
_cox      = None


def _ensure_loaded():
    """Charge tous les modèles en mémoire s'ils ne le sont pas."""
    global _model, _index, _metadata, _cox

    if _model is not None:
        return  # déjà chargé

    print("⏳ Chargement des modèles...")
    t0 = time.time()

    _model, _index, _metadata = search.load_search_components()
    _cox = load_cox_model()

    print(f"✅ Modèles chargés en {time.time() - t0:.1f}s")


# ============================================================================
# DÉTECTION DE SIGNAUX
# ============================================================================

# SIGNAL_KEYWORDS / _SIGNAL_PATTERNS viennent de signals.py (source unique,
# aussi utilisée par annote.py pour ré-annoter les chunks du corpus par
# contenu réel plutôt que par héritage du flag_type du projet entier).

def _find_signals_in_document(pdf_text, context_chars=120, llm_confirm_enabled=True):
    """
    Cherche les signaux directement dans le texte du document uploadé.

    Retourne (detected, spans) :
      detected : liste de signaux agrégés, triés par nombre d'occurrences
                 (utilisée pour la carte "Detected Signals")
      spans    : liste de (start, end, flag_num) — une entrée par occurrence
                 trouvée, utilisée pour surligner le document ("Annotated
                 Document")

    llm_confirm_enabled : filtre de polarité (voir llm_confirm.py, même
    logique que search.get_flag_scores_from_chunks). Le regex trouve un mot-clé
    ("grievance", "ESAP"...) sans savoir si le passage décrit un vrai
    problème ou une situation résolue/positive sur ce même sujet — un LLM
    confirme avant de garder le signal.
    FRAGILE: un seul appel LLM par (flag_num, signal_name), sur l'extrait
    autour de la PREMIÈRE occurrence seulement (pas une par occurrence) —
    cohérent avec "un appel par signal candidat, pas par page" et avec le
    fait que l'extrait affiché à l'utilisateur ne montre déjà que cette
    première occurrence. Limite assumée : si un même mot-clé apparaît une
    fois en négatif et une fois en positif plus loin dans le document, le
    verdict du premier extrait s'applique aux deux.
    """
    detected = []
    spans = []

    for (flag_num, signal_name), pattern in _SIGNAL_PATTERNS.items():
        matches = list(pattern.finditer(pdf_text))
        if not matches:
            continue

        first = matches[0]
        start_ctx = max(0, first.start() - context_chars)
        end_ctx = min(len(pdf_text), first.end() + context_chars)
        excerpt = pdf_text[start_ctx:end_ctx].strip().replace("\n", " ")

        if llm_confirm_enabled and not llm_confirm.confirm_risk(excerpt, flag_num):
            continue  # LLM juge que ce signal est une mention conforme/positive, pas un vrai risque

        spans.extend((m.start(), m.end(), flag_num) for m in matches)

        detected.append({
            "signal":           signal_name,
            "source_flag":      flag_num,
            "occurrences":      len(matches),
            "confidence":       min(len(matches) / 5, 1.0),
            "evidence_excerpt": ("…" if start_ctx > 0 else "") + excerpt + ("…" if end_ctx < len(pdf_text) else ""),
        })

    detected.sort(key=lambda x: x["occurrences"], reverse=True)
    spans.sort(key=lambda s: s[0])
    return detected, spans


# ============================================================================
# FONCTION PRINCIPALE
# ============================================================================

def analyze(pdf_text, risk_thresholds=None, k=15):
    """
    Pipeline complète : texte brut → résultat d'analyse ESG.

    Paramètres :
      pdf_text        : str — texte extrait du PDF uploadé (via ingest.py)
      risk_thresholds : voir model.predict_risk — permet à l'UI (Settings)
                        de surcharger les seuils de grade sans redémarrer.
      k               : nombre de voisins FAISS interrogés par chunk (voir
                        search.get_flag_scores/search_similar) — réglable
                        depuis l'UI (Settings).

    Retourne :
      {
        "flag_scores":        {"flag1_community": 72.3, ...},
        "prediction":         {"probability_12m": 0.63, "risk_label": "Alerte", ...},
        "similar_passages":   [{"text": ..., "project_name": ..., ...}, ...],
        "detected_signals":   [{"signal": ..., "confidence": ..., ...}, ...],
        "signal_spans":       [(start, end, flag_num), ...],
        "recommendation":     "Escalate given confirmed community opposition..." | None,
        "processing_time_s":  12.3,
      }
    """
    _ensure_loaded()
    t_start = time.time()

    # --- Étape 1 : Flag scores via FAISS ---
    flag_scores = search.get_flag_scores(
        pdf_text, _model, _index, _metadata, k=k
    )

    # --- Étape 2 : Passages similaires (pattern library) ---
    similar_passages = search.search_similar(
        pdf_text, _model, _index, _metadata, k=k
    )

    # --- Étape 3 : Prédiction Cox ---
    from model import predict_risk
    prediction = predict_risk(
        flag_scores, _cox, horizon_months=12,        # SEUIL: horizon
        risk_thresholds=risk_thresholds,
    )

    # --- Étape 4 : Signaux détectés (dans le document uploadé lui-même) ---
    detected_signals, signal_spans = _find_signals_in_document(pdf_text)

    # --- Étape 5 : Recommandation contextualisée ---
    # CHOIX: basée sur les signaux réellement détectés (post-filtre LLM),
    # pas un template fixe par grade — voir llm_confirm.generate_recommendation.
    # None si Ollama injoignable → app.py retombe sur RECOMMENDATION_BY_GRADE.
    recommendation = llm_confirm.generate_recommendation(
        prediction["risk_grade"], prediction["probability_12m"], detected_signals,
    )

    return {
        "flag_scores":       flag_scores,
        "prediction":        prediction,
        "similar_passages":  similar_passages,
        "detected_signals":  detected_signals,
        "signal_spans":      signal_spans,
        "recommendation":    recommendation,
        "processing_time_s": round(time.time() - t_start, 2),
    }


# ============================================================================
# MAIN — test standalone
# ============================================================================

if __name__ == "__main__":
    print("=== Test analyze() ===\n")

    test_text = """
    The project has faced significant community opposition. Local communities
    have filed grievances regarding involuntary resettlement and inadequate
    consultation processes. Indigenous peoples' rights under PS7 have not been
    adequately addressed. Environmental monitoring reports indicate exceedance
    of discharge thresholds on two occasions. The ESAP action plan shows
    delays in implementing corrective measures for biodiversity offsets.
    """

    result = analyze(test_text)

    print(f"Temps de traitement : {result['processing_time_s']}s\n")
    print(f"Flag scores :")
    for k, v in result["flag_scores"].items():
        print(f"  {k}: {v:.1f}")
    print(f"\nPrédiction :")
    print(f"  Probabilité 12m : {result['prediction']['probability_12m']:.2%}")
    print(f"  Grade : {result['prediction']['risk_grade']} ({result['prediction']['risk_label']})")
    print(f"\nSignaux détectés : {len(result['detected_signals'])}")
    for s in result["detected_signals"]:
        print(f"  - {s['signal']} (confiance: {s['confidence']:.2f})")