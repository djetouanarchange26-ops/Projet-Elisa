"""
CALIBRATION DES SEUILS DE GRADE — CHANTIER SIMPLIFICATION PIPELINE (2026-08-08)
================================================================================
Vérifie que DEFAULT_RISK_THRESHOLDS (model.py, seuils sur max(flag_scores),
0-100) sépare correctement les 46 projets connus du corpus : les 28 projets
à événement doivent tomber majoritairement en grade A/B (pire, cf. convention
conservée dans model.py), les 18 contrôles majoritairement en C/D (meilleur).

Réutilise model.build_training_data() (code mort pour le Cox, mais la
fonction elle-même reste valide : elle calcule juste les flag scores par
projet via search.get_flag_scores_from_chunks) — pas de nouveau calcul de
scoring ici, juste la classification par seuil appliquée après coup.

ATTENTION : lance jusqu'à MAX_CONFIRM_RISK_CALLS (30) appels LLM par projet
(confirm_risk), soit potentiellement 40+ minutes sur 46 projets même avec un
backend cloud rapide — à lancer une fois, pas en boucle.

Usage :
    cd scripts/
    python calibrate_thresholds.py
"""

import pandas as pd

import search
from model import build_training_data, compute_grade, DEFAULT_RISK_THRESHOLDS


def calibrate():
    model, index, metadata = search.load_search_components()

    print("Calcul des flag scores pour les 46 projets connus (peut prendre du temps)...")
    training_df = build_training_data(model, index, metadata)

    training_df["max_flag_score"] = training_df[
        ["flag1_community", "flag2_pollution", "flag3_compliance"]
    ].max(axis=1)
    training_df["grade"] = training_df["max_flag_score"].apply(
        lambda s: compute_grade(
            {"flag1_community": s, "flag2_pollution": 0, "flag3_compliance": 0},
            risk_thresholds=DEFAULT_RISK_THRESHOLDS,
        )["risk_grade"]
    )

    print("\n" + training_df[["project_name", "max_flag_score", "event", "grade"]]
          .sort_values("max_flag_score", ascending=False).to_string(index=False))

    events = training_df[training_df["event"] == 1]
    controls = training_df[training_df["event"] == 0]

    events_ab = (events["grade"].isin(["A", "B"])).sum()
    controls_cd = (controls["grade"].isin(["C", "D"])).sum()

    print(f"\n--- RÉSUMÉ ---")
    print(f"Événements ({len(events)}) en grade A/B : {events_ab}/{len(events)} "
          f"({events_ab / len(events):.0%})")
    print(f"Contrôles ({len(controls)}) en grade C/D : {controls_cd}/{len(controls)} "
          f"({controls_cd / len(controls):.0%})")
    print(f"\nDistribution grades événements : {events['grade'].value_counts().to_dict()}")
    print(f"Distribution grades contrôles  : {controls['grade'].value_counts().to_dict()}")

    if events_ab / len(events) < 0.5 or controls_cd / len(controls) < 0.5:
        print("\n⚠️  Seuils (15/35/60) probablement à ajuster — moins de la moitié "
              "des événements/contrôles du bon côté. Regarde la distribution "
              "ci-dessus pour choisir de nouvelles valeurs.")
    else:
        print("\n✅ Séparation raisonnable avec les seuils actuels.")


if __name__ == "__main__":
    calibrate()
