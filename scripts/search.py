import faiss
import numpy as np
from pathlib import Path

output = Path("C:/Users/djeto/Desktop/Projet-Elisa/models")
embeddings_normalized = np.load(output / "embeddings.npy")


#création de l'index
dimension = embeddings_normalized.shape[1]
faiss.normalize_L2(embeddings_normalized)
index = faiss.IndexFlatIP(dimension)
index.add(embeddings_normalized)

def recherche(query_text, model, index, metadata, k=5):
    # Encoder et normaliser la query
    query_embedding = model.encode([query_text])
    query_embedding = query_embedding / np.linalg.norm(query_embedding, axis=1, keepdims=True)
    
    # Recherche dans l'index
    distances, indices = index.search(query_embedding, k)
    
    # Afficher les résultats avec les métadonnées
    results = []
    for i in range(k):
        idx = indices[0][i]
        score = distances[0][i]
        results.append({
            "score": score,
            "project_id": metadata.iloc[idx]["project_id"],
            "chunk_id": metadata.iloc[idx]["chunk_id"],
        })
    
    return results

import pandas as pd
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
metadata = pd.read_pickle(output / "chunks_metadata.pkl")

results = recherche("community opposition to the project, grievance mechanism contested", model, index, metadata)
for r in results:
    print(f"Score: {r['score']:.4f} | Projet: {r['project_id']} | Chunk: {r['chunk_id']}")