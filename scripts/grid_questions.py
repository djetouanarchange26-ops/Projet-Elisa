"""
GRILLE ESG V4 — source de vérité (directive CC-V4-01)
====================================================
Structure des 12 questions produite par Elisa (analyste métier). Les
formulations R/A sont VERROUILLÉES — ne pas les reformuler ni les
compléter sans validation Elisa, même pour corriger une coquille
apparente.

Ce fichier ne contient QUE la structure (data pure) : pas de logique de
scoring, pas de prompts LLM, pas de critères d'évaluation OUI/NON. Le
scoring et l'intégration au pipeline sont hors périmètre de CC-V4-01.

Catégorie A — Facteurs de Risque Majeurs / Bloqueurs (5 questions) :
pénalité −25 pts, gain d'atténuation +5 pts.
Catégorie B — Risques Structurants (7 questions) : pénalité −15 pts,
gain d'atténuation +3 pts.

Changements V3 -> V4 (cf. directive CC-V4-01) :
  - +2 questions : A.1.3 (opposition communautaire) et B.4.1 (impacts
    sanitaires sur les communautés riveraines).
  - B.3.1 (biodiversité) : n'est plus polarité-inversée-sans-mitigation.
    A désormais une vraie question R ET une sous-question A séparée
    (has_separate_r=True), mais la sous-question A s'active quand
    R = NON (pas R = OUI comme le schéma standard) — cf. "a_condition".
  - Nouveau champ "shared_cap_group" : A.1.1 et A.1.3 partagent un
    plafond de pénalité combiné (−25 max pour les deux ensemble, pas
    −50) — cf. get_questions_by_shared_cap. Le calcul du plafond
    lui-même reste à implémenter dans grid_scoring.py (hors périmètre
    CC-V4-01, PENDING sur une prochaine directive V4).
  - Nouveau champ "a_condition" : "r_oui" (standard, la sous-question A
    s'active quand R=OUI) ou "r_non" (B.3.1 uniquement).

Deux cas particuliers restants :
  - B.3.1 (biodiversité) : a_condition="r_non", inverted_polarity=True —
    R=NON déclenche la pénalité (l'absence de mesures de compensation/
    suivi écologique est le risque), et c'est ALORS que la sous-question
    A (vérification tierce) s'active.
  - B.2.1/B.2.2/B.2.3 (pollution) : module N/A sectoriel — les 3
    questions sont exclues ensemble (na_module="B.2") si le projet n'a
    structurellement aucun vecteur de pollution.

CHOIX: liste de dicts, pas de dataclass/NamedTuple — cohérent avec le
reste du projet qui n'utilise ni l'un ni l'autre.

CHANTIER CC-08 (passe CBG, règles de silence) : chaque question porte
un champ "silence_type" ("evenement" | "etat") qui détermine comment
traiter l'absence de mention dans un document :
  - "evenement" : un fait daté (grève, blocage, déversement...) — le
    silence du rapport vaut NON (« pas de trace = pas eu lieu »).
  - "etat"      : l'existence d'un système/dispositif ou une conclusion
    qui nécessite des données de mesure — le silence du rapport vaut
    INCONNU (« pas décrit = on ne sait pas »), PAS NON.
CHOIX: la classification est fixée dans le paramétrage (ci-dessous), pas
décidée par le LLM au cas par cas — si Elisa modifie une classification,
changer uniquement la valeur "silence_type" ici, ne pas toucher au code
qui la consomme (grid_scoring.py/grid_result.py).
FRAGILE: classification provisoire, cf. table dans la directive CC-08 —
B.2.2 est classé "etat" (pas "evenement") parce que juger un dépassement
de seuil nécessite des données de mesure : sans ces données, on ne peut
pas conclure à un dépassement, contrairement à un événement daté comme un
blocage physique.

FRAGILE (CC-V4-01) : grid_scoring.py / grid_result.py / grid_prompts.py
n'ont pas encore été mis à jour pour la V4 (shared_cap_group, a_condition
sur B.3.1) — ce chantier est scopé à la seule structure de données
(grid_questions.py). ESG_QUESTIONS reste exposé comme alias de QUESTIONS
pour ne pas casser ces modules en attendant leur propre directive V4.
"""

import logging

logger = logging.getLogger(__name__)

GRID_VERSION = "V4"

