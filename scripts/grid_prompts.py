"""
GRILLE ESG V4 — prompts LLM, architecture 2 passes + JSON (directive CC-V4-12)
=============================================================
RÉÉCRITURE COMPLÈTE de l'architecture à appel unique / texte libre
(CC-V4-05 à CC-V4-11, récupérable dans l'historique git — commit 3fbf8b5
et antérieurs). Cause racine du sur-score constaté sur 3 dossiers (Aysha
100 au lieu de 73, Mundra 40 au lieu de 16, CBG 85 au lieu de 28-31) :
un appel unique empilait 5+ règles éliminatoires (R2/R5/R7/R10/R11) et le
LLM trouvait toujours une raison de dire NON avant d'avoir fini de lire
les règles suivantes.

4 changements structurels (CC-V4-12) :
  A. Sortie JSON forcée (plus de texte libre ligne par ligne) — cf.
     llm_backend.call_llm(response_format="json") et _parse_llm_json().
  B. Deux appels séquentiels par question : Passe 1 EXTRACTION (le texte
     parle-t-il du sujet ? pas de jugement R2/R10 approfondi) puis, SI
     found=true, Passe 2 QUALIFICATION (OUI/NON + mitigation, sur le
     verbatim extrait en Passe 1 seulement). R5 (silence) devient
     déterministe côté Python — cf. grid_analyze._silence_status — le LLM
     n'est plus consulté du tout si found=false.
  C. Polarité inversée : les prompts listent d'abord CE QUI COMPTE
     (raisons de dire OUI), CE QUI NE COMPTE PAS ensuite.
  D. Few-shot OUI/NON par question (FEW_SHOTS), tirés des 4 dossiers
     annotés (CBG, Mundra, Aysha, Indorama) — aucun exemple inventé.

Ce module construit des strings et en parse d'autres — il n'appelle
JAMAIS le LLM lui-même (invariant hérité, inchangé).

RÉORGANISATION DES RÈGLES (pas de suppression, cf. "Ce qu'il ne faut PAS
faire" de la directive) — chaque règle historique (R1/R2/R5/R7/R7bis/R8/
R9/R10/R11) est réaffectée à la passe où elle a le plus de sens :
  - R1 (biais faux positifs)      -> implicite dans "CHERCHE"/"RÉPONDS OUI
    si..." (polarité C) des deux passes, plus de mention explicite isolée
    nécessaire — c'est tout l'objet de la réorganisation C.
  - R2 (matérialisation)          -> Passe 1 (EXTRACTION) : "CE QUI COMPTE
    COMME CORRESPONDANCE" / "CE QUI NE COMPTE PAS", conditionné au
    reading_mode (repris de _MATERIALISATION_INSTRUCTION/_SUIVI, CC-V4-11).
  - R5 (silence)                  -> déterministe Python entre les passes
    (grid_analyze.py), plus jamais un jugement LLM. cf. décision ci-dessous.
  - R7/R3 (mitigation 2 portes, 4 statuts) -> Passe 2 (QUALIFICATION).
  - R7bis (ESAP jamais mitigant)  -> les deux passes : un item ESAP DOIT
    être trouvé en Passe 1 (found=true — c'est un fait pertinent pour le
    risque, cf. grid_analyze.py historique "un item ESAP renseigne le
    risque") mais ne peut JAMAIS être crédité comme mitigation en Passe 2.
    ÉCART VOLONTAIRE PAR RAPPORT À LA DIRECTIVE : l'exemple de prompt
    d'extraction fourni listait "un item d'ESAP" dans "CE QUI NE COMPTE
    PAS" — appliqué littéralement, ça aurait fait disparaître le
    déclencheur de risque que R7bis (CC-09/CC-V4-04) a spécifiquement
    corrigé. Gardé comme trouvaille valide côté risque, exclu seulement
    côté mitigation (ce que R7bis a toujours voulu dire).
  - R8 (couches temporelles, Type 3) -> Passe 1 (quel verbatim appartient
    à la bonne période, avant même de juger le fond).
  - R9 (hiérarchie des sources, Types 2-3) -> Passe 2 (une déclaration
    client contredite par un auditeur ne peut jamais servir de mitigation
    — c'est un jugement sur la CRÉDIBILITÉ d'une preuve de mitigation).
  - R10 (filtre de sujet)         -> Passe 1 (champ `subject` de
    l'extraction) ; Passe 2 consomme `subject` en entrée, ne le
    réévalue pas. ÉCART VOLONTAIRE : le schéma JSON donné dans la
    directive ne prévoyait que 3 valeurs (SPV/LENDER/AMBIGUOUS) — étendu
    aux 5 catégories déjà validées et testées (CC-V4-05/CC-V4-09) :
    SPV/LENDER/SUBSTITUTION/AMBIGUOUS/INDIRECT. Réduire à 3 aurait fait
    régresser la distinction SUBSTITUTION (verbatim de remplacement
    trouvé sur la SPV) et INDIRECT (réaction d'un tiers, non imputable),
    toutes deux ajoutées par des directives dédiées antérieures.
  - R11 (formes de preuve selon document_type) -> Passe 2 (Porte 2 de la
    mitigation), via {proof_forms_rule} — inchangé dans le fond.

DÉCISION R5 (silence) — PAS le mécanisme binaire donné littéralement par
la directive (`_SILENCE_MEANS_RISK = {"B.3.1", "B.3.2"}` sinon NON) :
appliqué tel quel, ce mécanisme aurait fait perdre la distinction
INCONNU/NON déjà validée (CC-08) pour B.2.1/B.2.2 (silence sur un
dépassement de seuil = "on ne sait pas", pas "pas de risque" — sans quoi
NE PAS MESURER redeviendrait plus avantageux que mesurer, cf.
grid_scoring._apply_b21_b22_lock, verrou construit exactement pour ça).
Le besoin réel de la directive (B.3.1/B.3.2 : le silence CONFIRME
l'absence que la question demande, donc OUI direct) est un cas
particulier au-dessus du mécanisme existant, pas un remplacement complet
— cf. grid_analyze._SILENCE_CONFIRMS_ABSENCE, qui garde silence_type
(evenement/etat) comme défaut et ne fait dévier que B.3.1/B.3.2 vers OUI.
"""

