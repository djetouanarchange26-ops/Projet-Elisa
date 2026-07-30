"""
CHANTIER 1 (PROMPT_CLAUDE_CODE_ESG_V2) — Rétro-remplissage des métadonnées
============================================================================
`ingest.py` peuple désormais `doc_date`/`section_type`/`chunk_type`/
`specificity_score` pour les NOUVEAUX documents, mais les 4203 chunks déjà
dans `chunks.csv` (corpus ingéré avant ce chantier) n'ont que des colonnes
`doc_date` vides et pas du tout `section_type`/`chunk_type`/
`specificity_score`. Ce script les calcule rétroactivement, une seule fois.

- `section_type`/`chunk_type`/`specificity_score` : calculés directement
  depuis la colonne `text` déjà présente dans chunks.csv (rien à relire).
- `doc_date` : recalculé au niveau DOCUMENT (pas chunk, cf.
  chunk_metadata.extract_doc_date) — nécessite de relire le texte complet
  du fichier corpus d'origine (`corpus/{project_id}`). Un seul document lu
  par projet (pas par chunk), avec cache en mémoire.

FRAGILE : certains fichiers du corpus original (PDF) ne sont plus présents
dans `corpus/` (seuls les .txt le sont au moment de cet audit — voir
AUDIT_ESG.md §1.1) — pour ces project_id, `doc_date` reste vide plutôt que
de planter (repli sur `ifc_board_dates.IFC_BOARD_DATES` déjà géré par
`extract_doc_date`, donc pas totalement vide pour les projets IFC connus).

Usage :
    cd scripts/
    python backfill_chunk_metadata.py --dry-run   # vérifie sans écrire
    python backfill_chunk_metadata.py              # écrit chunks.csv + régénère chunks_metadata.pkl
"""

import argparse
from pathlib import Path

import pandas as pd

from chunk_metadata import extract_doc_date, classify_section_type, classify_chunk_type, compute_specificity_score
from ifc_board_dates import IFC_BOARD_DATES

BASE = Path(__file__).resolve().parent.parent
CHUNKS_PATH = BASE / "data/processed/chunks.csv"
METADATA_PKL_PATH = BASE / "models/chunks_metadata.pkl"
CORPUS_DIR = BASE / "corpus"

_doc_date_cache = {}


def _doc_date_for_project(project_id):
    """Une lecture par project_id (pas par chunk) — le fichier corpus
    d'origine peut faire plusieurs Mo, pas question de le rouvrir 4203 fois."""
    if project_id in _doc_date_cache:
        return _doc_date_cache[project_id]

    path = CORPUS_DIR / project_id
    full_text = ""
    if path.exists() and path.suffix.lower() == ".txt":
        full_text = path.read_text(encoding="utf-8", errors="ignore")
    # FRAGILE: pas de ré-extraction PDF ici (OCR coûteux, pdfplumber pas
    # importé dans ce script) — pour un project_id .pdf absent/non relu,
    # extract_doc_date() retombe quand même sur IFC_BOARD_DATES via le
    # numéro de projet dans project_id, cf. sa docstring.

    result = extract_doc_date(full_text, IFC_BOARD_DATES, project_id) or ""
    _doc_date_cache[project_id] = result
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Calcule et affiche un résumé, n'écrit rien")
    args = parser.parse_args()

    df = pd.read_csv(CHUNKS_PATH)
    print(f"{len(df)} chunks à traiter, {df['project_id'].nunique()} documents distincts")

    for col in ("section_type", "chunk_type", "specificity_score"):
        if col not in df.columns:
            df[col] = None

    df["doc_date"] = df["doc_date"].astype(object)  # colonne vide lue comme float64 (NaN) sinon
    missing_date_mask = df["doc_date"].isna() | (df["doc_date"] == "")
    print(f"  doc_date manquant : {missing_date_mask.sum()} chunks")

    df["section_type"] = df["text"].apply(lambda t: classify_section_type(str(t)))
    df["chunk_type"] = df["text"].apply(lambda t: classify_chunk_type(str(t)))
    df["specificity_score"] = df["text"].apply(lambda t: compute_specificity_score(str(t)))

    if missing_date_mask.any():
        df.loc[missing_date_mask, "doc_date"] = df.loc[missing_date_mask, "project_id"].apply(_doc_date_for_project)

    print("\n--- Résumé ---")
    print("section_type:\n", df["section_type"].value_counts().to_string())
    print("\nchunk_type:\n", df["chunk_type"].value_counts().to_string())
    print(f"\nspecificity_score: moyenne={df['specificity_score'].mean():.3f}, "
          f"médiane={df['specificity_score'].median():.3f}")
    n_with_date = (df["doc_date"].astype(str).str.len() > 0).sum()
    print(f"\ndoc_date renseigné : {n_with_date}/{len(df)} chunks "
          f"({df.groupby('project_id')['doc_date'].first().astype(str).str.len().gt(0).sum()}/"
          f"{df['project_id'].nunique()} documents)")

    if args.dry_run:
        print("\n[DRY-RUN] chunks.csv et chunks_metadata.pkl non modifiés")
        return

    df.to_csv(CHUNKS_PATH, index=False, encoding="utf-8")
    print(f"\n{CHUNKS_PATH} mis à jour ({len(df)} lignes, colonnes : {list(df.columns)})")

    # Régénère les métadonnées (même format que pipeline.py/annote.py —
    # search.py y accède via .iloc[]).
    df.to_pickle(METADATA_PKL_PATH)
    print(f"{METADATA_PKL_PATH} régénéré")


if __name__ == "__main__":
    main()
