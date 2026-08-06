import re

import faiss
import numpy as np
import pandas as pd
from pathlib import Path
from sentence_transformers import SentenceTransformer

import signals
import llm_confirm as llm_confirm_mod
import reranker
import config

# CHANTIER 2 (PROMPT_CLAUDE_CODE_ESG_V2) : taille du pool FAISS interrogé
# avant re-ranking — plus large que k pour laisser au cross-encoder de
# vrais candidats à départager. Ignoré (repli sur k direct) si
# config.RERANKER_ENABLED est désactivé, cf. search_similar_from_chunks.
RERANK_POOL_SIZE = 30

# DIRECTIVE_CLAUDE_CODE_ESG_V3, Tier 1 (§1.1) : plafond global d'appels
# confirm_risk par appel à get_flag_scores_from_chunks. Un document de
# 45-70 pages (~100-200 chunks) où ~50 déclenchent un match mots-clés
# ferait sinon 50 appels LLM séquentiels (~2-5 min) — voir
# checklist.md pour le détail du chiffrage.
MAX_CONFIRM_RISK_CALLS = 30

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

# Table des matières / listes de figures — repérées en usage réel sur un
# rapport CAO (Mundra CGPL, 2026-08-06) : des chunks quasi entièrement faits
# de leaders de sommaire ("Effort and Rate ... 156 Figure 29: ... 88") se
# retrouvaient traités comme du contenu analytique — Pass 1 de deep_analysis.py
# y détectait des "formulations évasives" sur des titres de section, la
# spécificité du document était gonflée par les numéros de page (comptent
# comme marqueurs concrets dans compute_specificity_score). Validé sur le
# corpus existant (4203 chunks) : 1.6% flaggés, 100% des chunks échantillonnés
# étaient bien du bruit (leaders de sommaire ou glyphes de puces mal extraits
# du PDF), 0 faux positif observé.
_DOT_LEADER_RE = re.compile(r"\.{4,}|…{2,}")


def _is_boilerplate(chunk):
    """True si `chunk` est visiblement une table des matières/liste de
    figures plutôt que du texte analytique — cf. commentaire ci-dessus.
    Appelé uniquement sur des chunks qui ont déjà passé min_words (pas de
    recheck de longueur ici)."""
    if len(_DOT_LEADER_RE.findall(chunk)) >= 3:
        return True
    if chunk.count(".") / len(chunk) > 0.15:
        return True
    words = chunk.split()
    unique_ratio = len(set(w.lower() for w in words)) / len(words)
    return unique_ratio < 0.25


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP, min_words=CHUNK_MIN_WORDS):
    """Découpe `text` en fenêtres glissantes de ~chunk_size mots.

    Utilisée à la fois pour le corpus (ingest.py l'importe directement d'ici,
    pas de copie séparée) et pour une requête live (analyze.py/app.py) — le
    modèle d'embedding ("all-mpnet-base-v2") tronque silencieusement à 384
    tokens (~260-280 mots, marge suffisante pour nos chunks de 175 mots —
    contrairement à all-MiniLM-L6-v2 dont la fenêtre de 256 tokens/~180
    mots collait de plus près à CHUNK_SIZE). Si on interroge FAISS avec un
    texte plus long sans le découper, tout ce qui dépasse la fenêtre du
    modèle est ignoré par l'embedding
    — d'où l'importance de découper AUSSI le texte de la requête (document
    uploadé, ou texte concaténé d'un projet côté entraînement) de la même
    manière que le corpus.

    Peut retourner [] si `text` ne dépasse pas `min_words` mots, ou si tous
    les chunks candidats sont du boilerplate (cf. _is_boilerplate) — à gérer
    côté appelant (cf. search_similar/get_flag_scores).
    """
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if len(chunk.split()) > min_words and not _is_boilerplate(chunk):
            chunks.append(chunk)
    return chunks


def _encode_texts(texts, model):
    # DIRECTIVE_CLAUDE_CODE_ESG_V3, Tier 0 : normalize_embeddings=True délègue
    # la normalisation L2 à sentence-transformers (même résultat que l'ancienne
    # division manuelle par np.linalg.norm, en un appel) ; batch_size=64 pour
    # rester cohérent avec pipeline.py même si la requête live ne porte
    # généralement que sur 1-2 chunks.
    return model.encode(texts, batch_size=64, normalize_embeddings=True).astype("float32")


