# CLAUDE.md

Contexte opérationnel pour Claude Code / Claude Chat / Copilot.
Dernière mise à jour : 2026-08-15. Audit complet du repo : `AUDIT_REPOSITORY.md`.

---

## Projet

ESG Risk Intelligence — outil d'analyse de risque ESG pour CA-CIB (banque).
Analyse des rapports de monitoring IFC/CAO (45-70 pages) pour détecter des
signaux de risque E&S&G et produire un score traçable sur 100.

Utilisatrice finale : Elisa (analyste crédit).
Développeur : Archange. Associée métier : Stacy.

## Deadline et phase

**Présentation le 25/08/2026 — 3 jours.** Ce qui sera présenté est le MVP
de la refonte grille, pas l'ancien pipeline.

**L'ancien pipeline (3 flags community/pollution/compliance, scoring par
`max()`, grade A/B/C/D) est obsolète.** Il ne correspond plus aux attentes
des analystes. L'écart constaté sur CBG Expansion (outil : 78/100 zone verte
vs estimation manuelle Stacy : 30-40/100 zone rouge, projet classé "A –
Significant" par l'IFC) a déclenché la refonte complète.

Priorité absolue : livrer le MVP grille pour le 25/08. Tout le reste est
secondaire.

## Rôles

- **Claude Chat** : analyse des retours d'Elisa, proposition de valeur/priorités
- **Claude Code** : implémentation sur DIRECTIVE uniquement
- **Copilot** : tâches mineures (docstrings, renommage)
- **Archange** : validation, tests manuels, décisions finales

## Stack

- Python 3.11 / Streamlit (UI) / FAISS (`faiss-cpu`, `IndexFlatIP`)
- sentence-transformers (`all-mpnet-base-v2`, 768 dim)
- LLM : Together AI cloud = défaut MVP, abstraction Ollama conservée via `llm_backend.py`
- fpdf2 + openpyxl (exports) / plotly (graphiques)
- Docker Compose : 3 services (`app` + `ollama` + `caddy`)
- Pas de CI/CD, pas de pre-commit

## Architecture MVP — Grille d'Évaluation ESG

C'est LE pipeline à implémenter pour le 25/08. Il remplace l'ancien.

```
Rapport (PDF)
 → chunking (search.chunk_text — 175 mots, overlap 50, filtre boilerplate)
 → signals.py comme pré-filtre (détection de passages candidats)
 → 12 questions de la Grille d'Évaluation ESG (A.1.1 → B.3.2)
 → LLM avec sortie structurée : R = OUI/NON + verbatim justificatif
 → si R = OUI : sous-question d'atténuation A (preuve formelle requise)
 → scoring déterministe (barème arithmétique strict)
 → deep analysis (synthèse, omissions)
 → validation analyste (human-in-the-loop)
```

### Barème (déterministe, pas de LLM dans le calcul du score)

- Base : 100 pts
- Catégorie A (bloqueurs — 6 questions) : pénalité −25 pts, atténuation max +5 pts (ratio 20%)
- Catégorie B (structurants — 6 questions) : pénalité −15 pts, atténuation max +3 pts
- Plafond global d'atténuation cumulée : +20 pts
- Plancher : le score ne descend jamais sous 0
- L'atténuation (A) ne s'active que si le risque (R) = OUI
- **Polarité** : 100 = aucun risque identifié, 0 = catastrophique. Échelle continue, pas binaire.

### Ancrages de calibration (GROUND_TRUTH validé)

- CGPL/Tata Mundra → 23/100 (ROUGE — Éliminatoire)
- CBG Expansion → 30-40/100 (zone rouge, Cat A IFC)

### 7 décisions actées (Note de Cadrage, 14/08/2026)

1. **Réorganisation output** — score + flags en tête, commentaire sémantique par signal lié à la question de la grille
2. **Recommandations non-décisionnelles** — l'outil produit des indications de vigilance, jamais de verdict d'approbation/refus
3. **Scoring = Grille stricte** — barème ci-dessus, calibré sur benchmarks IFC
4. **Purge ancienne grille** — suppression des catégories community/pollution/compliance comme structure de scoring
5. **Flags = thème/sous-thème de la grille** — "Facteur de Risque Majeur / Oppositions" au lieu de lettres nues. Codes A.1.1, B.2.1… restent internes
6. **Mémoire inter-dossier** — historique par projet, comparaison avec rapports précédents
7. **Catégorisation IFC = repère externe fixe** — captée une fois, affichée à part, jamais recalculée

Détail : `Note_de_Cadrage_Refonte_Outil_ESG.pdf`.
Barème complet : `Guide_Methodologique_Scoring_ESG_1.pdf`.
Maquette grille : `1_Maquette_Vierge_Grille_ESG_1.pdf`.

### Ce qui est réutilisé de l'ancien pipeline

