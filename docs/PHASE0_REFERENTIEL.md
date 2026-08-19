# Phase 0 — Référentiel des 12 questions & mapping signals.py

Date : 2026-08-16. Extraction et structuration uniquement — aucune
implémentation de pipeline dans ce document (cf. directive Phase 0).
`signals.py` reste le mécanisme de pré-filtrage du MVP ; les 12 questions
sont reprises telles quelles (baseline de travail, cf.
`DIRECTIVE_CLAUDE_CODE_ESG_V3 (1).md` §"Questions de la grille" : ne pas
les modifier sans validation Elisa).

## Sources lues

| Document | Rôle |
|---|---|
| `1_Maquette_Vierge_Grille_ESG (1).pdf` | Grille — formulations exactes des 12 questions R/A, barème, plafonds |
| `Guide_Methodologique_Scoring_ESG (1).pdf` | Rationale du barème, étapes du pipeline cible, 5 questions Elisa/Claude déjà débattues |
| `Note_de_Cadrage_Refonte_Outil_ESG.pdf` | 7 décisions actées (14/08/2026), codebook d'annotation (PERMIT, COMM, QUALIF, ESAP-GAP, SPONSOR-DEP, EVOL, GOV-RISK), cas déclencheur CBG Expansion |
| `2_Application_CGPL_Mundra_23-100 (1).pdf` | Application chiffrée de la grille sur le cas Mundra — verbatims réels, utilisé ici uniquement comme illustration du type de preuve textuelle attendue par question, jamais comme source de formulation |
| `DIRECTIVE_CLAUDE_CODE_ESG_V3 (1).md` | Directive opérationnelle en vigueur — confirme que les 12 questions sont la baseline, référence la convention `PENDING_ELISA` |
| `scripts/signals.py` | Mécanisme de pré-filtrage actuel (intégralité lue) |
| `scripts/config.py` | Feature flags (aucun lié à la grille à ce jour) |
| `data/raw/corpus_cao_ifc.xlsx` | Ground truth existant — voir `docs/AUDIT_REPOSITORY.md` pour le détail (76 lignes, colonnes Flag/Censored/Notes) |

Aucun fichier « codebook » séparé n'a été trouvé : les 7 codes cités dans
la Note de Cadrage (décision 5 — `PERMIT`, `COMM`, `QUALIF`, `ESAP-GAP`,
`SPONSOR-DEP`, `EVOL`, `GOV-RISK`) n'apparaissent nulle part ailleurs dans
le repo (recherche exhaustive, hors un faux positif sur le mot
« qualificatifs » dans `PROMPT_CLAUDE_CODE_ESG.md`). Voir PENDING-6.

---

## 1. Les 12 fiches questions

### Catégorie A — Facteurs de Risque Majeurs / Bloqueurs
Pénalité brute : **−25 pts** | Gain atténuation max : **+5 pts** (ratio 20 %) | Impact net si atténué : **−20 pts**

---

**ID : A.1.1**
Catégorie : A (Facteur de Risque Majeur)
Sous-thème : Oppositions
Question Risque (R) : « Blocage physique du site ou grève active ? »
Question Mitigation (A) : « Un accord d'indemnisation ou de médiation a-t-il été signé avec les parties ? »
Pénalité brute : −25 pts | Gain atténuation : +5 pts
Éléments à rechercher : la Maquette et le Guide ne détaillent pas de liste de mots-clés par question — seule la formulation R fait foi, plus la règle transversale du Guide (Étape 4-5) : verbatim brut obligatoire pour R ; pour A, preuve d'un « accord formel, investissement vérifié, ou certification tierce — jamais une simple intention ». Illustration (pas une norme) tirée du cas Mundra appliqué : R confirmé par un verbatim décrivant un blocage physique mené par une communauté de pêcheurs ; A confirmé par un verbatim citant un programme d'indemnisation nommé et daté.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.1
Statut : VALIDÉ_MÉTHODOLOGIE

---