QUESTIONS = [
    {
        "code": "A.1.1",
        "category": "A",
        "sous_theme": "Opposition sociale — personnel",
        "question_r": "Grève ou action collective des employés du projet ou de ses contractants ayant interrompu les travaux ou l'exploitation sur la période ?",
        "question_a": "Accord collectif, médiation ou indemnisation formalisée avec les représentants du personnel ?",
        "penalty": -25,
        "gain": 5,
        "na_module": None,
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "evenement",
        "shared_cap_group": "A.1",
        "a_condition": "r_oui",
    },
    {
        "code": "A.1.3",
        "category": "A",
        "sous_theme": "Opposition communautaire",
        "question_r": "Blocage physique du site, d'une voie d'accès ou d'une installation par des riverains ou communautés tierces, ayant interrompu les travaux ou l'exploitation sur la période ?",
        "question_a": "Accord de sortie de crise, médiation ou indemnisation formalisée avec les communautés concernées ?",
        "penalty": -25,
        "gain": 5,
        "na_module": None,
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "evenement",
        "shared_cap_group": "A.1",
        "a_condition": "r_oui",
    },
    {
        "code": "A.2.1",
        "category": "A",
        "sous_theme": "Opposition environnementale / légale",
        "question_r": "Recours juridique ou plainte formelle (ONG / communautés / riverains) sur un motif environnemental ou social ?",
        "question_a": "Désistement obtenu ou jugement favorable rendu sur le fond du grief E&S ?",
        "penalty": -25,
        "gain": 5,
        "na_module": None,
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "evenement",
        "shared_cap_group": None,
        "a_condition": "r_oui",
    },
    {
        "code": "A.3.1",
        "category": "A",
        "sous_theme": "Conformité administrative / permis",
        "question_r": "Retard ou suspension d'obtention d'un permis lié à une lacune procédurale, bloquant le démarrage ou la poursuite du projet ?",
        "question_a": "Régularisation administrative formelle obtenue ?",
        "penalty": -25,
        "gain": 5,
        "na_module": None,
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "evenement",
        "shared_cap_group": None,
        "a_condition": "r_oui",
    },
    {
        "code": "A.4.1",
        "category": "A",
        "sous_theme": "Force majeure",
        "question_r": "Événement externe majeur (catastrophe naturelle, épidémie, conflit armé) ayant entraîné l'arrêt des travaux ou de l'exploitation ?",
        "question_a": "Plan de sécurisation et de reprise appliqué ?",
        "penalty": -25,
        "gain": 5,
        "na_module": None,
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "evenement",
        "shared_cap_group": None,
        "a_condition": "r_oui",
    },
    {
        "code": "B.1.1",
        "category": "B",
        "sous_theme": "Subsistance et déplacement",
        "question_r": "Perte de moyens de subsistance ou déplacement involontaire de communautés riveraines, non compensé ou non réinstallé conformément aux standards ?",
        "question_a": "Plan de restauration des moyens de subsistance déployé, vérifié par un tiers, et suivi dans le temps ?",
        "penalty": -15,
        "gain": 3,
        "na_module": None,
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "evenement",
        "shared_cap_group": None,
        "a_condition": "r_oui",
    },
    {
        "code": "B.1.2",
        "category": "B",
        "sous_theme": "Mécanisme de griefs",
        "question_r": "Absence ou dysfonctionnement du mécanisme de gestion des plaintes communautaires ?",
        "question_a": "Mécanisme opérationnel, accessible aux communautés concernées, et audité par un tiers ?",
        "penalty": -15,
        "gain": 3,
        "na_module": None,
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "etat",
        "shared_cap_group": None,
        "a_condition": "r_oui",
    },
    {
        "code": "B.2.1",
        "category": "B",
        "sous_theme": "Suivi des rejets",
        "question_r": "Absence ou non-vérifiabilité du suivi régulier et documenté des rejets (eau, air, bruit, effluents) ?",
        "question_a": "Protocole de suivi opérationnel, données accessibles et auditables ?",
        "penalty": -15,
        "gain": 3,
        "na_module": "B.2",
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "etat",
        "shared_cap_group": None,
        "a_condition": "r_oui",
    },
    {
        "code": "B.2.2",
        "category": "B",
        "sous_theme": "Dépassement de seuils",
        "question_r": "Dépassement des seuils environnementaux engagés à l'origine du projet (standards prêteurs et/ou normes nationales) ?",
        "question_a": "Équipements de traitement ou d'abattage déployés et efficaces, résultat vérifié ?",
        "penalty": -15,
        "gain": 3,
        "na_module": "B.2",
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "etat",
        "shared_cap_group": None,
        "a_condition": "r_oui",
    },
    {
        "code": "B.2.3",
        "category": "B",
        "sous_theme": "Déversement et fuite",
        "question_r": "Déversement accidentel, fuite ou émission hors contrôle constaté sur la période, avec impact sur le milieu ou les personnes ?",
        "question_a": "Notification formelle aux autorités et remédiation documentée ?",
        "penalty": -15,
        "gain": 3,
        "na_module": "B.2",
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "evenement",
        "shared_cap_group": None,
        "a_condition": "r_oui",
    },
    {
        "code": "B.3.1",
        "category": "B",
        "sous_theme": "Biodiversité",
        "question_r": "Mesures de compensation (offsets) ou suivi écologique déployés selon le plan prévu ?",
        "question_a": "Compensation vérifiée par un tiers et résultats de suivi documentés ?",
        "penalty": -15,
        "gain": 3,
        "na_module": None,
        "inverted_polarity": True,
        "has_separate_r": True,
        "silence_type": "etat",
        "shared_cap_group": None,
        "a_condition": "r_non",
    },
    {
        "code": "B.4.1",
        "category": "B",
        "sous_theme": "Impacts sanitaires sur les communautés riveraines",
        "question_r": "Dommage sanitaire attesté — maladie, blessure ou atteinte à la santé — imputable au projet sur des populations riveraines, sur la période ?",
        "question_a": "Programme de santé communautaire, accès aux soins ou indemnisation médicale déployé et vérifié par un tiers ?",
        "penalty": -15,
        "gain": 3,
        "na_module": None,
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "evenement",
        "shared_cap_group": None,
        "a_condition": "r_oui",
    },
]

