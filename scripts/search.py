import faiss
import numpy as np
import pandas as pd
from pathlib import Path
from sentence_transformers import SentenceTransformer

import signals
import llm_confirm as llm_confirm_mod

BASE = Path(__file__).resolve().parent.parent
EMBEDDING_PATH   = BASE / "models/embeddings.npy"
METADATA_PATH    = BASE / "models/chunks_metadata.pkl"
FAISS_INDEX_PATH = BASE / "models/faiss_index.bin"


def load_search_components():
    """Charge le modèle d'embedding, l'index FAISS et les métadonnées.

    Retourne (model, index, metadata) — metadata est un DataFrame pandas
    avec (au minimum) les colonnes project_name, text, chunk_id, flag_type.
    """
    model = SentenceTransformer("all-mpnet-base-v2")
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


CHUNK_SIZE = 175
CHUNK_OVERLAP = 50
CHUNK_MIN_WORDS = 30


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP, min_words=CHUNK_MIN_WORDS):
    """Découpe `text` en fenêtres glissantes de ~chunk_size mots.

    FRAGILE: doit rester identique à la fonction du même nom dans
    ingest.py (qui l'utilise pour construire le corpus, chunks.csv) — le
    modèle d'embedding ("all-mpnet-base-v2") tronque silencieusement à 384
    tokens (~260-280 mots, marge suffisante pour nos chunks de 175 mots —
    contrairement à all-MiniLM-L6-v2 dont la fenêtre de 256 tokens/~180
    mots collait de plus près à CHUNK_SIZE). Si on interroge FAISS avec un
    texte plus long sans le découper, tout ce qui dépasse la fenêtre du
    modèle est ignoré par l'embedding
    — d'où l'importance de découper AUSSI le texte de la requête (document
    uploadé, ou texte concaténé d'un projet côté entraînement) de la même
    manière que le corpus.

    Peut retourner [] si `text` ne dépasse pas `min_words` mots — à gérer
    côté appelant (cf. search_similar/get_flag_scores).
    """
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if len(chunk.split()) > min_words:
            chunks.append(chunk)
    return chunks


def _encode_texts(texts, model):
    embeddings = model.encode(texts).astype("float32")
    embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
    return embeddings


def search_similar_from_chunks(chunks, model, index, metadata, k=15, exclude_project=None):
    """Cœur de search_similar : `chunks` est déjà une liste de textes de
    taille raisonnable (~175 mots chacun, cf. chunk_text) — aucun découpage
    supplémentaire ici. Permet de réutiliser directement des chunks déjà
    connus (ex: ceux d'un projet du corpus dans model.build_training_data)
    sans les recoller puis les re-découper inutilement.

    `exclude_project` : si fourni, les voisins appartenant à ce projet sont
    ignorés. BUG CORRIGÉ: sans ça, interroger FAISS avec les chunks d'un
    projet qui est LUI-MÊME dans l'index (cas de build_training_data) fait
    ressortir le projet comme son propre plus proche voisin (score ~1.0) —
    fuite de données qui gonfle artificiellement les scores d'entraînement
    indépendamment de toute vraie similarité avec d'autres projets.

    Retourne l'union des résultats de tous les chunks. Chaque résultat
    porte `query_chunk_index` pour savoir de quel chunk de la requête il
    provient.
    """
    if not chunks:
        return []

    embeddings = _encode_texts(chunks, model)
    distances, indices = index.search(embeddings, k)

    results = []
    for chunk_i in range(len(chunks)):
        for neighbor_i in range(k):
            idx = indices[chunk_i][neighbor_i]
            row = metadata.iloc[idx]
            if exclude_project is not None and row["project_name"] == exclude_project:
                continue
            results.append({
                "score":             float(distances[chunk_i][neighbor_i]),
                "project_name":      row["project_name"],
                "chunk_id":          row["chunk_id"],
                "text":              row["text"],
                "flag_type":         row["flag_type"],
                "event":             row.get("event"),
                "time_to_event":     row.get("time_to_event"),
                "doc_date":          row.get("doc_date"),
                "query_chunk_index": chunk_i,
            })

    return results


def search_similar(query_text, model, index, metadata, k=15):
    """Découpe query_text (cf. chunk_text) puis délègue à
    search_similar_from_chunks. Utilisée comme "pattern library" (passages
    similaires) par analyze.py.
    """
    chunks = chunk_text(query_text) or [query_text]
    return search_similar_from_chunks(chunks, model, index, metadata, k=k)