- **Embeddings + FAISS** : le retrieval sémantique reste le mécanisme de recherche de passages candidats
- **`signals.py`** : conservé comme pré-filtre, pas comme source de scoring
- **`llm_backend.py`** : abstraction LLM réutilisée telle quelle
- **`llm_confirm.confirm_risk()`** : le filtre de polarité LLM reste pertinent (embedding capte le sujet, pas la polarité)
- **Deep analysis** : les 3 passes (extraction/omissions/synthèse) restent, les prompts devront être adaptés à la grille
- **Fail-open** : tous les appels LLM restent fail-open

### Ce qui est abandonné

- Scoring par 3 flags agrégés via `max()` → remplacé par le barème grille
- `compute_grade` via seuils → remplacé par le score /100 arithmétique
- `_group_severity` et ses seuils d'escalade → caducs
- Cross-encoder / reranker (`reranker.py`) → CODE MORT, confirmé par grep
- Cox (`model.py::predict_risk`) → CODE MORT
- Lettres nues A/B/C/D comme grade affiché → remplacé par les catégories de la grille
- Radar chart actuel (5 axes : 3 flags + spécificité + couverture) → à refaire sur la grille

## Correctifs à intégrer au MVP

Ces bugs doivent être corrigés dans le MVP, pas séparément :

| ID | Problème | Impact | Fichiers |
|----|----------|--------|----------|
| F1 | Table des matières comptée comme signaux | Chiffres faux à l'écran | `analyze.py` |
| F2 | Mélange français/anglais sorties LLM | Crédibilité en démo | `deep_analysis.py` (templates) |

F4 (wording Specificity) et F5 (Incident+Évasif même chunk) : si le temps le permet.
F3 (radar) : caduc — le radar sera refait sur la grille.

Specs détaillées : `SPECS_CORRECTIFS_RAPPORT_TEST.md`.

## Questions risque/mitigation

Les 12 questions actuelles sont une **baseline de travail**, pas figées.

```
Questions actuelles → tests rapports réels → retour Elisa → amélioration
```

- Un agent ne modifie pas les questions sans validation Elisa
- Si une modification semble nécessaire : marquer `PENDING_ELISA`
- Pas de mapping sémantique complexe au MVP
- Pas de cross-encoder ni de reranker

Structure : 6 questions Cat A (Oppositions, Conformité, Faisabilité) +
6 questions Cat B (Communautaire, Pollution, Gouvernance).
Évolution future : tronc commun + modules sectoriels.

## Ground truth — RÈGLE CRITIQUE

**Les données du repo ne sont PAS du ground truth métier validé.**

| Donnée | Statut | Usage autorisé |
|--------|--------|----------------|
| `corpus_cao_ifc.xlsx` (76 lignes) | **PENDING_GROUND_TRUTH** — 28 sans Flag, 9 "à vérifier" | Dev, tests techniques. Pas de métrique d'accuracy métier |
| `corpus/` (57 fichiers) | **TECHNICAL_TEST_DATA** | Tester le pipeline, vérifier le parsing |
| Ancrages Mundra + CBG | **GROUND_TRUTH** (validé manuellement par Stacy) | Calibration du barème |
| Caches LLM (`models/*.json`) | **ARTEFACT_TECHNIQUE** | Accélération pipeline |

Ne jamais inventer un ground truth ni présenter une comparaison comme une
mesure d'accuracy sans GT validé. Le GT métier sera fourni progressivement
par Elisa.

## Tests

### Maintenant

- `python scripts/test.py --unit --integ --business` — runner maison, 3 tiers
- `tests/` n'existe pas (malgré l'ancien CLAUDE.md)
- Pas de gold standard chiffré

### Après le 25/08

Migration vers **pytest** planifiée comme chantier séparé.

### Avant chaque commit

1. `python scripts/test.py --unit --integ --business` — tout doit passer
2. `git diff` pour review
3. Mettre à jour `docs/CHANGELOG.md`
4. Pas de chemin absolu local, pas de clé API en dur, pas de `print()`

## Conventions de code

- **PEP 8** respecté
- **Type hints** : quasi absents dans l'existant, dette connue
- **Docstrings** : convention maison `CHOIX:` / `ALT:` / `SEUIL:` / `FRAGILE:` — pas Google-style, prolonger cette convention
- **Logging** : `print()` interdit, utiliser `logging`
- **Imports** : plats (`import search`, `from model import compute_grade`) — `scripts/` n'est pas un package
- **Code mort** : bandeau `# CODE MORT — ...` obligatoire, jamais supprimé silencieusement

## Invariants à respecter