import json
import logging
import re

import grid_questions

logger = logging.getLogger(__name__)

# ============================================================================
# Règles dynamiques selon le type de document (R2/R8/R9/R11) — reprises
# telles quelles de l'architecture précédente, contenu inchangé, seul le
# point d'injection change (répartition Passe 1 / Passe 2 ci-dessus).
# ============================================================================

_PROOF_FORMS_INSTRUCTION = """Trois formes admises + UNE QUATRIÈME sur document d'instruction :
- accord formel signé
- investissement matériel réceptionné
- vérification par un tiers indépendant
- [TYPE 1 UNIQUEMENT] plan détaillé, budgété et calendé, produit par un tiers qualifié → statut 3"""

_PROOF_FORMS_SUIVI = """Trois formes admises, aucune autre :
- accord formel signé
- investissement matériel réceptionné
- vérification par un tiers indépendant
Un plan seul reste au statut 2, même budgété."""

_TEMPORAL_RULE_TYPE3 = """COUCHES TEMPORELLES (document Type 3) — étiqueter le verbatim avant de répondre :
- Couche 1 — résumé antérieur : contexte, faits avant la période auditée. NE COMPTE PAS.
- Couche 2 — période auditée : SEULE couche qui compte.
- Couche 3 — observation postérieure : mission terrain récente. NE COMPTE PAS.
ATTENTION : les rapports CAO résument souvent des manifestations historiques. Vérifier la couche temporelle avant de répondre found=true."""

_TEMPORAL_RULE_OTHER = ""  # Pas de règle temporelle pour Type 1, 2, 4

_HIERARCHY_RULE_TYPE23 = """HIÉRARCHIE DES SOURCES (pour juger une preuve de mitigation) :
1. Constat de l'auditeur indépendant (CAO, panel, expert tiers)
2. Observation directe en visite de terrain
3. Donnée chiffrée fournie par un tiers (labo, régulateur)
4. Témoignage de plaignant
5. Déclaration non étayée du client
RÈGLE : une déclaration client contredite par un constat d'auditeur dans le même document ne peut JAMAIS servir de mitigation (statut NON_FORME_INSUFFISANTE au mieux)."""

_HIERARCHY_RULE_OTHER = ""

# --- Matérialisation (R2), conditionnelle au reading_mode (CC-V4-11,
# reprise telle quelle — contenu déjà validé, seule la destination change :
# Passe 1 au lieu d'un bloc de règles dans l'appel unique) ---
_MATERIALISATION_INSTRUCTION = """EN MODE INSTRUCTION (due diligence pré-closing) :
- Un fait passé documenté (déplacement, pollution, plainte)
- Un état existant constaté (airshed dégradé, absence de baseline)
- Un legacy issue non résolu (griefs historiques non compensés)
- Un écart de conformité constaté par le consultant
- Une condition non remplie documentée dans l'ESRS/ESIA"""

_MATERIALISATION_SUIVI = """EN MODE SUIVI (monitoring rétrospectif) :
- Un fait daté survenu durant la période de monitoring
- Un constat de terrain de l'auditeur
- Une mesure défaillante documentée"""

# --- R10, filtre de sujet — 5 catégories (SPV/LENDER/SUBSTITUTION/
# AMBIGUOUS/INDIRECT), cf. docstring du module pour la justification de
# l'extension par rapport aux 3 valeurs de l'exemple de la directive. ---
_SUBJECT_RULE = """IDENTIFIER LE SUJET (qui est visé par le passage ?) :
- SPV : société de projet, sponsor, contractants, installation — le manquement est imputable au projet.
- LENDER : institution financière, auditeur, mécanisme de recours (ex. plainte visant l'IFC/la SFI, pas la SPV).
- SUBSTITUTION : le passage principal vise le prêteur, MAIS un autre passage des PASSAGES DU RAPPORT documente le même fait avec le CLIENT/la SPV pour sujet — dans ce cas, extraire CE second verbatim, sujet=SPV, pas LENDER.
- AMBIGUOUS : le passage ne permet pas de trancher avec certitude qui est visé.
- INDIRECT : le projet est concerné indirectement (réaction d'un tiers, contexte externe) mais aucun manquement n'est imputable à la SPV elle-même.
Ne JAMAIS résoudre une ambiguïté de sujet par défaut vers SPV — un doute sur QUI est visé n'est pas un doute sur CE QUI s'est passé."""

