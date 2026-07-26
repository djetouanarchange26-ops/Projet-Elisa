"""
COMPARATIF DES MODÈLES D'EMBEDDING
====================================
Chantier ouvert (voir checklist.md) : même après ré-annotation par contenu,
un texte neutre obtient un score quasi identique à un texte à risque réel.
Hypothèse à tester : le goulot d'étranglement est la capacité du modèle
d'embedding (all-MiniLM-L6-v2, 22M params, 256 tokens) à distinguer des
textes courts qui partagent le même registre "rapport ESG formel".

Ré-encode tout le corpus avec chaque modèle candidat (embeddings + FAISS en
mémoire, ne touche PAS aux fichiers models/*.npy/*.pkl utilisés par l'app en
prod), ré-entraîne un Cox sur ces embeddings, et mesure :
  - le C-index du Cox (pouvoir prédictif global)
  - le gap flag1_community entre un texte à risque et un texte neutre
    (différenciation réelle, ce qui manque aujourd'hui)

Résultats accumulés dans models/embedding_comparison.json, un modèle à la
fois, sauvegarde après CHAQUE modèle (y compris en cas d'erreur/interruption)
— une coupure de session ne fait perdre que le modèle en cours, pas les
précédents.

Usage :
    cd scripts/
    python compare_embeddings.py                              # tous les modèles pas encore testés
    python compare_embeddings.py --model all-mpnet-base-v2     # un seul modèle
    python compare_embeddings.py --force                       # reteste même les modèles déjà présents
"""

import argparse
import json
import time
import traceback
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

from model import build_training_data, train_cox
import search

BASE = Path(__file__).resolve().parent.parent
CHUNKS_PATH = BASE / "data/processed/chunks.csv"
RESULTS_PATH = BASE / "models/embedding_comparison.json"

MODELS = [
    "all-MiniLM-L6-v2",
    "all-mpnet-base-v2",
    "paraphrase-multilingual-mpnet-base-v2",
]

# CHOIX: mêmes deux textes de référence que test.py --business (Cas 1 =
# community opposition) pour le texte à risque, et un texte neutre "rapport
# de routine" au même registre formel — c'est cet écart de registre qui pose
# problème aujourd'hui (score quasi identique entre les deux).
TEXT_RISK = """
The project has faced significant community opposition. Local populations
report involuntary displacement without adequate compensation. Multiple
grievances filed through the CAO mechanism. Indigenous communities claim
violation of FPIC. Stakeholder engagement described as inadequate.
""".strip()

TEXT_NEUTRAL = """
The quarterly environmental and social monitoring report was submitted on
schedule. All performance indicators remain within the parameters agreed
with the lender. Site visits confirm continued compliance with the action
plan. No new grievances were recorded during the reporting period. Staff
refresher training on the grievance mechanism was conducted as planned.
""".strip()


def load_results():
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    return {}


def save_results(results):
    RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def evaluate_model(model_name):
    print(f"\n{'=' * 60}\n{model_name}\n{'=' * 60}")
    t0 = time.time()

    print("  Chargement du modèle...")
    model = SentenceTransformer(model_name)

    print("  Encodage du corpus...")
    chunks_df = pd.read_csv(CHUNKS_PATH)
    texts = chunks_df["text"].tolist()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
        batch_size=64,
    ).astype("float32")
    dim = embeddings.shape[1]

    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    metadata = chunks_df.reset_index(drop=True)

    print("  Entraînement Cox (flag scores par projet)...")
    training_df = build_training_data(model, index, metadata)
    cox = train_cox(training_df)

    print("  Test de différenciation (texte à risque vs texte neutre)...")
    scores_risk = search.get_flag_scores(TEXT_RISK, model, index, metadata, k=15)
    scores_neutral = search.get_flag_scores(TEXT_NEUTRAL, model, index, metadata, k=15)

    dt = time.time() - t0
    result = {
        "dimension": dim,
        "n_chunks": len(chunks_df),
        "n_projects": len(training_df),
        "n_events": int(training_df["event"].sum()),
        "c_index": round(float(cox.concordance_index_), 4),
        "scores_risk": scores_risk,
        "scores_neutral": scores_neutral,
        "gap_flag1": scores_risk["flag1_community"] - scores_neutral["flag1_community"],
        "encode_time_s": round(dt, 1),
    }
    print(
        f"\n  -> C-index={result['c_index']:.3f} | risque={scores_risk} | "
        f"neutre={scores_neutral} | gap flag1={result['gap_flag1']:+.0f} | {dt:.0f}s"
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=MODELS, help="Ne tester qu'un seul modèle")
    parser.add_argument(
        "--force", action="store_true",
        help="Reteste même les modèles déjà présents dans le fichier de résultats",
    )
    args = parser.parse_args()

    results = load_results()
    todo = [args.model] if args.model else MODELS

    for model_name in todo:
        if model_name in results and not args.force:
            print(f"[skip] {model_name} déjà testé (--force pour reforcer)")
            continue
        try:
            results[model_name] = evaluate_model(model_name)
        except Exception as e:
            print(f"[ERREUR] {model_name} : {e}")
            traceback.print_exc()
        finally:
            save_results(results)

    print("\n" + "=" * 60)
    print("RÉCAPITULATIF")
    print("=" * 60)
    for name, r in results.items():
        print(
            f"{name:45s} dim={r['dimension']:4d} C-index={r['c_index']:.3f} "
            f"risque={r['scores_risk']} neutre={r['scores_neutral']} "
            f"gap1={r['gap_flag1']:+.0f}"
        )


if __name__ == "__main__":
    main()
