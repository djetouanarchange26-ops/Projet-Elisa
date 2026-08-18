"""
GRILLE ESG V4 — moteur de scoring (directives CC-02, CC-07, CC-08, CC-V4-02)
=====================================================================
Calcule le score /100 de la Grille V4 (scripts/grid_questions.py,
CC-01/CC-V4-01) à partir des réponses par question. Purement
déterministe — aucun appel LLM ici, aucune dépendance à l'ancien
pipeline (signals.py/search.py).

Formule :
    score = max(0, 100 - Σ pénalités_R + min(Σ gains_A, 20))

Deux schémas de notation (cf. grid_questions.py, champ "a_condition") :
  - Schéma standard (11 questions sur 12, a_condition="r_oui") : R=OUI
    déclenche la pénalité ; R=OUI ET mitigation_status=OUI_PROUVEE ajoute
    le gain ; R=NON, R=INCONNU ou status=NA -> 0.
  - Schéma inversé (B.3.1 uniquement, a_condition="r_non") : R=NON
    déclenche la pénalité (c'est l'absence de mesure de compensation/
    suivi écologique qui est le risque) ET active la sous-question A
    (CHANTIER CC-V4-02 : avant la V4, B.3.1 n'avait pas de sous-question
    de mitigation séparée — cf. has_separate_r dans grid_questions.py) ;
    R=OUI, INCONNU ou NA -> 0.

CHANTIER CC-07 (passe d'annotation CBG) : la mitigation binaire OUI/NON
de CC-02 est remplacée par les 4 statuts de grid_questions.MITIGATION_STATUTS
— seul OUI_PROUVEE génère un gain (points_multiplier=1), les 3 autres
valent 0. Rétro-compatibilité conservée : l'ancien champ answer["mitigation"]
("OUI"/"NON") reste accepté et converti automatiquement
(OUI -> OUI_PROUVEE, NON -> NON_INTENTION), cf. _resolve_mitigation_status.
Le garde-fou du statut 4 (OUI_DEFAILLANTE exige double verbatim) est
inchangé en V4 — cf. _resolve_gain, partagé par les deux schémas.

CHANTIER CC-08 (passe CBG, règles de silence) :
  - Statut "INCONNU", distinct de NON et de NA — traité comme NON au
    score (0 pénalité, 0 gain) mais jamais confondu avec NON dans le
    détail retourné (cf. grid_questions.SILENCE_VALUES pour la sémantique :
    NON = "pas de risque", INCONNU = "non documenté"). Quel statut le
    silence d'un document doit produire (NON ou INCONNU) dépend du
    silence_type de la question (grid_questions.py) — décidé en amont
    (prompt LLM/analyste), pas dans ce module : compute_grid_score() ne
    fait que scorer le statut qu'on lui donne, il ne le devine pas.
  - Verrou logique B.2.1 -> B.2.2 : si B.2.1 (absence de suivi des rejets)
    = OUI et que B.2.2 (dépassement de seuils) a été répondu NON, B.2.2
    est forcé à INCONNU pour le calcul — sans mesure, aucune conclusion
    sur un dépassement n'est possible, et sans ce verrou, ne pas mesurer
    deviendrait plus avantageux que mesurer. Le verrou ne modifie QUE le
    calcul (comme le garde-fou du statut 4, CC-07) — jamais la réponse
    d'entrée. Cf. _apply_b21_b22_lock.

CHANTIER CC-V4-02 :
  - 4 zones de couleur (au lieu de 3) — cf. get_color.
  - Plafond partagé A.1.1/A.1.3 (grid_questions.py::shared_cap_group) :
    même famille de risque (interruption d'activité subie par le
    projet) — si les deux sont OUI, la pénalité combinée reste plafonnée
    à -25 (pas -50). Appliqué en post-traitement après le calcul
    individuel de chaque détail, cf. bloc "Plafond partagé" ci-dessous.
  - B.3.1 : sous-question A active quand R=NON (a_condition="r_non") —
    cf. schéma inversé ci-dessus et _resolve_gain.
  - R11 (mode de lecture par type de document) : document_type est un
    paramètre d'entrée, enregistré dans les métadonnées du résultat
    (reading_mode/reading_mode_label) mais N'INFLUENCE PAS le calcul du
    score — c'est le LLM/l'analyste qui tient compte du type de document
    pour choisir le statut de mitigation en amont (4ème forme de preuve
    admise pour le type 1) ; ce module se contente d'appliquer le statut
    reçu, quel que soit le type. Ne pas ajouter de branche document_type
    dans le calcul lui-même (cf. directive CC-V4-02, "ce qu'il ne faut
    pas faire").
  - Drapeau de saturation : score == 0 -> result["saturation"] = True
    (« ROUGE — Éliminatoire »), pour distinguer un score plancher d'un
    score simplement bas.
"""