_VALID_SUBJECTS = ("SPV", "LENDER", "SUBSTITUTION", "AMBIGUOUS", "INDIRECT")

# ============================================================================
# Templates — Passe 1 (EXTRACTION)
# ============================================================================

_EXTRACTION_PROMPT = """Tu extrais des faits d'un rapport ESG pour une question de la grille d'évaluation.

QUESTION : {question_r}

TYPE DE DOCUMENT : {document_type_label}
MODE DE LECTURE : {reading_mode}

PASSAGES :
{context_chunks}

=== CE QUE TU CHERCHES ===

CHERCHE un passage qui correspond à la question. Voici ce qui COMPTE comme correspondance :

{materialisation_rule}

CE QUI NE COMPTE PAS (dans tous les modes) :
- Une vulnérabilité théorique sans constat factuel ("le projet pourrait...")
- Un plan futur non commencé ("sera développé", "to be prepared")
- Un scénario d'urgence hypothétique (plans d'urgence)

CAS PARTICULIER — ITEM D'ESAP (obligation à faire, pas encore remplie) :
Un item d'ESAP COMPTE quand même comme correspondance (found=true) — c'est un manquement documenté, pas une vulnérabilité théorique. Le signaler dans `brief` ("item ESAP"). Ce n'est JAMAIS une preuve de mitigation (tranché en Passe 2, pas ici).

{temporal_rule}

=== SUJET ===

{subject_rule}

{few_shot_extraction}

Réponds en français dans "brief" (justification), quelle que soit la langue du texte source. "verbatim" reste tel quel dans sa langue d'origine — c'est une citation exacte, jamais une traduction.

Réponds UNIQUEMENT en JSON valide, sans backticks markdown, sans texte avant ou après :
{{"code": "{code}", "found": true/false, "verbatim": "extrait exact du passage, copié tel quel, max 200 mots, ou null", "page": numéro ou null, "subject": "SPV/LENDER/SUBSTITUTION/AMBIGUOUS/INDIRECT ou null si found=false", "brief": "12 mots max expliquant pourquoi ce passage correspond, ou pourquoi rien ne correspond"}}
"""

# ============================================================================
# Templates — Passe 2 (QUALIFICATION)
# ============================================================================

_QUALIFICATION_PROMPT = """Tu qualifies un fait extrait d'un rapport ESG.

QUESTION DE RISQUE : {question_r}
QUESTION DE MITIGATION : {question_a}
MODE DE LECTURE : {reading_mode}
SUJET IDENTIFIÉ (Passe 1, ne pas réévaluer) : {subject}

VERBATIM EXTRAIT :
"{verbatim}"

=== DÉCISION SUR LE RISQUE (R) ===

RÉPONDS OUI si le verbatim décrit un fait qui correspond à la question ET dont le sujet est le projet (SPV) ou ses opérations — même si c'est un rapport du prêteur qui le documente. Un impact physique constaté par un rapport CAO reste un impact du PROJET.

RÉPONDS NON_ARGUMENTE (valeur JSON "NA_ARGUMENTE") si le verbatim indique EXPLICITEMENT que la norme/le standard ne s'applique pas à ce projet, avec un motif donné (ex. "PS5 non déclenchée, maîtrise foncière en zone franche") — distinct d'un NON simple : le texte argumente activement l'inapplicabilité, ce n'est pas juste l'absence de risque.

RÉPONDS NON si :
- Le sujet du manquement est LENDER (supervision IFC/prêteur), pas SPV/SUBSTITUTION.
- Le sujet est AMBIGUOUS ou INDIRECT (ne jamais attribuer par défaut à la SPV).
- Le verbatim décrit un fait d'une période antérieure déjà couvert (Type 3 uniquement).

{hierarchy_rule}

CAS PARTICULIER — retrait de bailleur (A.2.2) :
Un retrait documenté est un OUI même si c'est un fait passé. La question demande si ça s'est produit, pas si c'est un risque futur.

{few_shot_qualification}

=== SI OUI — DÉCISION SUR LA MITIGATION (A) ===

Cherche dans le verbatim une preuve de mitigation correspondant à : {question_a}

PORTE 1 — La mesure existe-t-elle (temps du verbe) ?
- Verbe accompli ("a été installé", "a été signé", "were processed and closed") → Porte 2.
- Verbe futur/conditionnel/infinitif d'obligation ("sera installé", "to be prepared") → NON_INTENTION, gain = 0.

PORTE 2 — La forme de preuve (si Porte 1 passée) :
{proof_forms_rule}
Un plan, une procédure, une politique, un recrutement, une formation, un engagement verbal = ÉCHEC → NON_FORME_INSUFFISANTE, gain = 0.

Si les deux portes passent :
- Aucune défaillance de CETTE MÊME mesure documentée dans le verbatim → OUI_PROUVEE.
- Le verbatim établit que CETTE MÊME mesure n'a pas produit son effet ou a été interrompue (pas une conjonction concessive isolée sans lien de cause démontré avec CETTE mesure) → OUI_DEFAILLANTE, en citant les DEUX passages (verbatim_a_mesure ET verbatim_a_defaillance, chacun portant sur la même mesure). Si le lien n'est pas explicite dans le texte, rester à OUI_PROUVEE.

Rappel R7bis : un item d'ESAP (obligation non encore remplie) n'est JAMAIS une preuve de mitigation, quelle que soit sa formulation.

Réponds en français dans "brief_r"/"brief_a" (justification), quelle que soit la langue du texte source. Les champs "verbatim_*" restent tels quels dans leur langue d'origine — ce sont des citations exactes, jamais des traductions.

Réponds UNIQUEMENT en JSON valide, sans backticks markdown, sans texte avant ou après :
{{"code": "{code}", "status": "OUI/NON/NA_ARGUMENTE", "confidence": "HIGH/LOW", "mitigation_status": "OUI_PROUVEE/OUI_DEFAILLANTE/NON_INTENTION/NON_FORME_INSUFFISANTE ou null si status != OUI", "verbatim_r": "extrait risque, ou vide", "verbatim_a_mesure": "extrait mesure de mitigation, ou vide", "verbatim_a_defaillance": "extrait défaillance si OUI_DEFAILLANTE, ou null", "brief_r": "10 mots max", "brief_a": "10 mots max, ou vide"}}
"""

