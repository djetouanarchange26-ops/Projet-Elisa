"""
GRILLE ESG V4 — format de résultat (directives CC-03, CC-07, CC-08, CC-V4-03)
=====================================================================
Contrat d'interface entre le pipeline, l'UI et l'export pour une analyse
V4 complète. Assemble les réponses par question (grid_questions.py) et le
résultat du scoring (grid_scoring.compute_grid_score()) en un seul dict
sérialisable en JSON sans transformation.

Format du résultat (dict Python, sérialisable en JSON) :

    {
        "grid_version": str,   # "V4"
        "document_type": int,           # 1-4 (R11, CC-V4-02/03)
        "reading_mode": str,             # "instruction" | "suivi"
        "reading_mode_label": str,       # label humain du type de document
        "context": dict or None,        # 4 champs manuels obligatoires
            # (BLOC D, CC-V4-11) : {"ep_classification": str,
            # "sensitivity": str, "financing_amount": str, "cacib_role":
            # str} — saisis par l'analyste dans app.py, jamais extraits du
            # document, jamais utilisés dans le calcul du score. Simple
            # pass-through, comme "qualifying" par question.
        "questions": [
            {
                "code": str,                    # "A.1.1"
                "category": str,               # "A" | "B"
                "sous_theme": str,
                "question_r": str or None,     # None seulement si has_separate_r=False
                "question_a": str,
                "status": str,                  # "OUI" | "NON" | "NA" | "INCONNU"
                "mitigation_status": str or None, # une clé de
                    # grid_questions.MITIGATION_STATUTS ou None (CC-07 —
                    # remplace le binaire "mitigation" OUI/NON de CC-03)
                "mitigation_label": str or None,  # label humain dérivé,
                    # ex. "NON — intention" — jamais fourni par l'appelant,
                    # toujours recalculé depuis mitigation_status ici
                "evidence_r": {"passage": str, "page": int or None} or None,
                "evidence_a": {"verbatim_mesure": str or None,
                                "verbatim_defaillance": str or None,
                                "page": int or None} or None,
                "confidence_note": str or None, # texte libre — doute du LLM
                "silence_type": str,             # "evenement" | "etat"
                    # (CC-08, structurel — copié depuis grid_questions.py)
                "silence_applied": bool,         # True si la réponse vient
                    # du silence (pas de verbatim trouvé) — fourni en
                    # entrée (question_results), pas déduit ici
                "atteste": bool,                 # True si NON + verbatim
                    # explicite — DÉDUIT mécaniquement ici, jamais fourni
                    # par l'appelant : atteste = (status=="NON" and
                    # evidence_r is not None). Ne change PAS le score,
                    # change seulement la lisibilité (un NON attesté est
                    # plus fiable qu'un NON par silence).
                "verrou_applique": bool,         # True si le verrou
                    # B.2.1->B.2.2 a forcé cette réponse à INCONNU — repris
                    # tel quel depuis scoring["details"] (calculé par
                    # grid_scoring.py, pas ici)
                "shared_cap_applied": bool,      # True si le plafond partagé
                    # A.1 (grid_questions.py::shared_cap_group) a ramené
                    # cette pénalité à 0 — repris tel quel depuis
                    # scoring["details"]["_shared_cap_applied"] (CC-V4-02)
                "a_condition": str,              # "r_oui" | "r_non" —
                    # copié depuis grid_questions.py, pour que l'UI sache
                    # quel côté de status active la sous-question A
                "qualifying": dict or None,      # champs qualifiants V4,
                    # NON-SCORANTS, texte libre — simple pass-through de
                    # question_results (pas de logique ici), ex. :
                    # {"allegation": str|None, "transparency": str|None,
                    #  "lender_supervision": str|None, "species_list": str|None,
                    #  "access_denied": bool, "threshold_reference": str|None,
                    #  "temporal_layer": int|None, "source_level": int|None,
                    #  "subject_filter": str|None}
                "penalty": int,                 # pénalité effectivement appliquée
                "gain": int                     # gain effectivement appliqué
            }
        ],
        "scoring": {
            "total_penalty": int,
            "total_gain": int,
            "total_gain_capped": int,
            "cap_applied": bool,
            "score": int,
            "color": str,       # "VERT" | "JAUNE" | "ORANGE" | "ROUGE" (V4, CC-V4-02)
            "saturation": bool, # True si score == 0 ("ROUGE — Éliminatoire")
            "questions_active": int,
            "questions_na": int
        }
    }

`confidence_note` répond à la demande d'Elisa de voir les passages sur
lesquels le LLM doute : texte libre, jamais un score numérique — pas de
pseudo-probabilité non calibrée ici (cf. "Ce qu'il ne faut PAS faire",
CC-03 : pas de champ `probability`/`risk_level` spéculatif). Même principe
pour `qualifying` (CC-V4-03) : informatif, jamais scorant.

CHANTIER CC-07 : `mitigation_status`/`evidence_a` reflètent tels quels ce
qui a été fourni en entrée (question_results), MÊME si le garde-fou du
statut OUI_DEFAILLANTE a rétrogradé le calcul vers OUI_PROUVEE côté
grid_scoring.py — c'est voulu (traçabilité : `mitigation_status` reste
honnête sur ce qui a été constaté/affirmé, seuls `penalty`/`gain`
reflètent le résultat après garde-fou). Contrairement à
grid_scoring.compute_grid_score() (qui corrige silencieusement),
validate_grid_result() ici est STRICTE sur ce garde-fou : un résultat déjà
assemblé qui affiche OUI_DEFAILLANTE sans les deux verbatims est rejeté
(ValueError), pas corrigé — cf. sa docstring.

CHANTIER CC-08 (passe CBG, règles de silence) : contrairement au statut
OUI_DEFAILLANTE (CC-07, où `mitigation_status` reste honnête sur l'entrée
même après correction), `status` ici est repris depuis
scoring["details"] — PAS depuis question_results — précisément pour
refléter le verrou B.2.1->B.2.2 : le but du verrou est que l'analyste VOIE
"INCONNU" pour B.2.2, pas un "NON" qui masquerait l'opacité sur B.2.1.
Les deux mécanismes (CC-07 vs CC-08) sont donc volontairement asymétriques
sur ce point précis — documenté ici pour ne pas être relu comme une
incohérence.

CHANTIER CC-V4-03 :
  - `document_type`/`reading_mode`/`reading_mode_label` : simple
    pass-through de scoring (grid_scoring.compute_grid_score() les calcule
    déjà, cf. CC-V4-02) — aucune logique R11 ici.
  - `a_condition`/`shared_cap_applied` : nouveaux champs par question,
    même principe de pass-through que `verrou_applique` (CC-08).
  - `qualifying` : optionnel (None ou dict), jamais obligatoire, jamais
    utilisé dans le calcul du score — cf. "Ce qu'il ne faut PAS faire"
    de la directive.
  - validate_grid_result() : le garde-fou "pas de mitigation pour une
    question sans sous-question A séparée" (has_separate_r=False)
    disparaît de fait en V4 (toutes les questions ont has_separate_r=True
    depuis CC-V4-01) — remplacé par un garde-fou plus précis basé sur
    a_condition : la mitigation n'est légale que du côté "risque" de la
    question (status=OUI si a_condition="r_oui" ; status=NON si
    a_condition="r_non", cas de B.3.1 uniquement pour l'instant).

Ce module n'implémente AUCUNE logique de calcul (c'est le rôle de
grid_scoring.py) ni aucune logique LLM — assemblage et validation
structurelle uniquement.
"""

