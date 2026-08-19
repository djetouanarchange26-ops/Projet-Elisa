"""
GRILLE ESG V4 — prompts LLM complets (directive CC-V4-05)
=============================================================
Réécriture complète du squelette V3 (CC-04) : règles R1-R11 intégrales et
few-shot tirés des 4 dossiers annotés (CBG, Mundra, Aysha, Indorama). Ce
module construit des strings et en parse d'autres — il n'appelle JAMAIS le
LLM lui-même (pas d'import de llm_backend.py/llm_confirm.py/deep_analysis.py),
invariant hérité de CC-04.

Décisions de design actées (CC-04, confirmées V4) :
  - Biais faux positifs (R1) : en cas d'ambiguïté, le LLM doit pencher vers
    la réponse qui SIGNALE le risque, jamais vers celle qui le masque —
    Elisa préfère un faux positif à un faux négatif. La réponse qui
    "signale le risque" n'est PAS toujours OUI — pour B.3.1 (polarité
    inversée), c'est NON qui signale le risque ; le template B.3.1 dit
    donc explicitement "penche vers NON", jamais "OUI" tel quel.
  - Langue : toutes les sorties LLM en français, quelle que soit la
    langue du document source.
  - Format de réponse : ligne par ligne (pas JSON) — cohérent avec
    deep_analysis.py, plus robuste avec le modèle 4B utilisé.

Nouveautés V4 (CC-V4-05) :
  - R2 (matérialisation), R5 (silence, dépend de silence_type — cf.
    grid_questions.py), R3/R7 (mitigation à 2 portes + 4 statuts, CC-07),
    R7bis (items ESAP jamais mitigants, cf. grid_sections.py/CC-09),
    R8 (couches temporelles, documents Type 3 seulement), R9 (hiérarchie
    des sources, Types 2-3), R10 (filtre de sujet SPV/prêteur/substitution
    — évalué PAR LE LLM dans le prompt, jamais en post-traitement Python,
    cf. "Ce qu'il ne faut PAS faire"), R11 (formes de preuve admises selon
    document_type).
  - Few-shot par question (_FEW_SHOT_EXAMPLES) : EXCLUSIVEMENT les cas
    réellement rencontrés lors de l'annotation des 4 dossiers — aucun
    exemple inventé. Les questions sans cas annoté n'ont pas de few-shot
    (fallback "" dans get_prompt), ce n'est pas un oubli.
  - get_prompt(question_code, context_chunks, document_type=1) : le type
    de document conditionne R11/R8/R9/R2 (cf. CC-V4-11 ci-dessous) mais
    ne change ni R1 ni R7bis ni R10 — ces règles sont universelles,
    valables sur les 4 types.
  - parse_response() : nouveau champ SUJET (R10), en plus des champs
    hérités (MITIGATION_STATUS remplace le binaire MITIGATION de CC-02,
    cf. CC-07 ; EVIDENCE_MESURE/EVIDENCE_DEFAILLANCE remplacent
    EVIDENCE_MITIGATION unique pour porter le double verbatim du statut 4).

CORRECTIF CC-V4-11 ("Correctifs critiques Grille V4 — Soutenance
25/08", BLOC B) — cause racine du sur-score CBG (85 au lieu de 28-31) :
  - R2 devient CONDITIONNELLE au reading_mode (cf. _MATERIALISATION_*
    ci-dessous), au lieu d'une règle unique trop stricte pour les
    documents Type 1/2 (mode "instruction") : sur un ESRS de due
    diligence, un constat documenté (fait passé, état existant, legacy
    issue, écart relevé par le consultant) DOIT déclencher un OUI — le
    LLM confondait un constat de due diligence avec une "vulnérabilité
    future" et répondait NON à tort. R2 stricte (accompli seul, fait
    daté imputé au SPV) reste inchangée pour le mode "suivi" (Types 3/4).
  - Few-shot entièrement reconstruit pour les 12 nouveaux codes
    (cf. grid_questions.py, BLOC A) : les anciens codes A.1.3/A.4.1/
    B.2.3/B.4.1 n'existent plus, et plusieurs sujets ont changé de code
    (ex. l'ancien B.2.2 "dépassement de seuils" générique devient
    B.2.1 "Air/PM10" dans la Maquette Vierge — le few-shot Indorama sur
    les dépassements d'état initial/géogéniques, qui porte sur la
    qualité de l'air, a été déplacé en conséquence, PAS laissé sous
    l'ancien code B.2.2 qui porte désormais sur l'Eau/rejet thermique).
    Un few-shot dont le sujet ne correspond plus au code qui le porte
    aurait pollué le prompt de la mauvaise question.
  - Aucune question n'a plus `inverted_polarity=True` (cf.
    grid_questions.py) : `_B31_PROMPT_TEMPLATE` et la branche qui
    l'active dans get_prompt() ne sont plus jamais atteints — CODE MORT
    DORMANT, conservé (convention CLAUDE.md), pas supprimé.
  - `_ARTICULATION_B23_B41` (R2bis) : n'est plus jamais injectée
    (question_code ne vaut plus jamais "B.2.3"/"B.4.1", ces codes
    n'existant plus) — CODE MORT DORMANT, conservé.
"""

