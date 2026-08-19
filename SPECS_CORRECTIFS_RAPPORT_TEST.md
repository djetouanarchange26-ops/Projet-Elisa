# Specs — Correctifs suite au test d'un rapport réel (2026-08-14)

Document de spécification technique pour 5 problèmes remontés lors du lancement
d'un rapport réel dans l'app, discutés et vérifiés contre le code (voir
`checklist.md`, section "Retour terrain — rapport CAO Mundra CGPL" pour F1, déjà
documentée comme limite non résolue depuis le 2026-08-06).

À lire avec `USER_STORIES_CORRECTIFS_RAPPORT_TEST.md` (perspective Elisa) et
`PRIORISATION_CORRECTIFS_RAPPORT_TEST.md` (ordre de traitement, P0/P1/P2).

---

## Contexte projet — Stack & conventions

- **Langage** : Python 3.11
- **Frameworks / librairies clés** :
  - Streamlit — UI (4 onglets : Transaction Analysis, Portfolio Dashboard, Pattern Library, Settings)
  - sentence-transformers (`all-mpnet-base-v2`, 768 dim) — embeddings
  - FAISS (`faiss-cpu`, `IndexFlatIP`) — recherche vectorielle
  - Ollama local (`qwen3:4b-instruct`) + Together AI cloud (`Qwen/Qwen3.5-9B`), routés via une abstraction maison `scripts/llm_backend.py` (pas de framework LLM tiers type LangChain)
  - lifelines (`CoxPHFitter`) — présent dans `requirements.txt` mais **retiré du pipeline actif** depuis le 2026-08-08 (CHANTIER SIMPLIFICATION PIPELINE) ; code mort conservé dans `model.py`, encore utilisé par 2 scripts de calibration (`calibrate_thresholds.py`, `compare_embeddings.py`)
  - fpdf2 + openpyxl — exports PDF/Excel
  - plotly — graphiques (radar ESG)
- **Base de données** : aucune base relationnelle. Persistance par fichiers plats :
  - `data/processed/chunks.csv` — corpus chunké + métadonnées
  - `models/embeddings.npy`, `models/faiss_index.bin`, `models/chunks_metadata.pkl` — index vectoriel
  - `models/llm_confirm_cache.json`, `models/deep_analysis_cache.json` — caches LLM (JSON plat, réécrit intégralement à chaque écriture, pas de TTL/purge)
  - `data/raw/corpus_cao_ifc.xlsx` — annotations sources (event / time_to_event / flag_type)
- **Outils** :
  - Docker Compose — 3 services : `app` (Streamlit), `ollama`, `caddy` (reverse-proxy + basic auth)
  - **Pas de pytest** — la suite de tests (`scripts/test.py`) est un script maison avec un helper `_test()` custom (pas de fixtures/assertions pytest), organisée en 3 tiers : `--unit`, `--integ`, `--business`
  - Pas de pre-commit, pas de CI/CD (aucun `.github/workflows/`)