def get_flag_scores_from_chunks(chunks, model, index, metadata, k=15, exclude_project=None, llm_confirm=True):
    """Cœur de get_flag_scores : `chunks` est déjà une liste de textes de
    taille raisonnable (~175 mots chacun) — aucun découpage supplémentaire
    ici (cf. search_similar_from_chunks pour le pourquoi de cette variante
    et du paramètre `exclude_project`).

    Agrégation par max (score le plus élevé du flag) à travers tous les
    chunks et tous leurs k plus proches voisins.
    # ALT: moyenne ou moyenne pondérée par le score de similarité

    llm_confirm : filtre de polarité (voir llm_confirm.py, 2026-07-25).
    L'embedding capture le SUJET d'un chunk mais pas sa polarité — un chunk
    "ESAP actions completed ahead of schedule" matche les mêmes voisins
    FAISS qu'un chunk "ESAP action plan shows delays", gonflant le score à
    tort. Pour chaque chunk, signals.flags_mentioned_in_text() repère les
    flags topicalement candidats (mot-clé), et un LLM local confirme s'il
    s'agit vraiment d'un risque avant de laisser CE chunk contribuer au
    score de CE flag — les autres chunks/flags contribuent normalement.
    Mettre à False pour retrouver l'ancien comportement (debug/comparaison).
    """
    flag_scores = {"flag1_community": 0.0, "flag2_pollution": 0.0, "flag3_compliance": 0.0}
    if not chunks:
        return {name: round(v) for name, v in flag_scores.items()}

    gated_flags_per_chunk = [set() for _ in chunks]
    if llm_confirm:
        for i, chunk in enumerate(chunks):
            for flag_num in signals.flags_mentioned_in_text(chunk):
                if not llm_confirm_mod.confirm_risk(chunk, flag_num):
                    gated_flags_per_chunk[i].add(flag_num)

    embeddings = _encode_texts(chunks, model)
    distances, indices = index.search(embeddings, k)

    for chunk_i in range(len(chunks)):
        for neighbor_i in range(k):
            idx = indices[chunk_i][neighbor_i]
            row = metadata.iloc[idx]
            if exclude_project is not None and row["project_name"] == exclude_project:
                continue
            score = float(distances[chunk_i][neighbor_i])
            flag = str(row["flag_type"])
            gated = gated_flags_per_chunk[chunk_i]

            # Matcher les flags combinés ("Flag 1 + Flag 2" compte pour Flag 1 ET Flag 2)
            if "Flag 1" in flag and 1 not in gated:
                flag_scores["flag1_community"] = max(flag_scores["flag1_community"], score)
            if "Flag 2" in flag and 2 not in gated:
                flag_scores["flag2_pollution"] = max(flag_scores["flag2_pollution"], score)
            if "Flag 3" in flag and 3 not in gated:
                flag_scores["flag3_compliance"] = max(flag_scores["flag3_compliance"], score)

    return {name: round(v * 100) for name, v in flag_scores.items()}


def get_flag_scores(query_text, model, index, metadata, k=15, llm_confirm=True):
    """Découpe query_text (cf. chunk_text) puis délègue à
    get_flag_scores_from_chunks."""
    chunks = chunk_text(query_text) or [query_text]
    return get_flag_scores_from_chunks(chunks, model, index, metadata, k=k, llm_confirm=llm_confirm)


if __name__ == "__main__":
    model, index, metadata = load_search_components()

    print(get_flag_scores("Local fishing communities have filed formal complaints against the project, citing loss of livelihood and inadequate compensation. Three NGOs have issued public statements calling for project suspension. The grievance mechanism has been declared non-independent by community leaders who refuse to participate in further consultation processes.", model, index, metadata))

    print(get_flag_scores("The quarterly discharge monitoring report for Q2 was not submitted within the required timeframe. Water quality parameters at the downstream sampling point exceeded IFC EHS guideline thresholds for total suspended solids. An unplanned oil spill of approximately 200 liters was reported near the construction site.", model, index, metadata))

    print(get_flag_scores("The biodiversity offset equivalence assessment remains pending per the ESAP timeline agreed at financial close. PS6 Critical Habitat screening has not been updated since project approval. The annual E&S monitoring report is overdue by 4 months.", model, index, metadata))