**ID : A.1.2**
Catégorie : A
Sous-thème : Oppositions
Question Risque (R) : « Actions en justice suspensives à l'encontre du projet ? »
Question Mitigation (A) : « Un désistement, un jugement favorable ou un accord transactionnel a-t-il été obtenu ? »
Pénalité brute : −25 pts | Gain atténuation : +5 pts
Éléments à rechercher : idem A.1.1 — pas de checklist explicite dans le Guide au-delà de la formulation R elle-même (procédure judiciaire suspensive en cours) et de la règle générale de preuve pour A.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.1
Statut : VALIDÉ_MÉTHODOLOGIE

---

**ID : A.2.1**
Catégorie : A
Sous-thème : Conformité
Question Risque (R) : « Suspension / annulation d'un permis d'exploiter ? »
Question Mitigation (A) : « Une régularisation administrative formelle a-t-elle été obtenue ? »
Pénalité brute : −25 pts | Gain atténuation : +5 pts
Éléments à rechercher : formulation R seule + règle générale de preuve pour A. Aucune liste de types de permis n'est fournie par le Guide.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.1
Statut : VALIDÉ_MÉTHODOLOGIE

---

**ID : A.2.2**
Catégorie : A
Sous-thème : Conformité
Question Risque (R) : « Retrait d'un co-financeur / bailleur majeur (ex. IFC) ? »
Question Mitigation (A) : « Un refinancement ou un bailleur de substitution a-t-il été sécurisé ? »
Pénalité brute : −25 pts | Gain atténuation : +5 pts
Éléments à rechercher : formulation R seule. Note : dans l'application Mundra, cette question est évaluée NON avec le verbatim « Non renseigné dans l'extrait audité par NLP » — c'est-à-dire qu'aucun passage pertinent n'a été trouvé, pas qu'un passage confirme l'absence de retrait. Voir PENDING-2 (source de la donnée).
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.1 ; illustration `2_Application_CGPL_Mundra_23-100 (1).pdf`, p.1
Statut : PENDING_ELISA (formulation non ambiguë, mais voir PENDING-2 sur la faisabilité de la réponse à partir du seul document uploadé)

---

**ID : A.3.1**
Catégorie : A
Sous-thème : Faisabilité
Question Risque (R) : « Injonction d'arrêt administratif signifiée ? »
Question Mitigation (A) : « La levée de l'injonction a-t-elle été prononcée ? »
Pénalité brute : −25 pts | Gain atténuation : +5 pts
Éléments à rechercher : formulation R seule + règle générale de preuve. Chevauchement sémantique possible avec A.2.1 (suspension de permis) — voir PENDING-1.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.1
Statut : VALIDÉ_MÉTHODOLOGIE

---

**ID : A.3.2**
Catégorie : A
Sous-thème : Faisabilité
Question Risque (R) : « Accident structurel / rupture d'ouvrage ? »
Question Mitigation (A) : « Une réparation certifiée par un tiers indépendant a-t-elle été validée ? »
Pénalité brute : −25 pts | Gain atténuation : +5 pts
Éléments à rechercher : formulation R seule. La mitigation exige explicitement une certification tierce (pas juste « réparé »), cohérent avec la règle générale du Guide.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.2
Statut : VALIDÉ_MÉTHODOLOGIE

---

### Catégorie B — Risques Structurants
Pénalité brute : **−15 pts** | Gain atténuation max : **+3 pts** (ratio 20 %) | Impact net si atténué : **−12 pts**

---

**ID : B.1.1**
Catégorie : B (Risque Structurant)
Sous-thème : Communautaire
Question Risque (R) : « Perte de moyens de subsistance sans compensation ? »
Question Mitigation (A) : « Un plan de restauration des moyens de subsistance (LRP) est-il déployé ? »
Pénalité brute : −15 pts | Gain atténuation : +3 pts
Éléments à rechercher : formulation R seule ; l'application Mundra illustre A par un verbatim citant un LRP nommé avec des mesures concrètes (bateaux, glacières) — cohérent avec la règle « preuve, pas intention » du Guide.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.2
Statut : VALIDÉ_MÉTHODOLOGIE

---

