"""
GRILLE ESG V4 — orchestrateur (directive CC-V4-06)
=====================================================================
Assemble la chaîne complète pour UN document déjà chunké : classification
des sections structurelles (grid_sections.py), un appel LLM par question
(grid_prompts.py + llm_backend.py), scoring déterministe
(grid_scoring.py) et assemblage du résultat final (grid_result.py).

FRAGILE (hérité, pas revu par CC-V4-06) : ce module ne fait AUCUN
retrieval sémantique par question — tous les chunks du document (moins
les exclusions ESAP/plaintes IFC, cf. grid_sections.py) sont passés tels
quels à chaque prompt. Un retrieval plus fin (top-k par question, FAISS
ou autre) est un chantier séparé si la taille de contexte devient un
problème réel sur de gros documents (45-70 pages) — non traité ici.

`chunks` (paramètre d'entrée) : list de dicts {"text": str, "page":
int|None}, déjà découpés en amont (cf. search.chunk_text() pour le
découpage brut ; l'appariement page/texte n'est pas fait par ce module).

Invariant CC-V4-06 : UN SEUL appel LLM par question, jamais deux (pas de
second appel pour la sous-question de mitigation) — tous les templates de
grid_prompts.py demandent le statut R ET le statut de mitigation dans la
même réponse structurée, y compris B.3.1 (a_condition="r_non" : la
sous-question A n'est simplement pas pertinente si le LLM répond OUI,
cf. grid_scoring._resolve_gain qui l'ignore dans ce cas).

R10 (filtre de sujet) : évalué PAR LE LLM dans le prompt (grid_prompts.py),
jamais recalculé ici en post-traitement. Ce module se contente
d'enregistrer ce que le LLM a répondu (champ SUJET) dans `qualifying`
pour que l'analyste (boucle humaine, cf. Note de Cadrage décision 2) puisse
vérifier — il ne force JAMAIS un OUI à NON automatiquement, cf. "Ce qu'il
ne faut PAS faire" de la directive.

Fail-open (ADR-002) : un LLM injoignable, une réponse inexploitable, ou
l'absence de tout passage candidat pour une question retombent tous sur la
règle de silence R5 (grid_questions.py::silence_type) — jamais de crash,
jamais de question sans réponse dans le résultat final.
"""

import logging

import config
import grid_questions
import grid_scoring
import grid_result
import grid_prompts
import grid_sections
import llm_backend

logger = logging.getLogger(__name__)


def _silence_status(question):
    """Statut de repli selon silence_type (R5, grid_questions.py, CC-08) :
    "etat" -> INCONNU (silence ne prouve pas l'absence d'un système/état),
    "evenement" -> NON (silence vaut absence du fait daté)."""
    return "INCONNU" if question.get("silence_type") == "etat" else "NON"


def _silence_fallback(question, reason):
    return {
        "status": _silence_status(question),
        "mitigation_status": None,
        "evidence_r": None,
        "evidence_a": None,
        "confidence_note": reason,
        "silence_applied": True,
        "qualifying": None,
    }


def _parse_page(page_str):
    if page_str and page_str.strip().isdigit():
        return int(page_str.strip())
    return None


def _build_evidence_r(parsed):
    passage = (parsed.get("evidence_r") or "").strip()
    if not passage:
        return None
    return {"passage": passage, "page": _parse_page(parsed.get("page"))}


def _build_evidence_a(parsed):
    mesure = (parsed.get("evidence_mesure") or "").strip() or None
    defaillance = (parsed.get("evidence_defaillance") or "").strip() or None
    if mesure is None and defaillance is None:
        return None
    return {"verbatim_mesure": mesure, "verbatim_defaillance": defaillance, "page": None}


def _sanitize_mitigation(question, status, mitigation_status):
    """Neutralise mitigation_status si `status` n'est pas du côté "risque"
    de la question (cf. a_condition, grid_questions.py) — un LLM peut
    halluciner un MITIGATION_STATUS alors que la sous-question A n'était
    pas censée être évaluée (ex: B.3.1 répond OUI mais renvoie quand même
    un statut de mitigation). Sans ce filet, grid_result.validate_grid_result
    (CC-V4-03) rejetterait le résultat entier (ValueError) pour une
    hallucination mineure du LLM — fail-open : on neutralise plutôt que de
    faire échouer toute l'analyse."""
    a_condition = question.get("a_condition", "r_oui")
    risk_status = "OUI" if a_condition == "r_oui" else "NON"
    if status != risk_status:
        return None
    return mitigation_status