import logging
import re

import grid_questions

logger = logging.getLogger(__name__)

# ============================================================================
# Règles dynamiques selon le type de document (R8, R9, R11)
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

_TEMPORAL_RULE_TYPE3 = """R8 — COUCHES TEMPORELLES (document Type 3) :
Étiqueter chaque verbatim avant affectation :
- Couche 1 — résumé antérieur : contexte, faits avant la période auditée. N'ALIMENTE PAS le score.
- Couche 2 — période auditée : SEULE couche qui alimente le score.
- Couche 3 — observation postérieure : mission terrain récente. N'alimente pas le score.
ATTENTION A.1.1 : les rapports CAO résument souvent des manifestations historiques. Vérifier la couche temporelle avant de cocher OUI."""

_TEMPORAL_RULE_OTHER = ""  # Pas de règle temporelle pour Type 1, 2, 4

# --- R2 — matérialisation, conditionnelle au reading_mode (CC-V4-11) ---
# CHOIX: R2 stricte ("fait daté, survenu, attribué au SPV") est correcte
# pour un document de SUIVI rétrospectif (Types 3/4) mais trop stricte
# pour un document d'INSTRUCTION (Types 1/2, due diligence pré-closing) —
# un ESRS documente des CONSTATS (état existant, legacy issue, écart
# relevé) qui ne sont pas des "événements survenus pendant une période de
# monitoring" mais qui DOIVENT déclencher un OUI : c'est précisément
# l'objet de la due diligence. Cause racine du sur-score CBG (85 au lieu
# de 28-31, cf. directive CC-V4-11) : le LLM appliquait la version
# stricte à un document Type 1 et traitait des constats documentés (540
# plaignants, airshed dégradé) comme des "vulnérabilités futures".
_MATERIALISATION_INSTRUCTION = """R2 — MATÉRIALISATION (mode INSTRUCTION — Type 1/2, due diligence) :
Un CONSTAT DOCUMENTÉ dans le rapport de due diligence déclenche OUI. Cela inclut :
- un fait passé avéré (déplacement, pollution, plainte) ;
- un état existant documenté (airshed dégradé, absence de baseline) ;
- un legacy issue non résolu (griefs historiques non compensés) ;
- un écart de conformité constaté par le consultant.
NE déclenche PAS un OUI en mode instruction :
- une vulnérabilité théorique sans constat factuel ;
- un risque mentionné uniquement dans l'analyse d'impact (ESIA) sans constat terrain ;
- un engagement futur du sponsor sans début d'exécution."""

_MATERIALISATION_SUIVI = """R2 — MATÉRIALISATION (mode SUIVI — Type 3/4, monitoring rétrospectif) :
Seul un FAIT DATÉ, SURVENU durant la période de monitoring, ATTRIBUÉ AU PROJET (SPV) déclenche un OUI.
Vérifier : verbe au passé accompli + fait daté + attribution causale au projet.
NE déclenche PAS un OUI en mode suivi :
- un droit, une politique, une procédure ;
- une vulnérabilité future, un risque potentiel ;
- un constat d'une période antérieure déjà couvert dans un précédent rapport."""

_HIERARCHY_RULE_TYPE23 = """R9 — HIÉRARCHIE DES SOURCES :
1. Constat de l'auditeur indépendant (CAO, panel, expert tiers)
2. Observation directe en visite de terrain
3. Donnée chiffrée fournie par un tiers (labo, régulateur)
4. Témoignage de plaignant
5. Déclaration non étayée du client
RÈGLE : une déclaration client contredite par un constat d'auditeur dans le même document ne peut JAMAIS servir de mitigation."""

_HIERARCHY_RULE_OTHER = ""

