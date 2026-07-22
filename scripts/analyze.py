"""
BLOC 2.5 — Pipeline complète analyze()
=======================================
Orchestre tout : PDF text → flag scores → Cox → SHAP → résultat.

Usage depuis app.py :
    from scripts.analyze import analyze
    result = analyze(pdf_text)
"""

import time
import numpy as np
from pathlib import Path
from collections import defaultdict

import search
from model import load_cox_model, build_training_data
from explain import create_shap_explainer, explain_prediction


# --- Lazy loading (chargé une seule fois, pas à chaque appel) ---
# CHOIX: variables globales au module, chargées au 1er appel
# ALT:   classe AnalyzeEngine avec __init__ → plus propre mais plus verbeux
#        ex: engine = AnalyzeEngine(); result = engine.analyze(text)
_model     = None
_index     = None
_metadata  = None
_cox       = None
_explainer = None


def _ensure_loaded():
    """Charge tous les modèles en mémoire s'ils ne le sont pas."""
    global _model, _index, _metadata, _cox, _explainer

    if _model is not None:
        return  # déjà chargé

    print("⏳ Chargement des modèles...")
    t0 = time.time()

    _model, _index, _metadata = search.load_search_components()
    _cox = load_cox_model()

    # SHAP explainer a besoin du training data pour le background
    # CHOIX: on recalcule le training_df à chaque démarrage
    # ALT:   sauvegarder training_df dans un .pkl pour accélérer le startup
    #         training_df.to_pickle(BASE / "models/training_df.pkl")
    #         puis pd.read_pickle(...) ici
    training_df = build_training_data(_model, _index, _metadata)
    _explainer = create_shap_explainer(_cox, training_df)

    print(f"✅ Modèles chargés en {time.time() - t0:.1f}s")


# ============================================================================
# DÉTECTION DE SIGNAUX
# ============================================================================

def _extract_signals(passages, flag_scores):
    """
    Extrait les signaux détectés à partir des passages similaires.

    CHOIX: recherche de mots-clés prédéfinis dans les passages.
    ALT:   zero-shot classification avec un modèle NLP (plus précis, plus lent)
    ALT:   appeler un LLM pour résumer les passages en signaux (le plus précis)

    TODO: enrichir ces listes avec le feedback de ton associée
    """
    signal_keywords = {
        1: {
            "community opposition":  ["opposition", "protest", "community", "resist", "grievance"],
            "displacement risk":     ["displace", "resettle", "relocat", "involuntary", "land acquisition"],
            "stakeholder conflict":  ["stakeholder", "conflict", "indigenous", "livelihood", "affected people"],
            "consultation gaps":     ["consultation", "FPIC", "consent", "engagement", "participation"],
        },
        2: {
            "pollution risk":        ["pollut", "contaminat", "emission", "discharge", "effluent"],
            "monitoring gaps":       ["monitor", "threshold", "exceedance", "baseline", "sampling"],
            "spill risk":            ["spill", "leak", "seepage", "tailings", "waste"],
        },
        3: {
            "biodiversity threat":   ["biodiversity", "habitat", "critical habitat", "PS6", "endangered", "species"],
            "ESAP delays":           ["ESAP", "action plan", "delay", "overdue", "non-compliance"],
            "PS non-conformance":    ["performance standard", "PS1", "PS2", "PS3", "PS4", "PS5", "PS7", "PS8"],
        },
    }
    # ALT: ajouter des catégories supplémentaires :
    # 4: {"governance risk": ["governance", "board", "transparency", "audit"]}

    detected = []
    seen = set()

    for passage in passages:
        # FRAGILE: flag_type vient de chunks.csv sous forme de chaîne
        # ("Flag 1", "Flag 2 + Flag 3", ...), pas d'un int — un passage peut
        # donc matcher plusieurs flags. Même logique de matching que
        # search.get_flag_scores().
        flag_str = str(passage.get("flag_type", ""))
        text_lower = passage["text"].lower()

        for flag_num, keywords_by_signal in signal_keywords.items():
            if f"Flag {flag_num}" not in flag_str:
                continue

            for signal_name, keywords in keywords_by_signal.items():
                if signal_name in seen:
                    continue
                if any(kw.lower() in text_lower for kw in keywords):
                    detected.append({
                        "signal":           signal_name,
                        "source_flag":      flag_num,
                        "confidence":       passage["score"],
                        "evidence_excerpt": passage["text"][:150] + "...",
                    })
                    seen.add(signal_name)

    detected.sort(key=lambda x: x["confidence"], reverse=True)
    return detected


# ============================================================================
# FONCTION PRINCIPALE
# ============================================================================

def analyze(pdf_text):
    """
    Pipeline complète : texte brut → résultat d'analyse ESG.

    Paramètres :
      pdf_text : str — texte extrait du PDF uploadé (via ingest.py)

    Retourne :
      {
        "flag_scores":        {"flag1_community": 72.3, ...},
        "prediction":         {"probability_12m": 0.63, "risk_label": "Alerte", ...},
        "shap_explanations":  [{"flag": ..., "shap_value": ..., ...}, ...],
        "similar_passages":   [{"text": ..., "project_name": ..., ...}, ...],
        "detected_signals":   [{"signal": ..., "confidence": ..., ...}, ...],
        "processing_time_s":  12.3,
      }
    """
    _ensure_loaded()
    t_start = time.time()

    # --- Étape 1 : Flag scores via FAISS ---
    flag_scores = search.get_flag_scores(
        pdf_text, _model, _index, _metadata, k=15   # SEUIL: k
    )

    # --- Étape 2 : Passages similaires (pattern library) ---
    similar_passages = search.search_similar(
        pdf_text, _model, _index, _metadata, k=15   # SEUIL: k
    )

    # --- Étape 3 : Prédiction Cox ---
    from model import predict_risk
    prediction = predict_risk(
        flag_scores, _cox, horizon_months=12         # SEUIL: horizon
    )

    # --- Étape 4 : Explication SHAP ---
    shap_explanations = explain_prediction(flag_scores, _explainer)

    # --- Étape 5 : Signaux détectés ---
    detected_signals = _extract_signals(similar_passages, flag_scores)

    return {
        "flag_scores":       flag_scores,
        "prediction":        prediction,
        "shap_explanations": shap_explanations,
        "similar_passages":  similar_passages,
        "detected_signals":  detected_signals,
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
    print(f"\nSHAP :")
    for e in result["shap_explanations"]:
        arrow = "↑" if e["direction"] == "risk_increase" else "↓"
        print(f"  {arrow} {e['flag_label']}: {e['shap_value']:+.4f}")
    print(f"\nSignaux détectés : {len(result['detected_signals'])}")
    for s in result["detected_signals"]:
        print(f"  - {s['signal']} (confiance: {s['confidence']:.2f})")