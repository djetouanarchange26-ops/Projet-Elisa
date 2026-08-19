# Audit du repository — état des lieux pré-refonte Grille ESG

Date : 2026-08-15. Lecture seule, aucun fichier de code modifié — voir la
demande d'audit. Objectif : servir de référence avant la refonte du scoring
vers une Grille d'Évaluation ESG à 12 questions structurées.

---

## Architecture actuelle (flux `analyze()` en pseudo-code)

```
analyze(pdf_text, risk_thresholds=None, k=15, document_label=...)
  _ensure_loaded()                         # singleton thread-safe : model, index, metadata

  # 1+2. Un seul passage de scoring (fix perf documenté, ne pas dédoubler)
  flag_scores, similar_passages = search.analyze_query(pdf_text, model, index, metadata, k)
      chunks = search.chunk_text(pdf_text)                      # fenêtres 175 mots, overlap 50
      top_candidates_per_chunk = _rerank_all_chunks(...)        # embedding + FAISS + pondération métadonnées
      gated_flags_per_chunk = _gate_flags_with_llm(...)         # confirm_risk(), plafonné à 30 appels
      flag_scores = _aggregate_flag_scores(...)                 # max() par flag, 0-100
      similar_passages = candidats aplatis

  # 3. Grade par règle (remplace Cox)
  prediction = model.compute_grade(flag_scores, risk_thresholds)   # max(flag_scores) vs seuils -> A/B/C/D

  # 4. Signaux détectés dans LE document uploadé (regex + LLM de polarité)
  detected_signals, signal_spans = _find_signals_in_document(pdf_text)

  # 5. Recommandation 1 phrase (LLM, fail-open -> None)
  recommendation = llm_confirm.generate_recommendation(prediction["risk_grade"], detected_signals)

  # 6. Pipeline LLM multi-pass (Pass 1/2/3), jamais d'exception
  deep = deep_analysis.run_deep_analysis(pdf_text, document_label, prediction["risk_grade"], detected_signals)

  return { flag_scores, prediction, similar_passages, detected_signals,
           signal_spans, recommendation, deep_analysis, processing_time_s }
```

## Pipeline actuel (composants et ordre d'appel)

