import faiss
import numpy as np
import pandas as pd
from pathlib import Path
from sentence_transformers import SentenceTransformer

output = Path("C:/Users/djeto/Desktop/Projet-Elisa/models")
embeddings_normalized = np.load(output / "embeddings.npy")
model = SentenceTransformer('all-MiniLM-L6-v2')
metadata = pd.read_pickle(output / "chunks_metadata.pkl")


#création de l'index
dimension = embeddings_normalized.shape[1]
faiss.normalize_L2(embeddings_normalized)
index = faiss.IndexFlatIP(dimension)
index.add(embeddings_normalized)

def recherche(query_text, model, index, metadata, k=20):
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

def get_flag_scores(query_text, model, index, metadata, k=15):
    # Encoder et normaliser
    query_embedding = model.encode([query_text])
    query_embedding = query_embedding / np.linalg.norm(query_embedding, axis=1, keepdims=True)

    # Recherche
    distances, indices = index.search(query_embedding, k)

    # Grouper par flag
    flag_scores = {"Flag 1": 0, "Flag 2": 0, "Flag 3": 0}

    for i in range(k):
        idx = indices[0][i]
        score = distances[0][i]
        flag = str(metadata.iloc[idx]["flag_type"])

        # Matcher les flags combinés ("Flag 1 + Flag 2" compte pour Flag 1 ET Flag 2)
        if "Flag 1" in flag:
            flag_scores["Flag 1"] = max(flag_scores["Flag 1"], score)
        if "Flag 2" in flag:
            flag_scores["Flag 2"] = max(flag_scores["Flag 2"], score)
        if "Flag 3" in flag:
            flag_scores["Flag 3"] = max(flag_scores["Flag 3"], score)

    # Convertir en 0-100
    return {k: round(v * 100) for k, v in flag_scores.items()}

print(get_flag_scores("Local fishing communities have filed formal complaints against the project, citing loss of livelihood and inadequate compensation. Three NGOs have issued public statements calling for project suspension. The grievance mechanism has been declared non-independent by community leaders who refuse to participate in further consultation processes.", model, index, metadata))

print(get_flag_scores("The quarterly discharge monitoring report for Q2 was not submitted within the required timeframe. Water quality parameters at the downstream sampling point exceeded IFC EHS guideline thresholds for total suspended solids. An unplanned oil spill of approximately 200 liters was reported near the construction site.", model, index, metadata))

print(get_flag_scores("The biodiversity offset equivalence assessment remains pending per the ESAP timeline agreed at financial close. PS6 Critical Habitat screening has not been updated since project approval. The annual E&S monitoring report is overdue by 4 months.", model, index, metadata))