import logging

import grid_questions

logger = logging.getLogger(__name__)

MITIGATION_CAP = 20
BASE_SCORE = 100
SHARED_CAP_PENALTY = -25  # SEUIL V4: plafond combiné, uniquement pour Cat A (cf. grid_questions.py)

_VALID_STATUSES = {"OUI", "NON", "NA", "INCONNU"}
_VALID_MITIGATIONS = {"OUI", "NON"}  # ancien format binaire (CC-02), rétro-compatibilité


def get_color(score):
    """SEUIL V4 : 4 zones de couleur calibrées sur le corpus de 4 dossiers
    (remplace les 3 zones V3 — VERT/ORANGE/ROUGE).
    >=75 VERT, 50-74 JAUNE, 25-49 ORANGE, 0-24 ROUGE (Éliminatoire).
    """
    if score >= 75:
        return "VERT"
    if score >= 50:
        return "JAUNE"
    if score >= 25:
        return "ORANGE"
    return "ROUGE"


def _validate_answers(answers):
    """Lève ValueError si `answers` ne respecte pas le contrat attendu par
    compute_grid_score — cf. docstring de cette dernière."""
    known_codes = {q["code"] for q in grid_questions.QUESTIONS}

    for code in answers:
        if code not in known_codes:
            raise ValueError(
                f"grid_scoring: code inconnu {code!r} (absent de grid_questions.QUESTIONS)"
            )

    missing = known_codes - set(answers)
    if missing:
        raise ValueError(f"grid_scoring: codes attendus manquants dans answers : {sorted(missing)}")

    for code, answer in answers.items():
        status = answer.get("status")
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"grid_scoring: status invalide pour {code!r} : {status!r} (attendu OUI/NON/NA/INCONNU)"
            )

        mitigation_status = answer.get("mitigation_status")
        if mitigation_status is not None and mitigation_status not in grid_questions.MITIGATION_STATUTS:
            raise ValueError(
                f"grid_scoring: mitigation_status invalide pour {code!r} : {mitigation_status!r} "
                f"(attendu une clé de grid_questions.MITIGATION_STATUTS ou None)"
            )

        legacy_mitigation = answer.get("mitigation")
        if legacy_mitigation is not None and legacy_mitigation not in _VALID_MITIGATIONS:
            raise ValueError(
                f"grid_scoring: mitigation (ancien format) invalide pour {code!r} : "
                f"{legacy_mitigation!r} (attendu OUI/NON/None)"
            )

        has_mitigation_input = mitigation_status is not None or legacy_mitigation is not None

        question = grid_questions.get_question(code)

        if status == "NA" and has_mitigation_input:
            raise ValueError(f"grid_scoring: mitigation fournie pour {code!r} alors que status=NA")

        if not question["has_separate_r"] and has_mitigation_input:
            raise ValueError(
                f"grid_scoring: mitigation fournie pour {code!r} — pas de sous-question de "
                f"mitigation séparée pour cette question (schéma inversé)"
            )


def _resolve_mitigation_status(answer):
    """Résout le statut de mitigation à partir de l'entrée — priorité au
    nouveau champ "mitigation_status" (4 statuts, CC-07), repli sur
    l'ancien champ binaire "mitigation" ("OUI"/"NON", CC-02) pour
    rétro-compatibilité. Retourne None si aucun des deux champs n'est
    fourni (pas de mitigation renseignée)."""
    mitigation_status = answer.get("mitigation_status")
    if mitigation_status is not None:
        return mitigation_status

    legacy_mitigation = answer.get("mitigation")
    if legacy_mitigation == "OUI":
        return "OUI_PROUVEE"
    if legacy_mitigation == "NON":
        return "NON_INTENTION"
    return None


def _resolve_gain(question, answer):
    """Résout mitigation_status et gain pour une question dont la
    sous-question A est active (schéma standard : R=OUI ; B.3.1 (V4) :
    R=NON — cf. "a_condition" dans grid_questions.py).

    CHANTIER CC-V4-02 : factorisé pour être partagé par les deux schémas
    — avant la V4, B.3.1 n'avait pas de sous-question A séparée, donc pas
    besoin de partager ce code. Le garde-fou du statut 4 (CC-07,
    OUI_DEFAILLANTE exige double verbatim) reste inchangé, appliqué ici
    pour les deux schémas.
    """
    mitigation_status = _resolve_mitigation_status(answer)

    # GARDE-FOU statut 4 (CC-07) : OUI_DEFAILLANTE exige les DEUX
    # verbatims (preuve de la mesure ET preuve de la défaillance) — sans
    # ça, ce statut deviendrait une porte de sortie pour dégrader
    # n'importe quelle mitigation. Retombe silencieusement sur
    # OUI_PROUVEE ; ne modifie QUE le calcul, jamais la réponse d'entrée
    # (traçabilité — cf. answer["mitigation_status"] intact).
    if mitigation_status == "OUI_DEFAILLANTE":
        evidence = answer.get("evidence_a") or {}
        if not evidence.get("verbatim_mesure") or not evidence.get("verbatim_defaillance"):
            logger.warning(
                f"grid_scoring: statut 4 (OUI_DEFAILLANTE) sans double "
                f"verbatim pour {question['code']!r} — retour automatique en OUI_PROUVEE."
            )
            mitigation_status = "OUI_PROUVEE"

    gain = 0
    if mitigation_status in grid_questions.MITIGATION_STATUTS:
        multiplier = grid_questions.MITIGATION_STATUTS[mitigation_status]["points_multiplier"]
        gain = question["gain"] * multiplier

    return mitigation_status, gain