def _gather_candidates(chunk_i, indices, distances, metadata, exclude_project):
    """Construit la liste de candidats FAISS bruts pour un chunk de requête
    donné — un dict par voisin, avec les métadonnées enrichies du Chantier 1
    (chunk_type/specificity_score) en plus des champs déjà utilisés par les
    appelants existants. Factorise ce qui était dupliqué entre
    search_similar_from_chunks et get_flag_scores_from_chunks."""
    candidates = []
    for neighbor_i in range(indices.shape[1]):
        idx = indices[chunk_i][neighbor_i]
        row = metadata.iloc[idx]
        if exclude_project is not None and row["project_name"] == exclude_project:
            continue
        candidates.append({
            "score":             float(distances[chunk_i][neighbor_i]),
            "project_name":      row["project_name"],
            "chunk_id":          row["chunk_id"],
            "text":              row["text"],
            "flag_type":         row["flag_type"],
            "event":             row.get("event"),
            "time_to_event":     row.get("time_to_event"),
            "doc_date":          row.get("doc_date"),
            "chunk_type":        row.get("chunk_type"),
            "specificity_score": row.get("specificity_score"),
            "query_chunk_index": chunk_i,
        })
    return candidates


def _rerank_all_chunks(chunks, model, index, metadata, k, exclude_project):
    """Embedding + recherche FAISS + re-ranking cross-encoder, une fois par
    chunk de requête — cœur commun à search_similar_from_chunks,
    get_flag_scores_from_chunks ET analyze_chunks (nouveau, voir plus bas).

    AUDIT (2026-08-06, checklist.md) : avant factorisation, analyze.py
    appelait get_flag_scores PUIS search_similar sur les MÊMES chunks du
    même document — chacun refaisait tout ce calcul indépendamment,
    y compris le re-ranking cross-encoder (le plus coûteux des deux, CPU
    pur, aucun GPU sur cette machine). Mesuré sur un document réel de 171
    chunks : 246.6s de re-ranking pur (search_similar) + un 2e passage
    quasi identique dans get_flag_scores — ~46% du temps total d'analyze().
    analyze_chunks() appelle cette fonction UNE SEULE fois et en dérive à la
    fois flag_scores et similar_passages.

    Retourne une liste (une par chunk de `chunks`) de listes de candidats
    déjà re-rankés (au plus k chacune, triés par "rerank_score" décroissant
    — ou "score" FAISS brut si le re-ranker est désactivé, cf. reranker.rerank).
    """
    if not chunks:
        return []

    faiss_k = max(k, RERANK_POOL_SIZE) if config.RERANKER_ENABLED else k
    embeddings = _encode_texts(chunks, model)
    distances, indices = index.search(embeddings, faiss_k)

    return [
        reranker.rerank(chunks[i], _gather_candidates(i, indices, distances, metadata, exclude_project), top_k=k)
        for i in range(len(chunks))
    ]


