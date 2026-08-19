# Analyse par couches — Version corrigée (alignée sur le repo réel)

Ce document reprend l'analyse par couches (1 à 6) en intégrant les
corrections de `SYNTHESE_AUDIT_PIPELINE.md`, qui a confronté chaque
proposition au code réel, aux logs, et aux décisions déjà prises.

**Historique** : une première version de ce document (produite dans une
autre conversation) proposait déjà les prototypes de risque, le scoring
hybride, et la séparation explicite du problème statistique du Cox
(couche 6). Cette version corrige deux problèmes techniques trouvés en
relisant le code proposé pour la couche 3 (voir §3.4 et §3.5) et tranche
un point laissé ouvert en couche 4 (voir §4.3).

Chaque couche suit la structure : état réel du code → problème vérifié →
proposition corrigée → limites honnêtes → ce qu'on ne fait pas.

**Convention** : les affirmations marquées *[mesuré]* viennent de logs réels
ou de grep dans le repo. Les affirmations marquées *[hypothèse]* n'ont pas
été vérifiées — elles sont listées dans le Tier 1 (mesures obligatoires)
de la synthèse.

---

## PRÉALABLE — Tier 0 (à faire AVANT toute refonte, zéro risque)

Ces actions ne touchent pas à l'architecture. Elles corrigent des problèmes
évidents et gratuits identifiés par la synthèse.

### 0.1 — Vérifier/ajouter `@st.cache_resource`

*[hypothèse — à vérifier dans app.py]*

Si les chargements de modèles (SentenceTransformer, FAISS, Cox, métadonnées)
ne sont pas décorés `@st.cache_resource`, chaque interaction Streamlit
(clic, changement d'onglet, slider) recharge tout — 3-8 secondes de latence
par interaction, totalement invisible dans les logs d'analyse mais
destructrice pour l'UX.

```python
@st.cache_resource
def load_embedding_model():
    return SentenceTransformer("all-mpnet-base-v2")

@st.cache_resource
def load_faiss_components():
    index = faiss.read_index("models/faiss_index.bin")
    metadata = pd.read_pickle("models/chunks_metadata.pkl")
    return index, metadata

@st.cache_resource
def load_cox_model():
    return joblib.load("models/cox_model.pkl")
```

Fix de 5 minutes. Si déjà en place, documenter et passer.

### 0.2 — Supprimer le code mort

- `embed.py` : mort confirmé *[mesuré — zéro import dans le repo]*.
  Supprimer.
- `explain.py` : probablement mort — importé seulement par `test.py`,
  jamais par `app.py`, fonctionnellement remplacé par `deep_analysis.py`
  *[hypothèse]*. Vérifier et supprimer si confirmé.

### 0.3 — Optimisations Ollama gratuites

Paramètres de config qui divisent le temps par appel sans changer le code :

```python
OLLAMA_CONFIGS = {
    "confirm_risk": {
        "num_predict": 5,       # réponse = 1 mot (RISK/CLEAN)
        "num_ctx": 512,         # chunk 175 mots + prompt court
        "temperature": 0.1,     # déterministe
    },
    "summarize": {
        "num_predict": 80,      # ~1 phrase
        "num_ctx": 768,
        "temperature": 0.3,
    },
    "recommend": {
        "num_predict": 150,     # 2-3 phrases
        "num_ctx": 1024,
        "temperature": 0.4,
    },
    "deep_extract": {
        "num_predict": 100,     # Pass 1
        "num_ctx": 1024,
        "temperature": 0.1,
    },
    "deep_synthesize": {
        "num_predict": 200,     # Synthèse finale
        "num_ctx": 2048,
        "temperature": 0.3,
    }
}
```

Plus `OLLAMA_KEEP_ALIVE=-1` dans l'environnement (garde le modèle en RAM).

Et `batch_size=64`, `normalize_embeddings=True` dans les appels
`model.encode()` de sentence-transformers.

---

## PRÉALABLE — Tier 1 (mesures obligatoires avant la refonte)

On ne construit rien tant qu'on n'a pas ces chiffres. Chaque mesure est
une demi-journée de travail max.

### 1.1 — Profiler `analyze.py` sur un document réel de 10 Mo

Ajouter des `time.time()` autour de chaque bloc dans `analyze.py` :

```python
import time

t0 = time.time()
# ... étape X
t1 = time.time()
print(f"Étape X : {t1-t0:.1f}s")
```

Mesurer séparément :
- Extraction PDF (pdfplumber / OCR)
- Chunking
- Embedding (model.encode)
- FAISS search
- confirm_risk (tous les appels cumulés)
- deep_analysis (Pass 1 + Pass 2 + Pass 3 cumulés)
- summarize_passage (tous les appels cumulés)
- generate_recommendation
- Tout le reste

**But** : confirmer ou infirmer le double appel LLM redondant identifié
en §2.2 de la synthèse. Si `confirm_risk` et `deep_analysis` représentent
ensemble 80%+ du temps, c'est le problème. Si c'est l'extraction PDF
(OCR), c'est un tout autre problème.

### 1.2 — Mesurer le ratio boilerplate réel

Ouvrir 5-10 rapports du corpus. Pour chaque rapport, compter manuellement :
- Pages de couverture, table des matières, listes d'acronymes
- Disclaimers juridiques, conditions générales
- Pages de signatures
- Annexes non substantives

Calculer le ratio boilerplate / total. Si <15%, le filtre de la couche 1
n'est pas prioritaire. Si >25%, il l'est.

### 1.3 — Mesurer le recall du pré-filtre mots-clés

Prendre 5 rapports, identifier manuellement 20-30 passages qui décrivent
un risque ESG réel (un incident, une plainte, une violation, une omission
préoccupante). Vérifier combien de ces passages contiennent au moins un
mot-clé de `signals.py` pour le flag correspondant.

Si le recall est >90%, les mots-clés couvrent bien le vocabulaire de
risque IFC/CAO — le pré-filtre n'est pas le problème. Si <80%, le
pré-filtre est un vrai goulot qualitatif et les prototypes (couche 3)
deviennent plus urgents.

### 1.4 — Documenter les résultats de `compare_embeddings.py`

*[mesuré — décision déjà prise, §2.3 de la synthèse]*

mpnet : C-index 0.746, flag1 p<0.005.
MiniLM : C-index 0.758, flag1 p=0.01.
Décision du 2026-07-25 : garder mpnet (coefficient flag1 plus
significatif). **Question fermée.** Ne pas revisiter sauf changement
de corpus majeur.

---

## COUCHE 1 — INGESTION & FILTRAGE

### État réel du code

`ingest.py` : PDF/TXT → texte brut (pdfplumber + fallback OCR
pytesseract) → `chunk_text()` (fenêtre 175 mots, overlap 50, min 30)
→ `chunks.csv`. Aucun filtrage de qualité. `doc_date` jamais rempli.
Pas de hiérarchie Document → Section → Chunk. Pas de métadonnées
enrichies (chunk_type, specificity, section_type).

### Problème vérifié

*[hypothèse — à confirmer par mesure 1.2]* Ratio boilerplate estimé
30-40% mais non mesuré. Les chunks boilerplate polluent FAISS (faux
positifs de keywords) et déclenchent des appels LLM inutiles.

### Proposition corrigée

**Conditionnel à la mesure 1.2.** Si le boilerplate est >25% :

**Filtre rapide pré-embedding (seuls cas garantis safe) :**

```python
def is_obvious_noise(chunk_text):
    words = chunk_text.split()
    if len(words) < 15:
        return True
    unique_ratio = len(set(w.lower() for w in words)) / len(words)
    if unique_ratio < 0.25:
        return True
    return False
```

Seulement deux critères à taux de faux négatifs quasi nul. Pas de
distance au centroïde (circulaire — le corpus contient déjà le
boilerplate, le centroïde est pollué). Pas de pondérations inventées.

**Déduplication par Jaccard :**

Chunks avec overlap textuel >60% (Jaccard sur sets de mots) = doublons
probables (headers/footers répétés). Garder une instance, marquer les
autres. Plus fiable que la similarité cosine pour détecter la duplication
textuelle (vs la proximité sémantique).

**Info_weight comme pondération, pas comme filtre :**

```python
def compute_info_weight(chunk_text):
    words = chunk_text.split()
    unique_words = set(w.lower() for w in words)
    lexical_entropy = len(unique_words) / len(words) if words else 0
    concrete_tokens = count_concrete_tokens(chunk_text)  # chiffres, dates, unités, noms propres
    concreteness = min(concrete_tokens / len(words), 1.0) if words else 0
    info_weight = 0.5 * lexical_entropy + 0.5 * concreteness
    return max(info_weight, 0.1)  # plancher — aucun chunk à poids zéro
```

L'info_weight ne jette aucun chunk — il pondère leur contribution en
aval (couche 3 : `similarity * info_weight`, couche 4 : seuls les chunks
à info_weight > 0.5 sont envoyés au LLM). Un chunk boilerplate contribue
moins mais n'est pas éliminé — pas de faux négatifs.

**Fingerprint document :**

Hash SHA-256 du texte normalisé. Si le document a déjà été analysé,
résultats instantanés depuis le cache. Utile en démo (documents pré-
analysés) et pour éviter les recalculs accidentels.

### Limites honnêtes

- L'info_weight avec 2 composantes à poids 0.5/0.5 est encore arbitraire.
  Mieux que 3 composantes à 0.3/0.4/0.3, mais pas calibré.
- Le filtre rapide est conservateur par design — il laisse passer du bruit
  pour éviter les faux négatifs. Le gain en performance vient
  principalement de l'info_weight en aval, pas du filtre.
- Le fingerprint ne gère pas les versions mineures d'un même document
  (même contenu avec reformatage, en-têtes différents). Un hash strict
  ne matchera pas — acceptable pour le MVP.

### Ce qu'on ne fait pas

Distance au centroïde du corpus (circulaire). Score de pondération avec
composantes non normalisées. Chunking sémantique (effort trop important
pour le ROI en démo). Extraction de structure documentaire (graphe de
sections). Classification supervisée des pages boilerplate (pas de
dataset labellisé).

---

## COUCHE 2 — EMBEDDINGS

### État réel du code

`pipeline.py` : `SentenceTransformer("all-mpnet-base-v2")`, 768 dim,
float32, normalisés L2 → `embeddings.npy`. `search.py` recharge le
même modèle pour l'inférence. `embed.py` utilise MiniLM — code mort,
jamais appelé.

Benchmark déjà réalisé *[mesuré]* : mpnet C-index 0.746, flag1 p<0.005.
MiniLM C-index 0.758 mais flag1 p=0.01 seulement. Décision de garder
mpnet prise le 2026-07-25.

### Problème vérifié

L'encoding est le 2ème poste de coût *[hypothèse — à confirmer par
mesure 1.1]*. Estimé 20-40s pour 400 chunks sur CPU. Paramètres
d'encode non optimisés (batch_size par défaut, pas de progress bar).

