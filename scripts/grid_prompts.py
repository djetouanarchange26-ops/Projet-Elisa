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
    de document conditionne R11/R8/R9 mais ne change ni R1 ni R2 ni R7bis
    ni R10 — ces règles sont universelles, valables sur les 4 types.
  - parse_response() : nouveau champ SUJET (R10), en plus des champs
    hérités (MITIGATION_STATUS remplace le binaire MITIGATION de CC-02,
    cf. CC-07 ; EVIDENCE_MESURE/EVIDENCE_DEFAILLANCE remplacent
    EVIDENCE_MITIGATION unique pour porter le double verbatim du statut 4).
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
ATTENTION A.1.3 : les rapports CAO résument souvent des manifestations historiques. Vérifier la couche temporelle avant de cocher OUI."""

_TEMPORAL_RULE_OTHER = ""  # Pas de règle temporelle pour Type 1, 2, 4

_HIERARCHY_RULE_TYPE23 = """R9 — HIÉRARCHIE DES SOURCES :
1. Constat de l'auditeur indépendant (CAO, panel, expert tiers)
2. Observation directe en visite de terrain
3. Donnée chiffrée fournie par un tiers (labo, régulateur)
4. Témoignage de plaignant
5. Déclaration non étayée du client
RÈGLE : une déclaration client contredite par un constat d'auditeur dans le même document ne peut JAMAIS servir de mitigation."""

_HIERARCHY_RULE_OTHER = ""

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

R2 — MATÉRIALISATION : seul un FAIT DATÉ, SURVENU, ATTRIBUÉ AU PROJET déclenche un OUI. Un droit, une politique, une procédure, une vulnérabilité future = NON. Vérifier : verbe au passé accompli + fait daté + attribution causale au projet.

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
4. OUI_DEFAILLANTE — OK portes 1 et 2, MAIS le document établit que la mesure n'a pas produit son effet ou a été interrompue. Citer les DEUX passages.

R7bis — ITEMS ESAP : un item d'ESAP = obligation non encore remplie. Alimente toujours le risque, jamais la mitigation.

R10 — FILTRE DE SUJET : identifier le sujet du manquement.
- Sujet = société de projet, sponsor, contractants, installation → alimente le score.
- Sujet = institution financière, auditeur, mécanisme de recours → N'ALIMENTE PAS le score. Chercher un verbatim de substitution portant sur le même fait avec le client pour sujet AVANT de faire basculer la réponse.

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
EVIDENCE_DEFAILLANCE: [passage de la défaillance si statut 4 — ou vide]
SUJET: SPV ou PRÊTEUR ou SUBSTITUTION
CONFIDENCE: [explication du doute — ou vide]
"""

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
EVIDENCE_DEFAILLANCE: [si statut 4 — ou vide]
SUJET: SPV ou PRÊTEUR ou SUBSTITUTION
CONFIDENCE: [si doute — ou vide]
"""

# ============================================================================
# Few-shot par question — cas réels des 4 dossiers annotés (CBG, Mundra,
# Aysha, Indorama). AUCUN exemple inventé — cf. "Ce qu'il ne faut PAS
# faire" de CC-V4-05. Les questions absentes de ce dict (A.4.1, B.2.1,
# B.2.3) n'ont simplement pas de cas annoté encore disponible.
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
""",

    "A.1.3": """
=== EXEMPLES DE RÉFÉRENCE ===

PIÈGE R8 — couche temporelle (Mundra/Type 3) :
Les rapports CAO résument souvent des manifestations historiques. Vérifier TOUJOURS la couche temporelle. Un blocage cité en résumé de la période 2013-2015 NE DÉCLENCHE PAS A.1.3 sur la période 2017-2025.

