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

# DIRECTIVE_CLAUDE_CODE_ESG_V3, Tier 0 — plafonne num_predict/num_ctx par
# usage plutôt que de laisser Ollama sur ses défauts (num_predict=-1 = pas
# de limite, num_ctx=2048 par défaut). confirm_risk ne répond qu'un mot
# (RISK/CLEAN) : le laisser sur les défauts gaspille du temps de génération
# pour rien. Valeurs initiales reprises de la directive, deep_synthesize
# corrigée depuis (voir plus bas) — la température de chaque appel reste
# définie côté appelant (llm_confirm.py/deep_analysis.py), pas ici, pour ne
# pas modifier des réglages déjà choisis/documentés (ex: confirm_risk=0 pour
# la déterminisme, cf. llm_confirm.py).
# CORRECTIF (2026-08-06, retour terrain sur un vrai rapport CAO Mundra CGPL) :
# deep_synthesize à 200 (valeur brute de la directive) tronquait la synthèse
# Pass 3 en plein milieu de phrase — mesuré sur un cas réel ("Ces lacunes
# rendent impossible une évaluation f[...]"). Le prompt demande 3-5 phrases
# EN FRANÇAIS (plus de tokens/mot qu'en anglais pour un texte équivalent) —
# remonté à 450 pour laisser de la marge, toujours très en dessous de
# l'absence de plafond (comportement pré-Tier 0).
#
# CORRECTIF (2026-08-06, audit perf sur un document réel de 171 chunks) :
# deep_extract à 100 tronquait parfois la 3e ligne (EVASIF) de la réponse
# Pass 1 avant la fin — le format demande 3 lignes ENGAGEMENT/INCIDENT/EVASIF
# avec description/cible/horizon, en français (cf. deep_synthesize
# ci-dessus). Une ligne tronquée laissait un champ non reconnu par le
# parseur — combiné au bug de _parse_pass1_response (corrigé le même jour,
# voir deep_analysis.py), ça faisait planter Pass 3 en aval. Remonté à 180.
OLLAMA_CONFIGS = {
    "confirm_risk":    {"num_predict": 5,   "num_ctx": 512},
    "summarize":       {"num_predict": 80,  "num_ctx": 768},
    "recommend":       {"num_predict": 150, "num_ctx": 1024},
    "deep_extract":    {"num_predict": 180, "num_ctx": 1024},
    "deep_synthesize": {"num_predict": 450, "num_ctx": 2048},
}