**ID : B.1.2**
Catégorie : B
Sous-thème : Communautaire
Question Risque (R) : « Déplacement involontaire de populations non réinstallées ? »
Question Mitigation (A) : « Un plan de réinstallation conforme a-t-il été exécuté ? »
Pénalité brute : −15 pts | Gain atténuation : +3 pts
Éléments à rechercher : formulation R seule.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.2
Statut : VALIDÉ_MÉTHODOLOGIE

---

**ID : B.2.1**
Catégorie : B
Sous-thème : Pollution
Question Risque (R) : « Dépassements récurrents des seuils Air (PM10) ? »
Question Mitigation (A) : « Des dômes de confinement ou mesures d'abattement ont-ils été installés ? »
Pénalité brute : −15 pts | Gain atténuation : +3 pts
Éléments à rechercher : formulation R seule — spécifique à un polluant (PM10) et donc à des projets avec émissions atmosphériques industrielles (centrale, cimenterie, mine à ciel ouvert). Voir PENDING-3 sur l'applicabilité sectorielle.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.2
Statut : PENDING_ELISA (formulation exacte non ambiguë, mais applicabilité hors secteur énergie/industrie lourde à trancher — cf. Guide p.6, discussion Elisa/Claude sur les modules sectoriels)

---

**ID : B.2.2**
Catégorie : B
Sous-thème : Pollution
Question Risque (R) : « Défaut de modélisation du rejet thermique (Eau) ? »
Question Mitigation (A) : « Une étude de dispersion thermique à jour a-t-elle été validée ? »
Pénalité brute : −15 pts | Gain atténuation : +3 pts
Éléments à rechercher : formulation R seule — spécifique aux projets avec rejet d'eau de refroidissement (centrale thermique/nucléaire). Même réserve sectorielle que B.2.1.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.2
Statut : PENDING_ELISA (même réserve sectorielle que B.2.1)

---

**ID : B.3.1**
Catégorie : B
Sous-thème : Gouvernance
Question Risque (R) : « Absence de données de référence (baseline) socio-économiques ? »
Question Mitigation (A) : « Des études complémentaires couvrent-elles l'intégralité de la zone d'influence ? »
Pénalité brute : −15 pts | Gain atténuation : +3 pts
Éléments à rechercher : formulation R seule.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.2
Statut : VALIDÉ_MÉTHODOLOGIE

---