PIÈGE DE POLARITÉ — qui bloque qui ? :
Si c'est le PROJET qui bloque l'accès de la communauté (routes fermées, forces de sécurité) → B.1.1, JAMAIS A.1.3.
Si c'est la COMMUNAUTÉ qui bloque le projet → A.1.3.
""",

    "A.2.1": """
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

    "A.3.1": """
=== EXEMPLES DE RÉFÉRENCE ===

FAUX POSITIF — permis obtenu vs projet retardé (Aysha) :
« The ESIA has received Environmental Clearance from MoWIE... However, the project has been delayed for a significant period »
Les mots « permit », « delayed » et « mandatory » cohabitent. MAIS : l'autorisation A ÉTÉ OBTENUE. Le retard est celui du PROJET, pas du PERMIS. → NON

FAUX POSITIF — écart normatif vs irrégularité administrative (CBG) :
« gaps with the IFC Performance Standards were identified in the ESIA »
Écart avec les standards des PRÊTEURS, pas irrégularité vis-à-vis de l'AUTORITÉ qui a approuvé l'ESIA. → NON
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
""",

    "B.1.2": """
=== EXEMPLES DE RÉFÉRENCE ===

OUI_PROUVEE (CBG) :
« 24 of the 31 complaints have been processed and closed »
Chiffré, au passé, numérateur/dénominateur → statut 3

NON_FORME_INSUFFISANTE (CBG) :
« A complaints register was opened in 2015 »
Au passé, mais registre ≠ résultat → statut 2

PIÈGE — comité villageois (Mundra) :
Un comité consultatif villageois n'est ni accord signé, ni investissement, ni vérification tierce. Porte 2 échoue → statut 2.

PIÈGE — mécanisme ignoré des bénéficiaires (Mundra) :
« They were also unaware of the CGPL grievance redress function »
Le dispositif EXISTE mais ses destinataires l'IGNORENT → B.1.2 = OUI.
""",

    "B.2.2": """
=== EXEMPLES DE RÉFÉRENCE ===

ASYMÉTRIE RISQUE/MITIGATION — exemple canonique (CBG) :
« The existing plant has historically generated significant quantities of fugitive dust... ALTHOUGH additional filters and scrubbers were installed on the dryer stack in recent years. »
Filtres installés = mitigation authentique. Poussières persistantes = la mesure n'a pas produit son effet.
→ OUI_DEFAILLANTE. EVIDENCE_MESURE = filtres. EVIDENCE_DEFAILLANCE = poussières.

FAUX POSITIF — dépassement état initial (Indorama) :
« At night-time, measured LAeq exceeded the 45 dB IFC criterion at location N9 only »
Dépassement mesuré dans le chapitre état initial, AVANT travaux. Le projet n'en est pas la cause. → NON

FAUX POSITIF — dépassement géogénique (Indorama) :
« observed exceedances are likely attributable to natural background conditions typical of the regional geology »
Origine naturelle, pas anthropique. → NON

PIÈGE — déclaration client contredite (Mundra/R9) :
Déclaration client « no exceedances » sans donnée jointe, contredite par l'auditeur → ni NON ni mitigation.
""",

    "B.3.1": """
=== EXEMPLES DE RÉFÉRENCE ===

FAUX POSITIF — inventaire ≠ compensation (CBG) :
« An intensive primate survey of 142 km of transects is currently being undertaken »
Un inventaire est une donnée d'entrée, PAS une mesure de compensation. → NON (= risque)

FAUX POSITIF — partenariat ≠ déploiement (CBG/Mundra) :
L'annonce d'un partenariat avec une ONG de conservation ne franchit jamais la porte 2.

REFUS DE MONITORING — déclencheur aggravant (Mundra/R10) :
« The client later informed CRP that it was not prepared to carry out additional monitoring or share monitoring data »
Refus EXPLICITE du client de fournir des données → déclencheur, JAMAIS mitigation.
Sujet : le CLIENT (pas le prêteur). Verbatim de substitution supérieur à l'original (R10).

N/A VALIDE — pas d'habitat critique (Indorama) :
« the project area does not support Critical Habitat classification under IFC PS6 criteria »
Conclusion négative documentée. ATTENTION : un bon score ne doit jamais faire disparaître une espèce CR recensée sur l'emprise → verser au champ qualifiant.
""",

    "B.4.1": """
=== EXEMPLES DE RÉFÉRENCE ===

OUI (Mundra) :
Irritations cutanées liées à l'eau du canal de rejet de la centrale. Sujet : l'ouvrage du projet.

ARTICULATION B.4.1 / B.2.2 / B.2.3 :
- B.4.1 = dommage sur les PERSONNES
- B.2.2 = dépassement dans le MILIEU
- B.2.3 = événement ACCIDENTEL
Les trois peuvent se déclencher simultanément sur des faits distincts.

ALLÉGATION ≠ fait (CBG) :
« water contamination (by used oil, fuel) and impacts to local fish »
Allégation communautaire non confirmée par mesure → ALLÉGATION NON CONFIRMÉE (champ qualifiant), pas OUI.
""",
}


def get_prompt(question_code, context_chunks, document_type=1):
    """Assemble le prompt V4 pour une question donnée.

    CHOIX V4: le document_type conditionne :
    - les formes de preuve admises (R11)
    - les règles temporelles (R8, Type 3 seulement)
    - la hiérarchie des sources (R9, Types 2-3 seulement)
    Il ne change JAMAIS R1 (biais), R2 (matérialisation), R7bis (ESAP) ni
    R10 (filtre de sujet) — universels, valables sur les 4 types.

    Retourne None si question_code est inconnu (pas d'exception — cf.
    CC-V4-05 : l'appelant est censé valider le code en amont via
    grid_questions.get_question()).
    """
    question = grid_questions.get_question(question_code)
    if question is None:
        return None

    doc_info = grid_questions.DOCUMENT_TYPES.get(document_type, grid_questions.DOCUMENT_TYPES[1])

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
        silence_rule=silence_rule,
        proof_forms_rule=proof_rule,
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

_VALID_SUBJECT_FILTERS = ("SPV", "PRÊTEUR", "SUBSTITUTION")


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
