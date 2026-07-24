"""
annotate.py — Remplit flag_type, event, time_to_event dans chunks.csv
à partir du tableur d'annotations (corpus_cao_ifc.xlsx).

Logique : event/time_to_event sont hérités du projet (ce sont des attributs
du projet entier — a-t-il eu un événement ESG, et quand). flag_type, en
revanche, n'est PAS hérité en bloc : un chunk d'un projet "Flag 1" ne garde
"Flag 1" que si son TEXTE contient effectivement des mots-clés de cette
catégorie (via signals.flags_mentioned_in_text). Les chunks administratifs
génériques (page de garde, table des matières, procédures standard...) qui
ne mentionnent rien de spécifique au flag du projet reçoivent flag_type=""
et n'influencent plus les scores FAISS pour aucun flag.

BUG CORRIGÉ (2026-07-24) : avant, TOUS les chunks d'un projet "Flag 1"
étaient étiquetés "Flag 1", y compris le texte générique — ça bruitait
l'index FAISS (un texte neutre pouvait matcher "Flag 1" simplement parce
qu'il ressemblait à un chunk administratif d'un projet Flag 1). Voir
conversation du 2026-07-24 : le C-index restait bon sur le corpus, mais un
texte neutre de test obtenait quasiment les mêmes scores qu'un texte à
risque réel, quel que soit k (nombre de voisins FAISS).

Si un projet n'est pas dans le tableur, les colonnes restent vides.

time_to_event (mois) = durée entre T0 (date d'approbation IFC, voir
ifc_board_dates.IFC_BOARD_DATES) et la date de l'événement CAO (colonne F)
pour les projets event=1, ou entre T0 et aujourd'hui pour les projets
censurés (event=0). Sans T0 connu pour le numéro IFC, ou sans date
d'événement exploitable, time_to_event reste vide (NaN) — le projet sera
alors exclu de l'entraînement Cox (voir model.build_training_data).
"""

import re

import numpy as np
import pandas as pd
from pathlib import Path

from ifc_board_dates import IFC_BOARD_DATES
from signals import flags_mentioned_in_text

# --- Chemins ---
base = Path(__file__).resolve().parent.parent
chunks_path = base / "data/processed/chunks.csv"
excel_path = base / "data/raw/corpus_cao_ifc.xlsx"
models_path = base / "models"

TODAY = pd.Timestamp.now().normalize()


def _parse_flag_numbers(flag_str):
    """"Flag 1 + Flag 2" -> {1, 2}. "" ou NaN -> set() (ex: projets contrôle)."""
    return {int(n) for n in re.findall(r"Flag\s*(\d)", flag_str)}


def _format_flag_numbers(flag_nums):
    """{1, 2} -> "Flag 1 + Flag 2". set() -> ""."""
    return " + ".join(f"Flag {n}" for n in sorted(flag_nums))


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
    # BUG CORRIGÉ: si la colonne Censored est ambiguë (ni "true" ni "false"),
    # event_val doit rester None (→ NaN dans chunks.csv) pour que le projet
    # soit exclu par model.build_training_data (dropna(subset=["event"])).
    # Avant : event_val="" tombait dans le `else TODAY` ci-dessous comme un
    # censuré valide, produisait un time_to_event calculé à tort, et
    # crashait model.py plus tard sur int("").
    if event.lower() == "false":
        event_val = "1"
    elif event.lower() == "true":
        event_val = "0"
    else:
        event_val = None

    # Extraire chaque numéro IFC (peut y en avoir plusieurs séparés par des virgules)
    for num in ifc_numbers.replace(" ", "").split(","):
        num = num.strip()
        if num and num != "nan" and "vérifier" not in num.lower():
            time_to_event = np.nan
            t0 = IFC_BOARD_DATES.get(num)
            if t0 and event_val is not None:
                t0_ts = pd.Timestamp(t0)
                end = event_date if event_val == "1" else TODAY
                if end is not None and end > t0_ts:
                    time_to_event = round((end - t0_ts).days / 30.44, 1)
                elif event_val == "1":
                    print(f"  [WARN] IFC {num} : event=1 mais date d'événement illisible/absente → time_to_event non calculé")
            elif event_val is None:
                print(f"  [WARN] IFC {num} : colonne Censored illisible/absente → projet exclu")
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
flag_narrowed = 0  # chunks dont le flag hérité a été réduit/retiré par le contenu

for idx, row in chunks.iterrows():
    project_id = str(row["project_id"])
    found = False

    # Chercher si un numéro IFC du mapping apparaît dans le project_id du chunk
    for ifc_num, info in mapping.items():
        if ifc_num in project_id:
            project_flags = _parse_flag_numbers(info["flag_type"])

            if project_flags:
                # Le chunk ne garde que les flags du projet qu'il mentionne
                # vraiment (intersection) — pas d'invention de nouveaux flags
                # que le projet n'a pas, juste un filtrage du bruit.
                chunk_flags = flags_mentioned_in_text(str(row["text"])) & project_flags
                if chunk_flags != project_flags:
                    flag_narrowed += 1
                chunks.at[idx, "flag_type"] = _format_flag_numbers(chunk_flags)
            else:
                chunks.at[idx, "flag_type"] = info["flag_type"]  # "" pour les contrôles

            chunks.at[idx, "event"] = info["event"]
            chunks.at[idx, "time_to_event"] = info["time_to_event"]
            matched += 1
            found = True
            break

    if not found:
        unmatched_projects.add(project_id)

print(f"Chunks annotés : {matched}/{len(chunks)}")
print(f"Chunks sans correspondance : {len(chunks) - matched}")
print(f"Chunks dont le flag a été réduit par le contenu réel : {flag_narrowed}")

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