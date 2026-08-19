# AUDIT_ESG.md — Audit du codebase « ESG Risk Intelligence »

Audit réalisé conformément à la Phase 1 de `PROMPT_CLAUDE_CODE_ESG.md`, avant toute modification. Basé sur une lecture intégrale de `app.py`, des 14 scripts de `scripts/`, de `README.md`, `CORRECTIONS.md`, `checklist.md`, `requirements.txt`, et de l'état des artefacts dans `models/`/`data/`.

Deux documents internes déjà présents (`CORRECTIONS.md`, `checklist.md`) couvrent une bonne partie du terrain historique (bugs corrigés, décisions prises, chantiers en pause) — cet audit les recoupe avec l'état réel du code plutôt que de les paraphraser, et se concentre sur ce que `PROMPT_CLAUDE_CODE_ESG.md` demande explicitement.

---

## 1.1 Architecture

### Cartographie des modules

| Module | Rôle | Dépend de |
|---|---|---|
| `scripts/ingest.py` | PDF/TXT → texte brut (OCR de secours via `pytesseract`) → chunks → `data/processed/chunks.csv` | `search.chunk_text` |
| `scripts/embed.py` | Script exploratoire autonome (encode `chunks.csv`, sauvegarde `embeddings.npy` + test de similarité manuel) | — |
| `scripts/annote.py` | Remplit `flag_type`/`event`/`time_to_event` dans `chunks.csv` depuis `data/raw/corpus_cao_ifc.xlsx` | `ifc_board_dates`, `signals` |
| `scripts/ifc_board_dates.py` | Dictionnaire statique `{numéro IFC: date d'approbation}`, sourcé manuellement | — |
| `scripts/fill_t0_dates.py` | Écrit ces dates dans le xlsx pour traçabilité (side-effect, pas dans le pipeline critique) | `ifc_board_dates` |
| `scripts/signals.py` | Source unique des mots-clés de signaux ESG par flag (regex) | — |
| `scripts/search.py` | Chargement des composants (modèle, FAISS, métadonnées), chunking de requête, `get_flag_scores`, `search_similar` | `signals`, `llm_confirm` |
| `scripts/llm_confirm.py` | 3 fonctions LLM (Ollama local) : `confirm_risk` (filtre polarité), `summarize_passage`, `generate_recommendation` — cache disque partagé | — |
| `scripts/model.py` | Construction du dataset d'entraînement, `train_cox`, `predict_risk`, save/load | `search` |
| `scripts/pipeline.py` | Orchestrateur de ré-entraînement complet (embed → FAISS → flag scores → Cox) | `model` |
| `scripts/explain.py` | SHAP (KernelExplainer) sur le modèle Cox | — |
| `scripts/analyze.py` | Orchestrateur d'inférence : texte → flag scores → passages similaires → prédiction Cox → signaux → recommandation | `search`, `llm_confirm`, `model`, `signals` |
| `scripts/export.py` | Rapport PDF (fpdf2) / Excel (openpyxl) à partir du résultat de `analyze()` | — |
| `scripts/compare_embeddings.py` | Banc d'essai comparatif de modèles d'embedding (C-index + gap risque/neutre) | `model`, `search` |
| `scripts/warm_llm_cache.py` | Préchauffage parallèle du cache LLM (marqué non fonctionnel en l'état, voir §1.3) | `signals`, `llm_confirm` |
| `scripts/test.py` | Suite de tests (unitaires / intégration / cohérence métier) | tout le pipeline |
| `app.py` | Interface Streamlit (4 pages) | `analyze`, `model`, `signals`, `llm_confirm`, `export` |

### Pipeline complet réellement en place

```
corpus/*.pdf|*.txt
   │ ingest.py : extract_pdf() [pdfplumber + fallback OCR pytesseract] / lecture directe .txt
   ▼
chunk_text() [search.py, fenêtre glissante 175 mots / overlap 50]
   ▼
data/processed/chunks.csv  (project_id, project_name, chunk_id, text, flag_type="", event="", time_to_event="", doc_date="")
   │ annote.py : mapping numéro IFC → data/raw/corpus_cao_ifc.xlsx
   │   - event/time_to_event hérités du projet entier
   │   - flag_type restreint au contenu réel du chunk (intersection avec signals.flags_mentioned_in_text)
   ▼
chunks.csv annoté
   │ pipeline.py (étapes 1-3)
   ▼
SentenceTransformer("all-mpnet-base-v2").encode() → models/embeddings.npy (normalisés L2)
   ▼
faiss.IndexFlatIP → models/faiss_index.bin  +  models/chunks_metadata.pkl (DataFrame)
   │ pipeline.py (étape 4) : model.build_training_data()
   │   pour chaque projet annoté → search.get_flag_scores_from_chunks(exclude_project=soi-même)
   ▼
DataFrame [flag1_community, flag2_pollution, flag3_compliance, time_to_event, event]
   │ pipeline.py (étape 5) : model.train_cox()
   ▼
models/cox_model.pkl (CoxPHFitter, penalizer=0.1)

── Côté inférence (analyze.py, appelé par app.py) ──
texte uploadé/collé
   │ search.get_flag_scores()          → 3 flag scores (0-100), filtrés par llm_confirm.confirm_risk
   │ search.search_similar()           → passages historiques voisins (pattern library)
   │ model.predict_risk()              → probabilité 12 mois, grade A-D, courbe de survie
   │ analyze._find_signals_in_document() → signaux détectés dans LE document uploadé (regex + llm_confirm)
   │ llm_confirm.generate_recommendation() → 1 phrase de recommandation (ou None → fallback template)
   ▼
result{flag_scores, prediction, similar_passages, detected_signals, signal_spans, recommendation}
   │ app._map_result_to_display()      → agrégation par flag/projet, résumés LLM, evidence_by_flag
   ▼
Streamlit UI (4 pages) + export.py (PDF/Excel à la demande)
```

Il n'existe **aucune étape « scoring Cox → output final » distincte** de ce qui précède : `predict_risk` produit directement le grade/probabilité consommés tels quels par l'UI, sans post-traitement supplémentaire (pas de calibration, pas d'ajustement).

### Modèles utilisés

- **LLM** : Ollama local, `qwen3:4b-instruct` (`scripts/llm_confirm.py:50`). Utilisé pour 3 fonctions ponctuelles (filtre RISK/CLEAN, résumé de passage, recommandation en 1 phrase) — **jamais pour une analyse ou une synthèse structurée du document**. Aucun autre LLM (Claude, GPT, etc.) n'est intégré nulle part dans le codebase.
- **Embedding** : `sentence-transformers/all-mpnet-base-v2` (768 dim) en production (`search.py:22`, `pipeline.py:46`). `scripts/embed.py` (script exploratoire séparé, non appelé par le pipeline) utilise encore `all-MiniLM-L6-v2` (384 dim) — incohérence de fait entre ce script et la prod, déjà signalée comme obsolète dans `CORRECTIONS.md` §5.4.
- **FAISS** : `IndexFlatIP` (recherche exacte, produit scalaire sur vecteurs normalisés L2 = cosine similarity). Pas d'IVF/HNSW (taille du corpus — 4203 chunks — ne le justifie pas encore).
- **Survie** : `lifelines.CoxPHFitter`, 3 covariables, `penalizer=0.1`, `l1_ratio=0.0` (pure L2).
- **SHAP** : `shap.KernelExplainer` autour de `cox_model.predict_partial_hazard` — code présent (`explain.py`) mais **retiré de `analyze()` et de l'UI** le 24/07 (voir `checklist.md` ligne 50, `test.py` a dû être corrigé après ce retrait). Le module existe mais n'est plus appelé en production.

### Sources de données

- **Corpus documentaire** : `corpus/*.txt` (40 rapports IFC/CAO publics, project finance) + PDF historiques (non présents dans le répertoire actuel — `ingest.py` gère les deux formats). 82 documents mentionnés dans `checklist.md`, 4203 chunks résultants.
- **Annotations/labels** : `data/raw/corpus_cao_ifc.xlsx`, tableur manuel (46 projets exploitables : 28 avec événement CAO/`event=1`, 18 « contrôles »/`event=0`). Colonnes positionnelles (B=numéro IFC, F=date plainte, H=flag, I=censored).
- **Dates T0** : `scripts/ifc_board_dates.py`, dictionnaire codé en dur de 32 dates d'approbation IFC, sourcées manuellement une par une sur `disclosures.ifc.org`.
- **Aucune source de données alternative** (sanctions réglementaires, turnover dirigeants, presse, CDS spreads, etc.) n'est intégrée — uniquement les rapports ESG/E&S eux-mêmes et le registre de plaintes CAO comme unique proxy d'« issue ». C'est exactement le point que `PROMPT_CLAUDE_CODE_ESG.md` §2.5 identifie comme lacune.
- **Aucune API externe** n'est appelée (hormis Ollama en localhost). Pas de connexion à des bases réglementaires, satellites, ou flux de presse.

---

## 1.2 Chunking & Indexation

- **Découpage** : fenêtre glissante à **taille fixe** — `chunk_size=175` mots, `overlap=50` mots, `min_words=30` (`search.py:37-39,42-66`). Aucune notion de cohérence sémantique, de section, ou d'unité argumentative (claim + evidence) : un chunk peut couper une phrase ou un paragraphe en plein milieu.
- **Duplication de logique** : la fonction `chunk_text()` vit dans `search.py` et est réutilisée par `ingest.py` — bien identifiée comme couplage fragile dans un commentaire dédié (`search.py:45-59`) : elle **doit** rester identique entre construction du corpus et découpage d'une requête, sous peine d'incohérence train/serve.
- **Troncature du modèle d'embedding** : `all-mpnet-base-v2` tronque silencieusement à 384 tokens (~260-280 mots) — les chunks de 175 mots tiennent avec marge, mais **tout texte de requête plus long qu'un chunk doit être re-découpé avant l'embedding**, sinon la fin est purement ignorée (documenté dans le même commentaire).
- **Pas de hiérarchie Document → Section → Chunk.** Les seules métadonnées portées par chunk sont : `project_id`, `project_name`, `chunk_id`, `text`, `flag_type`, `event`, `time_to_event`, `doc_date` (colonne présente dans le schéma d'`ingest.py` mais **jamais remplie** — toujours `""`). Aucune notion de section thématique (E/S/G), de type de chunk (claim/metric/commitment/narrative), d'entités, de références temporelles, de sentiment, ni de score de spécificité.
- **flag_type n'est pas une métadonnée enrichie mais un label d'entraînement** : c'est une chaîne comme `"Flag 1"` ou `"Flag 2 + Flag 3"`, dérivée de l'héritage projet **filtré par la présence de mots-clés `signals.py`** dans le texte du chunk (`annote.py:141-160`, correctif du 24/07 documenté en détail). Utile pour l'entraînement Cox, mais ce n'est pas une métadonnée de traçabilité (pas de section, pas de date de rapport, pas d'entreprise distincte du projet).
- **Pas de re-ranking après FAISS.** `search_similar_from_chunks`/`get_flag_scores_from_chunks` (`search.py:75-118`, `130-182`) utilisent directement les scores de similarité cosine (produit scalaire IP) retournés par `index.search()`, agrégés **par max** à travers tous les chunks et tous les k voisins. Aucun cross-encoder, aucun score composite (recency/spécificité/crédibilité de la source) — la totalité de la pertinence retenue est la similarité lexico-sémantique brute.
- **exclude_project (anti-fuite de données)** : mécanisme correctement implémenté — lors de l'entraînement, un projet est exclu de ses propres voisins FAISS pour éviter l'auto-matching (bug corrigé documenté dans `CORRECTIONS.md`).
- **Filtre de polarité comme substitut partiel de re-ranking** : `llm_confirm.confirm_risk()` (voir §1.3) joue un rôle proche d'un re-ranker (il filtre des candidats jugés non pertinents), mais seulement en aval de l'agrégation par flag, jamais en remplaçant/reclassant les k voisins eux-mêmes.

---

## 1.3 Prompting & Chaîne LLM

Il n'existe **pas** de chaîne d'analyse LLM au sens du prompt (extraction structurée / détection de contradictions / scénarios contrefactuels / synthèse). Le LLM local (`qwen3:4b-instruct` via Ollama, `scripts/llm_confirm.py`) est utilisé pour **3 micro-tâches indépendantes**, chacune avec son propre prompt court, jamais chaînées entre elles :

1. **`confirm_risk(chunk_text, flag_num)`** (`llm_confirm.py:95-160`) — un appel par (chunk candidat via regex, flag) : « ce passage décrit-il un problème réel ou une situation conforme/résolue ? » → réponse `RISK`/`CLEAN` en un mot. C'est un **filtre binaire de polarité**, pas une analyse. Branché dans `search.get_flag_scores_from_chunks` (train + inférence) et dans `analyze._find_signals_in_document` (détection de signaux affichés).
2. **`summarize_passage(text)`** (`llm_confirm.py:163-220`) — reformule un passage historique (~175 mots) en une phrase, pour l'affichage « Historical Similar Cases » / « Evidence behind this score ». Résumé, pas analyse.
3. **`generate_recommendation(risk_grade, probability_12m, detected_signals)`** (`llm_confirm.py:223-279`) — une phrase de recommandation credit committee, à partir du grade + de la liste des noms de signaux détectés (pas du texte du document). Aucun raisonnement multi-étapes.

**Aucun prompt système structurant une chaîne d'analyse n'existe** — pas d'extraction JSON structurée des engagements/métriques/incidents, pas de comparaison à une matrice de matérialité sectorielle (SASB/GRI), pas de détection explicite de contradiction entre deux sources, pas de scénario d'impact chiffré, pas de note de synthèse pour comité de crédit au sens du prompt (`generate_recommendation` produit une phrase, pas une note).

- **Un seul appel LLM à la fois**, jamais de contexte multi-documents/multi-source transmis au LLM (le LLM ne voit jamais qu'un seul chunk ou qu'une liste de noms de signaux — pas de données de référence sectorielles, pas de données réglementaires/juridiques externes, qui de toute façon n'existent pas dans le codebase, cf. §1.1).
- **Fail-open partout** : si Ollama est injoignable, `confirm_risk` retourne `True` (comportement pré-filtre), `summarize_passage` retourne l'extrait tronqué à 220 caractères, `generate_recommendation` retourne `None` (fallback sur un template fixe par grade dans `app.py:37-42`). Robuste opérationnellement, mais confirme que le système est conçu pour dégrader gracieusement vers **zéro analyse LLM**, pas vers une analyse partielle.
- **Cache disque partagé** (`models/llm_confirm_cache.json`), clé = hash(flag_num + définition du flag + texte) pour `confirm_risk`, préfixes séparés pour `summarize`/`recommend`. Bien pensé pour éviter les appels redondants, mais un seul appel par (chunk, flag) sur la **première occurrence seulement** d'un mot-clé dans un document (`analyze.py:73-79` documente explicitement cette limite assumée).
- **Problème de débit non résolu** (`checklist.md`, section « Chantier ouvert ») : le débit LLM se dégrade sous charge soutenue (séquentielle ou parallèle), cause non diagnostiquée avec certitude. N'affecte pas l'usage live (quelques appels par document), mais bloque le ré-entraînement complet du Cox sur des scores filtrés par LLM — `cox_model.pkl` actuel est entraîné sur des flag scores **non filtrés** par `confirm_risk`, alors que l'inférence live, elle, filtre. **Décalage train/serve actuellement accepté comme dette technique.**

---

## 1.4 Modèle de Cox

- **Features** : exactement 3 covariables — `flag1_community`, `flag2_pollution`, `flag3_compliance` — chacune un score 0-100 dérivé de l'agrégation **max** des scores de similarité FAISS (cosine × 100, arrondi) sur les chunks d'un projet, filtrés par `confirm_risk` (`model.py:35-108`, `search.py:150-182`). Aucune feature de second ordre, de tendance temporelle, de volatilité, d'écart sectoriel, ni d'interaction — rien de ce que `PROMPT_CLAUDE_CODE_ESG.md` §2.4 propose n'existe.
- **Pas de transformation autre que le max par flag** : pas de moyenne pondérée par similarité, pas de decay temporel, pas de pondération par crédibilité de source (toutes les sources sont des rapports ESG/E&S du même registre).
- **Aucun terme d'interaction** (`env_x_gov`, `controversy_x_trend`, etc.) — le modèle Cox est ajusté sur les 3 scores bruts uniquement, `penalizer=0.1`, `l1_ratio=0.0`.
- **Performance actuelle** (mesurée, cf. `checklist.md`/`CORRECTIONS.md`, cohérente avec `models/embedding_comparison.json`) :
  - C-index ≈ **0.627 à 0.758** selon la version (0.627 rapporté dans `CORRECTIONS.md` après la 1ère correction de fuite de données ; 0.758 après ré-annotation par contenu ; 0.746 avec le passage à mpnet ; **pas de mesure post-filtre LLM**, cf. §1.3).
  - **Aucun coefficient statistiquement significatif** au moment de `CORRECTIONS.md` (p > 0.35 sur les 3 covariables) — `CORRECTIONS.md` §4 l'attribue explicitement au déséquilibre du corpus (28 événements pour seulement 2 témoins à l'origine, partiellement corrigé depuis à 28/18).
  - **Pas de calibration testée** (Brier score, calibration plot) — seul le C-index (discrimination) est mesuré. `explain.py` (SHAP) existe mais n'est plus appelé par `analyze()` depuis le 24/07.
  - Seuils de classification (`DEFAULT_RISK_THRESHOLDS`, `model.py:166-174`) : Vigilance <25%, Attention 25-55%, Alerte 55-80%, Escalade >80% — choix arbitraires ajustables depuis l'UI (`Settings`), pas calibrés statistiquement.
- **VIF/multicolinéarité** : non implémenté, non mesuré nulle part.
- **Traçabilité de l'importance des features** : SHAP existait (`explain.py`) mais retiré de l'UI/pipeline — aucune traçabilité d'importance de feature n'est actuellement exposée à l'utilisateur final.

---

## 1.5 Output & Reporting

- **Format de sortie** : dashboard Streamlit (4 pages : Transaction Analysis, Portfolio Dashboard, Pattern Library, Settings) + export PDF/Excel à la demande (`scripts/export.py`). Sortie structurée : grade lettre (A-D) + score 0-100 + probabilité 12 mois + liste de signaux détectés (regroupés par flag) + document annoté (surlignage) + passages historiques similaires + 1 phrase de recommandation.
- **Traçabilité** :
  - Les flag scores sont reliés à leurs preuves via `evidence_by_flag` (`app.py:176-198`) — dérivé des mêmes voisins FAISS que ceux utilisés pour le calcul du score, pas d'appel supplémentaire. C'est un vrai mécanisme de citation (projet historique + score + extrait résumé).
  - Les signaux détectés portent un `evidence_excerpt` (contexte textuel autour de la première occurrence, `analyze.py:82-105`).
  - **Mais** : aucune conclusion de la synthèse finale (recommandation, grade) n'est reliée explicitement à *quelles preuves l'ont produite* au-delà de ce niveau — la recommandation LLM cite des noms de signaux, pas des passages exacts ; le grade Cox est un chiffre, sans décomposition en contribution par flag visible dans l'UI actuelle (SHAP retiré).
- **Confiance/incertitude** : un seul signal de confiance existe — `confidence = min(occurrences / 5, 1.0)` par signal détecté (`analyze.py:103`), une heuristique de fréquence, pas une mesure statistique de la fiabilité du grade Cox lui-même. Aucun intervalle de confiance sur `probability_12m`, aucune indication de la fiabilité du modèle compte tenu du faible pouvoir discriminant mesuré (§1.4).
- **Ce que l'outil produit concrètement** : un score de similarité à des passages historiques (« ce texte ressemble à X% à des projets connus pour tel type de risque »), pas une analyse au sens du problème énoncé en tête de `PROMPT_CLAUDE_CODE_ESG.md` — c'est cohérent avec le diagnostic du prompt (« l'outil se comporte comme un résumeur/matcher de similarité, pas un analyste »).

---

## Synthèse — pourquoi les analyses sont superficielles

En clair, l'architecture explique directement le symptôme identifié en préambule du prompt :

1. **Le chunking à taille fixe** ne préserve aucune unité argumentative — un engagement et son évidence (ou son absence) peuvent se retrouver dans des chunks différents, jamais recombinés.
2. **Aucun re-ranking analytique** — FAISS + cosine similarity mesure une proximité lexico-sémantique de surface ; le seul filtre de qualité ajouté (LLM polarité) répond à un bug spécifique (confusion sujet/polarité), pas à un besoin d'évaluation analytique de la pertinence.
3. **Le LLM ne fait que 3 micro-tâches ponctuelles** (filtre binaire, résumé, une phrase de recommandation) — il n'y a **aucune étape d'extraction structurée, de détection de contradiction/omission, ni de construction de scénarios**. C'est très exactement l'écart entre « résumeur » et « analyste » que le prompt pointe.
4. **Le modèle Cox n'a que 3 features de similarité brute**, sans aucune feature de tendance, d'écart, d'interaction ou de contexte sectoriel — il ne peut structurellement pas capter de signal au-delà de « ce texte ressemble-t-il à un cas à risque connu ».
5. **Aucune source de données alternative** (réglementaire, presse, marché) n'existe pour trianguler ce que l'entreprise déclare — l'outil n'analyse que le document qu'on lui donne, contre un historique de documents du même type.

Ce constat correspond point par point aux priorités de la Phase 2 du prompt (`PROMPT_CLAUDE_CODE_ESG.md` §2.1-2.6), qui restent donc pertinentes telles quelles. Point additionnel à noter avant d'attaquer la Phase 2 : le corpus (46 projets, 28 événements/18 contrôles, aucun coefficient Cox significatif à ce jour) est un facteur limitant documenté indépendamment (`CORRECTIONS.md` §4) — les features avancées de Cox (§2.4 du prompt) risquent de se heurter au même manque de contraste statistique tant que le corpus n'est pas enrichi, indépendamment de la qualité de leur conception.

---

## Addendum — Chantier 0 de PROMPT_CLAUDE_CODE_ESG_V2 (enrichissement du corpus)

Note ajoutée suite à la lecture de `PROMPT_CLAUDE_CODE_ESG_V2 (1).md`, qui insère un **Chantier 0** (scraping CAO/IFC pour passer le corpus de 46 à 100-150 projets) avant tous les autres chantiers. Recherche de faisabilité effectuée, aucun code écrit.

### État actuel précis du corpus (vérifié, 2026-07-30)

- **4203 chunks**, **47 projets annotés** (`event` non vide) dans `chunks.csv`.
- **29 projets `event=1`** (plainte CAO), **18 projets `event=0`** (contrôles).
- **46 projets réellement exploitables** par `model.build_training_data` (un seul exclu : Bujagali 2 Refi / IFC 39102, `event=1` sans date d'événement lisible — incohérence déjà documentée dans `CORRECTIONS.md` §5.2, toujours non résolue).
- Les 32 dates T0 dans `ifc_board_dates.py` ont été **sourcées et vérifiées manuellement une par une** (docstring du fichier) — c'est le goulot d'étranglement humain que le Chantier 0 devra reproduire à plus grande échelle, pas seulement automatiser la collecte de documents.

### Faisabilité technique du scraping envisagé (Étapes 0a/0b)

Vérifié en direct sur les deux domaines cibles (`robots.txt` + structure de page) :

| Point | `cao-ombudsman.org` | `disclosures.ifc.org` |
|---|---|---|
| `robots.txt` | Présent (site Drupal). N'interdit **pas** `/cases/` ni les pages de cas individuelles ; interdit `/search/`, `/admin/`, les chemins de connexion/commentaires. Aucun `Crawl-delay` déclaré — le délai de 1-2s prévu par le prompt reste une bonne pratique à respecter, pas une obligation technique mesurée. | **Aucun `robots.txt` trouvé (404)** — ne pas en déduire une autorisation implicite ; vérifier les conditions d'utilisation du portail avant de scraper à grande échelle. |
| Nature de la page | Base de recherche **dynamique** (JS) avec filtres (statut, région, pays, institution, secteur, 30+ thèmes transverses) et pagination. `requests` + `BeautifulSoup` seuls (comme l'esquisse le prompt) **ne suffiront probablement pas** pour la liste elle-même. | Portail **piloté par JS** (dropdowns pays/secteur en navigation côté client). Les résultats de recherche semblent passer par des paramètres d'URL exploitables (`/search?Type_Description=Investment&sortBy=Disclosed_Date...`), mais ceci n'est pas confirmé en conditions réelles (à vérifier empiriquement avant d'écrire `scrape_ifc.py`, pas à supposer). |
| Bonne nouvelle trouvée | Une fonction **« Export All Cases » en CSV** existe sur la page `/cases` — bien plus fiable qu'un scraping HTML de la liste pour les métadonnées de cas (numéro, statut, pays, secteur). Ne dispense pas de visiter chaque page de cas individuellle pour les PDFs (rapports d'investigation/monitoring) et les dates précises. | Aucune API publique documentée trouvée. À confirmer avant d'écrire le script — le prompt suggère « utilise l'API si disponible », ce qui reste à vérifier plutôt qu'à supposer. |
| Implication pratique | `scrape_cao.py` devrait démarrer par ce CSV export plutôt que par un scraping de la page de liste — réduit le risque de casser au moindre changement de mise en page. | `scrape_ifc.py` nécessitera probablement un outil capable d'exécuter du JS (Playwright, déjà installé dans `venv/` pour les tests UI — cf. `checklist.md`) plutôt que `requests` seul, à valider dès la première tentative. |

### Risques/contraintes à garder en tête pour le Chantier 0

- **Le goulot n'est pas la collecte, c'est la vérification humaine.** Le prompt lui-même liste des tâches non automatisables (vérifier que les PDFs téléchargés sont les bons, valider dates T0/T_event, valider l'appariement secteur/région des contrôles). À l'échelle actuelle (32 dates), cette vérification a déjà pris un travail dédié documenté finement ; multiplier par ~3-4 le volume multiplie d'autant ce travail manuel, pas seulement le temps de scraping.
- **Qualité d'appariement des contrôles** : le prompt demande explicitement même secteur/région/période sans plainte CAO — un mauvais appariement (ex. comparer un projet minier à un barrage) dégraderait la qualité du corpus plutôt que de l'améliorer, contrairement à l'intuition « plus de données = mieux ».
- **`flag_type` des nouveaux cas CAO** : le prompt dit d'attribuer un `flag_type` « selon les catégories du cas » à la collecte — à recouper avec `annote.py`, qui aujourd'hui **restreint** le flag hérité du projet au contenu réel du chunk (voir §1.2 de cet audit). Il faudra appliquer la même logique de restriction aux nouveaux projets, pas hériter en bloc comme avant le correctif du 24/07.
- **Rien ne garantit un gain de significativité statistique** — le prompt le reconnaît lui-même (§ Chantier 0, critère de succès) : un C-index/coefficients significatifs seraient un bonus, pas l'objectif premier, qui reste le volume brut pour la crédibilité de la démo.

---

## Points hors-périmètre Phase 1 mais à connaître avant d'implémenter la Phase 2

- **`scripts/embed.py`** est un doublon obsolète de l'étape 1-3 de `pipeline.py` (MiniLM au lieu de mpnet, jamais appelé par le pipeline réel) — signalé comme candidat à suppression dans `CORRECTIONS.md` §5.4, toujours présent.
- **Chemins codés en dur** : tous les scripts utilisent `Path(__file__).resolve().parent.parent` (déjà corrigé selon `CORRECTIONS.md` §5.3) — vérifié dans le code actuel, ce point semble résolu.
- **`doc_date`** est dans le schéma de `chunks.csv` (`ingest.py`) mais n'est jamais rempli — si la Phase 2 (§2.1 du prompt) veut vraiment un `report_date` par chunk, il faudra soit l'extraire du document, soit l'hériter d'une métadonnée projet qui n'existe pas encore.
- **Le C-index actuel (~0.63-0.76 selon version) n'est pas mesuré post-filtre LLM** — toute nouvelle feature Cox (§2.4) devrait être validée sur un ré-entraînement à jour, ce qui suppose de débloquer le chantier de préchauffage du cache LLM (§1.3) ou d'accepter le décalage train/serve documenté.