import logging

import grid_questions

logger = logging.getLogger(__name__)

_VALID_STATUSES = {"OUI", "NON", "NA", "INCONNU"}
_VALID_COLORS = {"VERT", "JAUNE", "ORANGE", "ROUGE"}


def build_grid_result(question_results, scoring, context=None):
    """Assemble un résultat V3 complet à partir des réponses par question
    et du résultat de grid_scoring.compute_grid_score().

    question_results : dict {code: {"status": "OUI"|"NON"|"NA",
                                     "mitigation_status": une clé de
                                         grid_questions.MITIGATION_STATUTS
                                         ou None,
                                     "evidence_r": {"passage": str, "page": int|None} | None,
                                     "evidence_a": {"verbatim_mesure": str|None,
                                                     "verbatim_defaillance": str|None,
                                                     "page": int|None} | None,
                                     "confidence_note": str | None}}
    scoring : dict — retour de grid_scoring.compute_grid_score(), calculé
              sur les mêmes réponses (status/mitigation_status) que
              question_results.
    context : dict | None (BLOC D, CC-V4-11) — les 4 champs manuels
        obligatoires (classification Equator Principles, statut de
        sensibilité, montant du financement, rôle de CACIB), saisis par
        l'analyste dans app.py AVANT le lancement de l'analyse (contrôle
        humain bloquant, cf. app.py). Simple pass-through, comme
        "qualifying" — JAMAIS relu par grid_scoring.py, n'entre JAMAIS
        dans le calcul du score (cf. "Ce qu'il ne faut PAS faire",
        directive BLOC D). None si l'appelant ne les fournit pas
        (rétro-compatibilité tests/appels existants).

    CHOIX: pas de recalcul du score ici — build_grid_result assemble,
    grid_scoring.compute_grid_score() calcule. Le détail par question du
    scoring (penalty/gain effectivement appliqués, cf. scoring["details"])
    est repris tel quel, indexé par code. `mitigation_label` est dérivé
    ici (jamais fourni par l'appelant) via un lookup dans
    grid_questions.MITIGATION_STATUTS — source unique du libellé humain.
    """
    scoring_by_code = {d["code"]: d for d in scoring["details"]}

    questions = []
    for question in grid_questions.QUESTIONS:
        code = question["code"]
        answer = question_results.get(code, {})
        detail = scoring_by_code.get(code, {})

        mitigation_status = answer.get("mitigation_status")
        mitigation_label = None
        if mitigation_status in grid_questions.MITIGATION_STATUTS:
            mitigation_label = grid_questions.MITIGATION_STATUTS[mitigation_status]["label"]

        # CC-08 : status vient du scoring (reflète le verrou B.2.1->B.2.2),
        # pas de question_results — cf. docstring du module. Repli sur
        # answer.get("status") si le code est absent de scoring["details"]
        # (ne devrait pas arriver en usage normal).
        status = detail.get("status", answer.get("status"))
        evidence_r = answer.get("evidence_r")

        questions.append({
            "code": code,
            "category": question["category"],
            "sous_theme": question["sous_theme"],
            "question_r": question["question_r"],
            "question_a": question["question_a"],
            "status": status,
            "mitigation_status": mitigation_status,
            "mitigation_label": mitigation_label,
            "evidence_r": evidence_r,
            "evidence_a": answer.get("evidence_a"),
            "confidence_note": answer.get("confidence_note"),
            "silence_type": question["silence_type"],
            "silence_applied": bool(answer.get("silence_applied", False)),
            "atteste": status == "NON" and evidence_r is not None,
            "verrou_applique": bool(detail.get("verrou_applique", False)),
            "shared_cap_applied": bool(detail.get("_shared_cap_applied", False)),
            "a_condition": question.get("a_condition", "r_oui"),
            "qualifying": answer.get("qualifying"),
            "penalty": detail.get("penalty", 0),
            "gain": detail.get("gain", 0),
        })

    return {
        "grid_version": grid_questions.GRID_VERSION,
        "document_type": scoring.get("document_type"),
        "reading_mode": scoring.get("reading_mode"),
        "reading_mode_label": scoring.get("reading_mode_label"),
        "context": context,
        "questions": questions,
        "scoring": {
            "total_penalty": scoring["total_penalty"],
            "total_gain": scoring["total_gain"],
            "total_gain_capped": scoring["total_gain_capped"],
            "cap_applied": scoring["cap_applied"],
            "score": scoring["score"],
            "color": scoring["color"],
            "saturation": scoring.get("saturation", scoring["score"] == 0),
            "questions_active": scoring["questions_active"],
            "questions_na": scoring["questions_na"],
        },
    }