def _apply_shared_cap(details):
    """Plafond partagé V4 (directive CC-V4-02) : les questions d'un même
    grid_questions.py::shared_cap_group (A.1.1/A.1.3 pour l'instant)
    partagent un plafond de pénalité combiné à SHARED_CAP_PENALTY (-25)
    au lieu de cumuler -25 par question — même famille de risque
    (interruption d'activité subie par le projet).

    CHOIX: version simple — si plusieurs questions du même groupe sont
    pénalisées (OUI), seule la première (ordre de grid_questions.QUESTIONS)
    garde sa pénalité, les suivantes sont ramenées à 0. Modifie `details`
    en place (les dicts sont partagés avec compute_grid_score) et retourne
    la pénalité totale RETIRÉE (positive), à soustraire de total_penalty.
    N'affecte QUE la pénalité — le gain de mitigation de chaque question
    reste individuel, non plafonné par ce mécanisme.
    """
    groups = {}
    for detail in details:
        question = grid_questions.get_question(detail["code"])
        group = question.get("shared_cap_group")
        if group and detail["penalty"] < 0:
            groups.setdefault(group, []).append(detail)

    penalty_removed = 0
    for group_details in groups.values():
        if len(group_details) <= 1:
            continue
        for detail in group_details[1:]:
            penalty_removed += -detail["penalty"]
            detail["penalty"] = 0
            detail["_shared_cap_applied"] = True

    return penalty_removed


def _apply_b21_b22_lock(answers):
    """Verrou logique B.2.1 -> B.2.2 (passe CBG, CC-08).
    CHOIX: si B.2.1 (absence de suivi des rejets) = OUI, alors B.2.2
    (dépassement de seuils) ne peut pas être conclu à NON par simple
    absence de mention — sans mesure, aucune conclusion sur un
    dépassement n'est possible. Sans ce verrou, ne pas mesurer deviendrait
    plus avantageux que mesurer (un B.2.2=NON "propre" par silence
    paraîtrait meilleur qu'un B.2.2=OUI avéré, alors que l'opacité sur
    B.2.1 devrait plutôt inspirer MOINS de confiance).
    Ne s'applique QUE si B.2.2 était répondu NON — un B.2.2=OUI reste OUI
    (le risque est documenté malgré l'opacité sur B.2.1) ; un B.2.2=NA ou
    déjà INCONNU n'a pas besoin d'être forcé.
    SEUIL: verrou unique pour l'instant, codé en dur pour cette seule
    paire de questions — si d'autres dépendances inter-questions
    s'avèrent nécessaires (Mundra ?), généraliser en table de
    dépendances plutôt que multiplier les cas particuliers ad hoc.
    Ne mute PAS `answers` (traçabilité, même principe que le garde-fou du
    statut 4 en CC-07) — retourne simplement si le verrou s'applique ;
    c'est compute_grid_score() qui utilise ce résultat pour calculer avec
    un statut local corrigé, sans toucher à la réponse d'entrée.
    """
    b21 = answers.get("B.2.1") or {}
    b22 = answers.get("B.2.2") or {}
    return b21.get("status") == "OUI" and b22.get("status") == "NON"