- **Style** (écarts constatés à l'audit du 2026-08-14, à connaître avant de coder) :
  - PEP 8 globalement respecté visuellement
  - **Type hints quasi absents** malgré la règle affichée dans `CLAUDE.md` ("type hints obligatoires sur les fonctions publiques") — ne pas supposer leur présence en lisant le code existant
  - Docstrings riches mais **pas Google-style** — convention maison CHOIX/ALT/SEUIL/FRAGILE, souvent multi-paragraphes avec contexte métier/historique, pas de section Args/Returns/Raises
  - `logging` utilisé correctement dans `llm_confirm.py`/`llm_backend.py` ; `print()` encore présent ailleurs (`deep_analysis.py`, `model.py`, `pipeline.py`, `ingest.py`, `annote.py`) malgré la règle CLAUDE.md #3 — un correctif qui touche un de ces fichiers est une bonne occasion de nettoyer le `print()` local, pas d'en ajouter un nouveau

## Structure du projet (réelle, vérifiée — pas celle, légèrement obsolète, décrite dans CLAUDE.md)

```
esg-risk-intelligence/
├── app.py                    # UI Streamlit — 1270 lignes, mélange logique d'affichage/métier
├── docker-compose.yml / Dockerfile / Caddyfile
├── requirements.txt          # AUCUNE version épinglée
├── CLAUDE.md / COPILOT_CONTEXT.md
│
├── docs/
│   └── CHANGELOG.md          # seul fichier présent dans docs/ (ARCHITECTURE.md, BACKLOG.md
│                              # référencés par CLAUDE.md n'existent pas encore)
│
├── scripts/
│   ├── config.py              # feature flags, seuils Ollama, routage backend LLM
│   ├── signals.py             # SIGNAL_KEYWORDS / SIGNAL_PATTERNS — source unique des mots-clés ESG
│   ├── search.py               # chunk_text(), _is_boilerplate(), analyze_query() (scoring FAISS)
│   ├── analyze.py              # orchestrateur — analyze(), _find_signals_in_document()
│   ├── llm_confirm.py          # confirm_risk(), summarize_passage(), generate_recommendation()
│   ├── llm_backend.py          # abstraction Ollama/Together, call_llm()
│   ├── deep_analysis.py        # Pass 1/2/3 — _PASS1/2/3_PROMPT_TEMPLATE, run_deep_analysis()
│   ├── chunk_metadata.py       # compute_specificity_score(), classify_section_type/chunk_type
│   ├── export.py               # build_pdf_report(), build_excel_report()
│   └── model.py                # compute_grade() (actif) + Cox (code mort)
│
├── scripts/test.py            # suite de tests (PAS dans tests/, malgré CLAUDE.md)
├── corpus/ , models/ , data/  # gitignored
└── checklist.md                # journal de bord détaillé — source de vérité sur l'historique
```

---

## F1 — Table des matières comptée comme signaux ESG (Detected Signals gonflés + surlignage bruité)

### Contexte
Déjà documenté dans `checklist.md` (section "Retour terrain — rapport CAO Mundra CGPL", point 3, 2026-08-06) comme **limite connue et non résolue**. Le fix précédent (libellé "N mention(s) du terme" au lieu de "N occurrence(s)") n'a corrigé que l'affichage du warning, pas le comptage sous-jacent.

### Constat technique
- `analyze._find_signals_in_document()` (`scripts/analyze.py:76-128`) cherche les patterns `SIGNAL_PATTERNS` (`scripts/signals.py`) directement dans `pdf_text` — le texte brut extrait du document, **avant tout chunking/filtrage**.
- Le filtre `_is_boilerplate()` (`scripts/search.py:72-83`), qui exclut les lignes à leaders de points type table des matières, n'est appliqué que dans `search.chunk_text()` (`scripts/search.py:86-111`) — utilisé par le scoring FAISS (`analyze_query`) et par `deep_analysis.py`, **jamais** par `_find_signals_in_document`.
- Conséquence mesurée sur le rapport testé : les compteurs "Detected Signals" (158/97/238 mentions dans l'exemple discuté) sont gonflés par des titres de section/lignes de sommaire répétant des mots-clés ("Community", "Pollution", "Compliance"...), et le surlignage du document annoté (`_build_annotated_html`, `app.py:80-105`) met en évidence ces faux positifs.

### Comportement attendu
Les mentions comptées dans "Detected Signals" et surlignées dans "Annotated Document" ne doivent provenir que de texte analytique réel, pas de table des matières / listes de figures / en-têtes répétitifs.

### Approche technique proposée
Deux options, à trancher avant implémentation (voir `PRIORISATION...md`) :

**Option A — filtrer `pdf_text` avant détection** (préserve les positions de caractères, donc le surlignage) :
Détecter les mêmes motifs que `_is_boilerplate()` par fenêtre glissante sur `pdf_text` (paragraphe par paragraphe, ou ligne par ligne) et les exclure de la recherche de patterns — sans changer le système de coordonnées utilisé par `signal_spans`/`_build_annotated_html`.

**Option B — détecter sur les chunks filtrés** (réutilise `_is_boilerplate` tel quel, mais casse le surlignage) :
Faire tourner `_find_signals_in_document` sur le texte concaténé des chunks retournés par `search.chunk_text(pdf_text)` (déjà filtré). Nécessite de re-mapper les positions des matches vers le texte original `pdf_text` pour que `signal_spans` reste correct pour `_build_annotated_html` — sans ce re-mapping, le surlignage casse silencieusement (aucun test ne le couvre aujourd'hui).

**Recommandation** : Option A — évite d'introduire un problème de mapping de positions qui n'existe pas aujourd'hui, et réutilise une logique déjà validée (`_is_boilerplate`) sans avoir besoin d'un système de correspondance chunk→position.

### Fichiers à modifier
- `scripts/analyze.py` (`_find_signals_in_document`)
- Éventuellement `scripts/search.py` si `_is_boilerplate`/une nouvelle fonction de filtrage par fenêtre doit y être factorisée pour être réutilisée par les deux call sites

### Ce qu'il ne faut PAS toucher
- `search.chunk_text()` / `_is_boilerplate()` eux-mêmes (déjà validés sur le corpus réel, cf. checklist.md) — réutiliser, pas dupliquer avec une logique légèrement différente
- Le format de `signal_spans` (liste de `(start, end, flag_num)`) consommé par `_build_annotated_html` — les positions doivent rester relatives à `pdf_text` original, pas au texte filtré

### Critères d'acceptation
1. Sur le rapport CAO Mundra CGPL (ou un document de test synthétique TOC + contenu réel), le compte de mentions par signal ne prend plus en compte les lignes de type table des matières.
2. Le surlignage du document annoté ne colore plus les lignes de sommaire.
3. `test.py --business` reste à 4-5/5 sans nouvelle régression.
4. Ajouter un cas de test (synthétique TOC + contenu réel, comme celui déjà utilisé pour valider `_is_boilerplate`, cf. checklist.md ligne 203) couvrant spécifiquement `_find_signals_in_document`.

### Risques & dépendances
- Risque principal : casser le surlignage (positions décalées) si l'option B est choisie sans re-mapping rigoureux — préférer l'option A pour l'éviter structurellement.
- Aucune dépendance sur F2-F5.

---

## F2 — Mélange français/anglais dans les sorties LLM (Pass 1 findings + synthèse Pass 3)

### Contexte
Le corpus IFC/CAO est en anglais ; les prompts `deep_analysis.py` sont rédigés en français mais ne forcent pas explicitement la langue des champs de réponse libre.

### Constat technique
- `_PASS1_PROMPT_TEMPLATE` (`scripts/deep_analysis.py:135-151`) et `_PASS3_PROMPT_TEMPLATE` (`scripts/deep_analysis.py:349-362`) n'ont **aucune instruction explicite de langue de sortie**. Le modèle 4B (`qwen3:4b-instruct` sur Ollama, ou `Qwen/Qwen3.5-9B` sur Together) a tendance à reprendre la langue du passage cité (`{chunk_text}`, en anglais) dans ses champs de description libre.
- `_PASS2_PROMPT_TEMPLATE` (`scripts/deep_analysis.py:272-284`) **n'est pas concerné** : sa sortie brute est canonicalisée par `_topics_matched_in_block` (`scripts/deep_analysis.py:329-342`) vers des libellés fixes de `_CRITICAL_TOPICS` (en français), donc une dérive de langue du modèle n'affecte jamais le résultat affiché.

### Comportement attendu
Tous les champs de texte libre affichés à l'utilisateur (findings Pass 1, synthèse Pass 3) sont systématiquement en français, quelle que soit la langue du texte source.

### Approche technique proposée
Ajouter une ligne d'instruction explicite dans `_PASS1_PROMPT_TEMPLATE` et `_PASS3_PROMPT_TEMPLATE`, par exemple :
`"Réponds TOUJOURS en français, quelle que soit la langue du passage cité ci-dessus."`
Placer l'instruction en fin de prompt (juste avant le format de réponse attendu) — position à valider empiriquement, un LLM 4B suit parfois mieux une contrainte proche de la sortie attendue qu'une contrainte en tête de prompt.

### Fichiers à modifier
- `scripts/deep_analysis.py` (`_PASS1_PROMPT_TEMPLATE`, `_PASS3_PROMPT_TEMPLATE` uniquement — pas `_PASS2_PROMPT_TEMPLATE`, non concerné)

### Ce qu'il ne faut PAS toucher
- Le format ligne-par-ligne des réponses (`ENGAGEMENT:`/`INCIDENT:`/`EVASIF:`) et les regex de parsing (`_PASS1_LINE_RE`) — l'instruction de langue ne doit pas perturber le format attendu, seule la langue du contenu des champs change
- `config.OLLAMA_CONFIGS["deep_extract"]`/`["deep_synthesize"]` (plafonds `num_predict`) — un texte français est plus long en tokens qu'un texte anglais équivalent (déjà noté dans le commentaire `config.py` sur `deep_synthesize`), donc si une troncature apparaît après ce changement, c'est un signal pour révisiter le plafond, pas une raison de le changer préventivement ici

### Critères d'acceptation
1. Sur au moins 3 documents de test dont le texte source est en anglais, les findings Pass 1 et la synthèse Pass 3 sont intégralement en français (vérification manuelle, pas de détecteur de langue automatisé nécessaire pour ce volume de test).
2. `_cache_key`/`_call_llm` (`deep_analysis.py:82-87`) — le changement de prompt modifie le hash de cache, donc les entrées existantes de `models/deep_analysis_cache.json` pour Pass 1/3 seront naturellement invalidées (comportement voulu, pas un bug à corriger).
3. `test.py --integ`/`--business` restent verts.

### Risques & dépendances
- Aucun. Changement isolé à 2 templates de prompt.

---

## F3 — Radar ESG peu interprétable pour l'analyste

### Contexte
Le radar (`app._build_radar_chart`, `app.py:342-389`) affiche 5 axes (3 flag_scores + spécificité + couverture ESG) sans repère de comparaison — un score "76 en Community Risk" n'a pas de référence visible pour l'analyste.

### Constat technique
Les données pour donner du contexte existent déjà et sont déjà calculées dans le même appel à `analyze()` :
- `result["similar_passages"]` — voisins FAISS avec `project_name`, `score`, `text` (mêmes candidats que ceux utilisés pour calculer `flag_scores`, pas de nouvel appel FAISS nécessaire)
- `evidence_by_flag` (`app._map_result_to_display`, `app.py:221-244`) — déjà agrégé par flag, top 2 projets par flag, avec résumé LLM via `llm_confirm.summarize_passage`
- Un bloc `evidence_by_flag` est **déjà affiché** aujourd'hui, mais discrètement : dans un `<details>` dépliable ("Evidence behind this score") sous chaque barre de `Flag Scores` (`app.py:1032-1053`), et la carte "Historical Similar Cases" en bas de page (`app.py:1119-1135`) montre une vue similaire mais non filtrée par flag.

### Comportement attendu
À trancher côté produit (voir `PRIORISATION...md`, décision requise avant specs détaillées d'implémentation) — deux pistes discutées :
1. Ne pas remplacer le radar, mais rendre visible par défaut (pas dans un `<details>` replié) le contenu déjà calculé de `evidence_by_flag`, en le repositionnant à côté du radar plutôt que sous chaque barre de score.
2. Remplacer le radar par un bloc "Projets les plus similaires" consolidé, qui fusionnerait `evidence_by_flag` et "Historical Similar Cases" (aujourd'hui deux blocs séparés qui montrent une information proche) en un seul endroit de la page.

### Approche technique proposée
**Ne pas commencer l'implémentation avant validation du point produit ci-dessus** — c'est un changement de disposition UI, pas un pur bug fix, et il touche potentiellement 2 blocs existants (`Flag Scores`/evidence, `Historical Similar Cases`) en plus du radar. Une fois la piste choisie :
- Piste 1 (la plus sûre techniquement) : déplacer l'affichage de `evidence_by_flag` hors du `<details>`, à côté du radar (`col_radar`, `app.py:968-975`) — pas de nouveau calcul, juste un changement de mise en page.
- Piste 2 (plus large) : fusionner `evidence_by_flag` et `similar_cases` en une seule structure de données côté `_map_result_to_display`, avec une seule carte d'affichage — implique de revoir la déduplication par projet (`by_project`, `app.py:196-200`) pour éviter d'afficher deux fois le même projet s'il apparaît à la fois en evidence d'un flag et en cas similaire global.

### Fichiers à modifier
- `app.py` (`_map_result_to_display`, la carte "ESG Radar", potentiellement "Historical Similar Cases")

### Ce qu'il ne faut PAS toucher
- `search.analyze_query()` / `similar_passages` — aucune donnée supplémentaire à calculer, le fix est uniquement une réorganisation d'affichage de données déjà produites
- `llm_confirm.summarize_passage()` — déjà branché correctement, ne pas dupliquer sa logique

### Critères d'acceptation
Dépend de la piste retenue — à définir une fois la décision produit prise (cf. `PRIORISATION...md`).

### Risques & dépendances
- Dépend d'une décision produit préalable (voir la question ouverte en fin de `PRIORISATION...md`).
- Risque de régression visuelle si fait rapidement avant une démo (le radar reste un visuel "propre" même si peu interprétable — un remplacement raté serait pire qu'un statu quo imparfait).

---

## F4 — Document Specificity peu actionnable pour Elisa

### Contexte
`_compute_document_specificity()` (`app.py:308-316`, via `chunk_metadata.compute_specificity_score`, `scripts/chunk_metadata.py:264-282`) mesure la densité de marqueurs concrets (chiffres, dates, entités nommées) vs formulations vagues/hedging dans le document analysé — un signal de greenwashing potentiel, pas un résultat d'analyse de risque ESG au sens des 3 flags.

### Constat technique
Le calcul est correct et déjà validé (score confirmé cohérent lors de l'audit du 2026-08-14). Le problème n'est pas un bug de calcul mais un problème d'interprétabilité : un pourcentage seul ("91%") sans référence contextuelle claire pour un analyste crédit qui n'est pas familier avec la mécanique NLP sous-jacente.

### Comportement attendu
Éléments déjà partiellement en place à conserver : comparaison à la moyenne du corpus (`_corpus_avg_specificity`, `app.py:319-330`) et le message d'alerte sous 40% ("Rapport majoritairement composé de formulations vagues/évasives"). Le point à améliorer est la lisibilité pour un non-technicien — reformuler le label/la description à l'écran plutôt que changer le calcul.

### Approche technique proposée
Pas de changement de calcul recommandé — c'est un axe produit (reformulation du libellé/de l'aide contextuelle affichée), pas un fix technique. Voir `USER_STORIES...md` pour le point de vue attendu côté Elisa, et trancher le libellé exact avec elle avant implémentation (cohérent avec la règle CLAUDE.md : ne pas décider seul un changement de formulation destiné à l'utilisatrice finale).

### Fichiers à modifier
- `app.py` (uniquement le texte affiché autour de la carte "Document Specificity", `app.py:942-966`) — pas de changement de logique de calcul

### Ce qu'il ne faut PAS toucher
- `chunk_metadata.compute_specificity_score()` — calcul validé, ne pas re-calibrer les poids (`_CONCRETE_WEIGHT`, `_HEDGING_WEIGHT`) sans nouvelle mesure chiffrée (règle CLAUDE.md : "ne jamais promettre un gain sans mesure avant/après")

### Critères d'acceptation
À définir une fois le libellé validé avec Elisa (hors périmètre technique pur).

### Risques & dépendances
Aucun risque technique — dépendance produit uniquement (validation du wording).

---

## F5 — Incident + Évasif affichés comme deux findings distincts sur le même chunk (clarification, pas un bug)

### Contexte
Observé sur le rapport testé : un même chunk apparaît deux fois dans la table "Findings", une fois classé "Incident", une fois "Évasif".

### Constat technique
**Ce n'est pas un bug de parsing.** Le prompt Pass 1 (`_PASS1_PROMPT_TEMPLATE`, `scripts/deep_analysis.py:135-151`) pose 3 questions indépendantes (engagement chiffré / incident / formulation évasive) sur le même passage. `_parse_pass1_response` (`scripts/deep_analysis.py:160-199`) parse ces 3 champs indépendamment, et `_build_findings_table` (`app.py:275-305`) génère une ligne par type de finding présent — un chunk peut légitimement être à la fois un incident réel ET formulé de façon évasive (ex. "un incident a eu lieu, des mesures seront envisagées si approprié"). C'est le comportement voulu du design actuel, pas une régression.

### Comportement attendu (à valider, c'est une question produit, pas un bug à corriger tel quel)
Ne PAS forcer une classification unique par chunk (ça supprimerait des findings réels et distincts). Si la présentation à l'écran de deux lignes quasi-identiques (même `source_label`, même chunk source) est jugée confuse par Elisa, la piste à explorer est un **regroupement visuel** : une seule carte par chunk source, avec plusieurs badges de type (Incident + Évasif) plutôt que deux lignes de tableau séparées.

### Approche technique proposée
Dans `_build_findings_table` (`app.py:275-305`), regrouper les findings par `chunk_index` avant de construire les lignes du tableau : au lieu d'un `rows.append(...)` par type détecté, construire un seul dict par `chunk_index` avec une liste de types, puis adapter le rendu du tableau (`app.py:918-936`) pour afficher plusieurs badges de sévérité sur une même ligne.

### Fichiers à modifier
- `app.py` (`_build_findings_table` et son rendu dans la section "Findings Table")

### Ce qu'il ne faut PAS toucher
- `deep_analysis._parse_pass1_response` / le prompt Pass 1 — la logique de détection à 3 questions indépendantes reste correcte et ne doit pas être modifiée pour "forcer" une catégorie unique

### Critères d'acceptation
À définir avec Elisa — dépend de si le regroupement visuel est jugé nécessaire après clarification que ce n'est pas un bug (voir `USER_STORIES...md`).

### Risques & dépendances
Faible — changement d'affichage isolé à `app.py`, aucun impact sur le scoring ou les exports PDF/Excel (à vérifier si `export.py` doit aussi être adapté si le regroupement est retenu).