# Alias rétro-compatibilité V3 (CC-01) : grid_scoring.py / grid_result.py /
# grid_prompts.py importent encore ESG_QUESTIONS et n'ont pas encore été mis
# à jour pour consommer shared_cap_group / a_condition (hors périmètre de
# CC-V4-01, cf. docstring du module) — même liste, pas une copie.
ESG_QUESTIONS = QUESTIONS


def get_question(code):
    """Renvoie le dict de la question par son code, ou None."""
    for question in QUESTIONS:
        if question["code"] == code:
            return question
    logger.debug(f"grid_questions: code inconnu {code!r}")
    return None


def get_active_questions(na_modules=None):
    """Renvoie la liste des questions actives (hors N/A).
    CHOIX: na_modules est une liste de strings (ex. ["B.2"]). Toute question
    dont na_module est dans cette liste est exclue.
    """
    if not na_modules:
        return list(QUESTIONS)
    return [q for q in QUESTIONS if q["na_module"] not in na_modules]


def get_questions_by_shared_cap(group):
    """Renvoie la liste des questions partageant un plafond de pénalité.
    Ex: get_questions_by_shared_cap("A.1") -> [A.1.1, A.1.3]

    CHOIX: ne fait QUE regrouper — le calcul du plafond combiné lui-même
    (−25 max pour le groupe "A.1", pas −50) vit dans grid_scoring.py, à
    implémenter dans une prochaine directive V4 (hors périmètre CC-V4-01).
    """
    return [q for q in QUESTIONS if q.get("shared_cap_group") == group]


# --- Types de document V4 (directive CC-V4-01) ---
# CHOIX: le type est saisi manuellement par l'analyste (R11).
# Il conditionne le mode de lecture et la règle de preuve (porte 2).
DOCUMENT_TYPES = {
    1: {
        "label": "Instruction / due diligence pré-closing",
        "reading_mode": "instruction",
        "proof_forms": 4,  # 3 formes standard + plan budgété/calendé
        "description": "ESRS, ESIA, mémo de crédit. Obligation de planification.",
    },
    2: {
        "label": "Rapport annuel de suivi opérateur",
        "reading_mode": "suivi",
        "proof_forms": 3,
        "description": "AMR client, rapport E&S annuel. Obligation de résultat.",
    },
    3: {
        "label": "Rapport de monitoring multiannuel par auditeur indépendant",
        "reading_mode": "suivi",
        "proof_forms": 3,
        "description": "Rapport CAO, panel de conformité. 3 couches temporelles (R8).",
    },
    4: {
        "label": "Rapport de suivi thématique ou sectoriel",
        "reading_mode": "suivi",
        "proof_forms": 3,
        "description": "Rapport biodiversité, qualité de l'air. Périmètre étroit -> silence hors périmètre = INCONNU.",
    },
}