# ============================================================================
# Few-shot par question — cas réels des 4 dossiers annotés (CBG, Mundra,
# Aysha, Indorama), 1 OUI + 1 NON max par question, None si aucun cas
# annoté (jamais d'exemple inventé, cf. "Ce qu'il ne faut PAS faire").
#
# 2 ÉCARTS VOLONTAIRES PAR RAPPORT À LA DIRECTIVE (mêmes principes que la
# correction déjà appliquée en CC-V4-11, cf. grid_questions.py) :
#   - B.1.2 : les exemples donnés (griefs CBG "31 grievances.../24
#     addressed", mécanisme Aysha) portent sur le MÉCANISME DE GRIEFS,
#     sujet de l'ancien B.1.2 (pré-Maquette-Vierge). Le B.1.2 actuel porte
#     sur le "Déplacement involontaire de populations non réinstallées"
#     — sujet différent, aucun des deux exemples n'y répond réellement.
#     Laissés à None plutôt que mal étiquetés.
#   - B.2.2 : les exemples donnés (airshed CBG, bruit nocturne Indorama)
#     portent sur la qualité de l'AIR, déjà couverts sous B.2.1 (qui les
#     a littéralement, "oui" CBG PM10/poussières). B.2.2 porte désormais
#     sur le "Défaut de modélisation du rejet thermique (Eau)" — aucun
#     des deux dossiers annotés ne documente un défaut de modélisation
#     thermique. Laissés à None plutôt que dupliqués sous le mauvais sujet.
# ============================================================================

