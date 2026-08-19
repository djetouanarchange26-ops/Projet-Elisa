"""
GRILLE ESG V4 — source de vérité (directive CC-V4-11, "Correctifs
critiques Grille V4 — Soutenance 25/08", BLOC A)
====================================================
Structure des 12 questions, restaurée MOT POUR MOT depuis la Maquette
Vierge (`1_Maquette_Vierge_Grille_ESG (1).pdf`, 3 pages, table complète
lue et vérifiée directement contre ce fichier PDF pour CC-V4-11 — pas
depuis une paraphrase intermédiaire). Les formulations R/A sont
VERROUILLÉES — ne pas les reformuler ni les compléter sans validation
Elisa, même pour corriger une coquille apparente.

Ce fichier ne contient QUE la structure (data pure) : pas de logique de
scoring, pas de prompts LLM, pas de critères d'évaluation OUI/NON. Le
scoring et l'intégration au pipeline sont hors périmètre de ce fichier.

Catégorie A — Facteurs de Risque Majeurs / Bloqueurs (6 questions) :
pénalité −25 pts, gain d'atténuation max +5 pts.
Catégorie B — Risques Structurants (6 questions) : pénalité −15 pts,
gain d'atténuation max +3 pts.
(Ce 6+6 correspond enfin à CLAUDE.md — la répartition 5+7 du code V4
précédent, avec des questions absentes de la Maquette Vierge (A.1.3,
A.4.1, B.2.3, B.4.1), était un écart de dérive, pas une évolution
métier validée. Cf. AUDIT_PERTINENCE_NOTE_CADRAGE.md, point 7.)

CORRECTIF CC-V4-11 (remplace intégralement la liste QUESTIONS
précédente) :
  - Les 12 codes sont désormais EXACTEMENT ceux de la Maquette Vierge :
    A.1.1, A.1.2, A.2.1, A.2.2, A.3.1, A.3.2, B.1.1, B.1.2, B.2.1, B.2.2,
    B.3.1, B.3.2. Les anciens codes A.1.3 (opposition communautaire),
    A.4.1 (force majeure), B.2.3 (déversement/fuite), B.4.1 (impacts
    sanitaires) n'existent PAS dans la Maquette Vierge et sont retirés
    partout dans le code (grep récursif vérifié, cf. directive).
  - A.1.1 fusionne désormais les deux anciens sujets "grève du
    personnel" ET "blocage physique par des communautés tierces" en une
    seule question R ("Blocage physique du site OU grève active ?") —
    ce n'est plus seulement une question "personnel" comme dans le code
    V4 précédent.
  - B.3.1 : POLARITÉ STANDARD (PAS inversée), contrairement à l'ancien
    B.3.1 (biodiversité, inverted_polarity=True) qui portait un sujet
    différent. La Maquette Vierge formate B.3.1 ("Absence de données de
    référence (baseline) socio-économiques ?") EXACTEMENT comme les 11
    autres questions : "Si OUI : -25/-15 pts", mitigation "si R = OUI"
    — vérifié ligne par ligne contre le PDF, page 2. Aucune des 12
    questions de la Maquette Vierge n'utilise de polarité inversée.
    `inverted_polarity` et `a_condition="r_non"` restent des champs
    valides côté grid_scoring.py/grid_prompts.py (non supprimés, cf.
    "ne pas modifier grid_scoring.py au-delà du remplacement des
    codes") mais aucune question ne les active plus — code mort
    dormant, pas retiré, cf. grid_prompts.py.
  - "shared_cap_group" : plus aucune question ne le porte (était
    A.1.1/A.1.3, et A.1.3 n'existe plus — les deux sujets sont
    fusionnés dans un seul A.1.1, donc plus besoin de plafond partagé).
    Le mécanisme (`grid_scoring._apply_shared_cap`,
    `get_questions_by_shared_cap`) reste en place, dormant.
  - "a_condition" : "r_oui" pour les 12 questions (schéma unique, cf.
    ci-dessus) — le champ reste présent pour ne pas casser
    grid_scoring.py/grid_result.py qui le lisent déjà de façon
    générique.

CHOIX: liste de dicts, pas de dataclass/NamedTuple — cohérent avec le
reste du projet qui n'utilise ni l'un ni l'autre.

CHANTIER CC-08 (passe CBG, règles de silence, conservé tel quel en
CC-V4-11) : chaque question porte un champ "silence_type" ("evenement" |
"etat") qui détermine comment traiter l'absence de mention dans un
document :
  - "evenement" : un fait daté (grève, blocage, retrait de bailleur...)
    — le silence du rapport vaut NON (« pas de trace = pas eu lieu »).
  - "etat"      : l'existence d'un système/dispositif ou une conclusion
    qui nécessite des données de mesure — le silence du rapport vaut
    INCONNU (« pas décrit = on ne sait pas »), PAS NON.
CHOIX: la classification est fixée dans le paramétrage (ci-dessous), pas
décidée par le LLM au cas par cas — si Elisa modifie une classification,
changer uniquement la valeur "silence_type" ici, ne pas toucher au code
qui la consomme (grid_scoring.py/grid_result.py).
FRAGILE (CC-V4-11) : classification refaite pour les 12 nouveaux codes,
par analogie avec la logique CC-08 (mesure/donnée requise -> "etat" ;
fait daté -> "evenement"), PAS re-validée par Elisa question par
question — à confirmer lors de la prochaine passe d'annotation.

FRAGILE (CC-V4-11) : `na_module="B.2"` conservé sur B.2.1/B.2.2 (les 2
questions Pollution restantes) pour ne pas casser le contrôle
"Modules N/A" déjà présent dans la sidebar (app.py) — la Maquette Vierge
elle-même ne mentionne pas de mécanisme de désactivation modulaire, ceci
reste une extension outil, pas une exigence de la maquette.

ESG_QUESTIONS reste exposé comme alias de QUESTIONS pour compatibilité
avec les imports existants (grid_scoring.py / grid_result.py /
grid_prompts.py).
"""

