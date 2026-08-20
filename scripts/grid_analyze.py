"""
GRILLE ESG V4 — orchestrateur, architecture 2 passes (directive CC-V4-12)
=====================================================================
Assemble la chaîne complète pour UN document déjà chunké : classification
des sections structurelles (grid_sections.py), DEUX appels LLM par
question active (grid_prompts.py + llm_backend.py, cf. ci-dessous),
scoring déterministe (grid_scoring.py) et assemblage du résultat final
(grid_result.py) — la forme du résultat assemblé (grid_result.py) et le
calcul du score (grid_scoring.py) sont INCHANGÉS par CC-V4-12, ce module
se contente de traduire la sortie JSON 2 passes dans le même contrat
qu'avant (status/mitigation_status/evidence_r/evidence_a/confidence_note/
silence_applied/qualifying).

FRAGILE (hérité) : ce module ne fait AUCUN retrieval sémantique par
question — tous les chunks du document (moins les exclusions ESAP/
plaintes IFC, cf. grid_sections.py) sont passés à la Passe 1. Un
retrieval plus fin (top-k par question, FAISS ou autre) est un chantier
séparé si la taille de contexte devient un problème réel — non traité ici.

`chunks` (paramètre d'entrée) : list de dicts {"text": str, "page":
int|None}, déjà découpés en amont (cf. search.chunk_text() pour le
découpage brut).

ARCHITECTURE 2 PASSES (CC-V4-12, remplace l'invariant "un seul appel LLM
par question" de CC-V4-06) :
  Passe 1 — EXTRACTION (grid_prompts.get_extraction_prompt) : le texte
    contient-il un fait/état/constat pertinent pour la question ? Pas de
    jugement R5/R7 ici. found=false -> Passe 2 SAUTÉE, repli déterministe
    sur R5 (cf. _silence_status). found=true -> Passe 2 appelée SUR le
    verbatim extrait (jamais sur les chunks bruts).
  Passe 2 — QUALIFICATION (grid_prompts.get_qualification_prompt) :
    OUI/NON/NA_ARGUMENTE + statut de mitigation, à partir du seul verbatim
    de la Passe 1.
  Coût : jusqu'à 2 appels/question active, mais la Passe 2 est sautée dès
  que found=false (sur un dossier propre, la majorité des questions
  s'arrêtent après la Passe 1).

R5 (silence) : DÉTERMINISTE côté Python depuis CC-V4-12, le LLM n'est
plus consulté du tout quand found=false ou qu'aucun chunk candidat
n'existe — cf. _silence_status et _SILENCE_CONFIRMS_ABSENCE (justification
détaillée dans grid_prompts.py, section "DÉCISION R5" de son docstring).

R10 (filtre de sujet) : décidé PAR LE LLM en Passe 1 (champ `subject`),
consommé tel quel par la Passe 2, jamais recalculé ici en post-traitement
— ce module se contente d'enregistrer ce que le LLM a répondu dans
`qualifying` pour la boucle humaine (Note de Cadrage décision 2), jamais
de bascule automatique OUI->NON.

Fail-open (ADR-002), 3 paliers distincts (cf. docstring de
_answer_for_question pour le détail) :
  1. Aucun chunk candidat -> R5 silence, aucun appel LLM.
  2. Passe 1 injoignable/inexploitable -> pas de repli silence : traité
     comme found=true avec le texte brut des chunks en verbatim (le LLM
     n'a pas pu trancher, mais les chunks existent bel et bien — R5 ne
     s'applique qu'à l'ABSENCE de passage, pas à l'échec du LLM), Passe 2
     tente quand même de qualifier ce texte brut.
  3. Passe 2 injoignable/inexploitable (found=true en Passe 1) -> status
     OUI, confidence LOW (biais R1 : en cas de doute, signaler le risque),
     pas de mitigation.

SYNTHÈSE FINALE (directive "évolutions pipeline ESG/risk", 2026-08-20) :
troisième étape ajoutée APRÈS le scoring, dans analyze_grid() — cf.
_generate_synthesis. Un seul appel LLM texte libre par dossier (pas de
JSON, contrairement aux 2 passes ci-dessus), sur le résultat déjà
assemblé (grid_result.build_grid_result), jamais sur les chunks bruts.
N'affecte JAMAIS le score (déjà figé avant l'appel) — fail-open
indépendant (config.GRID_SYNTHESIS_ENABLED), échec -> result["synthesis"]
= None, le reste du résultat reste inchangé. Prompt et mise en forme des
questions OUI/INCONNU : grid_prompts.get_synthesis_prompt.
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

# --- R5 (silence), cas particulier (CC-V4-12) ---
# CHOIX: questions dont la formulation R est elle-même "Absence de X ?" —
# pour celles-ci, ne RIEN trouver dans le document EST la réponse (le
# silence confirme l'absence que la question demande), donc OUI direct,
# PAS le repli "etat -> INCONNU" générique. Cf. justification complète
# (pourquoi ce n'est PAS un remplacement du mécanisme silence_type
# existant, seulement un cas particulier au-dessus) dans le docstring de
# grid_prompts.py, section "DÉCISION R5".
_SILENCE_CONFIRMS_ABSENCE = {"B.3.1", "B.3.2"}

# Texte canonique affiché (UI/export/synthèse) quand une question n'a
# STRICTEMENT rien trouvé (found=false ou aucun chunk candidat) — cf.
# directive "gestion INCONNU" (2026-08-20), section "Affichage attendu" :
# jamais de justification inventée sur une absence de passage, seulement
# ce texte, tel quel, partout où confidence_note est affiché ou envoyé au
# LLM de synthèse (cf. grid_prompts._format_inconnu_block).
_NO_ELEMENT_FOUND = "Aucun élément n'a été trouvé."


def _silence_status(question):
    """Statut de repli selon silence_type (R5, grid_questions.py, CC-08),
    avec le cas particulier _SILENCE_CONFIRMS_ABSENCE en priorité :
    - code dans _SILENCE_CONFIRMS_ABSENCE -> OUI (le silence EST le risque)
    - "etat" -> INCONNU (silence ne prouve pas l'absence d'un système/état)
    - "evenement" -> NON (silence vaut absence du fait daté)."""
    if question["code"] in _SILENCE_CONFIRMS_ABSENCE:
        return "OUI"
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


def _normalize_page(page_value):
    """La Passe 1 peut renvoyer `page` en int, en string numérique, ou
    None/null — normalise vers int ou None, jamais d'exception sur une
    valeur mal formée (fail-open, cohérent ADR-002)."""
    if isinstance(page_value, int):
        return page_value
    if isinstance(page_value, str) and page_value.strip().isdigit():
        return int(page_value.strip())
    return None


_SUBJECT_QUALIFYING = {
    "LENDER": ("lender", "lender_supervision"),
    "AMBIGUOUS": ("ambiguous", "ambiguous_note"),
    "INDIRECT": ("indirect_not_imputable", "indirect_note"),
}


def _build_qualifying(subject, verbatim_r, na_argumente_reason):
    """Assemble `qualifying` (CC-V4-12) : sujet R10 (LENDER/AMBIGUOUS/
    INDIRECT — SPV/SUBSTITUTION n'ont rien à signaler, le score reflète
    déjà directement le fait) ET/OU motif N/A argumenté (nouveau CC-V4-12,
    cf. AUDIT_PERTINENCE_NOTE_CADRAGE.md point 3 — distinct d'un NON
    simple, verbatim + motif explicite d'inapplicabilité). Les deux
    peuvent coexister (rare) — simple dict, pas de logique de score ici,
    jamais relu par grid_scoring.py."""
    qualifying = {}
    if subject in _SUBJECT_QUALIFYING:
        key, note_key = _SUBJECT_QUALIFYING[subject]
        qualifying["subject_filter"] = key
        qualifying[note_key] = verbatim_r or ""
    if na_argumente_reason:
        # CHOIX: valeur texte (pas bool) — grid_display._render_evidence_explorer
        # filtre `v is not True`, un simple booléen n'apparaîtrait jamais
        # à l'analyste (cf. grid_display.py, non modifié par CC-V4-12).
        qualifying["na_argumente_reason"] = na_argumente_reason
    return qualifying or None


def _answer_for_question(question, question_chunks, document_type):
    """Orchestre les 2 passes pour UNE question. Cf. docstring du module
    pour les 3 paliers de fail-open (aucun chunk / Passe 1 KO / Passe 2 KO)."""
    code = question["code"]

    if not question_chunks:
        logger.info("grid_analyze: %s — aucun passage candidat, repli sur la règle de silence (R5).", code)
        return _silence_fallback(question, _NO_ELEMENT_FOUND)

    context_texts = [c["text"] for c in question_chunks]

    # --- Passe 1 — EXTRACTION ---
    extraction_prompt = grid_prompts.get_extraction_prompt(code, context_texts, document_type=document_type)
    raw_extraction = llm_backend.call_llm(extraction_prompt, response_format="json")
    extracted = grid_prompts.parse_extraction_response(raw_extraction) if raw_extraction else None

    if extracted is None:
        # Palier 2 : Passe 1 injoignable/inexploitable — PAS un repli
        # silence (les chunks existent, cf. docstring module) : on traite
        # comme found=true avec le texte brut, la Passe 2 tente quand même.
        logger.warning(
            "grid_analyze: %s — Passe 1 (extraction) injoignable ou réponse inexploitable, "
            "repli sur le texte brut des chunks (pas R5 — des passages existent).", code
        )
        raw_joined = "\n---\n".join(context_texts)[:4000]
        extracted = {"found": True, "verbatim": raw_joined, "page": None, "subject": "AMBIGUOUS", "brief": None}

    if not extracted["found"]:
        # CHOIX (directive "gestion INCONNU", 2026-08-20) : confidence_note
        # reste le texte canonique _NO_ELEMENT_FOUND même si le LLM a
        # fourni un `brief` — on n'affiche jamais une justification
        # inventée/reformulée par le modèle sur une ABSENCE de passage,
        # seulement le fait brut. Le `brief` éventuel est conservé en log
        # (utile en debug) mais jamais montré à l'analyste ni à la
        # synthèse finale.
        if extracted.get("brief"):
            logger.info("grid_analyze: %s — Passe 1 found=false, brief LLM (log seulement) : %s",
                        code, extracted["brief"])
        logger.info("grid_analyze: %s — Passe 1 : rien trouvé (found=false), repli sur R5.", code)
        return _silence_fallback(question, _NO_ELEMENT_FOUND)

    # --- Passe 2 — QUALIFICATION (uniquement si found=true) ---
    qualification_prompt = grid_prompts.get_qualification_prompt(
        code, extracted["verbatim"], extracted["subject"], document_type=document_type
    )
    raw_qualification = llm_backend.call_llm(qualification_prompt, response_format="json")
    qualified = grid_prompts.parse_qualification_response(raw_qualification) if raw_qualification else None

    evidence_r = {"passage": extracted["verbatim"], "page": _normalize_page(extracted.get("page"))}

    if qualified is None:
        # Palier 3 : Passe 2 injoignable/inexploitable — biais R1 (en cas
        # de doute, signaler le risque) : OUI, confidence LOW, pas de
        # mitigation (jamais évaluée).
        logger.warning(
            "grid_analyze: %s — Passe 2 (qualification) injoignable ou réponse inexploitable, "
            "repli R1 : status=OUI, confidence=LOW.", code
        )
        qualifying = _build_qualifying(extracted["subject"], extracted["verbatim"], None)
        return {
            "status": "OUI",
            "mitigation_status": None,
            "evidence_r": evidence_r,
            "evidence_a": None,
            "confidence_note": "[LOW] Passe 2 injoignable ou réponse mal formée — repli R1 (signale le risque).",
            "silence_applied": False,
            "qualifying": qualifying,
        }

    status = qualified["status"]
    na_argumente_reason = None
    if status == "NA_ARGUMENTE":
        # CC-V4-12 : nouveau statut, distinct d'un NON simple (motif
        # explicite d'inapplicabilité) — cf. AUDIT_PERTINENCE_NOTE_CADRAGE.md
        # point 3. grid_scoring.py n'accepte QUE OUI/NON/NA/INCONNU (non
        # modifié, hors périmètre CC-V4-12) : traduit en "NON" pour le
        # calcul (0 pénalité, comportement déjà correct), la nuance
        # "argumenté" est conservée dans `qualifying` pour l'analyste,
        # PAS perdue silencieusement.
        na_argumente_reason = qualified.get("brief_r") or qualified.get("verbatim_r") or "Motif non précisé"
        status = "NON"

    # Mitigation illégale si status != OUI (ex: NA_ARGUMENTE traduit en
    # NON, ou LLM qui hallucine un mitigation_status sur un NON) — même
    # garde-fou que l'ancien _sanitize_mitigation, cf. grid_result.py
    # (validate_grid_result rejetterait sinon le résultat entier).
    mitigation_status = qualified.get("mitigation_status") if status == "OUI" else None

    evidence_a = None
    if qualified.get("verbatim_a_mesure") or qualified.get("verbatim_a_defaillance"):
        evidence_a = {
            "verbatim_mesure": qualified.get("verbatim_a_mesure"),
            "verbatim_defaillance": qualified.get("verbatim_a_defaillance"),
            # Hérite de la page R (evidence_r), pas de page propre possible :
            # la Passe 2 ne voit JAMAIS les chunks/marqueurs [PAGE:N] bruts,
            # seulement le verbatim déjà extrait par la Passe 1 (cf.
            # get_qualification_prompt) — verbatim_a_mesure/_defaillance en
            # sont des sous-extraits, donc structurellement sur la même page
            # que evidence_r. Diagnostic "mitigation sans page" (2026-08-20).
            "page": evidence_r["page"],
        }

    confidence_note = qualified.get("brief_r")
    if qualified["confidence"] == "LOW" and confidence_note:
        confidence_note = f"[LOW] {confidence_note}"

    qualifying = _build_qualifying(extracted["subject"], qualified.get("verbatim_r") or extracted["verbatim"], na_argumente_reason)
    if extracted["subject"] in ("LENDER", "AMBIGUOUS", "INDIRECT") and status == "OUI":
        logger.warning(
            "grid_analyze: %s — sujet %s mais status=OUI reçu (R10 exige de ne pas attribuer "
            "par défaut à la SPV) ; réponse maintenue telle quelle mais qualifiée, validation "
            "analyste requise (Note de Cadrage décision 2).", code, extracted["subject"]
        )

    return {
        "status": status,
        "mitigation_status": mitigation_status,
        "evidence_r": evidence_r,
        "evidence_a": evidence_a,
        "confidence_note": confidence_note,
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


def _generate_synthesis(result):
    """Passe de synthèse finale (directive "évolutions pipeline ESG/risk",
    2026-08-20) — UN SEUL appel LLM par dossier, APRÈS le scoring, texte
    libre (response_format=None, contrairement aux 2 passes JSON par
    question). N'affecte JAMAIS le score : appelée une fois que `result`
    (donc `result["scoring"]`) est déjà entièrement calculé.

    Fail-open (ADR-002) : config.GRID_SYNTHESIS_ENABLED=False ou appel LLM
    injoignable/vide -> retourne None, ne lève jamais, ne modifie ni les
    questions ni le scoring déjà assemblés dans `result`. Un seul appel
    (pas de retry) — cf. directive, section "Robustesse".

    config_key="deep_synthesize" (config.OLLAMA_CONFIGS) : réutilisé tel
    quel depuis deep_analysis.run_pass3 (même type de tâche — 3-5 phrases
    de synthèse en français), pas de nouvelle clé de config créée.
    """
    if not config.GRID_SYNTHESIS_ENABLED:
        return None

    prompt = grid_prompts.get_synthesis_prompt(result)
    synthesis = llm_backend.call_llm(prompt, config_key="deep_synthesize", temperature=0.2, timeout=150)
    if not synthesis:
        logger.warning("grid_analyze: synthèse finale injoignable ou vide — result['synthesis']=None.")
        return None
    return synthesis


def analyze_grid(chunks, na_modules=None, document_type=1, context=None):
    """Analyse un document via la Grille V4 (12 questions).

    chunks : list de dicts {"text": str, "page": int|None} — chunks du
        document déjà découpés (cf. docstring du module).
    na_modules : liste de na_module à exclure (ex. ["B.2"]) — cf.
        grid_questions.get_active_questions().
    document_type : int, clé de grid_questions.DOCUMENT_TYPES (R11), saisi
        manuellement par l'analyste. Conditionne le mode de lecture dans
        les prompts (matérialisation R2/R8 en Passe 1, formes de preuve
        R11/hiérarchie R9 en Passe 2 — cf. grid_prompts.get_extraction_prompt/
        get_qualification_prompt, CC-V4-12) et les métadonnées du résultat
        (reading_mode/reading_mode_label). Passé tel quel à
        grid_scoring.compute_grid_score() pour ces métadonnées —
        N'AFFECTE PAS le calcul du score lui-même (cf. grid_scoring.py,
        CC-V4-02 : "ne pas ajouter de branche document_type dans le calcul").
    context : dict | None (BLOC D, CC-V4-11) — les 4 champs manuels
        obligatoires saisis par l'analyste (cf. grid_result.build_grid_result).
        Simple pass-through jusqu'au résultat final — jamais lu ni utilisé
        ici, jamais transmis au LLM, jamais dans le calcul du score.

    Retourne un résultat V4 complet (cf. grid_result.build_grid_result) AVEC
    une clé "synthesis" ajoutée (str|None, cf. _generate_synthesis — passe
    de synthèse finale exécutée ICI, après le scoring, directive
    "évolutions pipeline ESG/risk" 2026-08-20), ou None si le pipeline
    Grille est désactivé.

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
    result = grid_result.build_grid_result(question_results, scoring, context=context)
    # Synthèse finale : APRÈS le scoring, sur le résultat déjà assemblé
    # (result["scoring"] figé) — cf. _generate_synthesis. Ne relit ni ne
    # modifie question_results/scoring ci-dessus.
    result["synthesis"] = _generate_synthesis(result)
    return result