FEW_SHOTS = {
    "A.1.1": {
        "oui": {
            "source": "Mundra (Type 3)",
            "verbatim": "Des blocages physiques du canal d'amenée ont été menés par les "
                        "pêcheurs de Tragadi bunder, arrêtant les transports sur le site.",
            "brief": "Blocage physique par les pêcheurs, transport arrêté",
        },
        "non": {
            "source": "Aysha (Type 1)",
            "verbatim": "The project does not entail physical resettlement. Stakeholder "
                        "engagement activities have been conducted since 2023.",
            "brief": "Pas de mention de blocage, engagement communautaire en cours",
        },
    },
    "A.1.2": {
        "oui": None,
        "non": {
            "source": "Mundra (Type 3)",
            "verbatim": "The legal proceedings in the D.C. District Court of Appeals "
                        "concluded in 2021.",
            "brief": "Litige contre IFC (prêteur), pas contre la SPV",
        },
    },
    "A.2.1": {
        "oui": None,
        "non": {
            "source": "CBG (Type 1)",
            "verbatim": "L'ESIA a été approuvée par l'autorité guinéenne (BGÉÉE) en mai 2015 "
                        "et le permis environnemental a été délivré en juin 2015.",
            "brief": "Permis délivré, pas de suspension",
        },
    },
    "A.2.2": {
        "oui": {
            "source": "Mundra (Type 3)",
            "verbatim": "The client completed loan prepayments to IFC in 2018, ending the "
                        "financial relationship.",
            "brief": "IFC retirée en 2018, fait documenté = OUI",
        },
        "non": {
            "source": "Aysha (Type 1)",
            "verbatim": "IFC and AfDB are mandated lead arrangers.",
            "brief": "Bailleurs en place, aucun retrait",
        },
    },
    "A.3.1": {
        "oui": None,
        "non": {
            "source": "CBG (Type 1)",
            "verbatim": "The project has been in continuous operation since 1973.",
            "brief": "Aucune injonction d'arrêt mentionnée",
        },
    },
    "A.3.2": {
        "oui": None,
        "non": {
            "source": "Mundra (Type 3)",
            "verbatim": "Aucun accident structurel ou rupture d'ouvrage signalé.",
            "brief": "Silence explicite sur les accidents",
        },
    },
    "B.1.1": {
        "oui": {
            "source": "Aysha (Type 1)",
            "verbatim": "Economic displacement affects 909 persons, seasonal residents, "
                        "across 1,521 hectares. A Livelihood Restoration Plan is being finalized.",
            "brief": "Déplacement éco documenté, LRP pas encore en place = sans compensation",
        },
        "non": {
            "source": "Indorama (Type 1)",
            "verbatim": "PS5 is not triggered. The project site is within the Indorama Free "
                        "Zone with established land tenure.",
            "brief": "PS5 non déclenchée, maîtrise foncière établie = NA_ARGUMENTE",
        },
    },
    "B.1.2": {"oui": None, "non": None},  # cf. docstring module — sujet non couvert par les 4 dossiers
    "B.2.1": {
        "oui": {
            "source": "Mundra (Type 3)",
            "verbatim": "Repeated exceedances of PM10 standards were recorded at other site locations.",
            "brief": "Dépassements PM10 récurrents, fait daté",
        },
        "non": {
            "source": "Aysha (Type 1)",
            "verbatim": "Le projet est un parc éolien sans émissions atmosphériques industrielles.",
            "brief": "Pas de source de PM10, question non pertinente",
        },
    },
    "B.2.2": {"oui": None, "non": None},  # cf. docstring module — sujet non couvert par les 4 dossiers
    "B.3.1": {
        "oui": {
            "source": "Aysha (Type 1)",
            "verbatim": "Le rapport décrit les zones de peuplement mais ne fournit aucune "
                        "donnée chiffrée de référence socio-économique.",
            "brief": "Pas de baseline chiffrée = absence = OUI",
        },
        "non": {
            "source": "Indorama (Type 1)",
            "verbatim": "Baseline environmental and social conditions documented across 12 parameters.",
            "brief": "Baseline complète documentée",
        },
    },
    "B.3.2": {
        "oui": {
            "source": "Mundra (Type 3)",
            "verbatim": "The client later informed CRP that it was not prepared to carry out "
                        "additional monitoring or share monitoring data.",
            "brief": "Refus de suivi et de partage de données = absence de suivi RSE périodique",
        },
        "non": {
            "source": "Mundra (Type 3)",
            "verbatim": "Rapports de suivi transmis annuellement au prêteur.",
            "brief": "Reporting annuel en place",
        },
    },
}


def _format_few_shot_extraction(code):
    fs = FEW_SHOTS.get(code, {})
    parts = []
    if fs.get("oui"):
        parts.append(
            f"EXEMPLE OUI ({fs['oui']['source']}) :\n"
            f'Passage : "{fs["oui"]["verbatim"]}"\n'
            f"→ found=true. {fs['oui']['brief']}"
        )
    if fs.get("non"):
        parts.append(
            f"EXEMPLE NON ({fs['non']['source']}) :\n"
            f'Passage : "{fs["non"]["verbatim"]}"\n'
            f"→ found=false. {fs['non']['brief']}"
        )
    if not parts:
        return ""
    return "=== EXEMPLES DE RÉFÉRENCE ===\n\n" + "\n\n".join(parts)


def _format_few_shot_qualification(code):
    # CHOIX: mêmes exemples que l'extraction (mêmes verbatims des 4
    # dossiers), reformulés en décision status OUI/NON — pas un second jeu
    # de données à maintenir séparément.
    fs = FEW_SHOTS.get(code, {})
    parts = []
    if fs.get("oui"):
        parts.append(
            f"EXEMPLE OUI ({fs['oui']['source']}) :\n"
            f'Verbatim : "{fs["oui"]["verbatim"]}"\n'
            f"→ status=OUI. {fs['oui']['brief']}"
        )
    if fs.get("non"):
        parts.append(
            f"EXEMPLE NON ({fs['non']['source']}) :\n"
            f'Verbatim : "{fs["non"]["verbatim"]}"\n'
            f"→ status=NON (ou NA_ARGUMENTE si motif explicite). {fs['non']['brief']}"
        )
    if not parts:
        return ""
    return "=== EXEMPLES DE RÉFÉRENCE ===\n\n" + "\n\n".join(parts)