# --- R2bis — articulation B.2.3 / B.4.1 (correction V4) ---
# CODE MORT DORMANT (CC-V4-11) : B.2.3 et B.4.1 n'existent plus dans
# grid_questions.py (absents de la Maquette Vierge, cf. BLOC A) — la
# condition d'injection dans get_prompt() (question_code in ("B.2.3",
# "B.4.1")) ne matche donc plus jamais. Conservé (convention CLAUDE.md :
# jamais de suppression silencieuse) au cas où un besoin similaire
# (articulation entre deux questions pollution) réapparaîtrait.
# CHOIX: injectée uniquement pour B.2.3 et B.4.1 (cf. get_prompt), pas dans
# toutes les questions du template standard — évite de gonfler le prompt de
# règles hors-sujet pour les 9 autres questions qui partagent ce template.
# Corrige un sur-classement observé : un même verbatim mentionnant des
# impacts sanitaires (irritations, maladies) liés à un REJET CHRONIQUE
# AUTORISÉ déclenchait à tort B.2.3 (réservée aux événements ACCIDENTELS)
# EN PLUS de B.4.1 — les deux questions ne doivent partager un verbatim que
# si le texte décrit RÉELLEMENT un événement accidentel distinct.
_ARTICULATION_B23_B41 = """R2bis — ARTICULATION B.2.3 / B.4.1 : ne pas confondre un rejet CHRONIQUE
et un événement ACCIDENTEL.
- B.2.3 = un ÉVÉNEMENT PONCTUEL ET ACCIDENTEL : déversement accidentel,
  fuite, émission hors contrôle, rejet non maîtrisé — un fait qui sort du
  fonctionnement normal/autorisé de l'installation.
- B.4.1 = un DOMMAGE SANITAIRE sur des personnes, quelle qu'en soit
  l'origine — y compris un rejet CHRONIQUE et AUTORISÉ (ex : eaux de
  rejet habituelles d'une installation, dans le cadre de son permis) qui
  cause des irritations, maladies ou blessures documentées.
UN REJET CHRONIQUE AUTORISÉ QUI CAUSE UN DOMMAGE SANITAIRE ALIMENTE
UNIQUEMENT B.4.1, JAMAIS B.2.3 — l'autorisation/le caractère habituel du
rejet exclut par définition l'« événement hors contrôle » que B.2.3
exige. B.2.3 et B.4.1 ne peuvent se déclencher sur le MÊME verbatim que si
ce verbatim décrit explicitement un événement accidentel (déversement,
fuite) distinct du fonctionnement normal."""

# --- Règle de silence (R5) selon silence_type (cf. grid_questions.py, CC-08) ---
# CHOIX: deux variantes courtes, cohérentes avec grid_questions.SILENCE_VALUES
# — pas de nouvelle sémantique inventée ici, juste la formulation prompt de
# ce qui est déjà décidé et scoré côté grid_scoring.py.
_SILENCE_EVENEMENT = (
    "Question d'ÉVÉNEMENT : si aucune mention pertinente n'est trouvée dans "
    "les passages, réponds NON — l'absence de trace d'un fait daté vaut "
    "absence du fait (pas de risque)."
)
_SILENCE_ETAT = (
    "Question d'ÉTAT/SYSTÈME : si aucune mention pertinente n'est trouvée "
    "dans les passages, réponds INCONNU, JAMAIS NON — l'absence de "
    "description d'un système ou d'un état ne permet pas de conclure à "
    "son absence."
)

# ============================================================================
# Templates
# ============================================================================