mpnet est un modèle généraliste qui ne distingue pas la polarité ESG
("full compliance" vs "compliance failures" sont proches en embedding).
C'est la raison d'être de `confirm_risk` — un pansement LLM sur un
défaut d'embedding.

### Proposition corrigée

**Étape unique pour le MVP : optimiser les paramètres d'encode.**

```python
embeddings = model.encode(
    texts,
    batch_size=64,
    normalize_embeddings=True,
    show_progress_bar=True
)
```

Gain estimé 20-30% sur le throughput. Zéro risque.

**Cache d'embeddings par hash de chunk :**

```python
def encode_with_cache(chunks, model, cache_path="models/embedding_cache.pkl"):
    cache = load_cache(cache_path)
    to_encode = []
    to_encode_indices = []
    results = [None] * len(chunks)

    for i, chunk in enumerate(chunks):
        h = hashlib.sha256(chunk["text"].encode()).hexdigest()[:16]
        if h in cache:
            results[i] = cache[h]
        else:
            to_encode.append(chunk["text"])
            to_encode_indices.append(i)

    if to_encode:
        new_embeddings = model.encode(to_encode, batch_size=64,
                                       normalize_embeddings=True)
        for idx, emb in zip(to_encode_indices, new_embeddings):
            h = hashlib.sha256(chunks[idx]["text"].encode()).hexdigest()[:16]
            cache[h] = emb
            results[idx] = emb

        save_cache(cache, cache_path)

    return np.array(results)
```

Les chunks identiques à des chunks déjà vus (disclaimers standard,
sections copiées entre rapports IFC) sont récupérés du cache. Se
connecte au fingerprinting de la couche 1 (même hash).

### Limites honnêtes