def _gate_flags_with_llm(chunks, top_candidates_per_chunk):
    """Filtre de polarité LLM (voir llm_confirm.py, 2026-07-25) — pour
    chaque chunk, signals.flags_mentioned_in_text() repère les flags
    topicalement candidats (mot-clé), et un LLM local confirme s'il s'agit
    vraiment d'un risque avant de laisser CE chunk contribuer au score de
    CE flag. L'embedding capture le SUJET d'un chunk mais pas sa polarité —
    un chunk "ESAP actions completed ahead of schedule" matche les mêmes
    voisins FAISS qu'un chunk "ESAP action plan shows delays", gonflant le
    score à tort.

    DIRECTIVE_CLAUDE_CODE_ESG_V3, Tier 1 (§1.1) : sur un document de 100-200
    chunks, un appel confirm_risk par (chunk, flag topicalement matché) peut
    monter à 50-100 appels séquentiels (~2-5 min). Plafonné à
    MAX_CONFIRM_RISK_CALLS (30) — les paires sont priorisées par le meilleur
    score FAISS/rerank déjà obtenu pour ce chunk sur ce flag (donc celles les
    plus susceptibles de peser sur le max() final), pas par ordre
    d'apparition dans le document. Les paires sous le plafond ne sont pas
    vérifiées par LLM et retombent sur le comportement pré-filtre (pas
    gated) — cohérent avec le fail-open déjà appliqué partout ailleurs à ce
    filtre (Ollama injoignable = même repli).

    Retourne gated_flags_per_chunk (une liste de sets, un par chunk).
    """
    gated_flags_per_chunk = [set() for _ in chunks]
    pairs = []
    for i, chunk in enumerate(chunks):
        for flag_num in signals.flags_mentioned_in_text(chunk):
            flag_label = f"Flag {flag_num}"
            pair_score = max(
                (c.get("rerank_score", c["score"]) for c in top_candidates_per_chunk[i]
                 if flag_label in str(c["flag_type"])),
                default=0.0,
            )
            pairs.append((pair_score, i, flag_num, chunk))

    pairs.sort(key=lambda p: p[0], reverse=True)
    for _, i, flag_num, chunk in pairs[:MAX_CONFIRM_RISK_CALLS]:
        if not llm_confirm_mod.confirm_risk(chunk, flag_num):
            gated_flags_per_chunk[i].add(flag_num)

    return gated_flags_per_chunk


def _aggregate_flag_scores(top_candidates_per_chunk, gated_flags_per_chunk):
    """Agrégation par max (score le plus élevé du flag) à travers tous les
    chunks et tous leurs k plus proches voisins re-rankés.
    # ALT: moyenne ou moyenne pondérée par le score de similarité

    CHANTIER 2 (PROMPT_CLAUDE_CODE_ESG_V2) : le score utilisé pour le max()
    par flag est `rerank_score` (composite : pertinence cross-encoder +
    spécificité + récence + type de chunk) plutôt que la similarité FAISS
    brute, quand le re-ranker est actif. Impact train ET serve (utilisée par
    model.build_training_data via get_flag_scores_from_chunks), cohérent
    avec le traitement déjà réservé à llm_confirm dans ce fichier.
    """
    flag_scores = {"flag1_community": 0.0, "flag2_pollution": 0.0, "flag3_compliance": 0.0}
    for chunk_i, candidates in enumerate(top_candidates_per_chunk):
        gated = gated_flags_per_chunk[chunk_i]
        for c in candidates:
            score = c.get("rerank_score", c["score"])  # repli sur le score FAISS si re-ranker désactivé
            flag = str(c["flag_type"])

            # Matcher les flags combinés ("Flag 1 + Flag 2" compte pour Flag 1 ET Flag 2)
            if "Flag 1" in flag and 1 not in gated:
                flag_scores["flag1_community"] = max(flag_scores["flag1_community"], score)
            if "Flag 2" in flag and 2 not in gated:
                flag_scores["flag2_pollution"] = max(flag_scores["flag2_pollution"], score)
            if "Flag 3" in flag and 3 not in gated:
                flag_scores["flag3_compliance"] = max(flag_scores["flag3_compliance"], score)

    return {name: round(v * 100) for name, v in flag_scores.items()}


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

    Retourne l'union des résultats de tous les chunks (au plus k par
    chunk). Chaque résultat porte `query_chunk_index` pour savoir de quel
    chunk de la requête il provient.

    Appelée seule (pas via analyze_chunks), cette fonction refait tout le
    travail de _rerank_all_chunks à chaque appel — voir analyze_chunks() si
    tu as aussi besoin de flag_scores sur les MÊMES chunks, pour ne pas
    payer le re-ranking deux fois (cf. audit checklist.md 2026-08-06).
    """
    top_candidates_per_chunk = _rerank_all_chunks(chunks, model, index, metadata, k, exclude_project)
    return [c for candidates in top_candidates_per_chunk for c in candidates]


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
    et du paramètre `exclude_project`). Voir _gate_flags_with_llm pour
    `llm_confirm` et _aggregate_flag_scores pour l'agrégation.

    Appelée seule (pas via analyze_chunks), cette fonction refait tout le
    travail de _rerank_all_chunks à chaque appel — voir analyze_chunks() si
    tu as aussi besoin de similar_passages sur les MÊMES chunks, pour ne pas
    payer le re-ranking deux fois (cf. audit checklist.md 2026-08-06).
    """
    if not chunks:
        return {name: round(v) for name, v in {"flag1_community": 0.0, "flag2_pollution": 0.0, "flag3_compliance": 0.0}.items()}

    top_candidates_per_chunk = _rerank_all_chunks(chunks, model, index, metadata, k, exclude_project)
    gated_flags_per_chunk = (
        _gate_flags_with_llm(chunks, top_candidates_per_chunk) if llm_confirm else [set() for _ in chunks]
    )
    return _aggregate_flag_scores(top_candidates_per_chunk, gated_flags_per_chunk)