# R1 (biais faux positifs) intégré dans les deux templates ci-dessous — cf.
# docstring du module. Le mot "ambiguïté" et la formulation "penche vers"
# sont repris tels quels de CC-04, ne pas les retirer (cf. "Ce qu'il ne
# faut PAS faire" de CC-V4-05).
_STANDARD_PROMPT_TEMPLATE = """Tu es un analyste ESG spécialisé dans le financement de projets d'infrastructure. Tu analyses un rapport pour répondre à une question de la grille d'évaluation ESG V4.

TYPE DE DOCUMENT : {document_type_label}
MODE DE LECTURE : {reading_mode}

QUESTION DE RISQUE :
{question_r}

PASSAGES DU RAPPORT :
{context_chunks}

=== RÈGLES D'ÉVALUATION ===

R1 — BIAIS FAUX POSITIFS : en cas d'ambiguïté ou de doute persistant après application des règles ci-dessous, penche vers OUI (la réponse qui SIGNALE le risque) plutôt que vers celle qui le masque, et explique ton doute dans CONFIDENCE.

{materialisation_rule}

R5 — SILENCE :
{silence_rule}

R3/R7 — MITIGATION (si risque = OUI) :
Deux portes séquentielles. Ne pas chercher la porte 2 si la porte 1 échoue.

PORTE 1 — le temps du verbe.
Seul l'accompli passe. Will / plans to / proposes / to be prepared → statut 1 (gain = 0).

PORTE 2 — la forme de preuve.
{proof_forms_rule}
Un plan, une procédure, une politique, un recrutement, une formation, un engagement verbal = ÉCHEC → statut 2 (gain = 0).

Les 4 statuts :
1. NON_INTENTION — échec porte 1
2. NON_FORME_INSUFFISANTE — OK porte 1, échec porte 2
3. OUI_PROUVEE — OK portes 1 et 2
4. OUI_DEFAILLANTE — OK portes 1 et 2, MAIS le document établit que CETTE MÊME MESURE (celle citée en EVIDENCE_MESURE) n'a pas produit son effet ou a été interrompue. EVIDENCE_DEFAILLANCE doit porter EXPLICITEMENT sur la mesure décrite en EVIDENCE_MESURE — pas sur une autre mesure, pas sur un problème général du projet, pas sur une simple conjonction concessive (however/although/despite) isolée sans lien de cause démontré avec CETTE mesure. Si le lien entre les deux passages n'est pas explicite dans le texte, ne PAS conclure au statut 4 — rester au statut 3 (OUI_PROUVEE). Citer les DEUX passages, chacun portant sur la même mesure.

R7bis — ITEMS ESAP : un item d'ESAP = obligation non encore remplie. Alimente toujours le risque, jamais la mitigation.

R10 — FILTRE DE SUJET : identifier le sujet du manquement.
- Sujet = société de projet, sponsor, contractants, installation → alimente le score → SUJET: SPV.
- Sujet = institution financière, auditeur, mécanisme de recours → N'ALIMENTE PAS le score → SUJET: PRÊTEUR. Chercher un verbatim de substitution portant sur le même fait avec le client/la SPV pour sujet AVANT de faire basculer la réponse (si trouvé → SUJET: SUBSTITUTION, réponds sur la base de ce nouveau verbatim).
- Sujet ambigu ou non déterminable avec certitude (le passage ne permet pas de trancher qui est visé) → NE PAS attribuer automatiquement le manquement à la SPV : réponds NON (ou repli silence si aucun passage n'est réellement exploitable) → SUJET: AMBIGU.
- Le projet est concerné INDIRECTEMENT (réaction d'un tiers, contexte externe au projet) mais AUCUN manquement n'est imputable à la SPV/au projet lui-même → réponds NON → SUJET: INDIRECT.
Seul un manquement CLAIREMENT imputable à la SPV/au projet peut déclencher OUI. Le biais R1 (pencher vers OUI en cas de doute) s'applique au contenu du risque, JAMAIS à l'attribution du sujet — un doute sur QUI est visé n'est pas un doute sur CE QUI s'est passé, et ne se résout jamais par défaut vers la SPV.

{articulation_rule}

{temporal_rule}

{hierarchy_rule}

{few_shot_section}

Réponds TOUJOURS en français, quelle que soit la langue du texte.

RÉPONDS EXACTEMENT DANS CE FORMAT (une ligne par champ) :
STATUS: OUI ou NON ou INCONNU
EVIDENCE_R: [passage exact entre guillemets — ou vide]
PAGE: [numéro ou "inconnue"]
MITIGATION_STATUS: NON_INTENTION ou NON_FORME_INSUFFISANTE ou OUI_PROUVEE ou OUI_DEFAILLANTE ou N/A
EVIDENCE_MESURE: [passage de la mesure — ou vide]
EVIDENCE_DEFAILLANCE: [passage de la défaillance si statut 4, portant sur la MÊME mesure — ou vide]
SUJET: SPV ou PRÊTEUR ou SUBSTITUTION ou AMBIGU ou INDIRECT
CONFIDENCE: [explication du doute — ou vide]
"""

# CODE MORT DORMANT (CC-V4-11) : plus aucune question de grid_questions.py
# n'a inverted_polarity=True depuis la restauration Maquette Vierge (BLOC
# A) — cette branche n'est donc plus jamais sélectionnée par get_prompt().
# Conservée (convention CLAUDE.md : jamais de suppression silencieuse) au
# cas où une future question inversée serait réintroduite par Elisa.
_B31_PROMPT_TEMPLATE = """Tu es un analyste ESG spécialisé. Tu évalues si des mesures de compensation environnementale (offsets) ou un suivi écologique ont été EFFECTIVEMENT DÉPLOYÉS.

TYPE DE DOCUMENT : {document_type_label}
MODE DE LECTURE : {reading_mode}

QUESTION (POLARITÉ INVERSÉE — NON = risque) :
{question_r}

PASSAGES DU RAPPORT :
{context_chunks}

=== RÈGLES ===
R1 — BIAIS FAUX POSITIFS : en cas d'ambiguïté ou de doute persistant, penche vers NON (la réponse qui SIGNALE le risque ICI, à l'inverse du schéma standard) et explique ton doute dans CONFIDENCE.
- NON = risque (−15 pts). OUI = favorable (0 pts).
- Un inventaire, une étude de faisabilité, un plan non exécuté = NON.
- Seule une mesure EFFECTIVEMENT DÉPLOYÉE = OUI.
{proof_forms_rule}

SI TU RÉPONDS NON (= risque), évalue aussi la sous-question de mitigation :
QUESTION DE MITIGATION : « Compensation vérifiée par un tiers et résultats de suivi documentés ? »

{silence_rule}
{few_shot_section}

Réponds TOUJOURS en français.

RÉPONDS EXACTEMENT DANS CE FORMAT :
STATUS: OUI ou NON ou INCONNU
EVIDENCE_R: [passage exact — ou vide]
PAGE: [numéro ou "inconnue"]
MITIGATION_STATUS: NON_INTENTION ou NON_FORME_INSUFFISANTE ou OUI_PROUVEE ou OUI_DEFAILLANTE ou N/A
EVIDENCE_MESURE: [passage de mitigation — ou vide]
EVIDENCE_DEFAILLANCE: [si statut 4, portant sur la MÊME mesure — ou vide]
SUJET: SPV ou PRÊTEUR ou SUBSTITUTION ou AMBIGU ou INDIRECT
CONFIDENCE: [si doute — ou vide]
"""