**ID : B.3.2**
Catégorie : B
Sous-thème : Gouvernance
Question Risque (R) : « Absence de suivi périodique des données RSE ? »
Question Mitigation (A) : « Un reporting ESG périodique a-t-il été rétabli et vérifié ? »
Pénalité brute : −15 pts | Gain atténuation : +3 pts
Éléments à rechercher : formulation R seule. Dans l'application Mundra, R est évalué NON sur la base d'un verbatim affirmant que « des rapports de suivi sont transmis annuellement au prêteur » — c'est-à-dire qu'un document isolé peut, à la marge, attester positivement d'une pratique récurrente. Mais juger une « absence de suivi PÉRIODIQUE » à partir d'un document unique (une photo à l'instant T) est structurellement en tension avec la mémoire inter-dossier prévue par la Note de Cadrage (décision 6, "EVOL") mais pas encore construite. Voir PENDING-4.
Source : `1_Maquette_Vierge_Grille_ESG (1).pdf`, p.2-3
Statut : PENDING_ELISA (voir PENDING-4)

---

## 2. Tableau de mapping questions ↔ signals.py

`signals.py` n'expose qu'une seule fonction publique,
`flags_mentioned_in_text(text) -> set[int]`, qui renvoie des numéros de
**flag** (1, 2 ou 3) — pas de sous-thème, pas de question. Le dict module
`SIGNAL_PATTERNS` (10 catégories de signal au total, sous les 3 flags) est
importable directement et pourrait en théorie servir de pré-filtre à une
granularité plus fine que `flags_mentioned_in_text()`, mais **il n'y a pas
de correspondance 1:1** : 10 catégories de signal existantes vs 12
questions de la grille, et surtout les 3 flags actuels (communauté /
pollution / conformité) ne couvrent que 2 des 6 sous-thèmes de la nouvelle
grille (Communautaire, Pollution) — Oppositions, Conformité, Faisabilité
et Gouvernance n'ont pas d'équivalent direct.

| Question | Flag(s) `signals.py` topicalement proches | Mots-clés qui matchent | Fonction utilisable | Évaluation | Signal manquant si INSUFFISANT/PARTIEL |
|---|---|---|---|---|---|
| A.1.1 (blocage/grève) | Flag 1 — `community opposition` | `opposition`, `protest`, `resist` (adjacents ; ni "blocage"/"blockade" ni "grève"/"strike" ne sont des mots-clés) | `flags_mentioned_in_text` (renvoie flag 1, pas le signal précis) | **PARTIEL** | vocabulaire spécifique blocage physique / grève |
| A.1.2 (actions en justice suspensives) | Aucun | — | — | **INSUFFISANT** | tout le champ lexical juridique/contentieux (lawsuit, injunction, court, litigation, legal action) — absent des 3 flags |
| A.2.1 (suspension/annulation permis) | Flag 3 — `ESAP delays` (`non-compliance`) très indirect | `non-compliance` (générique, pas "permit"/"license"/"revoked"/"suspended") | `flags_mentioned_in_text` (flag 3) | **INSUFFISANT** | vocabulaire permis/licence (permit, license, revoke, suspend, cancel) |
| A.2.2 (retrait bailleur/IFC) | Aucun | — | — | **INSUFFISANT** | vocabulaire retrait de financement (withdraw, divest, lender exit, pull out) |
| A.3.1 (injonction d'arrêt) | Aucun | — | — | **INSUFFISANT** | vocabulaire injonction administrative (injunction, stop-work order, cease and desist, shutdown order) |
| A.3.2 (accident structurel/rupture) | Flag 2 — `spill risk` | `spill`, `leak`, `seepage`, `tailings` (adjacents à une rupture d'ouvrage minier/hydraulique, mais pas "structural failure"/"dam break"/"collapse") | `flags_mentioned_in_text` (flag 2) | **PARTIEL** | vocabulaire rupture d'ouvrage générique (structural failure, collapse, dam breach) |
| B.1.1 (perte moyens de subsistance sans compensation) | Flag 1 — `stakeholder conflict` | `livelihood` (match direct) | `flags_mentioned_in_text` (flag 1) | **PARTIEL** | la négation « sans compensation » n'est pas détectable par mot-clé — nécessite le filtre de polarité LLM (`llm_confirm.confirm_risk`), pas `signals.py` seul |
| B.1.2 (déplacement involontaire non réinstallées) | Flag 1 — `displacement risk` | `displace`, `resettle`, `relocat`, `involuntary` (couverture directe et complète) | `flags_mentioned_in_text` (flag 1) | **SUFFISANT** | — (mais même réserve que B.1.1 : « non réinstallées » = polarité, pas mot-clé) |
| B.2.1 (dépassements PM10 Air) | Flag 2 — `monitoring gaps`, `pollution risk` | `threshold`, `exceedance`, `emission` (génériques) | `flags_mentioned_in_text` (flag 2) | **PARTIEL** | spécificité polluant (PM10, particulate matter, air quality) absente |
| B.2.2 (défaut modélisation rejet thermique Eau) | Flag 2 — `pollution risk` | `discharge`, `effluent` (génériques) | `flags_mentioned_in_text` (flag 2) | **PARTIEL** | spécificité thermique/eau (thermal discharge, mixing zone, water temperature) absente |
| B.3.1 (absence baseline socio-éco) | Flag 2 — `monitoring gaps` | `baseline` (match direct, mais catégorisé sous le flag "pollution", pas un flag gouvernance) | `flags_mentioned_in_text` (flag 2, catégorie sémantiquement mal alignée) | **PARTIEL** | pas de flag "gouvernance" dans `signals.py` — voir note ALT non implémentée dans le fichier lui-même (`# 4: {"governance risk": [...]}`, commentée, jamais ajoutée) |
| B.3.2 (absence suivi périodique RSE) | Flag 2 — `monitoring gaps` (`monitor`, très générique) | `monitor` | `flags_mentioned_in_text` (flag 2) | **INSUFFISANT** | vocabulaire reporting ESG périodique (periodic reporting, annual disclosure, monitoring report submission) — `monitor` seul est trop générique et sur-matche |

---

## 3. Résumé de couverture

Sur les 12 questions de la grille, en utilisant `signals.py` tel quel comme pré-filtre :

- **SUFFISANT : 1/12** (B.1.2)
- **PARTIEL : 6/12** (A.1.1, A.3.2, B.1.1, B.2.1, B.2.2, B.3.1)
- **INSUFFISANT : 5/12** (A.1.2, A.2.1, A.2.2, A.3.1, B.3.2)

Constats structurels (au-delà du décompte par question) :

1. **Aucune question de la sous-partie "Faisabilité" (A.3.x) ni "Conformité" (A.2.x) n'est bien couverte** — ces deux sous-thèmes rassemblent des notions juridiques/administratives (permis, injonction, retrait de bailleur, contentieux) totalement absentes du vocabulaire actuel de `signals.py`, qui a été construit pour un usage différent (repérage thématique large ESG, pas suivi d'actes administratifs).
2. **Le flag 3 actuel ("compliance/conformité", `ESAP delays` + `PS non-conformance`) ne recouvre pas la Conformité de la nouvelle grille** — il porte sur les délais d'ESAP et la non-conformité aux Performance Standards IFC, pas sur les permis/licences/injonctions au sens strict de A.2.1/A.3.1.
3. **Aucun signal "gouvernance" n'existe** — B.3.1 et B.3.2 (sous-thème Gouvernance) n'ont de recoupement qu'indirect via `monitoring gaps` (flag 2, catégorisé "pollution"). `signals.py` porte lui-même la trace de cette lacune (commentaire ALT non implémenté pour un flag 4 "governance risk").
4. **Les négations et conditions de preuve ne sont pas capturables par mot-clé** — plusieurs questions R contiennent une négation implicite ("sans compensation", "non réinstallées", "absence de") que seul un filtre de polarité (type `llm_confirm.confirm_risk`, déjà existant) peut trancher ; `signals.py` seul ne peut que repérer le sujet, jamais la polarité — cohérent avec la limite déjà documentée dans le code actuel (`search.py`, commentaire sur `_gate_flags_with_llm`).
5. **10 catégories de signal existantes ne s'alignent pas sur 12 questions** — même en abandonnant la fonction `flags_mentioned_in_text()` pour utiliser `SIGNAL_PATTERNS` directement (granularité catégorie plutôt que flag), il n'y a pas de correspondance 1:1 avec les 12 questions.

---

## 4. Section PENDING_ELISA

### PENDING-1 — Chevauchement Faisabilité / Conformité (A.3.1 vs A.2.1)
Contexte : A.2.1 (Conformité) demande « Suspension / annulation d'un permis d'exploiter ? » et A.3.1 (Faisabilité) demande « Injonction d'arrêt administratif signifiée ? ». Les deux documents sources (Maquette, Guide) ne définissent pas de critère de distinction entre les deux.
Problème : une injonction d'arrêt administratif ET une suspension de permis peuvent être le même acte réglementaire vu sous deux angles (l'autorité suspend le permis en émettant une injonction). Un même verbatim source pourrait légitimement répondre OUI aux deux questions, doublant la pénalité (−25 −25 = −50 pts) pour un seul fait générateur.
Options possibles :
  A. Les deux questions sont volontairement redondantes (ceinture et bretelles) — le double comptage est assumé par le barème.
  B. Un critère de distinction existe dans la tête de l'auteur de la grille (ex. A.2.1 = acte définitif/permanent, A.3.1 = mesure provisoire/conservatoire) mais n'est écrit nulle part.
  C. Il faut une règle explicite d'exclusion mutuelle (« si A.2.1 = OUI, ne pas compter A.3.1 pour le même fait »).
Impact sur le pipeline : détermine si le prompt LLM par question doit inclure une instruction de désambiguïsation, et si le score Mundra (23/100, validé) reste atteignable avec une règle d'exclusion — actuellement, dans l'application Mundra, seule A.1.1 est à OUI côté Cat A (A.2.1 et A.3.1 sont toutes deux à NON), donc le cas de calibration ne permet pas de trancher empiriquement.

### PENDING-2 — A.2.2 (retrait de bailleur) : la donnée est-elle dans le document uploadé ?
Contexte : dans l'application Mundra, A.2.2 est évaluée NON avec le verbatim « Non renseigné dans l'extrait audité par NLP » — c'est-à-dire qu'aucune information sur un retrait de bailleur n'a été trouvée dans CE document (un rapport ISA), pas qu'une clause du document confirme l'absence de retrait.
Problème : un retrait de bailleur institutionnel (ex. IFC en 2018 sur Mundra) est typiquement documenté dans la presse ou les communiqués du bailleur, rarement dans le rapport E&S du projet lui-même qui est souvent antérieur ou simplement muet sur ce sujet. Si la seule source consultée est le document uploadé par l'analyste, cette question risque de retourner NON par défaut sur (quasiment) tous les dossiers, y compris ceux où un retrait a réellement eu lieu — un faux négatif structurel, pas un signal fiable.
Options possibles :
  A. La question reste répondue uniquement à partir du document uploadé (cohérent avec l'architecture actuelle mono-document), avec le risque de faux négatif assumé et documenté.
  B. Cette question nécessite une source externe (ex. le champ `Category`/`Notes` de `corpus_cao_ifc.xlsx`, ou une saisie manuelle par l'analyste hors pipeline NLP) — sort du périmètre "extraction NLP automatique".
Impact sur le pipeline : si B, A.2.2 n'est pas un candidat pour l'extraction automatique Pass 1/LLM comme les 11 autres questions — elle devient un champ à renseigner manuellement dans l'interface, ce qui change le contrat d'interface (human-in-the-loop pur, pas de pré-remplissage).

### PENDING-3 — Applicabilité sectorielle de B.2.1/B.2.2 (PM10, rejet thermique)
Contexte : le Guide Méthodologique lui-même (Question 3, p.6) reconnaît que les 12 questions sont dérivées du cas Mundra (centrale à charbon) et que des secteurs comme l'immobilier ou l'aéronautique n'ont pas de questions équivalentes ; l'auteur de la note y répond « Oui ça peut valoir le coût » pour ces deux secteurs spécifiquement.
Problème : B.2.1 (seuils PM10 air) et B.2.2 (rejet thermique eau) sont non pertinentes pour la majorité des dossiers hors énergie thermique/industrie lourde. Sur un projet sans émissions atmosphériques industrielles ni rejet d'eau de refroidissement, ces deux questions répondront structurellement NON (aucun verbatim possible), ce qui n'est pas un signal de qualité du projet mais une question mal posée pour ce secteur — à distinguer d'un vrai NON informatif.
Options possibles :
  A. Garder les 12 questions telles quelles pour tous les secteurs (les NON non informatifs sont acceptés comme un artefact connu).
  B. Ajouter un statut [N/A — hors périmètre sectoriel] distinct de NON pour ces cas, nécessitant une classification préalable du secteur du projet (déjà esquissée par `deep_analysis.guess_project_type`, mais qui n'alimente aujourd'hui que le prompt Pass 2, pas un routage de questions).
  C. Modules sectoriels en complément du tronc commun (évoqué par le Guide comme piste, jamais formalisé dans aucun document source).
Impact sur le pipeline : B et C demandent une étape de classification sectorielle en amont de l'évaluation des 12 questions — absente du pipeline MVP décrit dans `DIRECTIVE_CLAUDE_CODE_ESG_V3 (1).md`.

### PENDING-4 — B.3.2 (absence de suivi périodique) : évaluable sur un document unique ?
Contexte : B.3.2 demande si le suivi RSE est absent « périodiquement » — une notion intrinsèquement multi-documents/multi-temporelle. La Note de Cadrage prévoit une « Mémoire inter-dossier pour l'EVOL » (décision 6) qui compare les rapports successifs d'un même projet, mais ce mécanisme n'est pas encore construit (confirmé par `docs/AUDIT_REPOSITORY.md` : aucune trace de mémoire multi-rapports dans le code actuel).
Problème : sans historique multi-rapports, le LLM ne peut évaluer B.3.2 qu'à partir d'indices indirects dans le document unique (ex. une mention explicite « rapports transmis annuellement », comme dans le cas Mundra) — ce qui fonctionne quand le document se prononce explicitement sur sa propre récurrence, mais échoue silencieusement (NON par défaut, faussement rassurant) si le document est simplement muet sur le sujet.
Options possibles :
  A. B.3.2 reste évaluée sur le document unique dans le MVP, avec la limite documentée : un NON signifie « pas de mention de suivi périodique dans CE document », pas « suivi confirmé absent ».
  B. B.3.2 est mise en attente (non évaluée, affichée [N/A — nécessite historique]) jusqu'à ce que la mémoire inter-dossier (décision 6) soit implémentée.
Impact sur le pipeline : B retire une question du calcul du score pour tous les dossiers tant que la mémoire EVOL n'existe pas, ce qui change la base du barème (11 questions actives au lieu de 12) — à trancher avant toute implémentation du scoring déterministe.

### PENDING-5 — Ratio de mitigation uniforme à 20 % malgré des preuves de nature très différente
Contexte : le Guide Méthodologique (Question 4) demande lui-même si « un accord d'indemnisation signé (légalement contraignant) et une étude de dispersion thermique reportée (aucune action) méritent le même bonus » — actuellement oui pour les deux à la même catégorie (même +5 ou +3 selon Cat A/B), sans distinction sur la force probante de la preuve.
Problème : ce n'est pas une question d'extraction NLP au sens strict, mais elle conditionne directement comment noter la sous-question A pour chacune des 12 questions — un accord juridiquement contraignant (A.1.1) et une étude « en cours » (B.2.2, où le verbatim Mundra dit explicitement qu'elle a été « reportée sans action immédiate », donc évaluée NON) ne sont pas au même niveau de preuve, mais le barème actuel ne prévoit qu'un OUI/NON binaire par sous-question A, sans niveau intermédiaire.
Options possibles :
  A. Garder le binaire strict tel que documenté (le Guide penche pour cette option : « on pourrait imaginer des niveaux de mitigation... si Elisa le juge pertinent », donc pas acté).
  B. Introduire des niveaux de mitigation (partielle/complète) — évoqué mais explicitement non tranché par le Guide lui-même.
Impact sur le pipeline : B change le format de sortie attendu du LLM pour la sous-question A (plus binaire), le calcul du score (barème à 3 niveaux au lieu de 2), et la comparabilité avec l'ancrage Mundra (calculé en binaire).

### PENDING-6 — Codebook d'annotation (Note de Cadrage, décision 5) : contenu et mapping introuvables
Contexte : la Note de Cadrage mentionne un « codebook d'annotation (`PERMIT`, `COMM`, `QUALIF`, `ESAP-GAP`, `SPONSOR-DEP`, `EVOL`, `GOV-RISK`) » qui « reste un outil interne d'aide à la détection NLP » distinct des flags affichés.
Problème : ce codebook n'existe dans aucun fichier du repo (recherche exhaustive effectuée) — ni définition, ni mapping vers les 12 questions ou les 6 sous-thèmes. Il compte 7 codes pour 6 sous-thèmes et 12 questions, sans qu'aucune règle de correspondance ne soit documentée (7 ≠ 6 et 7 ≠ 12, donc pas de mapping évident 1:1 dans un sens ou l'autre).
Options possibles :
  A. Le codebook reste à créer de zéro en Phase 1, en s'appuyant sur les 12 questions comme référence unique (le codebook serait alors dérivé, pas une source indépendante).
  B. Le codebook existe déjà quelque part hors de ce repo (dans les échanges Stacy/Archange, un autre document non transmis) et doit être récupéré avant la Phase 1.
Impact sur le pipeline : si le codebook est censé structurer l'annotation interne (ex. pour ré-annoter `corpus_cao_ifc.xlsx` ou entraîner un futur classifieur), la Phase 1 ne peut pas le réutiliser tel quel tant que sa définition n'est pas retrouvée ou reconstruite — actuellement aucun fichier ne fait le pont entre ces 7 codes et les 12 A.x/B.x.