def compute_grid_score(answers, document_type=1):
    """Calcule le score V4 à partir des réponses aux 12 questions.

    CHOIX: le score reste sur base 100 même si des questions sont N/A.
    SEUIL: si Elisa décide de normaliser (score / questions_actives), modifier ici.
    ALT: normalisation possible → score = max(0, base_proportionnelle - pénalités + gains)

    answers : dict {code: {"status": "OUI"|"NON"|"NA"|"INCONNU",
                            "mitigation_status": une clé de
                                grid_questions.MITIGATION_STATUTS ou None,
                            "evidence_a": {"verbatim_mesure": str,
                                           "verbatim_defaillance": str} ou
                                           absent — requis seulement pour
                                           vérifier le garde-fou du statut
                                           OUI_DEFAILLANTE}}
    Rétro-compatibilité (CC-02) : "mitigation": "OUI"/"NON" reste accepté à
    la place de "mitigation_status" (converti automatiquement, cf.
    _resolve_mitigation_status) — ne pas supprimer ce repli.

    document_type : int, clé de grid_questions.DOCUMENT_TYPES (R11, V4).
    CHOIX V4: conditionne le mode de lecture affiché (reading_mode /
    reading_mode_label dans le résultat) — c'est le LLM/l'analyste qui
    tient compte du type de document en amont pour choisir le statut de
    mitigation (le type 1, instruction, admet une 4ème forme de preuve :
    plan budgété et calendé). Ce module applique le statut reçu tel
    quel, quel que soit document_type — PAS de branche document_type
    dans le calcul du score lui-même (cf. directive CC-V4-02).

    CC-08 : "INCONNU" est un statut à part entière (silence sur une
    question d'état/système, cf. grid_questions.SILENCE_VALUES) — scoré
    comme NON (0 pénalité, 0 gain) mais jamais réécrit en NON dans le
    détail retourné. Le verrou B.2.1->B.2.2 (cf. _apply_b21_b22_lock) peut
    forcer B.2.2 à INCONNU pour le calcul même si `answers["B.2.2"]`
    contient "NON" — sans modifier `answers` lui-même.

    CC-V4-02 : A.1.1/A.1.3 partagent un plafond de pénalité combiné à -25
    (cf. _apply_shared_cap) ; B.3.1 a désormais une sous-question A
    active quand R=NON (a_condition="r_non", cf. _resolve_gain) ; score
    == 0 -> result["saturation"] = True ("ROUGE — Éliminatoire").

    Retourne : dict avec score, détail des pénalités/gains, metadata
    """
    _validate_answers(answers)

    details = []
    total_penalty = 0
    total_gain = 0
    questions_active = 0
    questions_na = 0

    b21_b22_lock = _apply_b21_b22_lock(answers)

    for question in grid_questions.QUESTIONS:
        code = question["code"]
        answer = answers[code]
        status = answer.get("status")
        verrou_applique = False

        if code == "B.2.2" and b21_b22_lock:
            logger.warning(
                "grid_scoring: verrou B.2.1→B.2.2 — B.2.2 forcé à INCONNU "
                "(pas de mesure documentée sur B.2.1 = pas de conclusion possible sur B.2.2)."
            )
            status = "INCONNU"
            verrou_applique = True

        penalty = 0
        gain = 0
        mitigation_status = None

        if status == "NA":
            questions_na += 1
        else:
            questions_active += 1
            a_condition = question.get("a_condition", "r_oui")

            if a_condition == "r_non":
                # Schéma inversé (B.3.1, V4) : NON = risque, OUI = favorable.
                # La sous-question A s'active QUAND R=NON (pas R=OUI comme
                # le schéma standard) — cf. directive CC-V4-02.
                if status == "NON":
                    penalty = question["penalty"]
                    mitigation_status, gain = _resolve_gain(question, answer)
            else:
                # Schéma standard : OUI = risque ; NON = 0 pénalité, 0 gain,
                # mitigation ignorée même si fournie par erreur.
                if status == "OUI":
                    penalty = question["penalty"]
                    mitigation_status, gain = _resolve_gain(question, answer)

        total_penalty += penalty
        total_gain += gain

        details.append({
            "code": code,
            "status": status,
            "penalty": penalty,
            "gain": gain,
            "mitigation_status": mitigation_status,
            "verrou_applique": verrou_applique,
        })

    # --- Plafond partagé V4 (A.1.1/A.1.3, directive CC-V4-02) ---
    total_penalty += _apply_shared_cap(details)

    total_gain_capped = min(total_gain, MITIGATION_CAP)
    cap_applied = total_gain > MITIGATION_CAP
    if cap_applied:
        logger.info(
            f"grid_scoring: plafond d'atténuation atteint "
            f"({total_gain} pts bruts -> {MITIGATION_CAP} pts retenus)."
        )

    score = max(0, BASE_SCORE + total_penalty + total_gain_capped)

    document_type_meta = grid_questions.DOCUMENT_TYPES[document_type]

    return {
        "score": score,
        "color": get_color(score),
        "saturation": score == 0,
        "total_penalty": total_penalty,
        "total_gain": total_gain,
        "total_gain_capped": total_gain_capped,
        "cap_applied": cap_applied,
        "questions_active": questions_active,
        "questions_na": questions_na,
        "details": details,
        "document_type": document_type,
        "reading_mode": document_type_meta["reading_mode"],
        "reading_mode_label": document_type_meta["label"],
    }
