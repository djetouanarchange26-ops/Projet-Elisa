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
    4. Calculer les flag scores par projet
    5. Entraîner le modèle Cox → cox_model.pkl
"""

import time
import faiss
import numpy as np
import pandas as pd
from pathlib import Path
from sentence_transformers import SentenceTransformer

from model import build_training_data, train_cox, save_cox_model

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
    print("\n[1/5] Chargement du modèle d'embedding...")
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
    print("[2/5] Encodage des chunks...")
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
    print("[3/5] Construction de l'index FAISS...")
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
    # Étape 4 : Dataset d'entraînement (flag scores par projet)
    # ------------------------------------------------------------------
    print("[4/5] Calcul des flag scores par projet...")
    training_df = build_training_data(model, index, metadata)

    # ------------------------------------------------------------------
    # Étape 5 : Entraîner Cox
    # ------------------------------------------------------------------
    print("[5/5] Entraînement du modèle Cox...")
    cox_model = train_cox(training_df)
    save_cox_model(cox_model)

    # ------------------------------------------------------------------
    # Résumé
    # ------------------------------------------------------------------
    dt = time.time() - t_total
    print("\n" + "=" * 60)
    print("✅ PIPELINE TERMINÉE")
    print(f"  Chunks       : {len(chunks_df)}")
    print(f"  Projets      : {len(training_df)}")
    print(f"  Événements   : {training_df['event'].sum()}")
    print(f"  C-index      : {cox_model.concordance_index_:.3f}")
    print(f"  Temps total  : {dt:.1f}s")
    print("=" * 60)

    return cox_model, training_df


if __name__ == "__main__":
    retrain()