def analyze_grid_auto(chunks, full_text, na_modules=None, document_type_override=None, context=None):
    """Comme analyze_grid(), mais résout document_type (R11) AVANT
    l'annotation/le scoring au lieu de le recevoir en paramètre obligatoire
    — cf. grid_doctype.py : le type de document conditionne le mode de
    lecture de chaque question (grid_prompts.get_extraction_prompt/
    get_qualification_prompt, CC-V4-12), il doit donc être connu avant le
    premier appel LLM par question, pas après coup.

    full_text : texte intégral du document (pas les chunks) — transmis tel
    quel à grid_doctype.detect_document_type(), qui a besoin d'un extrait
    cohérent (début de document), pas de chunks découpés/mélangés.
    document_type_override : int (1-4) — saisie manuelle de l'analyste
    (contrôle humain, Note de Cadrage décision 2). Si fourni, la détection
    LLM n'est PAS appelée (pas d'appel superflu) ; le résultat porte
    quand même un bloc "document_type_detection" avec source="manuel"
    pour que l'UI affiche la provenance de façon uniforme.
    context : dict | None (BLOC D, CC-V4-11) — transmis tel quel à
        analyze_grid() (cf. sa docstring).

    Ajoute au résultat un bloc "document_type_detection" :
        {"document_type": int, "confidence": "haute"|"moyenne"|"faible"|
         "manuelle", "evidence": str|None,
         "source": "llm"|"manuel"|"fallback_heuristique_..."}
    Ce bloc est un simple pass-through informatif (comme "qualifying",
    grid_result.py) — jamais relu par grid_scoring.py, qui ne connaît que
    l'entier document_type déjà résolu ici.
    """
    if not config.GRID_V4_ENABLED:
        return None

    import grid_doctype

    if document_type_override is not None:
        detection = {
            "document_type": document_type_override,
            "confidence": "manuelle",
            "evidence": None,
            "source": "manuel",
        }
    else:
        detection = grid_doctype.detect_document_type(full_text)

    result = analyze_grid(
        chunks, na_modules=na_modules, document_type=detection["document_type"], context=context
    )
    if result is not None:
        result["document_type_detection"] = detection
    return result