- Le problème de polarité (mpnet ne distingue pas risque réel vs
  conformité déclarée) reste entier. Le seul vrai correctif serait un
  fine-tuning contrastif — écarté pour le MVP (2000 paires vs 500k+
  nécessaires *[mesuré par comparaison avec les papiers de référence]*).
- Le cache d'embeddings ajoute un fichier à maintenir. Si le modèle
  d'embedding change, le cache est invalide — le pipeline doit le
  détecter et le vider (via le hash du modèle dans pipeline_state.json).

### Ce qu'on ne fait pas

Changement de modèle d'embedding (décision mpnet déjà prise *[mesuré]*).
PCA (FAISS <5ms, gain invisible). Fine-tuning contrastif (corpus trop
petit de deux ordres de grandeur). Quantification int8 (inutile à cette
échelle). Matryoshka Representation Learning.

---

## COUCHE 3 — RETRIEVAL & SCORING

### État réel du code

`IndexFlatIP`, 4203 vecteurs. Deux fonctions dans `search.py` :
`search_similar_from_chunks` (passages similaires pour l'UI) et
`get_flag_scores_from_chunks` (scoring par flag avec pré-filtre
mots-clés + confirm_risk + agrégation max). `exclude_project` pour
l'anti-fuite de données — **ce garde-fou existe déjà dans le code actuel
et doit être préservé dans toute refonte** (voir §3.4).

Résultats Cox réels *[mesuré]* :
- flag1_community : z=3.15, p<0.005 → **significatif**
- flag2_pollution : z=-0.52, p=0.60 → **bruit**
- flag3_compliance : z=1.34, p=0.18 → **non significatif**

### Problème vérifié

**Le vrai problème n'est pas le retrieval, c'est la puissance
statistique.** Deux flags sur trois ne discriminent rien. Améliorer le
retrieval réduit le bruit dans les scores mais ne transforme pas 29
événements en 200. Aucune optimisation de FAISS ou de scoring ne rend
flag2 et flag3 significatifs — seul l'enrichissement du corpus (Chantier
0) peut le faire.

Le pré-filtre par mots-clés est un biais de couverture *[hypothèse —
à confirmer par mesure 1.3]*. L'agrégation par max est fragile (un seul
faux positif tire le score). Les appels `confirm_risk` sont le goulot
de performance *[hypothèse — à confirmer par mesure 1.1]*.

### Proposition corrigée

**Prototypes de risque — avec documentation honnête des limites.**

Idée validée par la synthèse comme "directionnellement bonne". Mais
avec un caveat critique *[mesuré, §2.1 de la synthèse]* :

`flag_type` par chunk vient de `signals.flags_mentioned_in_text()` —
le même pré-filtre par mots-clés. Donc "chunks confirmés RISK pour
flag N" = chunks dont le texte matche les mots-clés du flag N ET
appartenant à un projet event=1. C'est un proxy à deux niveaux
(mots-clés + événement projet), **pas** une polarité propre.

Les prototypes réduisent le nombre d'appels LLM et simplifient le
pipeline. Ils ne résolvent pas la circularité mots-clés — ils la
rendent explicite et documentée au lieu de la cacher dans une chaîne
FAISS → confirm_risk.

```python
def build_risk_prototypes(chunks_metadata, embeddings, n_prototypes=3):
    """
    Prototypes par flag. ATTENTION : flag_type vient de signals.py
    (mots-clés), pas d'un label sémantique pur. Documenté, pas résolu
    (voir §3 ci-dessus).

    Les centroïdes sont L2-normalisés après construction (§3.5) : une
    moyenne de vecteurs unitaires n'est PAS elle-même unitaire, et sans
    cette normalisation le produit scalaire utilisé pour le scoring
    n'est plus une similarité cosinus comparable entre flags.
    """
    prototypes = {}
    for flag_num in [1, 2, 3]:
        risk_mask = (
            chunks_metadata["flag_type"].str.contains(f"Flag {flag_num}")
            & (chunks_metadata["event"] == 1)
        )
        risk_embeddings = embeddings[risk_mask]

        if len(risk_embeddings) < n_prototypes:
            centers = np.array([np.mean(risk_embeddings, axis=0)])
        else:
            km = KMeans(n_clusters=n_prototypes, random_state=42, n_init=10)
            km.fit(risk_embeddings)
            centers = km.cluster_centers_

        # Normalisation L2 — voir §3.5. Sans ça, un flag dont les chunks
        # RISK sont sémantiquement diffus (cluster large) obtient un
        # centroïde de norme plus faible qu'un flag aux chunks RISK très
        # homogènes, et ses scores sont mécaniquement écrasés vers le bas
        # indépendamment du vrai signal.
        norms = np.linalg.norm(centers, axis=1, keepdims=True)
        centers = centers / np.clip(norms, 1e-8, None)

        prototypes[flag_num] = centers

    return prototypes
```

**Scoring hybride : prototypes (score) + FAISS (evidence).**

Les prototypes produisent le score (produit matriciel, <1ms — un
véritable cosinus maintenant que les deux côtés sont normalisés).
FAISS ne sert qu'à trouver les projets historiques à citer comme
evidence dans l'UI — seulement sur les top-5 chunks les plus proches
des prototypes, pas sur tous.

```python
def compute_flag_scores_hybrid(query_embeddings, info_weights,
                                 prototypes, faiss_index, metadata):
    results = {}
    for flag_num, flag_protos in prototypes.items():
        proto_matrix = np.array(flag_protos)  # déjà normalisés (§3.5)
        similarities = query_embeddings @ proto_matrix.T
        best_proto_sim = similarities.max(axis=1)
        weighted_sims = best_proto_sim * info_weights

        # Agrégation top-3 (remplace le max fragile)
        top_k = np.sort(weighted_sims)[-3:]
        score = float(np.mean(top_k) * 100)

        # Confiance
        n_significant = int(np.sum(weighted_sims > 0.50))
        confidence = min(n_significant / 10, 1.0)

        # Evidence par FAISS (top-5 chunks → top-3 projets distincts)
        top_chunk_indices = np.argsort(weighted_sims)[-5:]
        evidence = []
        for idx in top_chunk_indices:
            D, I = faiss_index.search(query_embeddings[idx:idx+1], k=3)
            for dist, match_idx in zip(D[0], I[0]):
                if dist > 0.45:
                    evidence.append({
                        "query_chunk_idx": int(idx),
                        "matched_project": metadata.iloc[match_idx]["project_id"],
                        "similarity": float(dist),
                        "info_weight": float(info_weights[idx])
                    })

        # Dédoublonner par projet
        seen = set()
        unique_evidence = []
        for e in sorted(evidence, key=lambda x: x["similarity"], reverse=True):
            if e["matched_project"] not in seen:
                seen.add(e["matched_project"])
                unique_evidence.append(e)

        results[f"flag{flag_num}"] = {
            "score": round(score),
            "confidence": round(confidence, 2),
            "n_significant_chunks": n_significant,
            "evidence": unique_evidence[:5]
        }

    return results
```