import logging

logger = logging.getLogger(__name__)

GRID_VERSION = "V4"

QUESTIONS = [
    {
        "code": "A.1.1",
        "category": "A",
        "sous_theme": "Oppositions",
        "question_r": "Blocage physique du site ou grève active ?",
        "question_a": "Un accord d'indemnisation ou de médiation a-t-il été signé avec les parties ?",
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
        "code": "A.1.2",
        "category": "A",
        "sous_theme": "Oppositions",
        "question_r": "Actions en justice suspensives à l'encontre du projet ?",
        "question_a": "Un désistement, un jugement favorable ou un accord transactionnel a-t-il été obtenu ?",
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
        "code": "A.2.1",
        "category": "A",
        "sous_theme": "Conformité",
        "question_r": "Suspension / annulation d'un permis d'exploiter ?",
        "question_a": "Une régularisation administrative formelle a-t-elle été obtenue ?",
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
        "code": "A.2.2",
        "category": "A",
        "sous_theme": "Conformité",
        "question_r": "Retrait d'un co-financeur / bailleur majeur (ex. IFC) ?",
        "question_a": "Un refinancement ou un bailleur de substitution a-t-il été sécurisé ?",
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
        "sous_theme": "Faisabilité",
        "question_r": "Injonction d'arrêt administratif signifiée ?",
        "question_a": "La levée de l'injonction a-t-elle été prononcée ?",
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
        "code": "A.3.2",
        "category": "A",
        "sous_theme": "Faisabilité",
        "question_r": "Accident structurel / rupture d'ouvrage ?",
        "question_a": "Une réparation certifiée par un tiers indépendant a-t-elle été validée ?",
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
        "sous_theme": "Communautaire",
        "question_r": "Perte de moyens de subsistance sans compensation ?",
        "question_a": "Un plan de restauration des moyens de subsistance (LRP) est-il déployé ?",
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
        "sous_theme": "Communautaire",
        "question_r": "Déplacement involontaire de populations non réinstallées ?",
        "question_a": "Un plan de réinstallation conforme a-t-il été exécuté ?",
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
        "code": "B.2.1",
        "category": "B",
        "sous_theme": "Pollution",
        "question_r": "Dépassements récurrents des seuils Air (PM10) ?",
        "question_a": "Des dômes de confinement ou mesures d'abattement ont-ils été installés ?",
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
        "sous_theme": "Pollution",
        "question_r": "Défaut de modélisation du rejet thermique (Eau) ?",
        "question_a": "Une étude de dispersion thermique à jour a-t-elle été validée ?",
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
        "code": "B.3.1",
        "category": "B",
        "sous_theme": "Gouvernance",
        "question_r": "Absence de données de référence (baseline) socio-économiques ?",
        "question_a": "Des études complémentaires couvrent-elles l'intégralité de la zone d'influence ?",
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
        "code": "B.3.2",
        "category": "B",
        "sous_theme": "Gouvernance",
        "question_r": "Absence de suivi périodique des données RSE ?",
        "question_a": "Un reporting ESG périodique a-t-il été rétabli et vérifié ?",
        "penalty": -15,
        "gain": 3,
        "na_module": None,
        "inverted_polarity": False,
        "has_separate_r": True,
        "silence_type": "etat",
        "shared_cap_group": None,
        "a_condition": "r_oui",
    },
]

# Alias rétro-compatibilité : grid_scoring.py / grid_result.py /
# grid_prompts.py importent encore ESG_QUESTIONS — même liste, pas une copie.
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

    CODE MORT DORMANT (CC-V4-11) : aucune question de la Maquette Vierge
    ne porte de "shared_cap_group" (l'ancien groupe "A.1", qui couplait
    A.1.1/A.1.3, a disparu avec la fusion des deux sujets dans un seul
    A.1.1 — cf. docstring du module). Conservé pour une réutilisation
    future si Elisa introduit un nouveau couplage de pénalités, jamais
    supprimé silencieusement (convention CLAUDE.md).

    CHOIX: ne fait QUE regrouper — le calcul du plafond combiné lui-même
    vit dans grid_scoring.py (_apply_shared_cap), lui aussi dormant tant
    qu'aucune question ne porte ce champ.
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