def get_flag_scores(query_text, model, index, metadata, k=15, llm_confirm=True):
    """Découpe query_text (cf. chunk_text) puis délègue à
    get_flag_scores_from_chunks."""
    chunks = chunk_text(query_text) or [query_text]
    return get_flag_scores_from_chunks(chunks, model, index, metadata, k=k, llm_confirm=llm_confirm)


def analyze_chunks(chunks, model, index, metadata, k=15, exclude_project=None, llm_confirm=True):
    """Calcule flag_scores ET similar_passages en un seul passage
    embedding/FAISS/rerank — au lieu des deux appels séparés
    get_flag_scores_from_chunks + search_similar_from_chunks, qui
    recalculaient deux fois le même re-ranking cross-encoder sur les mêmes
    chunks (mesuré : ~46% du temps total d'analyze() sur un document réel
    de 171 chunks, checklist.md 2026-08-06). Utilisée par analyze.py, qui a
    besoin des deux résultats sur le MÊME document — pas un remplacement de
    get_flag_scores_from_chunks/search_similar_from_chunks, qui restent
    utilisées telles quelles là où un seul des deux résultats est nécessaire
    (model.build_training_data n'a besoin que de flag_scores, par exemple).

    Retourne (flag_scores, similar_passages) — mêmes formats que
    get_flag_scores_from_chunks()/search_similar_from_chunks() respectivement.
    """
    if not chunks:
        return {name: round(v) for name, v in {"flag1_community": 0.0, "flag2_pollution": 0.0, "flag3_compliance": 0.0}.items()}, []

    top_candidates_per_chunk = _rerank_all_chunks(chunks, model, index, metadata, k, exclude_project)
    gated_flags_per_chunk = (
        _gate_flags_with_llm(chunks, top_candidates_per_chunk) if llm_confirm else [set() for _ in chunks]
    )
    flag_scores = _aggregate_flag_scores(top_candidates_per_chunk, gated_flags_per_chunk)
    similar_passages = [c for candidates in top_candidates_per_chunk for c in candidates]

    return flag_scores, similar_passages


def analyze_query(query_text, model, index, metadata, k=15, llm_confirm=True):
    """Découpe query_text (cf. chunk_text) puis délègue à analyze_chunks.
    Utilisée par analyze.py à la place de get_flag_scores + search_similar
    séparés (cf. analyze_chunks pour le pourquoi)."""
    chunks = chunk_text(query_text) or [query_text]
    return analyze_chunks(chunks, model, index, metadata, k=k, llm_confirm=llm_confirm)


if __name__ == "__main__":
    model, index, metadata = load_search_components()

    print(get_flag_scores("Local fishing communities have filed formal complaints against the project, citing loss of livelihood and inadequate compensation. Three NGOs have issued public statements calling for project suspension. The grievance mechanism has been declared non-independent by community leaders who refuse to participate in further consultation processes.", model, index, metadata))

    print(get_flag_scores("The quarterly discharge monitoring report for Q2 was not submitted within the required timeframe. Water quality parameters at the downstream sampling point exceeded IFC EHS guideline thresholds for total suspended solids. An unplanned oil spill of approximately 200 liters was reported near the construction site.", model, index, metadata))

    print(get_flag_scores("The biodiversity offset equivalence assessment remains pending per the ESAP timeline agreed at financial close. PS6 Critical Habitat screening has not been updated since project approval. The annual E&S monitoring report is overdue by 4 months.", model, index, metadata))
