"""
GRILLE ESG V4 — métadonnées projet (sponsor/pays/secteur/client/type de
projet), audit UI "ESG Risk Intelligence Workspace" (2026-08-20)
=====================================================================
Répond au constat de l'audit UI : l'analyste ne peut pas comprendre le
contexte d'un dossier ("quel est ce projet ?") sans lire la grille en
détail — aucune de ces 5 informations n'existait avant nulle part dans
result_v4 (vérifié : `deep_analysis.guess_project_type()` existe mais
reste interne au pipeline LEGACY, jamais branché sur V4, et ne devine
qu'un type générique par mots-clés, pas les 5 champs demandés).

CHOIX: un appel LLM dédié, séparé des 12 appels question-par-question —
même architecture que grid_doctype.py (détection R11) : une tâche de
lecture globale du document, pas une question de la grille. Un seul appel
par analyse, mêmes indices grid_doctype (excerpt du début du document).

CHOIX (vs champs manuels façon BLOC D) : ces 5 champs sont des FAITS
extraits du document (nom du sponsor, pays...), pas un jugement/une
classification interne à la banque (contrairement à BLOC D : EP
classification, statut de sensibilité — ceux-là restent manuels par
conception, cf. app.py). Une extraction LLM fail-open réduit la friction
de saisie sans reproduire le risque d'invention : consigne stricte de ne
JAMAIS deviner, null si absent du texte.

Fail-open (ADR-002) : si le LLM est injoignable ou répond dans un format
inexploitable, retourne tous les champs à None avec source="indisponible"
— PAS de repli heuristique ici (contrairement à grid_doctype.py) : il
n'existe pas d'équivalent lexical raisonnable pour deviner un nom de
sponsor. L'UI affiche alors "—", jamais une valeur inventée.
"""

import json
import logging
import re

import llm_backend

logger = logging.getLogger(__name__)

_EXCERPT_CHARS = 4000

_FIELDS = ("sponsor", "country", "sector", "client", "project_type")

_PROMPT_TEMPLATE = """Tu es un analyste ESG. Extrait les métadonnées suivantes du document ci-dessous, UNIQUEMENT si elles sont explicitement mentionnées.

- sponsor : le promoteur/développeur du projet (société qui porte le projet), pas la banque ni le prêteur.
- country : le pays où se situe le projet.
- sector : le secteur d'activité (ex. énergie renouvelable, mines, agroalimentaire, infrastructures).
- client : le client de la banque s'il est explicitement nommé et DIFFÉRENT du sponsor (ex. une SPV distincte) — sinon null, ne duplique jamais le sponsor ici.
- project_type : le type de projet précis (ex. parc éolien, mine de charbon, usine de transformation), plus spécifique que le secteur.

N'INVENTE JAMAIS une valeur absente du texte — réponds null pour tout champ non explicitement mentionné. Ne déduis rien d'un nom de société ou d'un acronyme ambigu.

EXTRAIT DU DOCUMENT (début) :
{excerpt}

Réponds UNIQUEMENT en JSON valide, sans backticks markdown, sans texte avant ou après :
{{"sponsor": "valeur ou null", "country": "valeur ou null", "sector": "valeur ou null", "client": "valeur ou null", "project_type": "valeur ou null"}}
"""

# FRAGILE: le LLM peut wrapper le JSON dans ```json...``` ou ajouter du
# texte avant/après malgré la consigne — tolérant sur le format, même
# idiome que grid_prompts._parse_llm_json (dupliqué ici plutôt
# qu'importé : fonction privée d'un autre module, mieux vaut ces
# quelques lignes en double qu'une dépendance entre modules non liés).
_BACKTICK_FENCE_RE = re.compile(r"```(?:json)?\s*|```\s*", re.IGNORECASE)


def _parse_response(raw_text):
    """Parse la réponse JSON du LLM. Retourne un dict {champ: str|None}
    pour les 5 champs, ou None si aucun JSON exploitable n'a pu être
    extrait (fail-open géré par l'appelant)."""
    if not raw_text:
        return None

    cleaned = _BACKTICK_FENCE_RE.sub("", raw_text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    cleaned = cleaned[start:end + 1]

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("grid_metadata: JSON invalide après nettoyage — parsing échoué.")
        return None

    if not isinstance(parsed, dict):
        return None

    result = {}
    for field in _FIELDS:
        value = parsed.get(field)
        if isinstance(value, str):
            value = value.strip() or None
        else:
            value = None
        result[field] = value
    return result


def detect_project_metadata(text):
    """Extrait sponsor/pays/secteur/client/type de projet depuis le texte
    intégral d'un document (même excerpt que grid_doctype.py — début du
    document, où ces informations apparaissent typiquement).

    Retourne un dict {"sponsor": str|None, "country": str|None,
    "sector": str|None, "client": str|None, "project_type": str|None,
    "source": "llm"|"indisponible"}.

    CHOIX: ne lève jamais d'exception (fail-open, ADR-002) — un texte
    vide ou un LLM injoignable retombent sur des champs à None avec
    source="indisponible", jamais sur un crash ni une valeur inventée.
    """
    text = text or ""
    excerpt = text[:_EXCERPT_CHARS] or "(document vide)"
    prompt = _PROMPT_TEMPLATE.format(excerpt=excerpt)

    raw = llm_backend.call_llm(
        prompt, config_key="detect_project_metadata", temperature=0.0, response_format="json"
    )
    parsed = _parse_response(raw) if raw else None

    if parsed is None:
        logger.warning(
            "grid_metadata: LLM injoignable ou réponse inexploitable — "
            "métadonnées projet indisponibles (pas de repli heuristique possible)."
        )
        return {field: None for field in _FIELDS} | {"source": "indisponible"}

    return parsed | {"source": "llm"}