**Détection d'omissions déterministe :**

```python
MATERIALITY_MATRIX = {
    "mining": ["biodiversity", "water_management", "community_health",
               "resettlement", "indigenous_peoples", "pollution",
               "worker_safety", "grievance_mechanism"],
    "infrastructure": ["resettlement", "community_consultation",
                        "environmental_impact", "cultural_heritage",
                        "grievance_mechanism", "worker_safety"],
    "agribusiness": ["biodiversity", "land_use", "water_management",
                      "labor_rights", "supply_chain", "pollution"],
    "default": ["environmental_impact", "community_impact",
                 "worker_safety", "grievance_mechanism",
                 "compliance", "pollution"]
}

def detect_omissions(document_section_types, project_type="default"):
    expected = set(MATERIALITY_MATRIX.get(project_type,
                                           MATERIALITY_MATRIX["default"]))
    covered = set(document_section_types)
    missing = expected - covered
    return [{"topic": t, "severity": "HIGH" if t in
             ["resettlement", "grievance_mechanism", "biodiversity"]
             else "MEDIUM"} for t in missing]
```

Plus fiable qu'un LLM 4B. Instantané. Le `project_type` peut être
renseigné par un dropdown dans l'UI ou inféré des section_types
dominants.

**Validation croisée mots-clés (filet de sécurité) :**

Les mots-clés de `signals.py` changent de rôle — de gate d'entrée
à signal de validation. Score élevé par prototypes + aucun mot-clé
= warning "vérification recommandée". Beaucoup de mots-clés + score
bas = warning "vocabulaire présent sans pattern de risque avéré".

### §3.4 — Fuite de données dans l'entraînement Cox (correction ajoutée)

**Problème trouvé en relisant le code de la couche 5** (`run_pipeline`,
qui appelle `build_risk_prototypes(chunks, embeddings)` une seule fois
sur tout le corpus, puis `train_cox(chunks, embeddings, info_weights,
prototypes)` avec ce même jeu de prototypes pour scorer tous les
projets) : un projet P est scoré, pendant l'entraînement du Cox, avec
un prototype qui peut contenir **ses propres chunks** (si des chunks de
P sont marqués `flag_type` = flag N et `event == 1`). Le score de P
mesure alors en partie la similarité de P à lui-même.

C'est la même classe de bug que celle déjà identifiée et corrigée dans
le code actuel — `model.py`, `build_training_data()` :

> *"exclude_project : le projet est lui-même dans l'index FAISS, sans
> ce filtre chaque chunk se retrouverait plus proche voisin de
> lui-même (score ~1.0), une fuite de données qui gonfle les scores
> d'entraînement indépendamment de toute similarité avec d'autres
> projets."*

Les prototypes réintroduisent cette fuite sous une forme différente s'ils
ne sont pas construits en excluant le projet scoré. Sans correction, le
C-index mesuré après la refonte serait artificiellement gonflé — on
croirait que les prototypes améliorent la discrimination alors qu'on
mesurerait en partie une auto-similarité.

**Correction : prototypes leave-one-project-out pour l'entraînement,
prototypes globaux pour l'inférence live.**

Un document uploadé n'a jamais fait partie du corpus d'entraînement —
pas de fuite possible en inférence live, les prototypes globaux
(`models/risk_prototypes.pkl`, construits une fois sur tout le corpus)
restent corrects pour ce cas. La fuite ne concerne que la construction
du **dataset d'entraînement Cox**, où il faut recalculer les prototypes
par projet, en excluant les chunks de ce projet :

```python
def build_cox_training_data(chunks_metadata, embeddings, info_weights,
                              faiss_index, n_prototypes=3):
    """
    Version leave-one-project-out de build_risk_prototypes, utilisée
    UNIQUEMENT pour construire le dataset d'entraînement Cox. Évite la
    fuite documentée en §3.4 : recalcule les prototypes de chaque flag
    en excluant les chunks du projet qu'on est en train de scorer,
    exactement comme exclude_project le fait déjà pour la recherche
    FAISS dans model.build_training_data().

    Coût : un refit KMeans par projet annoté (~47 refits sur ~4000
    chunks chacun) au lieu d'un seul — de l'ordre de quelques dizaines
    de secondes au total, pas un problème de perf à cette échelle de
    corpus. Les prototypes "globaux" persistés dans
    models/risk_prototypes.pkl (construits UNE fois sur tout le corpus,
    sans exclusion) restent utilisés tels quels pour scorer un document
    uploadé en inférence live — ce document n'a jamais contribué au
    corpus d'entraînement, donc pas de fuite à corriger dans ce cas.
    """
    records = []
    annotated = (chunks_metadata.dropna(subset=["event"])
                 .drop_duplicates("project_name"))

    for _, ann in annotated.iterrows():
        proj_name = ann["project_name"]

        other_mask = (chunks_metadata["project_name"] != proj_name).values
        prototypes_loo = build_risk_prototypes(
            chunks_metadata[other_mask], embeddings[other_mask],
            n_prototypes=n_prototypes
        )

        proj_mask = (chunks_metadata["project_name"] == proj_name).values
        proj_embeddings = embeddings[proj_mask]
        proj_info_weights = info_weights[proj_mask]

        scores = score_against_prototypes(
            proj_embeddings, proj_info_weights, prototypes_loo
        )

        records.append({
            "project_name": proj_name,
            "flag1_community":  scores["flag1"]["score"],
            "flag2_pollution":  scores["flag2"]["score"],
            "flag3_compliance": scores["flag3"]["score"],
            "time_to_event":    ann["time_to_event"],
            "event":            int(ann["event"]),
        })

    return pd.DataFrame(records)
```

