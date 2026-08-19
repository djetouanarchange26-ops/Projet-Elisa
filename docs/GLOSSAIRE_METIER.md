# Glossaire métier — ESG Risk Intelligence

Deux sections : le vocabulaire ESG/finance du domaine (IFC/CAO), et le
vocabulaire interne au projet (noms de champs, concepts propres au code).

## Vocabulaire ESG / finance de projet (domaine IFC/CAO)

| Terme | Définition |
|---|---|
| **ESG** | Environnemental, Social, Gouvernance — les 3 familles de risque analysées par l'outil |
| **IFC** | International Finance Corporation — bailleur de fonds privé, filiale du Groupe Banque Mondiale, finance des projets d'infrastructure/énergie dans les pays émergents |
| **CAO** | Compliance Advisor Ombudsman — mécanisme de plainte indépendant de l'IFC, reçoit les griefs de communautés affectées par un projet financé ; le corpus du projet (`corpus_cao_ifc.xlsx`) croise les dossiers CAO (`event=1`, projet avec plainte confirmée) et des projets contrôle sans plainte connue (`event=0`) |
| **ESIA** | Environmental and Social Impact Assessment — étude d'impact environnemental et social réalisée avant financement d'un projet |
| **ESAP** | Environmental and Social Action Plan — plan d'action correctif, souvent une condition de financement, avec un calendrier d'engagements à respecter |
| **Performance Standards (PS1–PS8)** | Les 8 normes de sauvegarde environnementale et sociale de l'IFC, référence de conformité pour tout projet financé. Les plus citées dans le code : **PS1** (évaluation et gestion des risques E&S), **PS6** (biodiversité et habitats naturels — voir "critical habitat"), **PS7** (peuples autochtones) |
| **FPIC** | Free, Prior and Informed Consent — consentement libre, préalable et éclairé, exigé des peuples autochtones affectés par un projet (lié à PS7) |
| **Réinstallation involontaire / involuntary resettlement** | Déplacement forcé de populations pour libérer l'emprise d'un projet — un des signaux de risque les plus graves suivis par l'outil (flag1) |
| **Grievance mechanism** | Mécanisme de plainte mis en place par un projet pour recueillir les griefs des communautés locales — son absence ou sa non-indépendance est un signal de risque |
| **Critical habitat** | Habitat critique au sens de PS6 — zone à forte valeur de biodiversité imposant des exigences renforcées (interdiction ou compensation stricte) |
| **Biodiversity offset** | Compensation biodiversité — mesure compensatoire pour un impact résiduel sur un habitat, exigée par PS6 |
| **Monitoring report** | Rapport de suivi périodique d'un projet déjà financé — c'est le type de document principal analysé par l'outil (45-70 pages typiquement) |
| **Due diligence** | Analyse préalable au financement — combine souvent plusieurs documents (ESIA + ESAP + Monitoring Report), d'où le support multi-documents de l'upload |
| **T0** | Date d'approbation du board IFC pour un projet — point de départ du calcul de `time_to_event` (voir `ifc_board_dates.py`) |

## Vocabulaire interne au projet (code / UI)

| Terme | Définition |
|---|---|
| **flag1 / flag2 / flag3** | Les 3 catégories de risque suivies par l'outil : **flag1_community** (opposition communautaire, déplacement, droits des parties prenantes), **flag2_pollution** (pollution, dépassements de seuils, déversements), **flag3_compliance** (biodiversité, non-conformité aux Performance Standards, retards ESAP) |
| **flag_score** | Score 0-100 par flag, dérivé du meilleur score de similarité (FAISS + pondération) parmi les chunks du document interrogé, après filtrage par polarité LLM |
| **rerank_score** | Score composite (similarité FAISS + spécificité + récence + type de chunk) qui remplace le score FAISS brut après pondération — nom conservé depuis l'ancien cross-encoder (retiré), pour ne pas casser les appelants existants |
| **risk_grade / risk_label** | Grade lettre A-D et son libellé, dérivés de `max(flag_scores)` vs seuils (`DEFAULT_RISK_THRESHOLDS`) : **D = Vigilance** (monitoring standard), **C = Attention** (revue renforcée à 90 jours), **B = Alerte** (downgrade proposé), **A = Escalade** (escalade immédiate au comité de crédit) — convention **A = pire**, **D = meilleur** |
| **confirm_risk / filtre de polarité** | Vérification LLM qu'un chunk qui MENTIONNE un sujet à risque le décrit réellement comme un problème (RISK) et non comme résolu/conforme (CLEAN) — corrige le fait que la similarité d'embedding capture le sujet mais pas la polarité |
| **fail-open** | Principe : si un appel LLM échoue (backend injoignable, timeout), l'outil retombe sur un comportement sûr par défaut (ex. `confirm_risk` retourne `True`) plutôt que de faire planter l'analyse |
| **specificity_score** | Score 0-1 mesurant à quel point un chunk est concret (chiffres, dates, unités, entités nommées précises) vs vague (formulations de type "des efforts raisonnables seront envisagés") — un rapport à faible spécificité est un signal de greenwashing potentiel |
| **chunk_type** | Classification rhétorique d'un chunk : `metric` (chiffré), `commitment` (engagement futur), `incident` (problème signalé), `narrative` (par défaut) |
| **section_type** | Classification thématique d'un chunk : `environmental` / `social` / `governance` / `general` — utilisé par la Pass 2 de `deep_analysis` pour construire la liste des thèmes couverts |
| **Deep Analysis — Pass 1 / Pass 2 / Pass 3** | Le pipeline LLM multi-pass de `deep_analysis.py` : **Pass 1** extrait, chunk par chunk, la présence d'un engagement chiffré / d'un incident / d'une formulation évasive ; **Pass 2** détecte les sujets ESG critiques absents du rapport (une seule fois, sur l'ensemble du document) ; **Pass 3** rédige une synthèse d'alerte en 3-5 phrases à partir des findings agrégés |
| **Document Specificity** | Carte de l'UI affichant la moyenne des `specificity_score` sur les chunks du document analysé, comparée à la moyenne du corpus — indicateur de qualité de langage du rapport, pas un résultat d'analyse de risque au même titre que les flag_scores |
| **Similar passages / Historical Similar Cases** | Voisins FAISS du document analysé parmi le corpus historique, résumés par LLM (`summarize_passage`) et affichés avec leur issue connue (événement ESG confirmé ou non) |
| **evidence_by_flag** | Pour chaque flag, les projets historiques (au plus 2) dont le passage le plus similaire porte ce flag — sert de traçabilité/justification au flag_score affiché |