def get_extraction_prompt(question_code, context_chunks, document_type=1):
    """Assemble le prompt de Passe 1 (EXTRACTION) pour une question donnée.

    CHOIX (CC-V4-12) : document_type conditionne la matérialisation (R2,
    instruction/suivi) et les couches temporelles (R8, Type 3 seulement).
    Ne demande AUCUN jugement R5 (silence, déterministe côté Python) ni R7
    (mitigation, Passe 2 seulement).

    Retourne None si question_code est inconnu (pas d'exception — même
    contrat que l'architecture précédente).
    """
    question = grid_questions.get_question(question_code)
    if question is None:
        return None

    doc_info = grid_questions.DOCUMENT_TYPES.get(document_type, grid_questions.DOCUMENT_TYPES[1])
    materialisation_rule = (
        _MATERIALISATION_INSTRUCTION if doc_info["reading_mode"] == "instruction" else _MATERIALISATION_SUIVI
    )
    temporal = _TEMPORAL_RULE_TYPE3 if document_type == 3 else _TEMPORAL_RULE_OTHER
    context = "\n---\n".join(context_chunks) if context_chunks else "(aucun passage fourni)"

    return _EXTRACTION_PROMPT.format(
        code=question_code,
        question_r=question["question_r"],
        document_type_label=doc_info["label"],
        reading_mode=doc_info["reading_mode"],
        context_chunks=context,
        materialisation_rule=materialisation_rule,
        temporal_rule=temporal,
        subject_rule=_SUBJECT_RULE,
        few_shot_extraction=_format_few_shot_extraction(question_code),
    )


def get_qualification_prompt(question_code, verbatim, subject, document_type=1):
    """Assemble le prompt de Passe 2 (QUALIFICATION) pour une question et un
    verbatim déjà extraits en Passe 1.

    verbatim : le passage extrait par la Passe 1 (found=true) — la
    Passe 2 ne voit JAMAIS les passages bruts du document, uniquement ce
    verbatim, cf. docstring module ("SUR le verbatim extrait en Passe 1").
    subject : la valeur `subject` de la Passe 1, consommée telle quelle,
    jamais réévaluée ici (cf. _SUBJECT_RULE).

    Retourne None si question_code est inconnu.
    """
    question = grid_questions.get_question(question_code)
    if question is None:
        return None

    doc_info = grid_questions.DOCUMENT_TYPES.get(document_type, grid_questions.DOCUMENT_TYPES[1])
    proof_rule = _PROOF_FORMS_INSTRUCTION if doc_info["reading_mode"] == "instruction" else _PROOF_FORMS_SUIVI
    hierarchy = _HIERARCHY_RULE_TYPE23 if document_type in (2, 3) else _HIERARCHY_RULE_OTHER

    return _QUALIFICATION_PROMPT.format(
        code=question_code,
        question_r=question["question_r"],
        question_a=question["question_a"],
        reading_mode=doc_info["reading_mode"],
        subject=subject or "AMBIGUOUS",
        verbatim=verbatim or "",
        hierarchy_rule=hierarchy,
        proof_forms_rule=proof_rule,
        few_shot_qualification=_format_few_shot_qualification(question_code),
    )


# ============================================================================
# Parsing JSON (CC-V4-12)
# ============================================================================

# FRAGILE: le LLM peut wrapper le JSON dans ```json...``` ou ajouter du
# texte avant/après malgré la consigne "sans backticks, sans texte" —
# tolérant sur le format, strict sur les clés (cf. directive, section E).
_BACKTICK_FENCE_RE = re.compile(r"```(?:json)?\s*|```\s*", re.IGNORECASE)


def _parse_llm_json(raw_text, expected_keys=None):
    """Parse un JSON retourné par le LLM, avec nettoyage tolérant.

    Retourne un dict (avec `expected_keys` manquantes complétées à None),
    ou None si aucun JSON exploitable n'a pu être extrait.
    """
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
        logger.warning("grid_prompts: JSON invalide après nettoyage — parsing échoué.")
        return None

    if not isinstance(parsed, dict):
        return None

    if expected_keys:
        for key in expected_keys:
            parsed.setdefault(key, None)

    return parsed


_EXTRACTION_KEYS = ("code", "found", "verbatim", "page", "subject", "brief")
_QUALIFICATION_KEYS = (
    "code", "status", "confidence", "mitigation_status",
    "verbatim_r", "verbatim_a_mesure", "verbatim_a_defaillance", "brief_r", "brief_a",
)

_VALID_QUALIFICATION_STATUSES = ("OUI", "NON", "NA_ARGUMENTE")