| Invariant | Réf |
|-----------|-----|
| `analyze_query()` re-ranking UNE SEULE FOIS (fix perf 246s) | ADR-001 |
| Tous les appels LLM sont fail-open (jamais de crash) | ADR-002 |
| Pass 2 deep_analysis SANS plafond `num_predict` | checklist.md |
| `OLLAMA_HOST` vient de `config.py` (env var, jamais localhost en dur) | config.py |
| Cache LLM invalide sur contenu ET config (hash backend:modèle + contenu) | llm_confirm.py |
| `signals.py` = source unique mots-clés → modifier = 4 modules impactés | — |
| Le scoring final est DÉTERMINISTE (barème arithmétique, pas de LLM) | Note de Cadrage |

## Bugs déjà corrigés — ne pas réintroduire

| Bug | Fichier | Fix |
|-----|---------|-----|
| Doublon re-ranking (246s) | search.py | analyze_query() unifié |
| `_parse_pass1_response` None→AttributeError | deep_analysis.py | Init `{"present": False}` |
| `run_pass2` texte libre compté comme omissions | deep_analysis.py | Filtrage `_CRITICAL_TOPICS` |
| `guess_project_type` "SPV"→"PV"→"solaire" | deep_analysis.py | Regex `\b` |
| `float('nan')` truthy pour flag_type | app.py | `pd.isna()` |
| `dominant_flag` KeyError | app.py | `result["flag_scores"]` |
| Pass 3 timeout 60s insuffisant | deep_analysis.py | timeout=150 |

## Ce qu'un agent ne doit PAS faire

- Réintroduire l'ancien scoring (3 flags, max(), grade A/B/C/D)
- Réintroduire cross-encoder / reranker / Cox
- Modifier les 12 questions de la grille sans validation Elisa
- Considérer les données du repo comme ground truth validé
- Rendre un appel LLM bloquant
- Supprimer du code sans `grep` préalable
- Ajouter une dépendance sans mention dans la directive
- Utiliser `print()`
- Lancer `pytest tests/ -v` — utiliser `python scripts/test.py`

## Structure du repo (vérifiée 15/08)

```
esg-risk-intelligence/
├── app.py                    # UI Streamlit (~1270 lignes)
├── docker-compose.yml / Dockerfile / Caddyfile
├── requirements.txt
├── CLAUDE.md                 # CE FICHIER
├── COPILOT_CONTEXT.md
├── checklist.md              # journal de bord détaillé
│
├── docs/
│   ├── CHANGELOG.md
│   ├── ARCHITECTURE.md
│   ├── CONVENTIONS_CODE.md
│   ├── DECISIONS_TECHNIQUES.md
│   └── GLOSSAIRE_METIER.md
│
├── scripts/
│   ├── config.py             # feature flags, seuils, routage LLM
│   ├── signals.py            # mots-clés ESG (pré-filtre)
│   ├── search.py             # chunking, FAISS, scoring
│   ├── analyze.py            # orchestrateur
│   ├── llm_confirm.py        # filtre polarité LLM
│   ├── llm_backend.py        # abstraction Ollama/Together
│   ├── deep_analysis.py      # 3 passes analyse LLM
│   ├── chunk_metadata.py     # spécificité, section_type
│   ├── export.py             # PDF/Excel
│   ├── model.py              # compute_grade (à refondre) + Cox (CODE MORT)
│   ├── reranker.py           # CODE MORT
│   ├── annote.py             # annotation corpus
│   ├── ingest.py             # PDF → chunks
│   ├── pipeline.py           # embedding + FAISS (offline)
│   └── test.py               # tests maison (PAS dans tests/)
│
├── corpus/                   # documents ESG (gitignored)
├── models/                   # index FAISS, caches LLM (gitignored)
└── data/                     # CSV, xlsx (gitignored)
```

## Nettoyage planifié (après 25/08)

- `reranker.py` + modèle cross-encoder → suppression
- Fonctions Cox dans `model.py` → suppression
- `lifelines` dans `requirements.txt` → retirer
- `.md` de travail à la racine → trier ou supprimer
- `*.log` non gitignorés → `.gitignore`
- `requirements.txt` → épingler les versions
- Migration tests vers pytest

## Pending Elisa

- Ground truth métier progressif (annotations `corpus_cao_ifc.xlsx`)
- Retour sur les 12 questions après tests rapports réels
- Wording "Document Specificity" (F4)
- Questions sectorielles (tronc commun + modules)

## Documentation de référence

| Document | Contenu |
|----------|---------|
| `Note_de_Cadrage_Refonte_Outil_ESG.pdf` | 7 décisions de la refonte |
| `Guide_Methodologique_Scoring_ESG_1.pdf` | Barème, taxonomie, justification |
| `1_Maquette_Vierge_Grille_ESG_1.pdf` | Grille 12 questions (R/A) |
| `AUDIT_REPOSITORY.md` | État des lieux repo (15/08) |
| `SPECS_CORRECTIFS_RAPPORT_TEST.md` | Specs correctifs F1-F5 |
| `checklist.md` | Journal de bord chronologique |