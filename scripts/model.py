"""
BLOC 2.3 — Entraînement Cox PH + Prédiction de risque ESG
==========================================================
Conventions commentaires :
  # CHOIX:   décision d'architecture
  # ALT:     approche alternative à tester
  # SEUIL:   valeur ajustable
  # FRAGILE: point sensible
"""

import pandas as pd
import numpy as np
import pickle
from pathlib import Path
from collections import defaultdict
from lifelines import CoxPHFitter

# On importe search.py (même dossier scripts/)
import search

# --- Chemins ---
BASE = Path(__file__).resolve().parent.parent
CHUNKS_PATH      = BASE / "data/processed/chunks.csv"
ANNOTATIONS_PATH = BASE / "data/raw/corpus_cao_ifc.xlsx"   # ton tableur CAO/IFC
EMBEDDING_PATH   = BASE / "models/embeddings.npy"
METADATA_PATH    = BASE / "models/chunks_metadata.pkl"
FAISS_INDEX_PATH = BASE / "models/faiss_index.bin"
COX_MODEL_PATH   = BASE / "models/cox_model.pkl"


# ============================================================================
# CODE MORT — build_training_data()/train_cox() (retiré du pipeline actif,
# 2026-08-08, cf. le bandeau "CODE MORT" plus bas pour le détail). Conservé
# sur disque, plus appelé par pipeline.py.
# ============================================================================

def build_training_data(model, index, metadata):
    """
    Pour chaque projet déjà annoté dans chunks.csv (via annote.py) :
      1. Concatène tous ses chunks
      2. Calcule les 3 flag scores via FAISS (search.py)
      3. Récupère time_to_event et event

    Retourne un DataFrame prêt pour CoxPHFitter.

    FRAGILE: on ne lit plus corpus_cao_ifc.xlsx ici — ses colonnes ("B —
    Numéro IFC", "H — Flag", ...) ne correspondent pas à project_name/
    time_to_event/event attendus. chunks.csv porte déjà flag_type/event/
    time_to_event par chunk (hérités du projet via annote.py), donc on
    part de là.

    Les projets sans time_to_event calculable (T0 IFC inconnu, ou date
    d'événement illisible — voir annote.py) sont exclus avec un avertissement
    plutôt que de faire planter l'entraînement Cox.
    """
    chunks_df = pd.read_csv(CHUNKS_PATH)

    # Regrouper les chunks par projet
    project_texts = defaultdict(list)
    for _, row in chunks_df.iterrows():
        project_texts[row["project_name"]].append(str(row["text"]))

    # Un projet = les chunks déjà annotés (event + time_to_event) par annote.py
    annotated = chunks_df.dropna(subset=["event"]).drop_duplicates("project_name")
    usable = annotated.dropna(subset=["time_to_event"])

    skipped = set(annotated["project_name"]) - set(usable["project_name"])
    for proj_name in sorted(skipped):
        print(f"  [WARN] Projet '{proj_name}' sans time_to_event exploitable → skip")

    if usable.empty:
        raise NotImplementedError(
            "time_to_event manquant pour tous les projets annotés. Vérifie "
            "ifc_board_dates.IFC_BOARD_DATES et les dates de la colonne F "
            "de corpus_cao_ifc.xlsx."
        )

    annotated = usable

    records = []
    for _, ann in annotated.iterrows():
        proj_name = ann["project_name"]

        # CHOIX: on interroge directement avec les chunks déjà existants du
        # projet (déjà dimensionnés à ~175 mots par ingest.py) plutôt que de
        # les recoller en un seul texte puis les re-découper — évite un
        # travail redondant et garde les frontières de chunk d'origine.
        # exclude_project : le projet est lui-même dans l'index FAISS, sans
        # ce filtre chaque chunk se retrouverait "plus proche voisin de
        # lui-même" (score ~1.0), une fuite de données qui gonfle les scores
        # d'entraînement indépendamment de toute similarité avec d'autres
        # projets.
        scores = search.get_flag_scores_from_chunks(
            project_texts[proj_name], model, index, metadata, k=15,
            exclude_project=proj_name,
        )

        records.append({
            "project_id":       ann.get("project_id", proj_name),
            "project_name":     proj_name,
            "flag1_community":  scores["flag1_community"],
            "flag2_pollution":  scores["flag2_pollution"],
            "flag3_compliance": scores["flag3_compliance"],
            "time_to_event":    ann["time_to_event"],
            "event":            int(ann["event"]),
        })

    df = pd.DataFrame(records)
    print(f"  Dataset : {len(df)} projets, {df['event'].sum()} événements")
    return df


