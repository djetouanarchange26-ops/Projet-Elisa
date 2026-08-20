"""
Feature flags — PROMPT_CLAUDE_CODE_ESG_V2, "CONTRAINTES TECHNIQUES INCHANGÉES" :
chaque amélioration doit être activable/désactivable sans toucher au code.

Lit des variables d'environnement, avec des valeurs par défaut qui activent
tout (comportement "MVP complet"). `export ESG_DEEP_ANALYSIS_ENABLED=0` (ou
`false`/`no`/vide) désactive une fonctionnalité sans rien casser côté
appelant — chaque module consommateur doit fail gracefully vers son
comportement pré-chantier quand son flag est désactivé (cf. deep_analysis.py).

CORRECTIF (reconnexion Together AI, 2026-08-18) : `.env` (racine du repo)
n'était jamais chargé en dehors de Docker Compose (qui l'interpole
nativement) — un `python scripts/test.py` ou `streamlit run app.py` lancé
directement ne voyait donc JAMAIS LLM_BACKEND=together ni TOGETHER_API_KEY
définis dans `.env`, et retombait silencieusement sur les défauts codés en
dur ("ollama"). `load_dotenv()` ci-dessous corrige ça — chemin explicite
(pas de recherche par CWD) pour un comportement identique quel que soit le
répertoire d'où le process est lancé. `override=False` (défaut) : une
variable déjà présente dans l'environnement réel (Docker, shell) garde
toujours priorité sur `.env`.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")


def _flag(name, default=True):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "")


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
    # R11 (grid_doctype.py) : un seul appel par document, réponse courte
    # (TYPE/CONFIANCE/EVIDENCE) — pas besoin du contexte large de deep_synthesize.
    "detect_doctype":  {"num_predict": 200, "num_ctx": 2048},
}

# CHANTIER LLM BACKEND (2026-08-07, checklist.md) — abstraction Ollama local
# / cloud, cf. llm_backend.py. Exception explicite au sprint "pas de nouveau
# modèle/pas de fix perf avant le 25 août" : dégradation Ollama sous charge
# (~17 -> <7 tok/s après ~50 appels) bloquait une démo live.
#
# CHOIX (reconnexion Together AI, 2026-08-18) : défaut "together", pas
# "ollama" — Together devient le fournisseur LLM PRINCIPAL de toute
# l'infrastructure (ancien pipeline ET Grille V4), conformément à
# CLAUDE.md ("LLM : Together AI cloud = défaut MVP") qui documentait déjà
# cette intention sans qu'elle soit reflétée ici. "ollama" reste
# entièrement supporté (LLM_BACKEND=ollama explicite, ou LLM_FALLBACK) —
# rien n'est supprimé, seul le défaut change.
LLM_BACKEND = os.environ.get("LLM_BACKEND", "together").strip().lower()

# Modèle par défaut selon le backend actif si LLM_MODEL n'est pas fourni.
# Qwen/Qwen3.5-9B choisi (pas Qwen3.7 Max) : Max a le "deep thinking" activé
# par défaut sur Together, qui casserait le parsing (confirm_risk attend un
# mot, deep_analysis attend un format ligne-par-ligne, pas un raisonnement
# visible) — même famille de bug que qwen3:4b vs qwen3:4b-instruct ci-dessous.
LLM_MODEL_BY_BACKEND = {
    "ollama":   "qwen3:4b-instruct",
    "together": "Qwen/Qwen3.5-9B",
}
LLM_MODEL = os.environ.get("LLM_MODEL") or LLM_MODEL_BY_BACKEND.get(LLM_BACKEND, "qwen3:4b-instruct")

TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY", "")

# Backend de repli si LLM_BACKEND échoue (down, rate-limit, clé invalide) —
# fail-open à un niveau au-dessus du fail-open par appel (cf. llm_backend.py).
# "" désactive le fallback.
LLM_FALLBACK = os.environ.get("LLM_FALLBACK", "ollama").strip().lower()

# Requêtes/seconde max vers un backend cloud — ignoré pour "ollama" (pas de
# rate limit externe en local).
LLM_RATE_LIMIT = float(os.environ.get("LLM_RATE_LIMIT", "10"))

# --- Grille ESG V4 (pipeline canonique) ---
# CHOIX: GRID_V4_ENABLED reste un simple disjoncteur (charge/ne charge pas
# les modules grid_*) — la question "quel pipeline tourne pour une analyse"
# est tranchée par ACTIVE_PIPELINE ci-dessous, pas par ce flag seul.
# RENOMMÉ (CC-V4-08) : GRID_V3_ENABLED -> GRID_V4_ENABLED — même flag,
# nom aligné sur la version courante de la grille.
GRID_V4_ENABLED = True

# Passe de synthèse finale (un seul appel LLM, texte libre, après le
# scoring — cf. grid_analyze._generate_synthesis). Disjoncteur séparé de
# GRID_V4_ENABLED : désactiver la synthèse ne doit pas désactiver la
# grille elle-même (fail-open indépendant, comme DEEP_ANALYSIS_ENABLED
# pour l'ancien pipeline).
GRID_SYNTHESIS_ENABLED = _flag("ESG_GRID_SYNTHESIS_ENABLED", True)

# --- Pipeline actif ---
# CHOIX: un enum à 2 valeurs ("v4" | "legacy"), pas deux flags booléens
# indépendants — deux flags pourraient être activés tous les deux par
# erreur (ou par défaut divergent d'un déploiement à l'autre) et
# réintroduire une double exécution LLM sur la même analyse (l'ancien
# pipeline `analyze.py` + la Grille V4 pour le même document uploadé,
# constaté dans app.py avant ce chantier). Un enum rend ça structurellement
# impossible : scripts/pipeline_dispatch.py::run_active_pipeline() appelle
# EXACTEMENT un des deux pipelines, jamais les deux, et lève une erreur
# plutôt que de retomber silencieusement sur l'autre si mal configuré.
# "v4"     : pipeline canonique — Grille ESG V4 (12 questions), scoring
#            déterministe (grid_scoring.py).
# "legacy" : ancien pipeline (3 flags FAISS, max(), compute_grade) —
#            CONSERVÉ (analyze.py, model.py::compute_grade toujours
#            présents et testés isolément par scripts/test.py) mais plus
#            jamais le défaut : réservé à une comparaison technique
#            ponctuelle via ESG_ACTIVE_PIPELINE=legacy, hors chemin
#            applicatif normal.
# CHOIX (rollout) : bascule du défaut vers "v4" — la Grille V4 a été
# vérifiée (calibration Indorama/Aysha/CBG/Mundra, dispatch unique testé,
# cf. scripts/test.py --unit) et devient la pipeline canonique en
# production. Commit isolé et minimal (une seule valeur change) pour
# rester facilement réversible (git revert) si un problème est repéré
# après déploiement — sans jamais revenir à une double exécution : même
# après un revert, pipeline_dispatch.py garantit qu'un seul pipeline
# tourne par analyse, jamais les deux.
ACTIVE_PIPELINE = os.environ.get("ESG_ACTIVE_PIPELINE", "v4").strip().lower()
