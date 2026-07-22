"""
SUITE DE TESTS MVP
==================
3 niveaux :
  1. Tests unitaires      — chaque fichier/composant isolé
  2. Tests d'intégration  — pipeline bout en bout
  3. Tests de cohérence   — les résultats ont-ils du sens métier ?

Usage :
    cd scripts/
    python tests.py              # lance tout
    python tests.py --unit       # unitaires seulement
    python tests.py --integ      # intégration seulement
    python tests.py --business   # cohérence métier seulement
"""

import sys
import time
import numpy as np
import pandas as pd
from pathlib import Path

# --- Chemins ---
BASE = Path("C:/Users/djeto/Desktop/Projet-Elisa")
CHUNKS_PATH      = BASE / "data/processed/chunks.csv"
EMBEDDING_PATH   = BASE / "models/embeddings.npy"
METADATA_PATH    = BASE / "models/chunks_metadata.pkl"
FAISS_INDEX_PATH = BASE / "models/faiss_index.bin"
COX_MODEL_PATH   = BASE / "models/cox_model.pkl"
ANNOTATIONS_PATH = BASE / "data/raw/corpus_cao_ifc.xlsx"

# Compteurs globaux
_passed = 0
_failed = 0
_warnings = 0


def _test(name, condition, msg_fail="", warning_only=False):
    global _passed, _failed, _warnings
    if condition:
        print(f"  ✅ {name}")
        _passed += 1
    elif warning_only:
        print(f"  ⚠️  {name} — {msg_fail}")
        _warnings += 1
    else:
        print(f"  ❌ {name} — {msg_fail}")
        _failed += 1


# ============================================================================
# 1. TESTS UNITAIRES
# ============================================================================

def test_unit():
    print("\n--- 1. Tests unitaires ---\n")

    # 1.1 Fichiers nécessaires
    _test("chunks.csv existe",      CHUNKS_PATH.exists(),      f"Manquant : {CHUNKS_PATH}")
    _test("embeddings.npy existe",  EMBEDDING_PATH.exists(),   f"Manquant : {EMBEDDING_PATH}")
    _test("metadata.pkl existe",    METADATA_PATH.exists(),    f"Manquant : {METADATA_PATH}")
    _test("faiss_index.bin existe", FAISS_INDEX_PATH.exists(), f"Manquant : {FAISS_INDEX_PATH}")
    _test("cox_model.pkl existe",   COX_MODEL_PATH.exists(),   f"Manquant : {COX_MODEL_PATH}")
    _test("annotations existe",     ANNOTATIONS_PATH.exists(), f"Manquant : {ANNOTATIONS_PATH}")

    # 1.2 Intégrité chunks.csv
    if CHUNKS_PATH.exists():
        chunks = pd.read_csv(CHUNKS_PATH)
        required_cols = ["project_name", "text", "chunk_id"]
        _test("chunks.csv colonnes requises",
              all(c in chunks.columns for c in required_cols),
              f"Colonnes : {list(chunks.columns)}")
        _test("chunks.csv > 100 lignes",
              len(chunks) > 100,
              f"Seulement {len(chunks)} lignes",
              warning_only=True)
        _test("Pas de texte vide",
              chunks["text"].notna().all() and (chunks["text"].str.len() > 10).all(),
              "Chunks avec texte vide ou trop court")

    # 1.3 Cohérence embeddings / chunks
    if EMBEDDING_PATH.exists() and CHUNKS_PATH.exists():
        embs = np.load(EMBEDDING_PATH)
        n_chunks = len(pd.read_csv(CHUNKS_PATH))
        _test("Embeddings shape cohérente",
              embs.shape[0] == n_chunks,
              f"embeddings={embs.shape[0]} vs chunks={n_chunks}")
        _test("Dimension = 384",
              embs.shape[1] == 384,
              f"Dimension = {embs.shape[1]}")
        norms = np.linalg.norm(embs[:10], axis=1)
        _test("Normalisés L2",
              np.allclose(norms, 1.0, atol=0.01),
              f"Norme moyenne = {norms.mean():.3f}")

    # 1.4 Modèle Cox
    if COX_MODEL_PATH.exists():
        from model import load_cox_model
        cox = load_cox_model()
        _test("Cox a 3 features",
              len(cox.params_) == 3,
              f"Features : {list(cox.params_.index)}")
        _test("C-index > 0.55 (mieux que le hasard)",
              cox.concordance_index_ > 0.55,
              f"C-index = {cox.concordance_index_:.3f}",
              warning_only=True)
        _test("C-index > 0.6 (acceptable MVP)",
              cox.concordance_index_ > 0.6,
              f"C-index = {cox.concordance_index_:.3f}",
              warning_only=True)