`run_pipeline` (couche 5) doit donc appeler **deux** constructions de
prototypes distinctes : `build_risk_prototypes()` une fois sur tout le
corpus → sauvegardé pour l'inférence live, et
`build_cox_training_data()` (qui refait un `build_risk_prototypes` par
projet, en interne) → utilisé uniquement pour entraîner le Cox. Voir la
mise à jour de la couche 5 (§5.2).

### §3.5 — Prototypes non normalisés = pas une vraie similarité cosinus (correction ajoutée)

**Problème trouvé en relisant `compute_flag_scores_hybrid`** : les
`query_embeddings` sont normalisés L2 (couche 2). Mais
`km.cluster_centers_` (les prototypes bruts, avant la correction de
§3.4/§3.5 ci-dessus) est une **moyenne** de vecteurs unitaires — sa
norme est strictement inférieure à 1 dès que les vecteurs moyennés ne
pointent pas exactement dans la même direction, et d'autant plus faible
que le cluster est dispersé.

Concrètement : `query_embeddings @ proto_matrix.T` n'est alors **pas**
une similarité cosinus mais un produit scalaire dont l'échelle dépend
de la dispersion sémantique de chaque flag. Un flag dont les chunks
RISK sont thématiquement homogènes (cluster serré → norme du centroïde
proche de 1) obtient des scores plus élevés, à signal égal, qu'un flag
dont les chunks RISK sont plus divers (cluster diffus → norme du
centroïde plus faible). Les seuils codés en dur (`weighted_sims >
0.50`, `dist > 0.45`) supposent une échelle cosinus cohérente entre
flags — qui ne l'est plus dans ce cas.

**Correction : L2-normaliser chaque prototype après construction**
(déjà intégrée dans `build_risk_prototypes` ci-dessus, §3 — trois
lignes de code, mais sans elles les scores entre flag1/flag2/flag3 ne
sont pas comparables entre eux).

### Limites honnêtes

- Les prototypes héritent la circularité de `flag_type` (§2.1 de la
  synthèse). C'est documenté, pas résolu. La résolution nécessiterait
  soit des labels humains par chunk (coûteux), soit un mécanisme
  d'attribution de flag indépendant des mots-clés (pas d'approche
  évidente à ce stade).
- flag2 (p=0.60) et flag3 (p=0.18) ne discriminent rien *[mesuré]*.
  Les prototypes pour ces flags produiront des scores aussi peu
  informatifs qu'avant, même une fois §3.4 et §3.5 corrigés — le
  problème est le volume d'événements, pas la méthode de scoring.
- Le seuil de similarité minimale (0.45) est arbitraire. À calibrer
  sur des cas réels, d'autant plus important maintenant que les
  prototypes sont normalisés (§3.5) et que ce seuil est enfin comparable
  entre flags.
- Le coût du leave-one-project-out (§3.4) n'a pas été mesuré (nombre de
  refits KMeans réel sur le corpus). À vérifier lors de l'implémentation
  — devrait rester négligeable à 47 projets, à surveiller si le corpus
  grossit (Chantier 0, couche 6).

### Ce qu'on ne fait pas

Suppression totale du pré-filtre mots-clés (casse l'attribution par
flag sans alternative). Centroïde de document comme pré-filtre FAISS
(over-engineering à cette échelle). Breadth/coverage comme feature Cox
(multicolinéarité + corpus trop petit). ColBERT / multi-vecteurs.

---

## COUCHE 4 — LLM (OLLAMA)

### État réel du code

`llm_confirm.py` : 3 fonctions (confirm_risk, summarize_passage,
generate_recommendation). `deep_analysis.py` : pipeline multi-pass
(Pass 1/2/3) ajouté par le Chantier 3.

**Double appel LLM identifié** *[mesuré, §2.2 de la synthèse]* :
`_find_signals_in_document()` appelle `confirm_risk` une fois par
extrait matché, PUIS `deep_analysis.run_deep_analysis()` tourne en
plus sur des zones du même document. Deux couches LLM indépendantes,
potentiellement redondantes.

Qwen 4B : pas fiable sur les cas ambigus. Le filtre RISK/CLEAN est
un coin-flip sur les passages nuancés.

### Problème vérifié