def _answer_for_question(question, question_chunks, document_type):
    code = question["code"]

    if not question_chunks:
        logger.info("grid_analyze: %s — aucun passage candidat, repli sur la règle de silence (R5).", code)
        return _silence_fallback(question, "Aucun passage pertinent trouvé dans le document sur ce sujet.")

    context_texts = [c["text"] for c in question_chunks]
    prompt = grid_prompts.get_prompt(code, context_texts, document_type=document_type)

    raw = llm_backend.call_llm(prompt)  # fail-open : None si backend injoignable (cf. llm_backend.py, ADR-002)
    parsed = grid_prompts.parse_response(raw) if raw else None

    if parsed is None:
        logger.warning("grid_analyze: %s — LLM injoignable ou réponse inexploitable, repli sur R5.", code)
        return _silence_fallback(question, "LLM injoignable ou réponse mal formée — repli sur la règle de silence (R5).")

    status = parsed["status"]
    mitigation_status = _sanitize_mitigation(question, status, parsed.get("mitigation_status"))

    # R10 — filtre de sujet : simple enregistrement de ce que le LLM a
    # répondu (il a déjà appliqué R10 dans le prompt, cf. grid_prompts.py)
    # — AUCUN filtre post-traitement ici, cf. docstring du module.
    qualifying = None
    if parsed.get("subject_filter") == "PRÊTEUR":
        qualifying = {
            "subject_filter": "lender",
            "lender_supervision": parsed.get("evidence_r") or "",
        }
        if status == "OUI":
            logger.warning(
                "grid_analyze: %s — verbatim sujet PRÊTEUR sans substitution trouvée par le "
                "LLM ; réponse OUI maintenue telle quelle mais qualifiée (R10, validation "
                "analyste requise, cf. Note de Cadrage décision 2).", code
            )

    return {
        "status": status,
        "mitigation_status": mitigation_status,
        "evidence_r": _build_evidence_r(parsed),
        "evidence_a": _build_evidence_a(parsed),
        "confidence_note": parsed.get("confidence_note"),
        "silence_applied": False,
        "qualifying": qualifying,
    }


def _na_answer(question):
    return {
        "status": "NA",
        "mitigation_status": None,
        "evidence_r": {
            "passage": f"Question exclue : module {question['na_module']} non applicable "
                       f"à ce projet (na_modules).",
            "page": None,
        },
        "evidence_a": None,
        "confidence_note": None,
        "silence_applied": False,
        "qualifying": None,
    }


def analyze_grid(chunks, na_modules=None, document_type=1):
    """Analyse un document via la Grille V4 (12 questions).

    chunks : list de dicts {"text": str, "page": int|None} — chunks du
        document déjà découpés (cf. docstring du module).
    na_modules : liste de na_module à exclure (ex. ["B.2"]) — cf.
        grid_questions.get_active_questions().
    document_type : int, clé de grid_questions.DOCUMENT_TYPES (R11), saisi
        manuellement par l'analyste. Conditionne le mode de lecture dans
        le prompt (formes de preuve R11, couches temporelles R8,
        hiérarchie des sources R9 — cf. grid_prompts.get_prompt) et les
        métadonnées du résultat (reading_mode/reading_mode_label). Passé
        tel quel à grid_scoring.compute_grid_score() pour ces métadonnées
        — N'AFFECTE PAS le calcul du score lui-même (cf. grid_scoring.py,
        CC-V4-02 : "ne pas ajouter de branche document_type dans le calcul").

    Retourne un résultat V4 complet (cf. grid_result.build_grid_result),
    ou None si le pipeline Grille est désactivé.

    CHOIX: `config.GRID_V4_ENABLED` (renommé depuis GRID_V3_ENABLED,
    CC-V4-08) gouverne le pipeline Grille toutes versions confondues —
    même flag, nom aligné sur la version courante de la grille.
    """
    if not config.GRID_V4_ENABLED:
        return None

    classified_chunks = grid_sections.classify_chunks(chunks or [])
    active_codes = {q["code"] for q in grid_questions.get_active_questions(na_modules)}

    question_results = {}
    for question in grid_questions.QUESTIONS:
        code = question["code"]

        if code not in active_codes:
            question_results[code] = _na_answer(question)
            continue

        # for_mitigation=False : un item ESAP renseigne le risque (R7bis) —
        # le prompt (une seule requête pour R et A) doit voir ce contenu
        # pour répondre correctement à R, tout en étant instruit de ne
        # jamais le créditer comme mitigation (cf. R7bis dans le prompt).
        question_chunks = grid_sections.get_chunks_for_question(classified_chunks, code, for_mitigation=False)
        question_results[code] = _answer_for_question(question, question_chunks, document_type)

    scoring = grid_scoring.compute_grid_score(question_results, document_type=document_type)
    return grid_result.build_grid_result(question_results, scoring)
