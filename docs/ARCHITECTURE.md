# Architecture technique — ESG Risk Intelligence

Résumé des choix clés, du schéma de données et des dépendances. Pour le détail
du "pourquoi" de chaque choix, voir `docs/DECISIONS_TECHNIQUES.md` (ADR). Pour
l'historique chronologique des changements, voir `docs/CHANGELOG.md`.

## Vue d'ensemble du pipeline

```
PDF/TXT uploadé
 → chunking (search.chunk_text — fenêtres glissantes de 175 mots, overlap 50,
   filtre boilerplate/table des matières)
 → embedding (sentence-transformers, all-mpnet-base-v2, 768 dim)
 → recherche FAISS (IndexFlatIP, cosine similarity, top-k)
 → pondération par métadonnées (spécificité, récence, type de chunk)
   [search._weight_candidates — remplace un ancien cross-encoder, retiré]
 → filtre de polarité LLM (llm_confirm.confirm_risk, plafonné à 30 appels)
   [élimine les faux positifs FAISS : un chunk qui MENTIONNE un sujet à
   risque matche les mêmes voisins qu'il soit traité comme un problème ou
   comme résolu — l'embedding capture le sujet, pas la polarité]
 → agrégation → flag_scores (community/pollution/compliance, 0-100 chacun)
 → grade par règle (model.compute_grade — max(flag_scores) vs seuils)
   [remplace un ancien modèle Cox, retiré]
 → détection de signaux dans le document lui-même (analyze._find_signals_in_document)
 → recommandation contextualisée (llm_confirm.generate_recommendation)
 → pipeline LLM multi-pass (deep_analysis.py) :
     Pass 1 — extraction par chunk (engagement/incident/formulation évasive)
     Pass 2 — détection d'omissions (sujets ESG critiques non couverts)
     Pass 3 — synthèse d'alerte en langage naturel
 → résultat agrégé (analyze.analyze() → dict result{})
 → affichage Streamlit (app.py) + exports PDF/Excel (export.py)
```

Tous les appels LLM (confirm_risk, summarize_passage, generate_recommendation,
Pass 1/2/3) sont **fail-open** : si le backend est injoignable, l'analyse se
dégrade gracieusement (repli sur un comportement pré-LLM ou un résultat vide
pour cette étape) au lieu de planter.

## Composants et responsabilités

| Module | Responsabilité |
|---|---|
| `app.py` | UI Streamlit (4 onglets), mapping `result` → `display` pour l'affichage |
| `scripts/config.py` | Feature flags, seuils Ollama (`num_predict`/`num_ctx` par usage), routage backend LLM |
| `scripts/signals.py` | Mots-clés ESG par flag — **source unique**, utilisée par `analyze.py`/`annote.py` |
| `scripts/search.py` | Chunking (`chunk_text`), embedding, recherche FAISS, pondération, agrégation des flag_scores |
| `scripts/analyze.py` | Orchestrateur (`analyze()`), chargement des modèles (singleton thread-safe), détection de signaux dans le document uploadé |
| `scripts/llm_backend.py` | Abstraction réseau Ollama local / Together cloud — une seule fonction publique `call_llm()`, jamais d'exception |
| `scripts/llm_confirm.py` | Filtre de polarité (`confirm_risk`), résumé de passages (`summarize_passage`), recommandation (`generate_recommendation`) — cache disque |
| `scripts/deep_analysis.py` | Pipeline LLM multi-pass (Pass 1/2/3), adapté à un modèle 4B (format ligne par ligne, pas de JSON) |
| `scripts/chunk_metadata.py` | Fonctions pures : date de document, type de section, type de chunk, score de spécificité |
| `scripts/model.py` | `compute_grade()` (actif) — grade par règle sur `max(flag_scores)`. Fonctions Cox conservées en code mort |
| `scripts/export.py` | Génération PDF (fpdf2) et Excel (openpyxl) du résultat d'analyse |
| `scripts/ingest.py` / `scripts/pipeline.py` | Ingestion du corpus (PDF → chunks.csv) et ré-entraînement (embeddings + index FAISS) |
| `scripts/annote.py` | Annotation du corpus (flag_type/event/time_to_event) à partir de `corpus_cao_ifc.xlsx` |

**Code mort, volontairement conservé sur disque, non appelé par le pipeline actif** : `scripts/reranker.py` (cross-encoder, retiré le 2026-08-08), les fonctions Cox de `scripts/model.py` (`build_training_data`/`train_cox`/`predict_risk`), `scripts/warm_llm_cache.py` (préchauffage de cache, en pause — dégradation de débit non résolue sur charge soutenue).

## Schéma de données

Aucune base relationnelle — persistance par fichiers plats.

**`data/processed/chunks.csv`** — un chunk par ligne :
`project_id, project_name, chunk_id, text, flag_type, event, time_to_event, doc_date, section_type, chunk_type, specificity_score`
- `flag_type` : chaîne libre type `"Flag 1 + Flag 2"` ou `""` (jamais castée en int)
- `event` : `1` (incident ESG confirmé) / `0` (contrôle) / vide (non annoté)
- `time_to_event` : mois entre T0 (approbation IFC) et l'événement (ou aujourd'hui si contrôle)

**`models/`** (gitignored) :
- `embeddings.npy` — vecteurs 768-dim normalisés L2, un par ligne de `chunks.csv`
- `faiss_index.bin` — index FAISS `IndexFlatIP`
- `chunks_metadata.pkl` — `chunks.csv` chargé en DataFrame pandas, indexé par position (`search.py` y accède via `.iloc[]`)
- `llm_confirm_cache.json` / `deep_analysis_cache.json` — caches LLM plats, clé = hash(backend + modèle + contenu pertinent), invalidation automatique si l'un change

**`data/raw/corpus_cao_ifc.xlsx`** — source des annotations (event/time_to_event/flag_type par projet), consommée par `annote.py`.

## Dépendances externes clés

- `sentence-transformers` (embedding, `all-mpnet-base-v2`)
- `faiss-cpu` (recherche vectorielle)
- Ollama local (`qwen3:4b-instruct`) ou Together AI cloud (`Qwen/Qwen3.5-9B`), routés par `llm_backend.py`
- `streamlit` (UI), `fpdf2` + `openpyxl` (exports), `pdfplumber` + `pytesseract`/`pdf2image` (extraction PDF, OCR de secours)
- `lifelines` — présent dans `requirements.txt` mais uniquement pour le code mort Cox

## Déploiement

Docker Compose, 3 services :
- `ollama` — non exposé au host, atteignable uniquement via le réseau Docker interne
- `app` — Streamlit, pas de `ports:` direct (accès uniquement via `caddy`)
- `caddy` — reverse-proxy + `basic_auth`, seul point d'entrée exposé (80/443)

`OLLAMA_HOST`/`LLM_BACKEND`/`TOGETHER_API_KEY`/`LLM_FALLBACK` configurés par variables d'environnement (`.env`, gitignored) — jamais en dur dans le code.
