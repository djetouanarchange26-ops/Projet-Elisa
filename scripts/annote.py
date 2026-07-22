"""
annotate.py — Remplit flag_type, event, time_to_event dans chunks.csv
à partir du tableur d'annotations (corpus_cao_ifc.xlsx).

Logique : chaque chunk hérite du flag de son projet.
Si un projet n'est pas dans le tableur, les colonnes restent vides.

time_to_event (mois) = durée entre T0 (date d'approbation IFC, voir
ifc_board_dates.IFC_BOARD_DATES) et la date de l'événement CAO (colonne F)
pour les projets event=1, ou entre T0 et aujourd'hui pour les projets
censurés (event=0). Sans T0 connu pour le numéro IFC, ou sans date
d'événement exploitable, time_to_event reste vide (NaN) — le projet sera
alors exclu de l'entraînement Cox (voir model.build_training_data).
"""

import numpy as np
import pandas as pd
from pathlib import Path

from ifc_board_dates import IFC_BOARD_DATES

# --- Chemins ---
base = Path("C:/Users/djeto/Desktop/Projet-Elisa")
chunks_path = base / "data/processed/chunks.csv"
excel_path = base / "data/raw/corpus_cao_ifc.xlsx"
models_path = base / "models"

TODAY = pd.Timestamp.now().normalize()


def _parse_event_date(raw):
    """Parse les dates de la colonne F, plus ou moins bien formées :
    "14 Jun 2011", "Mar 2011", "~2015". Retourne None si illisible.
    """
    s = str(raw).strip().lstrip("~").strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return pd.to_datetime(s, dayfirst=True)
    except (ValueError, TypeError):
        return None

# --- Charger les données ---
chunks = pd.read_csv(chunks_path)
annotations = pd.read_excel(excel_path)

# --- Afficher les colonnes du tableur pour vérifier ---
print("Colonnes du tableur :")
print(annotations.columns.tolist())
print(f"\n{len(annotations)} projets dans le tableur")
print(f"{len(chunks)} chunks dans le CSV\n")

# --- Construire le mapping IFC_number → annotations ---
# On crée un dict : si le project_id du chunk contient le numéro IFC, on matche
mapping = {}

for _, row in annotations.iterrows():
    ifc_numbers = str(row.iloc[1])  # Colonne B — Numéro IFC
    flag = str(row.iloc[7]) if pd.notna(row.iloc[7]) else ""  # Colonne H — Flag
    event = str(row.iloc[8]) if pd.notna(row.iloc[8]) else ""  # Colonne I — Censored
    event_date = _parse_event_date(row.iloc[5])  # Colonne F — Date plainte CAO (T_event)
    project_name = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""  # Colonne A — Nom

    # Convertir Censored en event (Censored=False → event=1, Censored=True → event=0)
    if event.lower() == "false":
        event_val = "1"
    elif event.lower() == "true":
        event_val = "0"
    else:
        event_val = ""

    # Extraire chaque numéro IFC (peut y en avoir plusieurs séparés par des virgules)
    for num in ifc_numbers.replace(" ", "").split(","):
        num = num.strip()
        if num and num != "nan" and "vérifier" not in num.lower():
            time_to_event = np.nan
            t0 = IFC_BOARD_DATES.get(num)
            if t0:
                t0_ts = pd.Timestamp(t0)
                end = event_date if event_val == "1" else TODAY
                if end is not None and end > t0_ts:
                    time_to_event = round((end - t0_ts).days / 30.44, 1)
                elif event_val == "1":
                    print(f"  [WARN] IFC {num} : event=1 mais date d'événement illisible/absente → time_to_event non calculé")
            mapping[num] = {
                "flag_type": flag,
                "event": event_val,
                "time_to_event": time_to_event,
                "project_display_name": project_name
            }

print(f"{len(mapping)} numéros IFC mappés\n")

# --- Appliquer le mapping aux chunks ---
matched = 0
unmatched_projects = set()

for idx, row in chunks.iterrows():
    project_id = str(row["project_id"])
    found = False

    # Chercher si un numéro IFC du mapping apparaît dans le project_id du chunk
    for ifc_num, info in mapping.items():
        if ifc_num in project_id:
            chunks.at[idx, "flag_type"] = info["flag_type"]
            chunks.at[idx, "event"] = info["event"]
            chunks.at[idx, "time_to_event"] = info["time_to_event"]
            matched += 1
            found = True
            break

    if not found:
        unmatched_projects.add(project_id)

print(f"Chunks annotés : {matched}/{len(chunks)}")
print(f"Chunks sans correspondance : {len(chunks) - matched}")

if unmatched_projects:
    print(f"\nProjets non trouvés dans le tableur :")
    for p in sorted(unmatched_projects):
        print(f"  - {p}")

# --- Sauvegarder ---
chunks.to_csv(chunks_path, index=False, encoding="utf-8")
print(f"\nchunks.csv mis à jour")

# Régénérer les métadonnées (même format que pipeline.py — search.py y accède via .iloc[])
chunks.to_pickle(models_path / "chunks_metadata.pkl")
print("chunks_metadata.pkl mis à jour")