def validate_grid_result(result):
    """Vérifie la cohérence structurelle d'un résultat V4.
    CHOIX: validation stricte — lève ValueError si le résultat est mal
    formé. Vérifie : grid_version="V4", document_type valide (R11),
    12 codes connus (tous présents, aucun inconnu), statuts valides,
    mitigation_status valide (une clé de MITIGATION_STATUTS ou None), pas
    de mitigation sur une question NA ni du côté "non-risque" de son
    a_condition (cf. CC-V4-02/03), valeurs de pénalité/gain par question
    cohérentes avec le barème de grid_questions.py, qualifying optionnel
    (None ou dict), et cohérence des totaux du bloc "scoring" avec le
    détail par question.

    CC-07 : contrairement à grid_scoring.compute_grid_score() (qui
    corrige silencieusement un statut OUI_DEFAILLANTE sans double
    verbatim en le retombant sur OUI_PROUVEE), cette fonction est STRICTE
    — un résultat déjà assemblé qui affiche OUI_DEFAILLANTE sans les deux
    verbatims (verbatim_mesure ET verbatim_defaillance non vides) est
    rejeté (ValueError), pas corrigé. Un résultat bien formé ne devrait
    jamais se trouver dans cet état si `build_grid_result` a été utilisé
    en aval de `compute_grid_score` sur les mêmes données — cette
    vérification protège contre un résultat construit/modifié autrement.

    CC-V4-03 : le garde-fou V3 "pas de mitigation pour une question sans
    sous-question A séparée" (has_separate_r=False) est remplacé par un
    garde-fou basé sur a_condition — plus précis depuis que B.3.1 a, elle
    aussi, has_separate_r=True (CC-V4-01) mais une sous-question A qui ne
    s'active QUE du côté "risque" propre à son schéma (status=NON, pas
    status=OUI) : la mitigation n'est légale que si status correspond au
    côté "risque" de a_condition (OUI pour "r_oui", NON pour "r_non").

    FRAGILE: ne recalcule PAS le score (formule + plafond + plancher) —
    ce serait dupliquer la logique de grid_scoring.py (interdit par
    CC-03). Se limite à des invariants structurels (sommes, bornes,
    cohérence interne) qui ne dépendent pas de connaître la formule.
    """
    if result.get("grid_version") != grid_questions.GRID_VERSION:
        raise ValueError(
            f"grid_result: grid_version invalide : {result.get('grid_version')!r} "
            f"(attendu {grid_questions.GRID_VERSION!r})"
        )

    document_type = result.get("document_type")
    if document_type not in grid_questions.DOCUMENT_TYPES:
        raise ValueError(
            f"grid_result: document_type invalide : {document_type!r} "
            f"(attendu une clé de grid_questions.DOCUMENT_TYPES)"
        )

    expected_meta = grid_questions.DOCUMENT_TYPES[document_type]
    if result.get("reading_mode") != expected_meta["reading_mode"]:
        raise ValueError(
            f"grid_result: reading_mode incohérent avec document_type={document_type!r} : "
            f"{result.get('reading_mode')!r} (attendu {expected_meta['reading_mode']!r})"
        )

    questions = result.get("questions")
    if not isinstance(questions, list):
        raise ValueError("grid_result: 'questions' doit être une liste")

    known_codes = {q["code"] for q in grid_questions.QUESTIONS}
    seen_codes = set()

    for entry in questions:
        code = entry.get("code")
        if code not in known_codes:
            raise ValueError(f"grid_result: code inconnu {code!r}")
        seen_codes.add(code)

        status = entry.get("status")
        if status not in _VALID_STATUSES:
            raise ValueError(f"grid_result: status invalide pour {code!r} : {status!r}")

        mitigation_status = entry.get("mitigation_status")
        if mitigation_status is not None and mitigation_status not in grid_questions.MITIGATION_STATUTS:
            raise ValueError(
                f"grid_result: mitigation_status invalide pour {code!r} : {mitigation_status!r}"
            )

        question = grid_questions.get_question(code)

        if status == "NA" and mitigation_status is not None:
            raise ValueError(f"grid_result: mitigation fournie pour {code!r} alors que status=NA")

        # CC-V4-03 : la sous-question A ne s'active que du côté "risque"
        # de a_condition — OUI pour le schéma standard ("r_oui"), NON pour
        # B.3.1 ("r_non"). Une mitigation fournie de l'autre côté est
        # incohérente (rien à atténuer si le risque n'est pas constaté).
        a_condition = question.get("a_condition", "r_oui")
        risk_status = "OUI" if a_condition == "r_oui" else "NON"
        if status != risk_status and status != "NA" and mitigation_status is not None:
            raise ValueError(
                f"grid_result: mitigation fournie pour {code!r} alors que status={status!r} "
                f"(a_condition={a_condition!r} exige status={risk_status!r} pour activer "
                f"la sous-question A)"
            )

        if mitigation_status is None and entry.get("evidence_a") is not None:
            raise ValueError(
                f"grid_result: evidence_a fournie pour {code!r} alors que mitigation_status=None"
            )

        qualifying = entry.get("qualifying")
        if qualifying is not None and not isinstance(qualifying, dict):
            raise ValueError(
                f"grid_result: qualifying invalide pour {code!r} — doit être un dict ou None "
                f"(obtenu {type(qualifying).__name__})"
            )

        if mitigation_status == "OUI_DEFAILLANTE":
            evidence_a = entry.get("evidence_a") or {}
            if not evidence_a.get("verbatim_mesure") or not evidence_a.get("verbatim_defaillance"):
                raise ValueError(
                    f"grid_result: statut OUI_DEFAILLANTE pour {code!r} sans les deux "
                    f"verbatims requis (verbatim_mesure et verbatim_defaillance)"
                )

        # CC-08 — règles de silence et verrou B.2.1->B.2.2.
        evidence_r = entry.get("evidence_r")

        if status == "NA" and evidence_r is None:
            raise ValueError(
                f"grid_result: status=NA pour {code!r} sans verbatim (evidence_r) — "
                f"cf. grid_questions.SILENCE_VALUES['NA'] : verbatim obligatoire"
            )

        silence_applied = entry.get("silence_applied", False)
        if silence_applied and evidence_r is not None:
            raise ValueError(
                f"grid_result: silence_applied=True pour {code!r} alors qu'un evidence_r "
                f"est fourni (le silence suppose l'absence de passage trouvé)"
            )

        atteste = entry.get("atteste", False)
        if atteste and not (status == "NON" and evidence_r is not None):
            raise ValueError(
                f"grid_result: atteste=True pour {code!r} incohérent — exige status=NON "
                f"ET evidence_r non-None (obtenu status={status!r}, evidence_r={evidence_r!r})"
            )

        verrou_applique = entry.get("verrou_applique", False)
        if verrou_applique and status != "INCONNU":
            raise ValueError(
                f"grid_result: verrou_applique=True pour {code!r} alors que status={status!r} "
                f"(attendu INCONNU)"
            )

        penalty = entry.get("penalty")
        gain = entry.get("gain")
        if penalty not in (0, question["penalty"]):
            raise ValueError(
                f"grid_result: penalty incohérent pour {code!r} : {penalty!r} "
                f"(attendu 0 ou {question['penalty']})"
            )
        if gain not in (0, question["gain"]):
            raise ValueError(
                f"grid_result: gain incohérent pour {code!r} : {gain!r} "
                f"(attendu 0 ou {question['gain']})"
            )

    missing = known_codes - seen_codes
    if missing:
        raise ValueError(f"grid_result: questions manquantes : {sorted(missing)}")

    scoring = result.get("scoring")
    if not isinstance(scoring, dict):
        raise ValueError("grid_result: 'scoring' doit être un dict")

    if scoring.get("color") not in _VALID_COLORS:
        raise ValueError(f"grid_result: color invalide : {scoring.get('color')!r}")

    if not (0 <= scoring.get("score", -1) <= 100):
        raise ValueError(f"grid_result: score hors bornes [0,100] : {scoring.get('score')!r}")

    # Cohérence des totaux agrégés avec le détail par question — simple
    # somme, pas la formule de score (cf. FRAGILE ci-dessus).
    sum_penalty = sum(q["penalty"] for q in questions)
    sum_gain = sum(q["gain"] for q in questions)
    if sum_penalty != scoring.get("total_penalty"):
        raise ValueError(
            f"grid_result: total_penalty incohérent : détail={sum_penalty} "
            f"vs scoring={scoring.get('total_penalty')}"
        )
    if sum_gain != scoring.get("total_gain"):
        raise ValueError(
            f"grid_result: total_gain incohérent : détail={sum_gain} "
            f"vs scoring={scoring.get('total_gain')}"
        )

    total_gain_capped = scoring.get("total_gain_capped")
    if total_gain_capped is None or total_gain_capped > sum_gain:
        raise ValueError(
            f"grid_result: total_gain_capped ({total_gain_capped!r}) ne peut pas "
            f"dépasser total_gain ({sum_gain})"
        )

    cap_applied = scoring.get("cap_applied")
    if cap_applied != (sum_gain > total_gain_capped):
        raise ValueError(
            f"grid_result: cap_applied ({cap_applied!r}) incohérent avec "
            f"total_gain={sum_gain} / total_gain_capped={total_gain_capped}"
        )