def parse_extraction_response(raw_response):
    """Parse la réponse JSON de la Passe 1 (EXTRACTION).

    Retourne un dict {found: bool, verbatim: str|None, page: str|None,
    subject: str|None, brief: str|None}, ou None si le JSON est
    inexploitable (found manquant/non-booléen).
    """
    parsed = _parse_llm_json(raw_response, expected_keys=_EXTRACTION_KEYS)
    if parsed is None:
        return None

    found = parsed.get("found")
    if not isinstance(found, bool):
        # Tolérance : certains modèles renvoient "true"/"false" en string.
        if isinstance(found, str) and found.strip().lower() in ("true", "false"):
            found = found.strip().lower() == "true"
        else:
            logger.warning("grid_prompts: champ 'found' absent ou invalide — parsing échoué.")
            return None

    subject = parsed.get("subject")
    # R10 : repli sûr sur AMBIGUOUS, JAMAIS SPV (cf. docstring module —
    # correction volontaire par rapport à l'ancien repli SPV de
    # l'architecture précédente, contraire au principe R10 lui-même).
    if subject not in _VALID_SUBJECTS:
        subject = "AMBIGUOUS" if found else None

    return {
        "found": found,
        "verbatim": (parsed.get("verbatim") or "").strip() or None,
        "page": parsed.get("page"),
        "subject": subject,
        "brief": (parsed.get("brief") or "").strip() or None,
    }


def parse_qualification_response(raw_response):
    """Parse la réponse JSON de la Passe 2 (QUALIFICATION).

    Retourne un dict {status, confidence, mitigation_status, verbatim_r,
    verbatim_a_mesure, verbatim_a_defaillance, brief_r, brief_a}, ou None
    si le JSON est inexploitable (status manquant/invalide).
    """
    parsed = _parse_llm_json(raw_response, expected_keys=_QUALIFICATION_KEYS)
    if parsed is None:
        return None

    status = (parsed.get("status") or "").strip().upper()
    if status not in _VALID_QUALIFICATION_STATUSES:
        logger.warning("grid_prompts: champ 'status' absent ou invalide (%r) — parsing échoué.", status)
        return None

    mitigation_status = (parsed.get("mitigation_status") or "").strip().upper() or None
    if mitigation_status not in grid_questions.MITIGATION_STATUTS:
        mitigation_status = None

    confidence = (parsed.get("confidence") or "").strip().upper()
    if confidence not in ("HIGH", "LOW"):
        confidence = "LOW"  # repli prudent : un champ mal formé ne doit pas se faire passer pour HIGH

    return {
        "status": status,
        "confidence": confidence,
        "mitigation_status": mitigation_status,
        "verbatim_r": (parsed.get("verbatim_r") or "").strip() or None,
        "verbatim_a_mesure": (parsed.get("verbatim_a_mesure") or "").strip() or None,
        "verbatim_a_defaillance": (parsed.get("verbatim_a_defaillance") or "").strip() or None,
        "brief_r": (parsed.get("brief_r") or "").strip() or None,
        "brief_a": (parsed.get("brief_a") or "").strip() or None,
    }


# ============================================================================
# SYNTHÈSE FINALE (post-scoring, un seul appel/dossier, texte libre)
# ============================================================================
# Directive "évolutions pipeline ESG/risk" (2026-08-20) : dernière étape du
# pipeline, APRÈS grid_scoring.compute_grid_score() — reçoit le résultat
# déjà assemblé (grid_result.build_grid_result), n'appelle JAMAIS le LLM
# pendant l'extraction/le scoring eux-mêmes (inchangés). Réutilise
# llm_backend.call_llm() tel quel (response_format=None, texte libre —
# contrairement à l'extraction/qualification JSON ci-dessus) et le
# config_key "deep_synthesize" déjà calibré pour une tâche identique
# (3-5 phrases de synthèse en français, cf. deep_analysis.run_pass3 /
# config.OLLAMA_CONFIGS) — pas de nouvelle clé de config.
#
# CHOIX: seules les questions OUI/INCONNU sont envoyées au LLM (jamais les
# NON/NA, ni les chunks bruts du rapport) — budget indicatif ~2000 tokens
# en entrée (cf. directive, section "Coût / taille du contexte"), verbatims
# tronqués à 300 caractères. Un NON n'a rien à contribuer à une synthèse de
# risque (par construction, un NON = absence établie, hors sujet), un
# INCONNU y contribue explicitement car "INCONNU ne signifie jamais NON"
# est la règle la plus facile à violer par un LLM qui n'a jamais vu la
# distinction posée noir sur blanc.

_SYNTHESIS_PROMPT = """Tu es un analyste risque chargé de rédiger une synthèse concise d'un dossier ESG.

Tu dois UNIQUEMENT utiliser les informations fournies ci-dessous. N'invente aucune information, ne déduis jamais une absence de risque à partir de l'absence de données, et ne cherche pas à compléter ce qui manque.

Un critère OUI correspond à un risque ou sujet identifié et documenté par les éléments fournis.
Un critère NON correspond à une absence de risque explicitement établie par le rapport (non listés ci-dessous, {n_non} au total sur les 12 critères de la grille — hors sujet pour cette synthèse).
Un critère INCONNU signifie que le rapport ne contient pas suffisamment d'informations pour conclure. INCONNU NE SIGNIFIE JAMAIS NON : si aucun élément n'a été trouvé pour un critère INCONNU, ne cherche pas à déduire une conclusion, indique simplement qu'aucun élément n'a été trouvé si ce point est pertinent pour la synthèse.

=== CONTEXTE DU DOSSIER ===
{context_block}

=== SCORE FINAL ===
{score}/100 - {color}

=== RISQUES IDENTIFIÉS (OUI) ===
{oui_block}

=== POINTS NON DOCUMENTÉS (INCONNU) ===
{inconnu_block}

Rédige une synthèse de 3 à 5 phrases MAXIMUM, en français, destinée à un analyste risque ou à un comité de crédit qui ne connaît pas nécessairement les codes de la grille.

Mets en avant les risques réellement identifiés, leur importance et les principaux éléments expliquant le score. Traduis les codes techniques de la grille en langage métier compréhensible — ne cite pas inutilement les codes de critères sauf lorsqu'ils apportent une vraie valeur. Mentionne les points importants encore INCONNU lorsque c'est pertinent, sans jamais les présenter comme une absence de risque établie. Si aucun risque bloquant majeur n'est identifié, indique-le clairement.

Retourne UNIQUEMENT la synthèse finale, sans titre, sans markdown et sans commentaire sur ton raisonnement."""