# ============================================================================
# ENTRAÎNEMENT COX
# ============================================================================

def train_cox(training_df):
    """
    Entraîne un CoxPHFitter sur les 3 flag scores.

    SEUIL: penalizer — régularisation L2
      0.1  → défaut, bon compromis
      0.5  → si très peu de données (<20 projets)
      0.01 → si beaucoup de données (>100 projets)
    """
    feature_cols = ["flag1_community", "flag2_pollution", "flag3_compliance"]
    fit_cols = feature_cols + ["time_to_event", "event"]

    # Vérifications
    assert training_df["time_to_event"].min() > 0, \
        "time_to_event doit être > 0 pour tous les projets"
    assert set(training_df["event"].unique()).issubset({0, 1}), \
        "event doit être 0 ou 1"

    cph = CoxPHFitter(
        penalizer=0.1,   # SEUIL: augmenter si convergence échoue
        l1_ratio=0.0,    # CHOIX: pure L2. ALT: 0.5 pour elastic net
    )

    try:
        cph.fit(
            training_df[fit_cols],
            duration_col="time_to_event",
            event_col="event",
            show_progress=False,
        )
    except Exception as e:
        print(f"  [ERREUR] Convergence Cox : {e}")
        print("  → Augmente penalizer (0.5 ou 1.0)")
        print("  → Vérifie que time_to_event a assez de variance")
        raise

    print("\n--- RÉSUMÉ MODÈLE COX ---")
    cph.print_summary()
    print(f"\n  C-index : {cph.concordance_index_:.3f}")

    # SEUIL: c-index > 0.6 = acceptable MVP, > 0.7 = bon, < 0.55 = hasard
    if cph.concordance_index_ < 0.55:
        print("  ⚠️  C-index < 0.55 — le modèle ne discrimine pas.")

    return cph


# ============================================================================
# PRÉDICTION
# ============================================================================

# CHANTIER SIMPLIFICATION PIPELINE (2026-08-08, directive) : le Cox est
# retiré (46 projets, coefficients flag2/flag3 non significatifs, décalage
# train/serve non résolu — cf. checklist.md). compute_grade() le remplace,
# voir plus bas. DEFAULT_RISK_THRESHOLDS change donc de sémantique : avant
# des seuils de PROBABILITÉ Cox (0-1), maintenant des seuils sur max(flag_scores)
# (0-100, même échelle que les flag scores eux-mêmes). Convention conservée :
# A = pire (Escalade), D = meilleur (Vigilance) — comme avant, pour ne pas
# inverser la lecture du grade pour Elisa/le Portfolio Dashboard.
# À calibrer sur les 46 cas connus du corpus (28 événements/18 contrôles) —
# valeurs initiales, voir checklist.md pour la vérification post-déploiement.
DEFAULT_RISK_THRESHOLDS = [
    (15,  "Vigilance", "D"),     # max flag score < 15
    (35,  "Attention", "C"),     # 15–35
    (60,  "Alerte",    "B"),     # 35–60
    (101, "Escalade",  "A"),     # > 60
]


def compute_grade(flag_scores, risk_thresholds=None):
    """
    Grade ESG à partir du max des 3 flag scores (0-100) — remplace le
    modèle Cox (CHANTIER SIMPLIFICATION PIPELINE, 2026-08-08). Pas de
    probabilité d'événement : juste un grade/label transparent et ajustable
    (contrairement au Cox, fragile sur 46 projets avec des coefficients
    flag2/flag3 non significatifs).

    Paramètres :
      flag_scores     : dict avec flag1_community, flag2_pollution, flag3_compliance (0-100)
      risk_thresholds : liste [(seuil_score, label, grade), ...] triée par
                        seuil croissant — voir DEFAULT_RISK_THRESHOLDS. Permet
                        à l'UI (Settings) de surcharger les seuils sans
                        toucher au code (même mécanisme qu'avant).

    Retourne :
      {
        "risk_score":  int,    # max(flag_scores), 0-100
        "risk_label":  str,    # Vigilance / Attention / Alerte / Escalade
        "risk_grade":  str,    # D / C / B / A
      }
    """
    risk_thresholds = risk_thresholds or DEFAULT_RISK_THRESHOLDS
    max_score = max(flag_scores.values())

    risk_label, risk_grade = "Escalade", "A"
    for threshold, label, grade in risk_thresholds:
        if max_score < threshold:
            risk_label, risk_grade = label, grade
            break

    return {
        "risk_score": round(max_score),
        "risk_label": risk_label,
        "risk_grade": risk_grade,
    }