# ============================================================================
# Few-shot par question — cas réels des 4 dossiers annotés (CBG, Mundra,
# Aysha, Indorama). AUCUN exemple inventé — cf. "Ce qu'il ne faut PAS
# faire" de CC-V4-05. Les questions absentes de ce dict n'ont simplement
# pas de cas annoté disponible pour leur sujet précis.
#
# RECONSTRUIT EN ENTIER POUR CC-V4-11 (BLOC A + BLOC B) : les 12 codes de
# grid_questions.py ont changé (Maquette Vierge). Chaque exemple existant
# a été replacé sous le code dont le SUJET correspond réellement,
# jamais laissé sous son ancien code par défaut :
#   - A.1.1 (nouveau, fusion "blocage physique OU grève") reçoit les
#     exemples de l'ancien A.1.1 (grève) ET de l'ancien A.1.3 (blocage
#     communautaire, piège de polarité).
#   - A.1.2 (actions en justice suspensives) reçoit les exemples de
#     l'ancien A.2.1 (recours juridique).
#   - A.2.1 (suspension/annulation de permis) reçoit les exemples de
#     l'ancien A.3.1 (permis/conformité administrative).
#   - B.1.1 (perte de subsistance sans compensation) garde ses propres
#     exemples + le nouveau cas CBG legacy grievances (BLOC B point 2).
#   - B.2.1 (Air/PM10) reçoit l'exemple de poussières/filtres CBG (déjà
#     un sujet Air/particules dans l'ancien B.2.2) + le nouveau cas
#     Indorama airshed/WHO limits (BLOC B point 3) : cet exemple est un
#     constat de qualité de l'AIR, donc placé sous B.2.1 (Air), PAS sous
#     B.2.2 qui porte désormais sur l'Eau/rejet thermique — la directive
#     CC-V4-11 le nommait "B.2.2" en supposant l'ancien découpage
#     générique "dépassement de seuils", devenu obsolète après BLOC A.
#   - B.3.1 (absence de données de référence baseline) reçoit l'exemple
#     de refus de partage de données de monitoring (Mundra) — un refus
#     de fournir des données de référence est un cas topique pour cette
#     question, même si l'exemple d'origine portait sur le suivi
#     écologique plutôt que socio-économique.
#   - Sans équivalent net dans les 4 dossiers annotés pour le nouveau
#     sujet : A.2.2 (retrait bailleur), A.3.1 (injonction d'arrêt), A.3.2
#     (accident structurel), B.1.2 (déplacement non réinstallé — l'ancien
#     B.1.2 portait sur le mécanisme de griefs, sujet disparu), B.2.2
#     (rejet thermique eau), B.3.2 (suivi RSE périodique) — fallback ""
#     dans get_prompt(), pas d'exemple inventé.
# ============================================================================

