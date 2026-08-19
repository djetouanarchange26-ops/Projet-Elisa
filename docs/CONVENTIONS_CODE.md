# Conventions de code — ESG Risk Intelligence

Décrit les conventions **réellement appliquées** dans le code existant, pas un
idéal aspirationnel — pour que le code généré s'intègre sans détonner plutôt
que d'introduire un deuxième style. Les écarts connus entre la règle affichée
dans `CLAUDE.md` et la réalité du code sont signalés explicitement ci-dessous.

## Nommage

- Fonctions/variables : `snake_case`. Fonctions privées à un module : préfixe `_` (`_load_cache`, `_gather_candidates`, `_cache_key`).
- Constantes de module : `UPPER_CASE` (`MAX_CONFIRM_RISK_CALLS`, `CHUNK_SIZE`, `DEFAULT_RISK_THRESHOLDS`).
- Regex compilées : suffixe `_RE` (`_DOT_LEADER_RE`, `_HEDGING_RE`).
- Noms de flags métier fixes dans tout le code : `flag1_community`, `flag2_pollution`, `flag3_compliance` (jamais `flag_1`/`community_flag`/variantes) — cohérence attendue partout où un flag est référencé par son nom complet plutôt que son numéro.

## Structure des fichiers

- `scripts/` n'est **pas** un package Python (pas de `__init__.py`) — les imports sont plats (`import search`, `from model import compute_grade`), et fonctionnent parce que `app.py` fait `sys.path.insert(0, .../scripts)` avant d'importer. Un nouveau script dans `scripts/` doit suivre le même pattern d'import, pas `from scripts.search import ...`.
- Un module = un domaine métier clair (`signals.py` = mots-clés, `search.py` = retrieval, `llm_confirm.py`/`llm_backend.py` = appels LLM, `export.py` = génération de fichiers) — éviter de mélanger logique de scoring et logique d'affichage dans un même fichier (l'exception connue est `app.py`, qui mélange les deux par nécessité Streamlit — ne pas reproduire ce mélange ailleurs sans raison).
- Code mort : conservé sur disque avec un bandeau explicite `# CODE MORT — ...` expliquant pourquoi il n'est plus appelé et depuis quand, jamais supprimé silencieusement (cf. `scripts/model.py`, `scripts/reranker.py`).

## Docstrings — convention maison, pas Google-style

Les docstrings suivent une convention à 4 tags, à utiliser tels quels (pas de section `Args:`/`Returns:`/`Raises:`) :
- `CHOIX:` — une décision d'architecture et pourquoi cette option plutôt qu'une autre évidente
- `ALT:` — une alternative envisagée mais pas retenue, pour éviter qu'elle soit re-proposée sans raison
- `SEUIL:` — une valeur numérique ajustable, avec la justification du choix actuel
- `FRAGILE:` — un point sensible, une limite assumée, ou un piège à ne pas réintroduire

Toute fonction dont le comportement n'est pas évident à la lecture (seuil, heuristique, contournement d'un bug) doit avoir au moins un de ces tags. Une docstring d'une ligne suffit pour une fonction dont le nom et la signature suffisent à comprendre l'usage.

## Type hints

**Absents dans la quasi-totalité du code existant**, malgré la règle affichée dans `CLAUDE.md` ("type hints sur les fonctions publiques"). Ne pas supposer leur présence en lisant le code, et ne pas les ajouter isolément sur une seule fonction touchée en passant — c'est un chantier à part entière, pas un sous-produit d'un autre correctif (cf. `docs/DECISIONS_TECHNIQUES.md` si ce chantier est un jour lancé).

## Gestion d'erreurs

Deux régimes distincts, à ne pas confondre :

**1. Appels LLM — fail-open systématique.** Le pattern est toujours le même (voir `llm_backend.call_llm`, `llm_confirm.confirm_risk`, chaque passe de `deep_analysis.py`) :
```python
try:
    response = _call_llm(prompt, ...)
except Exception as e:
    logger.warning(f"LLM indisponible pour {usage}: {e}")
    return <valeur de repli sûre>   # jamais de raise
```
Le repli est spécifique à l'appelant (`confirm_risk` → `True`, `summarize_passage` → extrait tronqué, `run_pass2` → `None` distinct de `[]`) — jamais un `except` générique qui avale l'erreur sans repli explicite documenté.

**2. Reste du code — laisser remonter, sauf point d'entrée explicite.** Les fonctions de scoring/chunking/parsing ne catchent pas leurs propres erreurs — c'est `run_deep_analysis()` (orchestrateur des 3 passes) et le `try/except` autour de `analyze()` dans `app.py` qui bornent le rayon d'explosion, pas chaque fonction individuellement. Un `except Exception` sans repli explicite ni log est à éviter — cf. l'écueil identifié pour `_load_cache()` (aucun `try/except` autour du `json.loads`, alors que ça devrait suivre le régime fail-open comme le reste de la couche LLM).

## Logging

- `logger = logging.getLogger(__name__)` en tête de module, `logger.warning()` pour les fallbacks fail-open, `logger.debug()` pour le détail technique.
- `print()` encore présent dans plusieurs modules (`deep_analysis.py`, `model.py`, `pipeline.py`, `ingest.py`, `annote.py`) malgré la règle CLAUDE.md — dette connue, ne pas en rajouter dans du nouveau code, et profiter d'un correctif dans un de ces fichiers pour nettoyer les `print()` locaux.

## Cache disque (pattern répété dans `llm_confirm.py` et `deep_analysis.py`)

- Clé = `hashlib.sha256(f"{backend}:{modèle}:{contexte pertinent}")` — invalide automatiquement si le backend/modèle change ou si le contenu qui influence la réponse change (ex. définition d'un flag).
- Chargement paresseux (`_load_cache`, variable globale `_cache`), protégé par un `threading.Lock()` module-level.
- Écriture : fichier JSON réécrit en entier à chaque `save=True` (comportement par défaut). `save=False` + `flush_cache()` périodique disponible pour un usage en masse (cf. `warm_llm_cache.py`).

## Tests

- `scripts/test.py`, pas un dossier `tests/` — 3 tiers : `--unit` (fichiers/composants isolés, pas de réseau), `--integ` (pipeline bout en bout, nécessite `models/`/`data/` présents), `--business` (cohérence métier sur des cas synthétiques).
- Pas de `pytest` — helper maison `_test(name, condition, msg_fail, warning_only=False)`, compteurs globaux, résumé en fin de run. Un nouveau test suit ce pattern, pas des `assert` pytest.
- Le seul test qui mocke proprement une dépendance externe est celui de `llm_backend` (monkey-patch de `_dispatch`) — modèle à suivre pour tester une logique qui dépend normalement du réseau/LLM.
