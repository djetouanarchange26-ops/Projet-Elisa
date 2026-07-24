"""
BLOC 2.4 — Explication SHAP du modèle Cox
==========================================
Pourquoi le modèle donne ce score — quel flag a le plus contribué.

Conventions commentaires :
  # CHOIX:   décision d'architecture
  # ALT:     approche alternative à tester
  # SEUIL:   valeur ajustable
"""

import numpy as np
import pandas as pd
import shap
import pickle
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SHAP_BG_PATH = BASE / "models/shap_background.npy"


# ============================================================================
# CRÉATION DE L'EXPLAINER
# ============================================================================

def create_shap_explainer(cox_model, training_df):
    """
    Crée un KernelExplainer SHAP autour du modèle Cox.

    SEUIL: n_background — nombre d'observations en arrière-plan
      30  → défaut, bon compromis précision/vitesse
      15  → si trop lent (>15s par prédiction)
      50  → si beaucoup de données et tu veux plus de précision
    """
    feature_cols = ["flag1_community", "flag2_pollution", "flag3_compliance"]

    n_background = min(30, len(training_df))  # SEUIL: ajuster ici

    # CHOIX: échantillon aléatoire du training set
    # ALT:   shap.kmeans(training_df[feature_cols], 10) → résume en 10 clusters
    #         beaucoup plus rapide, légèrement moins précis
    background = training_df[feature_cols].sample(n=n_background, random_state=42)

    # Wrapper : le KernelExplainer a besoin d'une fonction f(X) → y
    # CHOIX: predict_partial_hazard = risque relatif
    # ALT:   1 - predict_survival_function(t=12) = proba d'événement à 12 mois
    #         → SHAP values seraient en unité de probabilité (plus intuitif)
    def cox_predict(X):
        df = pd.DataFrame(X, columns=feature_cols)
        return cox_model.predict_partial_hazard(df).values

    explainer = shap.KernelExplainer(cox_predict, background.values)

    # Sauvegarder le background pour ne pas recalculer
    np.save(SHAP_BG_PATH, background.values)

    return explainer


# ============================================================================
# EXPLICATION D'UNE PRÉDICTION
# ============================================================================

def explain_prediction(flag_scores, explainer):
    """
    Calcule les SHAP values pour une observation (3 flag scores).

    Retourne une liste triée par importance absolue :
      [
        {"flag": "flag1_community", "flag_label": "...", "shap_value": 0.35,
         "abs_shap_value": 0.35, "direction": "risk_increase", "score": 72.3},
        ...
      ]

    SEUIL: nsamples — nombre d'échantillons pour l'estimation SHAP
      100 → défaut (~5-10s)
      50  → rapide (~2-5s), moins précis
      500 → précis (~30s), pour le rapport final
    """
    feature_cols = ["flag1_community", "flag2_pollution", "flag3_compliance"]

    input_array = np.array([[
        flag_scores["flag1_community"],
        flag_scores["flag2_pollution"],
        flag_scores["flag3_compliance"],
    ]])

    shap_values = explainer.shap_values(input_array, nsamples=100)  # SEUIL

    # Labels lisibles pour l'interface Streamlit
    flag_labels = {
        "flag1_community":  "Community & Stakeholder Risk",
        "flag2_pollution":  "Environmental Pollution Risk",
        "flag3_compliance": "Structural Compliance Risk",
    }
    # ALT: labels en français si l'associée préfère :
    # "Risque communautaire", "Risque pollution", "Risque conformité"

    explanations = []
    for i, col in enumerate(feature_cols):
        sv = float(shap_values[0][i])
        explanations.append({
            "flag":           col,
            "flag_label":     flag_labels[col],
            "shap_value":     round(sv, 4),
            "abs_shap_value": round(abs(sv), 4),
            "direction":      "risk_increase" if sv > 0 else "risk_decrease",
            "score":          flag_scores[col],
        })

    # Trier par importance absolue décroissante
    explanations.sort(key=lambda x: x["abs_shap_value"], reverse=True)

    return explanations


# ============================================================================
# MAIN — test standalone
# ============================================================================

if __name__ == "__main__":
    from model import load_cox_model, build_training_data
    import search

    print("=== Test SHAP ===\n")

    # Charger les composants
    model_st, index, metadata = search.load_search_components()
    cox = load_cox_model()
    training_df = build_training_data(model_st, index, metadata)

    # Créer l'explainer
    explainer = create_shap_explainer(cox, training_df)

    # Test
    test_scores = {
        "flag1_community": 80.0,
        "flag2_pollution": 20.0,
        "flag3_compliance": 45.0,
    }
    result = explain_prediction(test_scores, explainer)

    print("Résultat SHAP :")
    for r in result:
        arrow = "↑" if r["direction"] == "risk_increase" else "↓"
        print(f"  {arrow} {r['flag_label']}: SHAP={r['shap_value']:+.4f} (score={r['score']:.0f})")