_FEW_SHOT_EXAMPLES = {
    "A.1.1": """
=== EXEMPLES DE RÉFÉRENCE ===

FAUX POSITIF — droit vs fait (CBG) :
« CBG workers have the right to freely associate in unions as well as a right to strike. »
« strike » = droit, pas événement → NON

FAUX POSITIF — fin normale vs blocage (CBG) :
« Prepare Worker Demobilization Plans for future demobilization events »
Démobilisation planifiée, pas opposition → NON

PIÈGE R8 — couche temporelle (Mundra/Type 3) :
Les rapports CAO résument souvent des manifestations historiques. Vérifier TOUJOURS la couche temporelle. Un blocage cité en résumé de la période 2013-2015 NE DÉCLENCHE PAS A.1.1 sur la période 2017-2025.

PIÈGE DE POLARITÉ — qui bloque qui ? :
A.1.1 couvre un blocage SUBI par le projet (grève du personnel OU blocage physique par des riverains/communautés tierces). Si c'est au contraire le PROJET qui restreint l'accès de la communauté (routes fermées, forces de sécurité), ce n'est PAS un fait imputable à la communauté ou au personnel — ne pas cocher A.1.1 pour ce cas ; vérifier si un autre thème de la grille (ex. B.1.1, perte de moyens de subsistance) documente une conséquence de cette restriction.
""",

    "A.1.2": """
=== EXEMPLES DE RÉFÉRENCE ===

PIÈGE R10 — filtre de sujet (Mundra) :
« active litigation proceedings in U.S. federal court involving the affected communities and IFC »
Sujet : la SFI. L'affaire Jam c. SFI vise le prêteur, pas la SPV → ÉCARTÉ par R10.
Vérifier : existe-t-il un recours dirigé contre la SPV ? Non → NON.

PIÈGE — clôture ≠ résolution :
Une clôture de dossier CAO pour épuisement ou absence de relation commerciale ≠ résolution du grief E&S. Lire le MOTIF.

PIÈGE — dérogation locale ≠ dérogation prêteur :
Une dérogation obtenue d'un régulateur local ne vaut pas dérogation aux standards des prêteurs.
""",

    "A.2.1": """
=== EXEMPLES DE RÉFÉRENCE ===

FAUX POSITIF — permis obtenu vs projet retardé (Aysha) :
« The ESIA has received Environmental Clearance from MoWIE... However, the project has been delayed for a significant period »
Les mots « permit », « delayed » et « mandatory » cohabitent. MAIS : l'autorisation A ÉTÉ OBTENUE, pas suspendue ni annulée. Le retard est celui du PROJET, pas du PERMIS. → NON

FAUX POSITIF — écart normatif vs irrégularité administrative (CBG) :
« gaps with the IFC Performance Standards were identified in the ESIA »
Écart avec les standards des PRÊTEURS, pas suspension/annulation par l'AUTORITÉ qui a approuvé l'ESIA. → NON
""",

    "B.1.1": """
=== EXEMPLES DE RÉFÉRENCE ===

MITIGATION INTERROMPUE — statut 4 (Mundra) :
Services de compensation fournis puis arrêtés en août 2017 → statut 4, gain = 0.

FAUX POSITIF — engagement ≠ réparation (CBG) :
« Formal written commitment by CBG not to disturb land before any LRP is in place »
Engagement PROSPECTIF = n'atténue pas un risque DÉJÀ matérialisé → ne pas créditer.

N/A ARGUMENTÉ — exemplaire (Indorama) :
« the Project is not expected to result in physical or economic displacement and therefore IFC Performance Standard 5 is not triggered. Land required for the Project is located within the existing Indorama Free Zone »
N/A avec verbatim positif, norme nommée, motif donné. C'est le modèle.

CONSTAT DE DUE DILIGENCE (mode INSTRUCTION, Type 1) — cas CBG :
Document : ESRS instruction pré-closing, mine de bauxite, Afrique.
Passage : « CBG is committed to retroactively assess legacy involuntary resettlement and to identify outstanding grievances. 31 grievances have been received, of which 24 have been addressed. »
→ OUI. L'ESRS documente des griefs non résolus (7 sur 31) et un engagement de réévaluation rétroactive — c'est un constat de due diligence (cf. R2, mode instruction), pas une vulnérabilité théorique. Le déplacement historique non compensé est un fait documenté, même s'il n'est pas daté sur la période de suivi.
""",

    "B.2.1": """
=== EXEMPLES DE RÉFÉRENCE ===

ASYMÉTRIE RISQUE/MITIGATION — exemple canonique (CBG, poussières/PM) :
« The existing plant has historically generated significant quantities of fugitive dust... ALTHOUGH additional filters and scrubbers were installed on the dryer stack in recent years. »
Filtres installés = mitigation authentique. Poussières persistantes = la mesure n'a pas produit son effet.
→ OUI_DEFAILLANTE. EVIDENCE_MESURE = filtres. EVIDENCE_DEFAILLANCE = poussières.

CONSTAT DE DUE DILIGENCE (mode INSTRUCTION, Type 1) — état initial dégradé (Indorama) :
Document : ESRS instruction, mine de bauxite.
Passage : « The affected airshed at both Kamsar and Sangarédi is already degraded, with some baseline ambient air quality data already exceeding WHO limits »
→ OUI. En mode instruction (cf. R2), un airshed documenté comme dégradé AVANT le projet est un constat de due diligence à signaler : le projet s'ajoute à une situation déjà non conforme. Ce n'est pas "le projet a pollué" mais "le contexte est déjà dégradé et le projet va l'aggraver".

FAUX POSITIF — dépassement état initial en mode SUIVI (Indorama) :
« At night-time, measured LAeq exceeded the 45 dB IFC criterion at location N9 only »
Dépassement mesuré dans le chapitre état initial, AVANT travaux, sur un document de type SUIVI (R2, mode suivi : seul un fait survenu pendant la période imputable au projet compte). Le projet n'en est pas la cause. → NON

FAUX POSITIF — dépassement géogénique :
« observed exceedances are likely attributable to natural background conditions typical of the regional geology »
Origine naturelle, pas anthropique. → NON

PIÈGE — déclaration client contredite (Mundra/R9) :
Déclaration client « no exceedances » sans donnée jointe, contredite par l'auditeur → ni NON ni mitigation.
""",

    "B.3.1": """
=== EXEMPLES DE RÉFÉRENCE ===

REFUS DE PARTAGE DE DONNÉES — déclencheur (Mundra/R10) :
« The client later informed CRP that it was not prepared to carry out additional monitoring or share monitoring data »
Refus EXPLICITE du client de fournir des données de référence → déclencheur pour l'absence de données de référence, JAMAIS mitigation.
Sujet : le CLIENT (pas le prêteur). Verbatim de substitution supérieur à l'original (R10).
""",
}


