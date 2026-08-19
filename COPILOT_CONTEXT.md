# COPILOT_CONTEXT.md
# Contexte pour GitHub Copilot. Ouvre ce fichier dans VS Code
# avant de poser une question — il sera dans le workspace.
# Pour le contexte complet : lire CLAUDE.md.

## Projet

ESG Risk Intelligence — outil NLP d'analyse de risque ESG pour CA-CIB.
Python 3.11 / Streamlit / FAISS / Together AI (LLM) / sentence-transformers.

## Phase actuelle

Refonte du moteur de score vers une Grille d'Évaluation ESG à 12 questions.
L'ancien pipeline (3 flags community/pollution/compliance, scoring par max(),
cross-encoder, Cox) est **abandonné**. Ne pas s'y référer.

Présentation MVP : 25/08/2026.

## Pipeline MVP

```
PDF → chunks (175 mots, overlap 50) → signals.py (pré-filtre)
  → 12 questions grille (R=OUI/NON + verbatim)
  → si R=OUI : atténuation (A) avec preuve formelle
  → scoring déterministe (Cat A: −25/+5, Cat B: −15/+3, cap +20, plancher 0)
  → deep analysis 3 passes → affichage Streamlit
```

## Conventions

- `print()` interdit → `logging`
- Docstrings : tags `CHOIX:` / `ALT:` / `SEUIL:` / `FRAGILE:` (pas Google-style)
- Imports plats : `import search`, pas `from scripts.search import ...`
- `scripts/` n'est pas un package (pas de `__init__.py`)
- Code mort : bandeau `# CODE MORT — ...`, jamais supprimé silencieusement
- Type hints : quasi absents dans l'existant (dette connue)
- LLM toujours fail-open (try/except, jamais de raise)
- Scoring final = code déterministe, pas de LLM

## Tests

- Runner : `python scripts/test.py --unit --integ --business`
- `tests/` n'existe PAS — ne pas lancer `pytest tests/`
- Migration pytest prévue plus tard

## Structure utile

```
app.py                      # UI Streamlit (~1270 lignes)
scripts/
  config.py                 # feature flags, routage LLM
  signals.py                # mots-clés ESG (pré-filtre, source unique)
  search.py                 # chunking, FAISS
  analyze.py                # orchestrateur
  llm_confirm.py            # filtre polarité LLM
  llm_backend.py            # abstraction Together/Ollama
  deep_analysis.py          # 3 passes LLM
  chunk_metadata.py         # spécificité, section_type
  model.py                  # compute_grade (à refondre) + Cox (CODE MORT)
  export.py                 # PDF/Excel
  reranker.py               # CODE MORT — ne pas importer
  test.py                   # tests maison
```

## Ne pas faire

- Importer `reranker.py`, Cox, cross-encoder
- Réintroduire l'ancien scoring 3 flags
- Modifier les 12 questions de la grille sans validation métier
- Considérer les données du repo comme ground truth validé
- Utiliser `print()` au lieu de `logging`
- Rendre un appel LLM bloquant (toujours fail-open)
- Ajouter une dépendance sans demande explicite

## Signaux d'alerte dans le code existant

- `flag1_community`, `flag2_pollution`, `flag3_compliance` → ancien scoring, en cours de remplacement
- `_group_severity` → caduc
- `predict_risk()`, `train_cox()` → CODE MORT
- `reranker.py` → CODE MORT
- `BACKLOG.md`, `tests/`, `test_gold_standard.py` → référencés dans l'ancien CLAUDE.md mais n'existent pas