"""
Écrit les dates d'approbation IFC (ifc_board_dates.IFC_BOARD_DATES) dans la
colonne E ("Date ESRS (T0)") de corpus_cao_ifc.xlsx, pour traçabilité.

À relancer si de nouveaux numéros sont ajoutés à IFC_BOARD_DATES (par
exemple après avoir enrichi le corpus avec de nouveaux projets).

Usage :
    cd scripts/
    python fill_t0_dates.py
"""

import openpyxl
from pathlib import Path

from ifc_board_dates import IFC_BOARD_DATES

BASE = Path(__file__).resolve().parent.parent
XLSX_PATH = BASE / "data/raw/corpus_cao_ifc.xlsx"

COL_IFC_NUM = 2   # colonne B
COL_T0      = 5   # colonne E


def fill_t0_dates():
    wb = openpyxl.load_workbook(XLSX_PATH)
    ws = wb.active

    filled = 0
    for row in ws.iter_rows(min_row=2):
        raw_nums = row[COL_IFC_NUM - 1].value
        if not raw_nums:
            continue

        nums = [n.strip() for n in str(raw_nums).replace(" ", "").split(",")]
        dates = [IFC_BOARD_DATES[n] for n in nums if n in IFC_BOARD_DATES]

        if not dates:
            continue

        # CHOIX: une seule cellule T0 par ligne — si la ligne référence
        # plusieurs numéros IFC (ex: "33557, 36699"), on affiche les deux
        # dates séparées par une virgule (alignées avec la colonne B),
        # mais le calcul réel de time_to_event (annote.py) utilise
        # IFC_BOARD_DATES par numéro, pas cette colonne.
        row[COL_T0 - 1].value = ", ".join(dates)
        filled += 1

    wb.save(XLSX_PATH)
    print(f"T0 rempli pour {filled} lignes → {XLSX_PATH}")


if __name__ == "__main__":
    fill_t0_dates()
