"""
Feature flags — PROMPT_CLAUDE_CODE_ESG_V2, "CONTRAINTES TECHNIQUES INCHANGÉES" :
chaque amélioration doit être activable/désactivable sans toucher au code.

Lit des variables d'environnement, avec des valeurs par défaut qui activent
tout (comportement "MVP complet"). `export ESG_RERANKER_ENABLED=0` (ou
`false`/`no`/vide) désactive une fonctionnalité sans rien casser côté
appelant — chaque module consommateur doit fail gracefully vers son
comportement pré-chantier quand son flag est désactivé (cf. search.py,
deep_analysis.py).
"""

import os


def _flag(name, default=True):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "")


# CHANTIER 2 — re-ranker cross-encoder post-FAISS (search.py)
RERANKER_ENABLED = _flag("ESG_RERANKER_ENABLED", True)

# CHANTIER 3 — pipeline d'analyse LLM multi-pass (deep_analysis.py / analyze.py)
DEEP_ANALYSIS_ENABLED = _flag("ESG_DEEP_ANALYSIS_ENABLED", True)

# CHANTIER 5 — filtre de polarité LLM en entraînement (train/serve) — voir
# llm_confirm.py, déjà avec son propre paramètre confirm_risk(...)/llm_confirm=
# au niveau appel ; ce flag global permet de désactiver partout d'un coup
# sans modifier chaque site d'appel individuellement.
LLM_CONFIRM_ENABLED = _flag("ESG_LLM_CONFIRM_ENABLED", True)

# URL Ollama — configurable pour Docker (CHANTIER 7 : Ollama dans un autre
# container, pas sur localhost). Fallback sur localhost en dev local.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
