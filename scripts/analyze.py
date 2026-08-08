"""
BLOC 2.5 — Pipeline complète analyze()
=======================================
Orchestre tout : PDF text → flag scores → Cox → résultat.

Usage depuis app.py :
    from scripts.analyze import analyze
    result = analyze(pdf_text)
"""

import re
import threading
import time
import numpy as np
from pathlib import Path
from collections import defaultdict

import search
import llm_confirm
import deep_analysis
from model import compute_grade
from signals import SIGNAL_KEYWORDS, SIGNAL_PATTERNS as _SIGNAL_PATTERNS


# --- Lazy loading (chargé une seule fois, pas à chaque appel) ---
# CHOIX: variables globales au module, chargées au 1er appel
# ALT:   classe AnalyzeEngine avec __init__ → plus propre mais plus verbeux
#        ex: engine = AnalyzeEngine(); result = engine.analyze(text)
#
# DIRECTIVE_CLAUDE_CODE_ESG_V3, Tier 0 — @st.cache_resource (suggéré par la
# directive) est redondant ici, PAS ajouté : app.py n'appelle jamais
# search.load_search_components() directement, seulement via analyze() →
# _ensure_loaded(), qui joue déjà ce rôle (singleton au niveau module,
# chargé une fois par process, comme @st.cache_resource l'aurait fait).
# Empiler les deux chargerait les modèles en double sans bénéfice. Seul vrai
# trou vérifié : sans verrou, deux premières requêtes Streamlit concurrentes
# (plusieurs sessions sur le VPS, Phase 1 §1.3) pouvaient toutes les deux
# voir _model is None et déclencher un chargement en double → _lock corrige
# ça.
# CHANTIER SIMPLIFICATION PIPELINE (2026-08-08) : plus de _cox — compute_grade()
# (model.py) n'a pas de modèle à charger, juste des seuils (DEFAULT_RISK_THRESHOLDS).
_lock     = threading.Lock()
_model    = None
_index    = None
_metadata = None


def _ensure_loaded():
    """Charge tous les modèles en mémoire s'ils ne le sont pas (une seule
    fois par process, thread-safe)."""
    global _model, _index, _metadata

    if _model is not None:
        return  # déjà chargé

    with _lock:
        if _model is not None:
            return  # chargé par un autre thread pendant l'attente du verrou

        print("⏳ Chargement des modèles...")
        t0 = time.time()

        _model, _index, _metadata = search.load_search_components()

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

def analyze(pdf_text, risk_thresholds=None, k=15, document_label="Document analysé"):
    """
    Pipeline complète : texte brut → résultat d'analyse ESG.

    Paramètres :
      pdf_text        : str — texte extrait du PDF uploadé (via ingest.py)
      risk_thresholds : voir model.compute_grade — permet à l'UI (Settings)
                        de surcharger les seuils de grade sans redémarrer.
      k               : nombre de voisins FAISS interrogés par chunk (voir
                        search.get_flag_scores/search_similar) — réglable
                        depuis l'UI (Settings).
      document_label  : nom du projet/document affiché dans la synthèse
                        Pass 3 du pipeline LLM multi-pass (Chantier 3) —
                        optionnel, app.py ne le passe pas encore (Chantier 4).

    Retourne :
      {
        "flag_scores":        {"flag1_community": 72.3, ...},
        "prediction":         {"risk_score": 72, "risk_label": "Alerte",
                                "risk_grade": "B"} — voir model.compute_grade
                                (CHANTIER SIMPLIFICATION PIPELINE, 2026-08-08 :
                                plus de probability_12m/survival_curve, le
                                Cox est retiré).
        "similar_passages":   [{"text": ..., "project_name": ..., ...}, ...],
        "detected_signals":   [{"signal": ..., "confidence": ..., ...}, ...],
        "signal_spans":       [(start, end, flag_num), ...],
        "recommendation":     "Escalate given confirmed community opposition..." | None,
        "deep_analysis":      {"enabled": bool, "pass1_findings": [...],
                                "omissions": [...] | None, "synthesis": str | None,
                                "project_type": str | None} — voir deep_analysis.py
                                (Chantier 3). "enabled": False ou champs à None
                                si config.DEEP_ANALYSIS_ENABLED est désactivé ou
                                qu'Ollama est injoignable (fail-open, jamais
                                d'exception propagée jusqu'ici).
        "processing_time_s":  12.3,
      }
    """
    _ensure_loaded()
    t_start = time.time()

    # --- Étape 1+2 : Flag scores + passages similaires (pattern library) ---
    # AUDIT (2026-08-06, checklist.md) : un seul appel plutôt que
    # get_flag_scores() + search_similar() séparés — les deux opéraient sur
    # les mêmes chunks de CE document et recalculaient chacun tout le
    # re-ranking indépendamment. Mesuré : ~46% du temps total d'analyze()
    # gaspillé en travail dupliqué sur un document réel de 171 chunks.
    # search.analyze_query() calcule le scoring une seule fois et en dérive
    # les deux résultats.
    flag_scores, similar_passages = search.analyze_query(
        pdf_text, _model, _index, _metadata, k=k
    )

    # --- Étape 3 : Grade ESG (CHANTIER SIMPLIFICATION PIPELINE, 2026-08-08) ---
    # Remplace la prédiction Cox — plus de modèle à charger, juste des seuils
    # sur max(flag_scores), cf. model.compute_grade.
    prediction = compute_grade(flag_scores, risk_thresholds=risk_thresholds)

    # --- Étape 4 : Signaux détectés (dans le document uploadé lui-même) ---
    detected_signals, signal_spans = _find_signals_in_document(pdf_text)

    # --- Étape 5 : Recommandation contextualisée ---
    # CHOIX: basée sur les signaux réellement détectés (post-filtre LLM),
    # pas un template fixe par grade — voir llm_confirm.generate_recommendation.
    # None si le LLM est injoignable → app.py retombe sur RECOMMENDATION_BY_GRADE.
    recommendation = llm_confirm.generate_recommendation(
        prediction["risk_grade"], detected_signals,
    )

    # --- Étape 6 : Pipeline d'analyse LLM multi-pass (CHANTIER 3) ---
    # CHOIX: après la prédiction/les signaux — la Pass 3 (synthèse) en a
    # besoin. Ne lève jamais d'exception (cf. deep_analysis.run_deep_analysis) :
    # dégradé gracieusement à {"enabled": False, ...} si désactivé, ou à des
    # champs None/[] passe par passe si le LLM est injoignable en cours de
    # route — le reste du résultat (flag_scores, recommendation...) reste
    # valide dans tous les cas.
    deep = deep_analysis.run_deep_analysis(
        pdf_text, document_label, prediction["risk_grade"],
        detected_signals,
    )

    return {
        "flag_scores":       flag_scores,
        "prediction":        prediction,
        "similar_passages":  similar_passages,
        "detected_signals":  detected_signals,
        "signal_spans":      signal_spans,
        "recommendation":    recommendation,
        "deep_analysis":     deep,
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
    print(f"  Score : {result['prediction']['risk_score']}/100")
    print(f"  Grade : {result['prediction']['risk_grade']} ({result['prediction']['risk_label']})")
    print(f"\nSignaux détectés : {len(result['detected_signals'])}")
    for s in result["detected_signals"]:
        print(f"  - {s['signal']} (confiance: {s['confidence']:.2f})")