def _truncate_for_synthesis(text, max_len=300):
    """Tronque un verbatim avant de l'envoyer au LLM de synthèse — même
    esprit que export._truncate (colonnes PDF), mais ici pour maîtriser le
    budget d'entrée (~2000 tokens indicatif, cf. directive), pas une
    largeur de cellule."""
    text = str(text or "")
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def _format_context_for_synthesis(context):
    """context : dict|None — les 4 champs manuels (BLOC D, CC-V4-11).
    Simple mise en forme, jamais relu par le score (comme partout
    ailleurs où `context` transite)."""
    if not context:
        return "(non renseigné)"
    parts = []
    if context.get("ep_classification"):
        parts.append(f"Classification EP : {context['ep_classification']}")
    if context.get("sensitivity"):
        parts.append(f"Sensibilité : {context['sensitivity']}")
    if context.get("financing_amount"):
        parts.append(f"Montant du financement : {context['financing_amount']}")
    if context.get("cacib_role"):
        parts.append(f"Rôle dans le deal : {context['cacib_role']}")
    return " | ".join(parts) if parts else "(non renseigné)"


def _format_oui_block(questions):
    oui = [q for q in questions if q["status"] == "OUI"]
    if not oui:
        return "Aucun."
    lines = []
    for q in oui:
        ev_r = q.get("evidence_r")
        verbatim = _truncate_for_synthesis(ev_r["passage"]) if ev_r and ev_r.get("passage") else None
        mit_label = q.get("mitigation_label")
        line = f"- [{q['code']}] {q['sous_theme']} — {q['question_r']}"
        if verbatim:
            line += f'\n  Verbatim : "{verbatim}"'
        if mit_label:
            line += f"\n  Mitigation : {mit_label}"
        lines.append(line)
    return "\n".join(lines)


def _format_inconnu_block(questions):
    """CHOIX: distinct de _format_oui_block — n'affiche JAMAIS de
    "conclusion" sur un INCONNU, seulement le sujet (code + intitulé) et,
    s'il existe (cas du verrou B.2.1->B.2.2, où un verbatim peut exister
    malgré le statut INCONNU forcé par le score, cf. grid_scoring.py), un
    élément jugé insuffisant pour conclure — jamais présenté comme une
    absence de risque. Sinon, texte canonique "Aucun élément n'a été
    trouvé." (même texte que grid_analyze._silence_fallback, cf. sa
    docstring — cohérence UI/export/synthèse sur la même formulation)."""
    inconnu = [q for q in questions if q["status"] == "INCONNU"]
    if not inconnu:
        return "Aucun."
    lines = []
    for q in inconnu:
        ev_r = q.get("evidence_r")
        verbatim = _truncate_for_synthesis(ev_r["passage"]) if ev_r and ev_r.get("passage") else None
        line = f"- [{q['code']}] {q['sous_theme']} — {q['question_r']}"
        if verbatim:
            line += f'\n  Élément trouvé, insuffisant pour conclure : "{verbatim}"'
        else:
            line += "\n  Aucun élément n'a été trouvé."
        lines.append(line)
    return "\n".join(lines)


def get_synthesis_prompt(result):
    """Assemble le prompt de la passe de synthèse finale (post-scoring).

    `result` : dict déjà assemblé par grid_result.build_grid_result (clés
    "questions"/"scoring"/"context", cf. contrat documenté dans ce
    module). N'envoie au LLM QUE les questions OUI/INCONNU + le score/
    couleur + le contexte dossier — jamais les NON/NA, jamais les chunks
    bruts du rapport (cf. bandeau ci-dessus, "Coût / taille du contexte").
    """
    scoring = result["scoring"]
    questions = result["questions"]
    context = result.get("context")
    n_non = sum(1 for q in questions if q["status"] == "NON")

    return _SYNTHESIS_PROMPT.format(
        context_block=_format_context_for_synthesis(context),
        score=scoring["score"],
        color=scoring["color"],
        oui_block=_format_oui_block(questions),
        inconnu_block=_format_inconnu_block(questions),
        n_non=n_non,
    )