# ============================================================================
# CODE MORT — modèle Cox (retiré du pipeline actif, 2026-08-08)
# ============================================================================
# Conservé sur disque (pas supprimé) au cas où le Cox serait ré-envisagé
# plus tard avec plus de données — plus importé/appelé nulle part ailleurs
# depuis ce chantier. build_training_data()/train_cox()/save_cox_model()/
# load_cox_model()/predict_risk() ci-dessous n'ont plus d'appelant. ATTENTION
# si tu les réactives : predict_risk() attend des risk_thresholds au format
# probabilité (0-1) — PAS compatible avec les valeurs de DEFAULT_RISK_THRESHOLDS
# ci-dessus (0-100, format flag score), qui ont changé de sémantique pour
# compute_grade().


def predict_risk(flag_scores, cox_model, horizon_months=12, risk_thresholds=None):
    """
    Prédit le risque ESG à partir des 3 flag scores.

    Paramètres :
      flag_scores     : dict avec flag1_community, flag2_pollution, flag3_compliance
      cox_model       : CoxPHFitter entraîné
      horizon_months  : horizon de prédiction
      risk_thresholds : liste [(seuil_proba, label, grade), ...] triée par
                        seuil croissant — voir DEFAULT_RISK_THRESHOLDS.
                        Permet à l'UI (Settings) de surcharger les seuils
                        sans toucher au code.

    Retourne :
      {
        "probability_12m": float,
        "risk_label": str,          # Vigilance / Attention / Alerte / Escalade
        "risk_grade": str,          # D / C / B / A
        "survival_curve": dict,     # {mois: P(survie)}
        "hazard_ratios": dict,
      }
    """
    input_df = pd.DataFrame([{
        "flag1_community":  flag_scores["flag1_community"],
        "flag2_pollution":  flag_scores["flag2_pollution"],
        "flag3_compliance": flag_scores["flag3_compliance"],
    }])

    # Courbe de survie
    surv_func = cox_model.predict_survival_function(input_df)
    times = surv_func.index.values

    # Probabilité à l'horizon
    if horizon_months > times.max():
        surv_at_horizon = float(surv_func.iloc[-1, 0])
        print(f"  [WARN] Horizon {horizon_months}m > max données ({times.max():.0f}m)")
    else:
        surv_at_horizon = float(
            np.interp(horizon_months, times, surv_func.iloc[:, 0].values)
        )

    prob_event = 1.0 - surv_at_horizon

    # --- SEUILS DE CLASSIFICATION ---
    risk_thresholds = risk_thresholds or DEFAULT_RISK_THRESHOLDS

    risk_label, risk_grade = "Escalade", "A"
    for threshold, label, grade in risk_thresholds:
        if prob_event < threshold:
            risk_label, risk_grade = label, grade
            break

    # Courbe de survie pour le graphique Streamlit
    # CHOIX: tous les points. ALT: sous-échantillonner à 1/mois
    survival_curve = {float(t): float(s) for t, s in
                      zip(times, surv_func.iloc[:, 0].values)}

    return {
        "probability_12m": round(prob_event, 4),
        "risk_label":      risk_label,
        "risk_grade":      risk_grade,
        "survival_curve":  survival_curve,
        "hazard_ratios":   cox_model.summary["exp(coef)"].to_dict(),
    }


# ============================================================================
# SAUVEGARDE / CHARGEMENT
# ============================================================================

def save_cox_model(cox_model):
    with open(COX_MODEL_PATH, "wb") as f:
        pickle.dump(cox_model, f)
    print(f"  Modèle sauvegardé → {COX_MODEL_PATH}")


def load_cox_model():
    with open(COX_MODEL_PATH, "rb") as f:
        return pickle.load(f)


# ============================================================================
# MAIN — lancer directement pour entraîner
# ============================================================================

if __name__ == "__main__":
    print("=== Entraînement du modèle Cox ===\n")

    # Charger les composants de search.py
    model, index, metadata = search.load_search_components()

    # Construire le dataset
    training_df = build_training_data(model, index, metadata)
    print(training_df[["project_name", "flag1_community", "flag2_pollution",
                        "flag3_compliance", "event"]].to_string())

    # Entraîner
    cox = train_cox(training_df)
    save_cox_model(cox)

    # Test rapide
    print("\n--- Test de prédiction ---")
    test_scores = {
        "flag1_community": 75.0,
        "flag2_pollution": 30.0,
        "flag3_compliance": 50.0,
    }
    result = predict_risk(test_scores, cox)
    print(f"  Probabilité 12m : {result['probability_12m']:.2%}")
    print(f"  Grade : {result['risk_grade']} ({result['risk_label']})")