1. **Ingestion corpus** (offline, `ingest.py` → `pipeline.py`) : PDF/TXT → `chunk_text()` (175 mots, overlap 50, filtre boilerplate/table des matières) → embeddings `all-mpnet-base-v2` (768-dim, normalisés L2) → `faiss_index.bin` (`IndexFlatIP`) + `chunks_metadata.pkl`. Enrichissement Chantier 1 (`chunk_metadata.py` : `doc_date`, `section_type`, `chunk_type`, `specificity_score`) appliqué au corpus uniquement, jamais à une requête live.
2. **Annotation** (offline, `annote.py`) : `corpus_cao_ifc.xlsx` → `flag_type`/`event`/`time_to_event` par chunk, avec réduction du `flag_type` hérité du projet à ce que le texte du chunk mentionne réellement (`signals.flags_mentioned_in_text`).
3. **Requête live** (`analyze.py`) : voir pseudo-code ci-dessus.
4. **Affichage** (`app.py`, 1270 lignes, 4 onglets Streamlit) : mapping `result` → `display`, radar chart (flag_scores + specificity + score d'omission), document annoté (surlignage via `signal_spans`), Pattern Library (passages similaires), Portfolio Dashboard.
5. **Export** (`export.py`) : PDF (`fpdf2`) et Excel (`openpyxl`) du résultat.

Composant retiré du pipeline actif mais conservé sur disque : le
cross-encoder de re-ranking (`reranker.py`, `cross-encoder/ms-marco-MiniLM-L-6-v2`)
et le modèle de survie Cox (`model.py::build_training_data/train_cox/predict_risk`).
Confirmé par grep : `reranker` n'est importé nulle part dans `scripts/`. Les
fonctions Cox de `model.py` ne sont plus importées que par deux scripts
utilitaires annexes (`compare_embeddings.py`, `calibrate_thresholds.py`),
pas par `analyze.py`/`app.py`.

## Questions — grille structurée présente dans le code ?

**Absente.** Recherche exhaustive (`grille`, `question_grid`, `ESG_QUESTIONS`,
`grid`, "12 questions") dans `scripts/` : aucune occurrence. Le scoring
actuel n'a pas de notion de question structurée — il repose sur 3 "flags"
agrégés (community/pollution/compliance), chacun un score continu 0-100
dérivé du max des candidats FAISS pondérés, sans décomposition par question
ni par critère E/S/G individuel. `chunk_metadata.classify_section_type`
classe bien un chunk en `environmental`/`social`/`governance`/`general`,
mais ce résultat n'alimente aujourd'hui que le prompt Pass 2 (thèmes
couverts) — il n'est pas utilisé comme dimension de scoring.

## Signals (`scripts/signals.py`, source unique — 59 lignes)

- **3 flags**, **10 catégories de signal**, **54 mots-clés** au total :
  - Flag 1 (communauté) : 4 catégories (`community opposition`, `displacement risk`, `stakeholder conflict`, `consultation gaps`) — 20 mots-clés
  - Flag 2 (pollution) : 3 catégories (`pollution risk`, `monitoring gaps`, `spill risk`) — 15 mots-clés
  - Flag 3 (conformité) : 3 catégories (`biodiversity threat`, `ESAP delays`, `PS non-conformance`) — 19 mots-clés
- **2 fonctions publiques** : `flags_mentioned_in_text(text) -> set[int]` (utilisée par `annote.py` et `search._gate_flags_with_llm`). Pas de docstring de module formel mais un bloc d'en-tête explicatif (CHOIX/ALT/TODO).
- `SIGNAL_PATTERNS` : dict `(flag_num, signal_name) -> re.Pattern` compilé une fois à l'import, `\b(?:kw1|kw2|...)\w*` insensible à la casse.
- Consommateurs documentés : `analyze.py`, `annote.py`, `search.py` (indirectement via `_gate_flags_with_llm`), `app.py` (non vérifié en détail ici, mais listé dans `CLAUDE.md` comme un des 4 modules impactés par tout changement de `signals.py`).

## Scoring (`model.py::compute_grade` — actif depuis le 2026-08-08)

```python
DEFAULT_RISK_THRESHOLDS = [
    (15,  "Vigilance", "D"),
    (35,  "Attention", "C"),
    (60,  "Alerte",    "B"),
    (101, "Escalade",  "A"),
]
```

Règle exacte : `max_score = max(flag_scores.values())` (0-100), puis premier
seuil de la liste (triée croissant) tel que `max_score < threshold` donne le
label/grade ; sinon (`max_score >= 60`) grade `A`/"Escalade" par défaut.
Convention : **A = pire, D = meilleur**. Pas de moyenne pondérée entre
flags — un seul flag élevé suffit à déclencher un grade sévère
(`compute_grade({"flag1": 90, "flag2": 5, "flag3": 5})` → grade A, testé
explicitement dans `test.py`).

Le modèle Cox (`CoxPHFitter`, `lifelines`) est **code mort documenté** :
retiré le 2026-08-08 (coefficients flag2/flag3 non significatifs sur 46
projets, décalage train/serve non résolu — `checklist.md`). `lifelines`
reste dans `requirements.txt` uniquement pour ce code mort.

## LLM (backends, modèles, templates de prompt)

**Backends** (`llm_backend.py`, abstraction ajoutée le 2026-08-07) :
- `ollama` (défaut) — appel direct `POST /api/generate`, modèle `qwen3:4b-instruct`, host configurable via `config.OLLAMA_HOST` (jamais `localhost` en dur, nécessaire pour Docker).
- `together` (cloud, opt-in via `LLM_BACKEND=together`) — API compatible OpenAI, modèle `Qwen/Qwen3.5-9B`, nécessite `TOGETHER_API_KEY`, avec `chat_template_kwargs.enable_thinking=False` pour les modèles Qwen (bug corrigé : sans ça, le raisonnement interne consommait tout le budget de tokens et laissait `content=""`).
- `LLM_FALLBACK` (défaut `ollama`) : bascule automatique si le backend principal échoue — fail-open à deux niveaux (par appel, puis par backend).
- Rate limiting (`LLM_RATE_LIMIT=10 req/s`) appliqué uniquement aux backends cloud.

**5 usages configurés** (`config.OLLAMA_CONFIGS`, num_predict/num_ctx) :
`confirm_risk` (5/512), `summarize` (80/768), `recommend` (150/1024),
`deep_extract`=Pass1 (180/1024), `deep_synthesize`=Pass3 (450/2048). **Pass 2
n'a délibérément aucun plafond** (`config_key=None`) — invariant documenté
et testé (`test.py` : `_resolve_options(None, 0.0)["max_tokens"] is None`).

**Templates de prompt** (3, dans `deep_analysis.py`) :
- **Pass 1** (`_PASS1_PROMPT_TEMPLATE`) — par chunk (borné à `MAX_CHUNKS_PASS1=20`), format ligne-par-ligne `ENGAGEMENT/INCIDENT/EVASIF: OUI/NON | champs`, parsé par regex tolérant (`_parse_pass1_response`).
- **Pass 2** (`_PASS2_PROMPT_TEMPLATE`) — un seul appel, liste les 6 `_CRITICAL_TOPICS` contre les `section_type` détectés, demande les sujets absents. Parsing fragile documenté : le modèle 4B répète sa réponse plusieurs fois (jusqu'à 29 lignes observées), seul le dernier bloc matchant est retenu.
- **Pass 3** (`_PASS3_PROMPT_TEMPLATE`) — synthèse 3-5 phrases à partir des findings agrégés + grade + signaux, `timeout=150` (explicite, plus long que le défaut 60s).

Plus 3 usages ponctuels dans `llm_confirm.py` : `confirm_risk` (polarité
RISK/CLEAN, fail-open → `True`), `summarize_passage` (résumé 1 phrase,
fail-open → extrait tronqué à 220 caractères), `generate_recommendation`
(1 phrase pour comité de crédit, fail-open → `None`).

Tous les appels LLM sont fail-open (retour `None`/valeur par défaut sûre,
jamais d'exception propagée) — cohérent avec l'invariant documenté dans
`CLAUDE.md`.

## Tests

**Écart notable avec `CLAUDE.md` : pas de répertoire `tests/`.** La structure
documentée (`tests/test.py`, `tests/test_gold_standard.py`,
`tests/fixtures/`) n'existe pas sur le disque. Le seul test présent est
`scripts/test.py` (357 lignes), un runner maison (pas pytest) invoqué par
`python test.py [--unit|--integ|--business]`, avec compteurs
`_passed/_failed/_warnings` et sorties `print()` (dont des emojis — en
tension avec la règle "pas d'emoji dans les logs" de `CLAUDE.md`, bien que
ce ne soient pas des logs de production).

3 tiers, dans un seul fichier :
- **Unitaires** (`test_unit`) : existence des artefacts (`chunks.csv`,
  `embeddings.npy`, `chunks_metadata.pkl`, `faiss_index.bin`,
  `corpus_cao_ifc.xlsx`), intégrité `chunks.csv` (colonnes requises, texte
  non vide), cohérence embeddings/chunks (shape, dimension 768, normes L2),
  monotonie de `DEFAULT_RISK_THRESHOLDS`, 2 cas `compute_grade` (bas → D,
  un seul flag haut → A), 4 assertions sur `llm_backend` (fail-open,
  fallback, plafond `confirm_risk`, absence de plafond quand
  `config_key=None`) — celles-ci mockent `llm_backend._dispatch`, pas
  d'appel réseau réel.
- **Intégration** (`test_integration`) : `get_flag_scores` (3 valeurs,
  0-100), `compute_grade` (clés attendues, grade valide), `analyze()`
  bout-en-bout (clés attendues, durée `< 45s` en warning seulement).
- **Cohérence métier** (`test_business`) : 4 textes synthétiques
  (community opposition, ESAP delays, biodiversity, projet propre),
  vérifie l'ordonnancement des scores (`Cas 1 > Cas 4`, `Cas 4` = minimum)
  et la présence de signaux détectés pour `Cas 1`.

Aucun test ne s'exécute contre un vrai document du corpus (PDF réel) ni
contre `corpus_cao_ifc.xlsx` comme gold standard chiffré — la référence
"gold standard" mentionnée dans `CLAUDE.md` (`tests/test_gold_standard.py`)
n'existe pas dans le code actuel.

## Ground truth — `data/raw/corpus_cao_ifc.xlsx`

76 lignes (projets), colonnes : `sa` (nom), `Numéro IFC`, `Pays`, `Secteur`,
`Date ESRS (T0)`, `Date plainte CAO (T_event)`, `Type d'événement`, `Flag`,
`Censored` (bool), `Category`, `Notes`. Complétude par colonne :

| Colonne | Non-null / 76 |
|---|---|
| Date ESRS (T0) | 42 |
| Date plainte CAO (T_event) | 57 |
| Type d'événement | 57 |
| Flag | 48 |
| Category | 73 |
| Notes | 73 |

Distribution `Flag` : `Flag 1` seul = 24, `Flag 1 + Flag 2` = 9, `Flag 2 + Flag 3` = 4,
`Flag 2` seul = 2, `"à vérifier"` = 9 (non résolu), vide/NaN = 28. **Aucun
projet `Flag 3` seul** dans le tableur actuel. Distribution `Censored` :
`False` (événement confirmé) = 58, `True` (contrôle) = 18. La colonne
`Type d'événement` contient aussi 16 lignes `"à vérifier"` et plusieurs
libellés `"Same project as..."` (doublons de projets fusionnés) — nettoyage
manuel partiel encore nécessaire avant tout ré-entraînement supervisé.
`model.py::build_training_data` (code mort) utilisait un sous-ensemble de
~46 projets avec `time_to_event` calculable — cohérent avec l'écart entre
76 lignes brutes et le chiffre "46 projets" cité dans les commentaires de
`model.py`/`checklist.md`.

## Rapports disponibles pour tests (`corpus/`)

57 fichiers au total : 15 PDF, 41 TXT (+ 1 fichier sans extension,
`IFC_32874_GulpurHydro_CTRL`, à vérifier). Mélange de rapports CAO
(assessment/compliance appraisal, ex. `CAO_Serbia_Morava_Corridor_Motorway_05_*`)
et de documents IFC (ESIA, RAP, ESAP, contrôles `_CTRL`), certains projets
ayant plusieurs documents (ex. `IFC_29197_TogoLCT` : texte + 2 PDF RAP).
Deux fichiers CSV de métadonnées complémentaires dans `data/raw/` :
`cao_cases_metadata.csv` (cas CAO scrappés — numéro projet IFC, pays,
secteur, date de plainte, statut, URL) et `ifc_controls_metadata.csv`
(projets contrôle — `t0_status` souvent `A_VERIFIER`). Deux scripts de
scraping présents (`scripts/scrape_cao.py`, `scripts/scrape_ifc.py`) mais
non exécutés dans le cadre de cet audit (lecture seule).

## Caches LLM (`models/`)

| Fichier | Taille | Dernière écriture |
|---|---|---|
| `llm_confirm_cache.json` | 117 405 octets | 2026-08-08 |
| `deep_analysis_cache.json` | 44 452 octets | 2026-08-08 |

Les deux existent et sont peuplés. Clé = hash(backend + modèle + contenu
pertinent) — invalidation automatique documentée si `FLAG_LABELS`,
`config.LLM_BACKEND` ou `config.LLM_MODEL` changent (vérifié dans le code :
`_cache_key` de `llm_confirm.py` et `deep_analysis.py` incluent tous deux
`config.LLM_BACKEND:config.LLM_MODEL`).

Autres artefacts dans `models/` (gitignorés) : `chunks_metadata.pkl`
(5,29 Mo), `embeddings.npy` (12,91 Mo), `faiss_index.bin` (12,91 Mo),
`cox_model.pkl` (9,7 Ko — code mort), `shap_background.npy` (848 o),
`embedding_comparison.json` (439 o).

## Risques identifiés (dette technique, incohérences code/doc)

1. **`tests/` n'existe pas** — `CLAUDE.md` prescrit `pytest tests/ -v` avant
   chaque commit et documente une structure `tests/test.py` +
   `tests/test_gold_standard.py` + `tests/fixtures/`. En réalité, tout tient
   dans `scripts/test.py`, un runner maison non-pytest. Toute future
   directive qui suit `CLAUDE.md` à la lettre ("lance `pytest tests/ -v`")
   échouera silencieusement (aucun test collecté) sans ce constat.
2. **`docs/BACKLOG.md` référencé mais absent** — `CLAUDE.md` liste ce
   fichier dans la structure du repo ; il n'existe pas dans `docs/`
   (seuls présents : `ARCHITECTURE.md`, `CHANGELOG.md`, `CONVENTIONS_CODE.md`,
   `DECISIONS_TECHNIQUES.md`, `GLOSSAIRE_METIER.md`).
3. **Aucune grille de 12 questions dans le code** — le scoring repose
   entièrement sur 3 flags agrégés par max(), sans dimension par question
   individuelle. Une refonte vers une grille structurée est un changement
   de modèle de données de bout en bout (chunks.csv → flag_scores →
   compute_grade → prompts Pass 1-3 → radar chart app.py), pas une
   extension additive.
4. **Ground truth incomplet et bruité** — 28/76 projets sans `Flag`
   assigné, 9 encore `"à vérifier"`, 0 projet `Flag 3` isolé (sous-représenté
   structurellement pour tout calibrage futur par flag), doublons de projets
   fusionnés non dédupliqués dans la colonne `Type d'événement`.
5. **`lifelines` dans `requirements.txt` pour du code mort uniquement**
   (Cox retiré du pipeline actif) — dépendance non nettoyée, cohérent avec
   `CLAUDE.md` ("ne pas supprimer sans vérifier avec grep" — ici la
   vérification a été faite ci-dessus : uniquement utilisé par
   `compare_embeddings.py`/`calibrate_thresholds.py`, scripts utilitaires
   annexes).
6. **Racine du repo encombrée de fichiers de travail non gitignorés** —
   de nombreux `.md` de directives/notes (`AUDIT_ESG.md`,
   `DIRECTIVE_CLAUDE_CODE_ESG_V3 (1).md`, `PROMPT_CLAUDE_CODE_ESG_V2 (2).md`,
   `SEMAINE_TYPE_ESG.md`, etc.) et des logs (`*.log`) sont trackés en `??`
   dans `git status` à la racine — pas un problème de code, mais à trier
   avant une éventuelle réorganisation du repo pour la refonte.
7. **`scripts/warm_llm_cache.py`** documenté comme "en pause" dans
   `ARCHITECTURE.md` (dégradation de débit non résolue au-delà de ~4 threads
   sur charge soutenue) — non ré-audité en détail ici (hors périmètre de la
   demande), à garder en tête si le préchauffage de cache redevient
   pertinent pour une nouvelle grille de questions (plus d'appels LLM par
   document → plus de valeur à préchauffer, mais le goulot d'étranglement
   déjà mesuré n'est pas résolu).
