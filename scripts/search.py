import faiss
import numpy as np
import pandas as pd
from pathlib import Path
from sentence_transformers import SentenceTransformer

BASE = Path("C:/Users/djeto/Desktop/Projet-Elisa")
EMBEDDING_PATH   = BASE / "models/embeddings.npy"
METADATA_PATH    = BASE / "models/chunks_metadata.pkl"
FAISS_INDEX_PATH = BASE / "models/faiss_index.bin"


def load_search_components():
    """Charge le modèle d'embedding, l'index FAISS et les métadonnées.

    Retourne (model, index, metadata) — metadata est un DataFrame pandas
    avec (au minimum) les colonnes project_name, text, chunk_id, flag_type.
    """
    model = SentenceTransformer("all-MiniLM-L6-v2")
    metadata = pd.read_pickle(METADATA_PATH)

    if FAISS_INDEX_PATH.exists():
        index = faiss.read_index(str(FAISS_INDEX_PATH))
    else:
        # ALT: reconstruire l'index à la volée si pipeline.py n'a pas encore tourné
        embeddings = np.load(EMBEDDING_PATH).astype("float32")
        faiss.normalize_L2(embeddings)
        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)

    return model, index, metadata


def _encode_query(query_text, model):
    query_embedding = model.encode([query_text]).astype("float32")
    query_embedding = query_embedding / np.linalg.norm(query_embedding, axis=1, keepdims=True)
    return query_embedding


def search_similar(query_text, model, index, metadata, k=15):
    """Recherche les k chunks les plus proches. Retourne une liste de dicts
    utilisée comme "pattern library" (passages similaires) par analyze.py.
    """
    query_embedding = _encode_query(query_text, model)
    distances, indices = index.search(query_embedding, k)

    results = []
    for i in range(k):
        idx = indices[0][i]
        row = metadata.iloc[idx]
        results.append({
            "score":        float(distances[0][i]),
            "project_name": row["project_name"],
            "chunk_id":     row["chunk_id"],
            "text":         row["text"],
            "flag_type":    row["flag_type"],
        })

    return results


def get_flag_scores(query_text, model, index, metadata, k=15):
    """Calcule un score 0-100 par flag à partir des k passages les plus
    proches de query_text. Agrégation par max (score le plus élevé du flag
    parmi les k voisins).
    # ALT: moyenne ou moyenne pondérée par le score de similarité
    """
    query_embedding = _encode_query(query_text, model)
    distances, indices = index.search(query_embedding, k)

    flag_scores = {"flag1_community": 0.0, "flag2_pollution": 0.0, "flag3_compliance": 0.0}

    for i in range(k):
        idx = indices[0][i]
        score = float(distances[0][i])
        flag = str(metadata.iloc[idx]["flag_type"])

        # Matcher les flags combinés ("Flag 1 + Flag 2" compte pour Flag 1 ET Flag 2)
        if "Flag 1" in flag:
            flag_scores["flag1_community"] = max(flag_scores["flag1_community"], score)
        if "Flag 2" in flag:
            flag_scores["flag2_pollution"] = max(flag_scores["flag2_pollution"], score)
        if "Flag 3" in flag:
            flag_scores["flag3_compliance"] = max(flag_scores["flag3_compliance"], score)

    return {k: round(v * 100) for k, v in flag_scores.items()}


if __name__ == "__main__":
    model, index, metadata = load_search_components()

    print(get_flag_scores("Local fishing communities have filed formal complaints against the project, citing loss of livelihood and inadequate compensation. Three NGOs have issued public statements calling for project suspension. The grievance mechanism has been declared non-independent by community leaders who refuse to participate in further consultation processes.", model, index, metadata))

    print(get_flag_scores("The quarterly discharge monitoring report for Q2 was not submitted within the required timeframe. Water quality parameters at the downstream sampling point exceeded IFC EHS guideline thresholds for total suspended solids. An unplanned oil spill of approximately 200 liters was reported near the construction site.", model, index, metadata))

    print(get_flag_scores("The biodiversity offset equivalence assessment remains pending per the ESAP timeline agreed at financial close. PS6 Critical Habitat screening has not been updated since project approval. The annual E&S monitoring report is overdue by 4 months.", model, index, metadata))