def get_prompt(question_code, context_chunks, document_type=1):
    """Assemble le prompt V4 pour une question donnée.

    CHOIX V4: le document_type conditionne :
    - la règle de matérialisation (R2, CC-V4-11 : instruction vs suivi)
    - les formes de preuve admises (R11)
    - les règles temporelles (R8, Type 3 seulement)
    - la hiérarchie des sources (R9, Types 2-3 seulement)
    Il ne change JAMAIS R1 (biais), R7bis (ESAP) ni R10 (filtre de sujet)
    — universels, valables sur les 4 types.

    Retourne None si question_code est inconnu (pas d'exception — cf.
    CC-V4-05 : l'appelant est censé valider le code en amont via
    grid_questions.get_question()).
    """
    question = grid_questions.get_question(question_code)
    if question is None:
        return None

    doc_info = grid_questions.DOCUMENT_TYPES.get(document_type, grid_questions.DOCUMENT_TYPES[1])

    # R2 — matérialisation, conditionnelle au reading_mode (CC-V4-11) :
    # cf. _MATERIALISATION_INSTRUCTION/_SUIVI, cause racine du sur-score
    # CBG corrigée par ce BLOC B.
    materialisation_rule = (
        _MATERIALISATION_INSTRUCTION if doc_info["reading_mode"] == "instruction" else _MATERIALISATION_SUIVI
    )

    # R5 — silence, dépend de silence_type (grid_questions.py, CC-08)
    silence_rule = _SILENCE_ETAT if question.get("silence_type") == "etat" else _SILENCE_EVENEMENT

    # R11 — formes de preuve admises selon le mode de lecture
    proof_rule = _PROOF_FORMS_INSTRUCTION if doc_info["reading_mode"] == "instruction" else _PROOF_FORMS_SUIVI

    # R8 — couches temporelles (Type 3 seulement)
    temporal = _TEMPORAL_RULE_TYPE3 if document_type == 3 else _TEMPORAL_RULE_OTHER

    # R9 — hiérarchie des sources (Types 2-3 seulement)
    hierarchy = _HIERARCHY_RULE_TYPE23 if document_type in (2, 3) else _HIERARCHY_RULE_OTHER

    # Few-shot — cf. _FEW_SHOT_EXAMPLES, "" si aucun cas annoté pour ce code
    few_shot = _FEW_SHOT_EXAMPLES.get(question_code, "")

    # R2bis — articulation B.2.3/B.4.1 (correction V4) : CODE MORT DORMANT
    # depuis CC-V4-11, cf. docstring de _ARTICULATION_B23_B41 — ces codes
    # n'existent plus dans grid_questions.py, la condition ne matche donc
    # plus jamais.
    articulation = _ARTICULATION_B23_B41 if question_code in ("B.2.3", "B.4.1") else ""

    context = "\n---\n".join(context_chunks) if context_chunks else "(aucun passage fourni)"

    if question.get("inverted_polarity"):
        return _B31_PROMPT_TEMPLATE.format(
            document_type_label=doc_info["label"],
            reading_mode=doc_info["reading_mode"],
            question_r=question["question_r"],
            context_chunks=context,
            silence_rule=silence_rule,
            proof_forms_rule=proof_rule,
            few_shot_section=few_shot,
        )

    return _STANDARD_PROMPT_TEMPLATE.format(
        document_type_label=doc_info["label"],
        reading_mode=doc_info["reading_mode"],
        question_r=question["question_r"],
        context_chunks=context,
        materialisation_rule=materialisation_rule,
        silence_rule=silence_rule,
        proof_forms_rule=proof_rule,
        articulation_rule=articulation,
        temporal_rule=temporal,
        hierarchy_rule=hierarchy,
        few_shot_section=few_shot,
    )