# --- Jeu de valeurs R6 V4 (directive CC-V4-01) ---
RESPONSE_VALUES = {"OUI", "NON", "INCONNU", "NA"}

# Champs qualifiants non-scorants (texte libre, pas des statuts de score)
QUALIFYING_FLAGS = {
    "ALLEGATION_NON_CONFIRMEE": "Fait rapporté non établi ni infirmé — non scorant",
    "NON_ATTESTE": "NON adossé à un verbatim explicite d'absence confirmée par l'auditeur",
}


# --- Statuts de mitigation V3 (passe CBG, directive CC-07) ---
# CHOIX: 4 statuts au lieu du binaire OUI/NON. Seul OUI_PROUVEE génère un
# gain. Le filtre est en deux étapes : temporel (accompli seul) puis preuve
# (accord formel / investissement matériel / vérification tierce).
# Test en deux étapes successives :
#   ÉTAPE 1 — filtre temporel (grammatical) : seul l'accompli passe
#     ("were installed", "was opened", "have been processed and closed").
#     Futur / conditionnel / infinitif d'obligation -> échec -> NON_INTENTION.
#   ÉTAPE 2 — filtre de preuve (la forme) : seules trois formes sont
#     admises -- accord formel signé, investissement matériel réceptionné,
#     vérification par un tiers indépendant. Un plan, une procédure, une
#     politique, un recrutement ou une formation ne sont PAS des preuves,
#     même énoncés au passé -> échec -> NON_FORME_INSUFFISANTE.
#   Les deux filtres passés + aucune défaillance constatée -> OUI_PROUVEE.
#   Les deux filtres passés MAIS le document établit que la mesure n'a pas
#     produit son effet -> OUI_DEFAILLANTE (exige verbatim_mesure ET
#     verbatim_defaillance -- cf. garde-fou dans grid_scoring.py : sans les
#     deux verbatims, OUI_DEFAILLANTE est impossible et retombe sur
#     OUI_PROUVEE). Une vérification NON ENCORE effectuée n'est PAS une
#     défaillance constatée.
# CHANTIER CC-V4-01 : R7 inchangé — statuts et description NON modifiés,
# seule la description d'OUI_DEFAILLANTE précise désormais le sous-cas
# "mitigation interrompue" (même traitement, gain=0), cf. ci-dessous.
MITIGATION_STATUTS = {
    "NON_INTENTION": {
        "label": "NON — intention",
        "points_multiplier": 0,
        "description": "Échoue au filtre temporel (futur, conditionnel, infinitif d'obligation)"
    },
    "NON_FORME_INSUFFISANTE": {
        "label": "NON — forme insuffisante",
        "points_multiplier": 0,
        "description": "Passe le filtre temporel, échoue au filtre de preuve (plan, procédure, politique, formation)"
    },
    "OUI_PROUVEE": {
        "label": "OUI — prouvée",
        "points_multiplier": 1,
        "description": "Passe les deux filtres (accord formel, investissement matériel, vérification tierce)"
    },
    "OUI_DEFAILLANTE": {
        "label": "OUI — défaillante",
        "points_multiplier": 0,
        "description": "Passe les deux filtres MAIS le document établit que la mesure n'a pas produit son "
                        "effet, ou mesure exécutée puis interrompue (même traitement : gain = 0)"
    }
}

# SEUIL: conjonctions concessives fréquemment associées au statut 4 —
# indice syntaxique, pas une règle absolue : dans ~50% des cas observés
# lors de la passe CBG, la phrase de défaillance se trouve dans la MÊME
# phrase que la mesure, introduite par l'une de ces conjonctions.
CONCESSIVE_MARKERS = ["although", "however", "nevertheless", "despite", "whilst", "notwithstanding"]

# --- Valeurs du champ silence (passe CBG, directive CC-08) ---
# CHOIX: table de référence pour la lisibilité — la logique elle-même
# (quelle valeur appliquer selon silence_type) vit dans grid_scoring.py/
# le futur prompt LLM, pas ici (ce fichier reste data pure, cf. docstring
# du module).
SILENCE_VALUES = {
    "NON": "Aucune mention → pas de risque (question d'événement)",
    "INCONNU": "Aucune mention → non documenté (question d'état/système)",
    "NA": "Inapplicable par nature du projet (verbatim obligatoire)",
}