Le coût LLM total sur un document de 10 Mo est *[hypothèse — à
confirmer par mesure 1.1]* dominé par le cumul confirm_risk +
deep_analysis. Les deux se chevauchent sur le même document. Le LLM
fait trop de choses, et les choses les plus coûteuses (confirm_risk :
centaines d'appels) sont les moins informatives (un bit par appel).

### Proposition corrigée

**Le LLM est un rédacteur, pas un analyste.** Les couches 1-3
produisent déjà les données structurées. Le LLM transforme ces données
en prose. Deux types d'appels seulement :

**Type 1 — Extraction ciblée (Pass 1 réduite) :**

Seulement 8-12 chunks pré-sélectionnés par `prototypes × info_weight`.
Pas tous les chunks. Regroupés en 5-8 passages.

```
Lis cet extrait d'un rapport de projet. Réponds EXACTEMENT :
INCIDENT: OUI ou NON | description en 10 mots max
ENGAGEMENT_VAGUE: OUI ou NON | la formulation évasive détectée
CHIFFRE_CLÉ: OUI ou NON | le chiffre et ce qu'il mesure
```

5-8 appels à 8-12s = 40-96s.

Fallback : si non parsable, utiliser les métadonnées couche 1
(chunk_type, specificity_score) comme substitut.

**Type 2 — Synthèse finale (UN seul appel) :**

```
Tu complètes un rapport d'alerte ESG. Les données ci-dessous ont été
extraites automatiquement. Reformule-les en 4-5 phrases pour un comité
de crédit.

DONNÉES :
- Projet : {project_name}
- Grade : {risk_grade} ({probability}%)
- Spécificité du rapport : {specificity}%
- Findings : {findings_table}
- Omissions : {omissions_list}
- Projets similaires : {similar_projects}

INSTRUCTIONS :
- Phrase 1 : conclusion de risque
- Phrase 2 : finding le plus critique
- Phrase 3 : omissions et leur implication
- Phrase 4 : comparaison historique
- NE PAS inventer d'information absente des données
```

10-15 secondes. Un seul appel.

Fallback template :

```python
def generate_fallback_synthesis(data):
    lines = [
        f"Le projet {data['project_name']} présente un risque "
        f"{data['risk_grade']} ({data['probability']}% à 12 mois).",
        f"{data['n_findings']} signaux détectés dont "
        f"{data['n_high']} de sévérité haute."
    ]
    if data["omissions"]:
        lines.append(f"Sujets non couverts : {', '.join(data['omissions'])}.")
    if data["specificity"] < 40:
        lines.append(f"Spécificité du rapport : {data['specificity']}% "
                      f"— niveau de détail insuffisant.")
    return " ".join(lines)
```

**Ce qui disparaît :**

- `confirm_risk` dans le scoring → remplacé par les prototypes (couche 3).
- Pass 2 (détection d'omissions par LLM) → remplacée par la matrice
  de matérialité déterministe (couche 3).

### §4.3 — `_find_signals_in_document` : décision tranchée (point laissé ouvert dans la version précédente)

La version précédente de ce document listait deux options sans
trancher : remplacer `confirm_risk` par info_weight+prototypes de façon
autonome, ou réutiliser les findings de la Pass 1.

**Décision : réutiliser les findings de la Pass 1.** Maintenir un
deuxième mécanisme de sélection de signaux en parallèle (prototypes +
info_weight, indépendant de ce que la Pass 1 a déjà classifié) recrée
le même risque que la situation actuelle — deux chemins qui peuvent
diverger sur ce qu'ils considèrent "un signal", avec le surlignage UI
qui ne correspond plus à ce que l'analyse LLM a retenu. En dérivant le
surlignage directement des `findings` retournés par
`run_pass1_extraction()` (type INCIDENT / ENGAGEMENT_VAGUE / CHIFFRE_CLÉ,
avec la position du chunk dans le document), un seul mécanisme
détermine à la fois ce qui est surligné et ce qui est analysé — plus
d'appels `confirm_risk` du tout dans ce chemin.

Effet de bord positif : ça retire aussi le dernier appel LLM par
extrait mots-clés qui contribuait au double comptage identifié en §2.2
de la synthèse — un des deux postes de coût LLM disparaît
structurellement, pas seulement en étant réduit.

**Résumés de passages — cache incrémental :**

Pas de pré-calcul batch (5+ heures, même problème de débit que le
chantier de préchauffage *[mesuré, §2.5 de la synthèse]*). Cache
incrémental : chaque résumé est calculé une fois au premier affichage
et caché pour les suivants. Pour la démo : pré-analyser les 3-4
documents prévus la veille.

### Limites honnêtes

- Le budget LLM total (50-150s) est une estimation. La mesure 1.1
  donnera le vrai chiffre. Si l'extraction PDF (OCR) prend 15-30
  minutes, le LLM n'est pas le vrai goulot.
- Un 4B produit des synthèses de qualité variable. Le fallback
  template est la baseline — si le LLM ne fait pas significativement
  mieux, il n'ajoute pas de valeur. Tester systématiquement.
- Réutiliser les findings de la Pass 1 pour le surlignage (§4.3) est un
  chantier de code, pas juste une décision d'architecture — le
  refactoring doit être testé sur des cas réels, notamment pour
  vérifier que la granularité des findings (par passage regroupé) est
  suffisante pour surligner des passages précis dans l'UI.

### Ce qu'on ne fait pas

Classifieur distillé (composant ML supplémentaire à maintenir, alors
que les prototypes éliminent déjà le besoin de confirm_risk pour le
scoring). Cascade à 3 niveaux (over-engineering — 2 niveaux suffisent :
heuristiques/prototypes + LLM pour les cas ciblés). Wildcards aléatoires
(10% de chance de capter un signal, coût garanti). Pass contrefactuelle
(un 4B ne fait pas d'estimation d'impact financier).

---

## COUCHE 5 — PIPELINE & ORCHESTRATION

### État réel du code

Pipeline batch (`pipeline.py`) : séquentiel, reconstruit tout.
Pipeline live (`analyze.py`) : monolithique, séquentiel, pas de
sauvegarde intermédiaire, pas de callback de progression.

Chantier ouvert *[mesuré, §2.5 de la synthèse]* : le préchauffage
du cache LLM est instable/trop lent, donc `cox_model.pkl` est
entraîné sur des scores NON filtrés par confirm_risk alors que
l'inférence live filtre. C'est un décalage train/serve connu et
délibérément mis en pause.

Décision "features avant perf" *[mesuré, §2.7]* prise le 2026-07-25.
Cohérent avec l'approche : bug fixes (Tier 0) maintenant,
optimisations (PCA, fine-tuning) différées.

### Problème vérifié

Le monolithe `analyze.py` bloque l'UI pendant toute l'analyse. Pas
d'affichage progressif. Si une étape plante, tout est perdu.

Le couplage `search.py` ↔ `ingest.py` (chunk_text partagé) est
fragile — déjà identifié dans l'audit.

Le réentraînement Cox sur corpus complet doit rester praticable après
la refonte (§2.5 de la synthèse). Les prototypes (couche 3)
simplifient ce réentraînement (pas de confirm_risk dans la boucle),
ce qui résout le décalage train/serve — **à condition d'utiliser la
version leave-one-project-out des prototypes pour l'entraînement**
(§3.4), sinon on remplace un problème connu (décalage train/serve) par
un autre non détecté (fuite de données).

### Proposition corrigée

**Étape 1 — `@st.cache_resource` (Tier 0, déjà couvert).**

**Étape 2 — `analyze.py` restructuré en étapes.**

```python
def analyze_document(text, project_type, components, on_step=None):
    result = {
        "status": "in_progress",
        "completed_steps": [],
        "errors": [],
        "document_hash": hashlib.sha256(text.encode()).hexdigest()[:16]
    }

    def notify(step, data):
        result["completed_steps"].append(step)
        result.update(data)
        if on_step:
            on_step(step, result)

    # — Couche 1 (~100ms) —
    try:
        chunks = chunk_and_filter(text)
        notify("ingestion", {"n_chunks": len(chunks)})
    except Exception as e:
        result["errors"].append(f"Ingestion: {e}")
        result["status"] = "failed"
        return result

    # — Couche 2 (~20-40s) —
    try:
        embeddings, info_weights = embed_and_weight(
            chunks, components["embedding_model"],
            components["corpus_centroid"])
        notify("embedding", {
            "avg_specificity": float(np.mean(
                [c.get("specificity", 0.5) for c in chunks]))
        })
    except Exception as e:
        result["errors"].append(f"Embedding: {e}")
        result["status"] = "failed"
        return result

    # — Couche 3 (<1s) —
    try:
        flag_scores = compute_flag_scores_hybrid(
            embeddings, info_weights,
            components["prototypes"],
            components["faiss_index"],
            components["metadata"])
        omissions = detect_omissions(
            [c.get("section_type", "general") for c in chunks],
            project_type)
        prediction = predict_risk(flag_scores, components["cox_model"])
        notify("scoring", {
            "flag_scores": flag_scores,
            "omissions": omissions,
            "prediction": prediction
        })
    except Exception as e:
        result["errors"].append(f"Scoring: {e}")
        notify("scoring", {"scoring_error": str(e)})

    # — Couche 4 (50-150s) —
    try:
        selected = select_chunks_for_deep_analysis(
            embeddings, info_weights, components["prototypes"])
        findings = run_pass1_extraction(
            [chunks[i] for i in selected],
            components.get("ollama_url", "http://localhost:11434"))
        synthesis = run_synthesis(result, findings,
                                  components.get("ollama_url"))
        notify("analysis", {"findings": findings, "synthesis": synthesis})
    except Exception as e:
        result["errors"].append(f"LLM: {e}")
        synthesis = generate_fallback_synthesis(result)
        notify("analysis", {"findings": [], "synthesis": synthesis,
                             "synthesis_source": "template"})

    result["status"] = "complete" if not result["errors"] else "partial"
    return result
```

**Aucune dépendance Streamlit dans analyze.py.** Le callback `on_step`
est un callable générique. Streamlit passe son propre callback qui
appelle `st.status()`. Un test unitaire passe un callback qui loge.

**Étape 3 — Branchement Streamlit avec session_state.**

```python
def run_analysis_with_progress(text, project_type):
    doc_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    cache_key = f"analysis_{doc_hash}"

    if cache_key in st.session_state:
        prev = st.session_state[cache_key]
        if prev["status"] in ("complete", "partial"):
            return prev

    components = {
        "embedding_model": load_embedding_model(),
        "faiss_index": load_faiss_components()[0],
        "metadata": load_faiss_components()[1],
        "cox_model": load_cox_model(),
        "prototypes": load_prototypes(),
        "corpus_centroid": load_corpus_centroid(),
        "ollama_url": os.environ.get("OLLAMA_HOST",
                                      "http://localhost:11434")
    }

    status = st.status("Analyse en cours...", expanded=True)

    def on_step(step, result):
        with status:
            if step == "ingestion":
                st.write(f"✓ {result['n_chunks']} passages filtrés")
            elif step == "embedding":
                st.write(f"✓ Spécificité : "
                         f"{result['avg_specificity']:.0%}")
            elif step == "scoring":
                if "prediction" in result:
                    st.write(f"✓ {result['prediction']['grade']} "
                             f"({result['prediction']['probability']}%)")
            elif step == "analysis":
                n = len(result.get("findings", []))
                st.write(f"✓ {n} findings")
        st.session_state[cache_key] = result

    result = analyze_document(text, project_type, components, on_step)

    status.update(
        label="Analyse terminée" if result["status"] == "complete"
              else "Analyse partielle",
        state="complete" if result["status"] == "complete" else "error",
        expanded=False)

    return result
```

Les résultats des couches 1-3 apparaissent en ~35s. L'utilisateur
lit déjà les scores et omissions pendant que le LLM travaille.

**Étape 4 — `core.py` pour le code partagé.**

```
core.py (fonctions atomiques : chunk_text, filtre, info_weight,
         flag_scores, detect_omissions)
    ↑               ↑
pipeline.py     analyze.py
                    ↑
                  app.py
```

Résout le couplage `search.py` ↔ `ingest.py`. `chunk_text()` vit
dans `core.py`, importée par les deux pipelines.

### §5.2 — `pipeline.py` simplifié (mis à jour avec la correction §3.4)

Fichier d'état léger (8 lignes JSON) qui skip l'encoding si le
modèle et le corpus n'ont pas changé. Tout le reste est recalculé
(rapide avec les prototypes — plus de confirm_risk dans la boucle).
Pas de manifeste JSON complet.

**Deux constructions de prototypes distinctes**, voir §3.4 : les
prototypes "globaux" (persistés, servent à l'inférence live) et les
prototypes "leave-one-project-out" (calculés à la volée à l'intérieur
de `build_cox_training_data`, jamais persistés en tant que tels, servent
uniquement à construire le dataset d'entraînement sans fuite).

```python
PIPELINE_STATE_FILE = "models/pipeline_state.json"

def run_pipeline(force_rebuild=False):
    state = load_state()
    model_name = "all-mpnet-base-v2"
    corpus_hash = compute_corpus_hash()

    need_reembed = (
        force_rebuild
        or state.get("model_fingerprint") != hash(model_name)
        or state.get("corpus_hash") != corpus_hash
        or not Path("models/embeddings.npy").exists()
    )

    chunks = load_and_process_chunks()  # couche 1

    if need_reembed:
        embeddings = encode_all(chunks, model_name)
        np.save("models/embeddings.npy", embeddings)
    else:
        embeddings = np.load("models/embeddings.npy")

    # Tout le reste : rapide, toujours recalculé
    build_and_save_faiss(embeddings)
    centroid = np.mean(embeddings, axis=0)
    np.save("models/corpus_centroid.npy", centroid)

    info_weights = compute_all_info_weights(chunks, embeddings, centroid)
    np.save("models/info_weights.npy", info_weights)

    # Prototypes GLOBAUX — pour l'inférence live uniquement (§3.4)
    prototypes_global = build_risk_prototypes(chunks, embeddings)
    joblib.dump(prototypes_global, "models/risk_prototypes.pkl")

    # Dataset Cox — prototypes LEAVE-ONE-PROJECT-OUT en interne (§3.4),
    # jamais les prototypes globaux ci-dessus, pour éviter la fuite
    training_df = build_cox_training_data(
        chunks, embeddings, info_weights, faiss_index=None
    )
    cox, c_index = train_cox(training_df)
    joblib.dump(cox, "models/cox_model.pkl")

    save_state(model_name, corpus_hash, len(chunks), c_index)
```

**Lien avec le chantier de préchauffage LLM (§2.5) :** les prototypes
éliminent confirm_risk du pipeline batch. Le réentraînement Cox utilise
les flag scores par prototypes leave-one-project-out — pas d'appels LLM
dans la boucle, pas de fuite. Le décalage train/serve disparaît
structurellement : l'inférence live utilise les prototypes globaux, qui
sont cohérents avec (mais pas identiques à) les prototypes
leave-one-out utilisés pour évaluer le Cox à l'entraînement — c'est
attendu et correct (même logique que n'importe quel modèle évalué en
cross-validation vs déployé sur toutes les données). Le chantier de
préchauffage n'est plus nécessaire.

**Étape 6 — Vérification d'intégrité au démarrage (minimaliste).**

```python
def check_pipeline_ready():
    required = ["models/embeddings.npy", "models/faiss_index.bin",
                "models/chunks_metadata.pkl", "models/cox_model.pkl",
                "models/risk_prototypes.pkl", "models/corpus_centroid.npy"]
    missing = [f for f in required if not Path(f).exists()]
    if missing:
        st.error(f"Lancer pipeline.py d'abord. Manquant : {missing}")
        st.stop()

    state = Path("models/pipeline_state.json")
    if state.exists():
        s = json.loads(state.read_text())
        st.sidebar.caption(
            f"{s.get('n_chunks','?')} chunks | "
            f"C-index {s.get('c_index','?'):.3f} | "
            f"{s.get('built_at','?')[:10]}")
```

Vérifie que les fichiers existent. Affiche les stats en sidebar.
Pas de vérification de cohérence croisée — si les artefacts sont
incohérents, la solution c'est `python -m scripts.pipeline --force`.

### Limites honnêtes

- L'affichage progressif via `st.status` est limité par le modèle
  d'exécution de Streamlit (re-run complet à chaque interaction).
  Si l'utilisateur clique pendant l'analyse, le run est interrompu.
  Le `session_state` persiste les résultats déjà calculés, mais la
  couche 4 (LLM) devra être relancée.
- Le skip d'encoding dans pipeline.py repose sur un hash du corpus.
  Si un document est modifié sans que le hash global change (peu
  probable mais possible avec des modifications mineures), le skip
  sera incorrect. Le flag `--force` est le recours.
- Le coût du leave-one-project-out (§3.4/§5.2) n'a pas été mesuré en
  conditions réelles — à vérifier lors de l'implémentation.

### Ce qu'on ne fait pas

Manifeste JSON complet (over-engineering pour un MVP solo). Dataclass
AnalysisResult (un dict documenté suffit). Machine à états (le
session_state couvre le besoin). DAG de dépendances (Airflow/dbt/
Dagster — pour la phase banque, pas le MVP).

---

## COUCHE 6 — COX & PUISSANCE STATISTIQUE (hors scope du PDF initial)

La synthèse identifie en §2.4 que le vrai frein à la pertinence n'est
pas le retrieval mais la puissance statistique du Cox. C'est le seul
problème que les couches 1-5 ne résolvent pas — et §3.4 ci-dessus
montre qu'il faut être vigilant à ne pas réintroduire un biais qui
masquerait artificiellement ce problème (un C-index gonflé par fuite
donnerait l'illusion que la refonte a réglé la puissance statistique).

### État réel *[mesuré]*

47 projets, 29 événements, 18 censurés. 3 covariables.
flag1 (community) : significatif (p<0.005).
flag2 (pollution) : bruit (p=0.60).
flag3 (compliance) : non significatif (p=0.18).

Règle empirique : 10-15 événements par covariable — il faudrait
30-45 événements pour 3 covariables. On en a 29, c'est limite.
Ajouter des covariables (omission_count, specificity) sans enrichir
le corpus = overfitting garanti.

### Options

**Option A — Enrichir le corpus (Chantier 0).** Passer à 100-150
projets (60-70 événements, 60-80 contrôles). Le registre CAO public
a 200+ cas. Le portail IFC disclosures a des milliers de contrôles.
C'est la seule solution au problème statistique.

**Option B — Afficher une confiance différenciée par flag.** En
attendant l'enrichissement, l'UI affiche la significativité de chaque
flag : flag1 "fiable (p<0.005)", flag2 "non significatif — à
interpréter avec prudence", flag3 "non significatif". Le banquier
sait sur quoi il peut s'appuyer et sur quoi il ne peut pas.

**Option C — Réduire à un seul flag.** Si seul flag1 est significatif,
un Cox univarié sur flag1_community est plus robuste qu'un Cox à 3
covariables dont 2 sont du bruit. Moins riche mais plus honnête. Le
score de l'outil est "score de risque communautaire", pas "score ESG
global". C'est un positionnement qui peut fonctionner en démo si c'est
bien présenté.

Les options B et C sont compatibles avec le MVP. L'option A est le
Chantier 0 du prompt V2, à mener en parallèle.

---

## RÉSUMÉ — Temps estimé du pipeline corrigé

*[hypothèse — non mesuré, à vérifier via Tier 1.1]*

(Document de 10 Mo, ~500 chunks bruts, première analyse)

| Couche | Temps | Ce qui se passe |
|---|---|---|
| 1 — Ingestion | 10-30s | Extraction PDF + filtre + dédup |
| 2 — Embedding | 15-35s | Encode 350-400 chunks (cache) |
| 3 — Scoring | <1s | Prototypes (normalisés) + FAISS evidence + omissions |
| 4 — LLM | 50-150s | 5-8 extractions + 1 synthèse (surlignage inclus, §4.3) |
| **Total** | **~75-215s** | |

Versus l'actuel (centaines d'appels confirm_risk) : **10-20+ minutes**.

Les résultats des couches 1-3 sont publiés en ~35s. Le banquier lit
déjà les scores, omissions, et spécificité pendant que le LLM travaille.

---

## Changelog

- **v2** (base) : intégration des corrections de `SYNTHESE_AUDIT_PIPELINE.md`
  — prototypes avec caveat circularité (§3), point mort `_find_signals_in_document`
  identifié sans être tranché, couche 6 séparée pour la puissance statistique.
- **v2 + corrections** (cette version) : ajout §3.4 (fuite de données Cox
  via prototypes non leave-one-out), §3.5 (prototypes non normalisés ≠
  cosinus comparable entre flags), §4.3 (décision tranchée : réutiliser
  les findings de la Pass 1 pour le surlignage plutôt que de laisser
  `confirm_risk` ou un mécanisme parallèle), §5.2 mise à jour en
  conséquence (deux constructions de prototypes distinctes dans
  `run_pipeline`).