# ============================================================================
# Parsing de la réponse LLM
# ============================================================================

# FRAGILE: regex ancrées en début de ligne (^, re.MULTILINE) plutôt qu'un
# split naïf — tolère des lignes vides ou dans un ordre légèrement
# différent, cohérent avec la tolérance déjà appliquée dans
# deep_analysis._parse_pass1_response face à un modèle 4B.
# FRAGILE (bug corrigé, CC-V4-06) : le "\s*" après les deux-points est
# volontairement remplacé par "[ \t]*" (espaces/tabs, PAS \n) — "\s"
# inclut le saut de ligne, donc "\s*" après ":" pour un champ VIDE
# ("EVIDENCE_R:\n") avalait le \n et le "(.*)$" capturait alors toute la
# ligne SUIVANTE au lieu d'une chaîne vide. Repéré via grid_analyze.py :
# evidence_r/evidence_a se retrouvaient peuplés du contenu du champ
# suivant sur toute réponse LLM où un champ optionnel était vide.
_LINE_PATTERNS = {
    "status":               re.compile(r"^STATUS\s*:[ \t]*(OUI|NON|INCONNU)\b", re.IGNORECASE | re.MULTILINE),
    "evidence_r":           re.compile(r"^EVIDENCE_R\s*:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE),
    "page":                 re.compile(r"^PAGE\s*:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE),
    "mitigation_status":    re.compile(r"^MITIGATION_STATUS\s*:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE),
    "evidence_mesure":      re.compile(r"^EVIDENCE_MESURE\s*:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE),
    "evidence_defaillance": re.compile(r"^EVIDENCE_DEFAILLANCE\s*:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE),
    "subject_filter":       re.compile(r"^SUJET\s*:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE),
    "confidence_note":      re.compile(r"^CONFIDENCE\s*:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE),
}

_VALID_SUBJECT_FILTERS = ("SPV", "PRÊTEUR", "SUBSTITUTION", "AMBIGU", "INDIRECT")


def parse_response(raw_response):
    """Parse la réponse LLM V4 ligne par ligne.
    CHOIX: regex simple, pas de JSON parsing — cohérent avec deep_analysis.py.
    FRAGILE: le modèle 4B ne suit pas toujours le format parfaitement.

    Champs attendus : STATUS, EVIDENCE_R, PAGE, MITIGATION_STATUS,
    EVIDENCE_MESURE, EVIDENCE_DEFAILLANCE, SUJET (R10), CONFIDENCE.

    Retourne un dict {status, evidence_r, page, mitigation_status,
    evidence_mesure, evidence_defaillance, subject_filter, confidence_note}
    ou None si le parsing échoue (pas de ligne STATUS exploitable).

    R10 : subject_filter n'est PAS un filtre appliqué ici en post-traitement
    — c'est le LLM qui évalue le sujet dans le prompt (cf. get_prompt).
    Cette fonction se contente de lire ce que le LLM a répondu, avec un
    repli sûr sur "SPV" si le champ est absent ou invalide (fail-open,
    cohérent ADR-002 : ne jamais bloquer sur un champ mal formé).
    """
    if not raw_response:
        return None

    status_match = _LINE_PATTERNS["status"].search(raw_response)
    if not status_match:
        logger.warning("grid_prompts: aucune ligne STATUS exploitable — parsing échoué.")
        return None

    def _field(key):
        m = _LINE_PATTERNS[key].search(raw_response)
        return m.group(1).strip() if m else ""

    mitigation_status = _field("mitigation_status").upper()
    if mitigation_status in ("", "N/A") or mitigation_status not in grid_questions.MITIGATION_STATUTS:
        mitigation_status = None

    page = _field("page") or "inconnue"

    subject_filter = _field("subject_filter") or "SPV"
    if subject_filter not in _VALID_SUBJECT_FILTERS:
        subject_filter = "SPV"  # repli sûr, cf. docstring

    return {
        "status": status_match.group(1).strip().upper(),
        "evidence_r": _field("evidence_r"),
        "page": page,
        "mitigation_status": mitigation_status,
        "evidence_mesure": _field("evidence_mesure"),
        "evidence_defaillance": _field("evidence_defaillance"),
        "subject_filter": subject_filter,
        "confidence_note": _field("confidence_note") or None,
    }