# ============================================================================
# 2. TESTS D'INTÉGRATION
# ============================================================================

def test_integration():
    print("\n--- 2. Tests d'intégration ---\n")

    try:
        import search
        from model import load_cox_model, predict_risk
        from explain import create_shap_explainer, explain_prediction
        from analyze import analyze

        model, index, metadata = search.load_search_components()
        cox = load_cox_model()

        # 2.1 Flag scores
        test_text = """
        Community opposition around the project. Grievances filed regarding
        involuntary resettlement. Indigenous peoples rights not addressed.
        """
        scores = search.get_flag_scores(test_text, model, index, metadata)
        _test("Flag scores → 3 valeurs",  len(scores) == 3)
        _test("Flag scores 0–100",
              all(0 <= v <= 100 for v in scores.values()),
              f"Scores : {scores}")
        _test("Texte communautaire → flag1 domine",
              scores["flag1_community"] >= scores["flag2_pollution"],
              f"f1={scores['flag1_community']:.1f} vs f2={scores['flag2_pollution']:.1f}",
              warning_only=True)

        # 2.2 Prédiction Cox
        pred = predict_risk(scores, cox)
        expected_keys = ["probability_12m", "risk_label", "risk_grade", "survival_curve"]
        _test("Prédiction toutes les clés",
              all(k in pred for k in expected_keys))
        _test("Probabilité ∈ [0, 1]",
              0 <= pred["probability_12m"] <= 1,
              f"prob = {pred['probability_12m']}")
        _test("Grade valide",
              pred["risk_grade"] in ["A", "B", "C", "D"],
              f"grade = {pred['risk_grade']}")

        # 2.3 SHAP
        from model import build_training_data
        training_df = build_training_data(model, index, metadata)
        explainer = create_shap_explainer(cox, training_df)
        shap_exp = explain_prediction(scores, explainer)
        _test("SHAP → 3 explications",   len(shap_exp) == 3)
        _test("SHAP values sont floats", all(isinstance(e["shap_value"], float) for e in shap_exp))

        # 2.4 Pipeline complète
        t0 = time.time()
        result = analyze(test_text)
        dt = time.time() - t0
        expected_result_keys = [
            "flag_scores", "prediction", "shap_explanations",
            "similar_passages", "detected_signals", "processing_time_s",
        ]
        _test("analyze() toutes les clés",
              all(k in result for k in expected_result_keys))
        _test(f"analyze() < 45s (actuel: {dt:.1f}s)",
              dt < 45,
              "Trop lent → réduire SHAP n_background ou nsamples",
              warning_only=True)

    except Exception as e:
        print(f"  ❌ Erreur d'intégration : {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# 3. TESTS DE COHÉRENCE MÉTIER (bloc 3.2 de la roadmap)
# ============================================================================

def test_business():
    print("\n--- 3. Tests de cohérence métier ---\n")

    try:
        from analyze import analyze

        # --- CAS 1 : Community Opposition (haut risque) ---
        text_community = """
        The project has faced significant community opposition. Local populations
        report involuntary displacement without adequate compensation. Multiple
        grievances filed through the CAO mechanism. Indigenous communities claim
        violation of FPIC. Stakeholder engagement described as inadequate.
        """

        # --- CAS 2 : ESAP Delays (risque moyen) ---
        text_esap = """
        The ESAP action plan shows delays in implementation of corrective measures.
        Several environmental monitoring commitments are overdue. Non-compliance
        with PS1 requirements on assessment and management. Pollution discharge
        thresholds exceeded on two occasions. Remediation plan not yet submitted.
        """

        # --- CAS 3 : Biodiversity Risk (haut risque flag3) ---
        text_biodiversity = """
        The project area overlaps with a critical habitat for endangered species.
        PS6 requirements for biodiversity management have not been fully met.
        No adequate biodiversity offset program established. Environmental impact
        assessment did not properly identify all species at risk. Habitat
        fragmentation concerns raised by independent environmental review.
        """

        # --- CAS 4 : Projet propre (bas risque) ---
        text_clean = """
        The project's environmental and social management system is fully operational.
        Regular monitoring reports demonstrate compliance with all Performance Standards.
        Community feedback mechanisms are active with positive stakeholder sentiment.
        Biodiversity offset program is on track. ESAP actions completed ahead of schedule.
        """

        # Analyser chaque cas
        print("  Analyse des 4 cas de test...")
        r1 = analyze(text_community)
        r2 = analyze(text_esap)
        r3 = analyze(text_biodiversity)
        r4 = analyze(text_clean)

        # Résumé visuel
        print(f"\n  Cas 1 (Community Opposition) : {r1['prediction']['risk_grade']} "
              f"({r1['prediction']['risk_label']}) — prob={r1['prediction']['probability_12m']:.2%}")
        print(f"  Cas 2 (ESAP Delays)          : {r2['prediction']['risk_grade']} "
              f"({r2['prediction']['risk_label']}) — prob={r2['prediction']['probability_12m']:.2%}")
        print(f"  Cas 3 (Biodiversity Risk)    : {r3['prediction']['risk_grade']} "
              f"({r3['prediction']['risk_label']}) — prob={r3['prediction']['probability_12m']:.2%}")
        print(f"  Cas 4 (Projet propre)        : {r4['prediction']['risk_grade']} "
              f"({r4['prediction']['risk_label']}) — prob={r4['prediction']['probability_12m']:.2%}")

        # Vérifications
        _test("Cas 1 (risque) > Cas 4 (propre)",
              r1["prediction"]["probability_12m"] > r4["prediction"]["probability_12m"],
              f"{r1['prediction']['probability_12m']:.2f} vs {r4['prediction']['probability_12m']:.2f}")

        _test("Cas 1 = grade A ou B",
              r1["prediction"]["risk_grade"] in ["A", "B"],
              f"Grade = {r1['prediction']['risk_grade']}",
              warning_only=True)

        _test("Cas 4 = grade C ou D",
              r4["prediction"]["risk_grade"] in ["C", "D"],
              f"Grade = {r4['prediction']['risk_grade']}",
              warning_only=True)

        _test("Cas 1 : signaux détectés",
              len(r1["detected_signals"]) > 0,
              "Aucun signal — vérifier les mots-clés dans analyze._extract_signals")

        # SHAP cohérence
        top_shap_1 = r1["shap_explanations"][0]
        _test("Cas 1 SHAP : flag1 domine",
              top_shap_1["flag"] == "flag1_community",
              f"Top = {top_shap_1['flag']}",
              warning_only=True)

        top_shap_3 = r3["shap_explanations"][0]
        _test("Cas 3 SHAP : flag3 domine",
              top_shap_3["flag"] == "flag3_compliance",
              f"Top = {top_shap_3['flag']}",
              warning_only=True)

        # Ordonnancement global
        probs = [r1["prediction"]["probability_12m"],
                 r2["prediction"]["probability_12m"],
                 r3["prediction"]["probability_12m"],
                 r4["prediction"]["probability_12m"]]
        _test("Cas propre a la probabilité la plus basse",
              probs[3] == min(probs),
              f"Probas : community={probs[0]:.2f} esap={probs[1]:.2f} "
              f"bio={probs[2]:.2f} propre={probs[3]:.2f}",
              warning_only=True)

    except Exception as e:
        print(f"  ❌ Erreur tests métier : {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# RÉSUMÉ + MAIN
# ============================================================================

def print_summary():
    total = _passed + _failed + _warnings
    print("\n" + "=" * 60)
    print(f"RÉSULTATS : {_passed}/{total} passés, {_failed} échecs, {_warnings} warnings")
    if _failed == 0:
        print("🎉 Tous les tests critiques passent !")
    else:
        print("🔴 Des tests critiques ont échoué — à corriger avant la démo")
    print("=" * 60)


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--unit" in args:
        test_unit()
    elif "--integ" in args:
        test_integration()
    elif "--business" in args:
        test_business()
    else:
        # Tout lancer
        test_unit()
        test_integration()
        test_business()

    print_summary()