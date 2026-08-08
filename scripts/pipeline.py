"""
PIPELINE DE RÉ-ENTRAÎNEMENT
============================
À lancer après chaque ajout de nouveaux projets au corpus.

Usage :
    cd scripts/
    python pipeline.py

Séquence :
    1. Charger le modèle d'embedding
    2. Encoder les chunks → embeddings.npy
    3. Construire l'index FAISS → faiss_index.bin

CHANTIER SIMPLIFICATION PIPELINE (2026-08-08, directive) : les anciennes
étapes 4 (flag scores par projet) et 5 (entraînement Cox) sont retirées —
elles ne servaient qu'à `model.build_training_data`/`train_cox`, plus
utilisés (le grade est maintenant une règle sur max(flag_scores), voir
model.compute_grade, pas un modèle entraîné). Gain de temps direct : cette
étape faisait tourner get_flag_scores_from_chunks (donc tout le
retrieval/scoring) sur les 4203 chunks du corpus à chaque ré-entraînement.
"""

import time
import faiss
import numpy as np
import pandas as pd
from pathlib import Path
from sentence_transformers import SentenceTransformer

# --- Chemins ---
BASE = Path(__file__).resolve().parent.parent
CHUNKS_PATH      = BASE / "data/processed/chunks.csv"
EMBEDDING_PATH   = BASE / "models/embeddings.npy"
METADATA_PATH    = BASE / "models/chunks_metadata.pkl"
FAISS_INDEX_PATH = BASE / "models/faiss_index.bin"


def retrain():
    """Pipeline complète de ré-entraînement."""
    print("=" * 60)
    print("PIPELINE DE RÉ-ENTRAÎNEMENT")
    print("=" * 60)
    t_total = time.time()

    # ------------------------------------------------------------------
    # Étape 1 : Modèle d'embedding
    # ------------------------------------------------------------------
    print("\n[1/3] Chargement du modèle d'embedding...")
    model = SentenceTransformer("all-mpnet-base-v2")
    # CHOIX (2026-07-25): bascule depuis all-MiniLM-L6-v2 — dimension 768,
    # plus précis, adopté sans confirmation chiffrée que ça règle le
    # problème de différenciation sur texte externe (comparatif interrompu
    # volontairement, voir checklist.md "Chantier ouvert"). Plus lent à
    # l'entraînement (~768 dim vs 384) mais l'inférence live reste ~instantanée.
    # ALT: un modèle fine-tuné sur du texte ESG/finance si tu en trouves un

    # ------------------------------------------------------------------
    # Étape 2 : Encoder les chunks
    # ------------------------------------------------------------------
    print("[2/3] Encodage des chunks...")
    chunks_df = pd.read_csv(CHUNKS_PATH)
    texts = chunks_df["text"].tolist()

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,    # L2 normalization → cosine similarity
        show_progress_bar=True,
        batch_size=64,                # SEUIL: ajuster selon ta RAM
    )
    np.save(EMBEDDING_PATH, embeddings)
    print(f"  → {embeddings.shape[0]} chunks, dimension {embeddings.shape[1]}")

    # ------------------------------------------------------------------
    # Étape 3 : Index FAISS
    # ------------------------------------------------------------------
    print("[3/3] Construction de l'index FAISS...")
    dim = embeddings.shape[1]

    # CHOIX: IndexFlatIP — recherche exacte, cosine similarity
    # ALT:   IndexIVFFlat → plus rapide pour >100k chunks (nécessite .train())
    # ALT:   IndexHNSWFlat → bon compromis vitesse/précision pour >50k chunks
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings.astype("float32"))
    faiss.write_index(index, str(FAISS_INDEX_PATH))
    print(f"  → Index : {index.ntotal} vecteurs")

    # Sauvegarder les métadonnées associées
    # CHOIX: DataFrame (pas une liste de dicts) — search.py indexe via .iloc[]
    # FRAGILE: flag_type reste une chaîne ("Flag 1", "Flag 2 + Flag 3", ...)
    #          telle que produite par annote.py — ne pas la caster en int.
    metadata = chunks_df.reset_index(drop=True)
    metadata.to_pickle(METADATA_PATH)

    # ------------------------------------------------------------------
    # Résumé
    # ------------------------------------------------------------------
    dt = time.time() - t_total
    print("\n" + "=" * 60)
    print("✅ PIPELINE TERMINÉE")
    print(f"  Chunks       : {len(chunks_df)}")
    print(f"  Temps total  : {dt:.1f}s")
    print("=" * 60)

    return metadata


if __name__ == "__main__":
    retrain()