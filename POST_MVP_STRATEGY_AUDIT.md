# Audit stratégique — Roadmap post-MVP (corpus, wiki, few-shot, SQLite)

Auteur : Claude Code (revue red-team, à la demande d'Archange)
Date : 2026-08-22
Portée : évaluation critique de la stratégie proposée pour l'APRÈS 25/08. Aucun code modifié.
Méthode : lecture directe du code (`scripts/*.py`), de l'état réel des données (`corpus/`, `data/`, `models/`), et des mémoires de sprint récentes — pas seulement CLAUDE.md.

---

## 1. Résumé exécutif

La direction stratégique (corpus public → base structurée → wiki → few-shot → spécialisation bancaire) est **directionnellement défendable** — vous ne partez pas de zéro et le code contient déjà des briques dans cet esprit (`scrape_cao.py`, `scrape_ifc.py`, `grid_metadata.py`, `analysis_store.py`). Mais la **séquence proposée est prématurée et inversée** : elle fait grossir le volume et construit des couches de connaissance (wiki, few-shot) avant que les deux préalables indispensables existent — (a) une grille de scoring stabilisée et validée, et (b) une méthodologie de mesure capable de dire si une version du système est meilleure qu'une autre.

Fait qui change la donne par rapport au brief initial : la grille V4 elle-même a été réécrite en profondeur il y a quelques jours (CC-V4-11, restauration mot-pour-mot de la Maquette Vierge après un drift significatif des codes de question), et le seul écart chiffré diagnostiqué à ce jour (CBG : outil 40 vs GT 28-31) a **2 des 3 causes encore ouvertes, en attente d'arbitrage Elisa** (`project_cbg_score_gap_diagnosis`). Construire un wiki et une bibliothèque few-shot sur une grille encore en calibration, c'est figer du savoir sur une fondation mouvante.

Autre correction factuelle importante : le LLM du pipeline n'est **pas un 14B**. `config.py` fixe `Qwen/Qwen3.5-9B` (Together, cloud, défaut) ou `qwen3:4b-instruct` (Ollama, repli local). Cet écart de taille de modèle change directement la réponse aux sections 9 et 13.

---

## 2. Compréhension du MVP actuel

Ce qui tourne réellement en production (`scripts/config.py::ACTIVE_PIPELINE = "v4"`, `pipeline_dispatch.py`) :

```
PDF → ingest.py (extraction texte)
    → grid_doctype.py (détection type de document, 1 appel LLM)
    → grid_metadata.py (sponsor/pays/secteur/client/type projet, 1 appel LLM, fail-open vers null)
    → grid_sections.py (découpage/exclusion sections plaintes)
    → grid_prompts.py + llm_backend.py → 12 questions R (OUI/NON/NA/INCONNU) + verbatim,
      puis sous-question A (preuve de mitigation) si R déclenché — 1 appel LLM par question
    → grid_scoring.py (scoring 100% arithmétique, AUCUN appel LLM, verrous/plafonds explicites)
    → grid_result.py (assemblage JSON sérialisable)
    → grid_analyze._generate_synthesis (1 appel LLM de synthèse finale, désactivable)
    → analysis_store.py (persistance JSON sur disque, un fichier par analyse)
```

Points structurants pour l'évaluation de la stratégie :

- **Le LLM ne score jamais** — il extrait des réponses courtes et structurées à partir d'un seul document. Le scoring est un barème arithmétique déterministe (`grid_scoring.compute_grid_score`). C'est une contrainte de conception forte, explicitement voulue (Note de Cadrage), et elle borne ce que le LLM doit faire dans toute extension future.
- **Stockage = fichiers plats, pas de base de données** : `data/analyses/*.json` (une analyse = un fichier), `data/processed/chunks.csv` (4204 lignes), `models/*.pkl`/`*.npy`/`faiss_index.bin` (embeddings), `data/raw/corpus_cao_ifc.xlsx` (76 lignes, ground truth candidat non validé). `analysis_store.py` documente lui-même la limite : `list_analyses()` relit tout le dossier à chaque appel — "correct pour un volume MVP (dizaines), un index (CSV/SQLite léger) éviterait de tout relire si le volume grossit — pas fait ici, prématuré." **C'est le code lui-même qui pose la question de la Section 5 bis.**
- **La validation humaine n'est PAS structurée** : `data/analyses/` est vide à ce jour (0 fichier) — aucune analyse n'a encore été sauvegardée en usage réel. Il n'existe **aucun mécanisme de correction tracée** : pas de champ "Elisa a changé B.1.2 de NON à OUI", pas d'historique, pas de table de review. Toute la logique "chaque correction devient un exemple few-shot" (Axe 2/3) suppose une infrastructure de capture des corrections qui **n'existe pas encore, même à l'état embryonnaire**.
- **Le corpus réel dans le repo** : 58 fichiers dans `corpus/` = **~46-47 projets distincts** (comptage par dédoublonnage des variantes .txt/.pdf/annexes) — cohérent avec le "46" du brief. `data/raw/corpus_cao_ifc.xlsx` référence 76 lignes au total (donc ~30 projets référencés mais pas encore téléchargés/ingérés) et `data/raw/ifc_controls_metadata.csv`/`cao_cases_metadata.csv` ne contiennent que 2 lignes chacun (quasi vides — la collecte via scraper n'a servi qu'à des tests ponctuels).
- **Le scraping existe déjà, mais pour la mauvaise architecture** : `scrape_cao.py` (319 lignes) est documenté "CHANTIER 0a — collecte pour enrichir les projets `event=1` du **modèle Cox**". Le Cox (`model.py`) est du code mort déclaré. Le scraper CAO fonctionne (export CSV officiel, 260 cas au 2026-07-30, scraping HTML des fiches individuelles), mais sa finalité documentée est obsolète — il faudrait le réorienter vers "alimenter la Grille V4", pas juste le réactiver tel quel.
- **Ground truth** : officiellement `PENDING_GROUND_TRUTH` (CLAUDE.md). Seulement 2 ancrages validés par Stacy (Mundra 23/100, CBG 30-40/100), et même l'ancrage CBG a 2 questions de calibration encore ouvertes.
- **Pas de pytest, pas de CI** — `scripts/test.py`, runner maison à 3 tiers. À l'exécution (`--unit`), l'environnement local a échoué sur un `ModuleNotFoundError: dotenv` (venv non activé) — signal mineur mais révélateur que même la vérification de base n'est pas triviale à relancer à froid.

**Ce qui évoluerait naturellement vers l'architecture proposée** : `grid_metadata.py` (extraction de faits structurés) est déjà le bon patron pour des "fiches projet". `analysis_store.py` est déjà le bon point d'insertion pour une base structurée. Le FAISS existant est déjà un retrieval fonctionnel.

**Ce qui nécessiterait une refonte réelle** : tout mécanisme de capture/versionnement des corrections humaines (n'existe pas), toute notion de "cas de référence" séparé des données de production (n'existe pas), toute séparation formelle corpus d'entraînement/calibration/évaluation (n'existe pas — les 2 seuls ancrages servent À LA FOIS à calibrer le barème ET de preuve de qualité, ce qui est déjà, à petite échelle, le problème de fuite de données de la Section 7).

---

## 3. Évaluation de l'hypothèse « 46 → 100/150 »

**Le volume n'est pas le facteur limitant aujourd'hui.** Trois faits l'établissent :

1. Il existe un **écart non résolu** entre les 76 lignes déjà référencées dans `corpus_cao_ifc.xlsx` et les ~46 projets réellement présents dans `corpus/`. Il y a donc déjà ~30 projets "en attente" avant même de aller chercher une seule nouvelle source externe. Scraper CAO/BAD/BEI maintenant, avant d'avoir traité ce qui est déjà répertorié, c'est empiler du backlog non exploité.
2. Sur les 46 projets actuels, **2 seulement ont un score de référence validé par un humain métier** (Mundra, CBG), et l'un des deux a des questions de calibration encore ouvertes. Le facteur limitant n'est pas "combien de documents avons-nous" mais "combien avons-nous de réponses vérifiées par Elisa, question par question". Un corpus de 150 documents sans plus de vérité terrain que 2 ancrages n'apporte aucune capacité de mesure supplémentaire — juste plus de texte à faire lire au LLM.
3. La grille elle-même (les 12 questions, leur formulation, leur `silence_type`, le verrou B.2.1→B.2.2) a changé structurellement il y a moins d'une semaine (CC-V4-11) et reste "à revalider avec Elisa avant la soutenance" sur au moins un mécanisme. Annoter 100+ documents contre une grille qui peut encore bouger = ré-annoter 100+ documents plus tard.

**Recommandation chiffrée, argumentée** : ne pas viser 100-150 maintenant. Viser d'abord **la conversion des 46 déjà présents en corpus vérifié** (objectif : 15-20 projets avec ground truth validé question-par-question par Elisa, pas juste un score final), puis combler l'écart 46→76 avec ce qui est déjà référencé dans le xlsx (croissance quasi gratuite : métadonnées déjà connues). Ce n'est qu'après avoir mesuré une précision par question sur ce socle de ~70-76 projets, avec au moins 15-20 vérifiés, qu'un objectif de 100-150 devient une décision pilotée par la donnée plutôt qu'un chiffre rond. Si la mesure (Section 8) montre une précision par question déjà stable et élevée sur ce socle, le prochain palier de valeur ne sera de toute façon plus le volume mais la diversité sectorielle/géographique (Section 4) — pas un N plus grand du même type de documents.

**Résumé : 70-76 avant 100-150, et la priorité immédiate n'est pas le volume mais la part vérifiée du volume existant.**

---

## 4. Évaluation de la qualité des sources

| Source | Pertinence | Fiabilité/structure | Automatisation | Risque |
|---|---|---|---|---|
| **CAO** | Très haute — c'est la source du GT actuel (Mundra, CBG), vocabulaire aligné sur la grille (IFC Performance Standards). Scraper existant (`scrape_cao.py`), CSV officiel exhaustif (260 cas). | Bonne — documents structurés (Assessment/Compliance/Monitoring reports), mais couvre par construction des cas **de plainte** (voir Section 5). | Facile pour les métadonnées (CSV statique), moyenne pour les PDF individuels (slugs devinés, repli manuel documenté). | Faible techniquement, à vérifier juridiquement (voir plus bas). |
| **IFC (disclosure/monitoring, hors CAO)** | Haute — c'est la seule source réaliste pour des projets "normaux" sans plainte (contrepoids au biais CAO). Scraper existant (`scrape_ifc.py`). | Variable — disclosure IFC est hétérogène en profondeur selon les projets/années. | Moyenne. | Faible techniquement. |
| **Banque mondiale** | Moyenne — cadre E&S proche (Environmental and Social Framework) mais **pas identique** aux Performance Standards IFC sur lesquels la grille est calée. | Bonne structurellement, mais vocabulaire à re-mapper. | Moyenne-faible (pas de scraper existant, formats variés selon projets/pays). | Risque méthodologique : un B.1.2 "griefs communautaires" ne se lit pas forcément pareil dans un document ESF Banque Mondiale. |
| **BAD, BEI, BERD** | Faible à court terme — cadres et niveaux de disclosure hétérogènes entre eux, pas de scraper, pas de mapping taxonomique fait. | Variable, souvent moins granulaire que CAO/IFC. | Faible — travail d'ingénierie par institution, ce n'est pas un connecteur générique. | Coût élevé pour un gain incertain à ce stade. |

**Alerte explicite sur la réutilisation** — ne pas assumer que "document public" = "librement réexploitable dans un produit commercial bancaire". Points précis à vérifier avant tout scraping à l'échelle, institution par institution :
- Les conditions d'utilisation du site CAO (`cao-ombudsman.org`) et de la Banque Mondiale/IFC (`disclosures`, `ifc.org`) sur la réutilisation, la republication d'extraits, et la création de dérivés commerciaux.
- Si les documents portent une licence explicite (CC-BY, etc.) ou un simple "publicly disclosed" sans droit de réutilisation dérivée.
- Si stocker des extraits verbatim de ces documents dans une base interne bancaire (potentiellement montrée à des clients/régulateurs) pose un problème différent de les avoir simplement lus une fois.

Cette vérification n'est pas faite dans ce repo à ce jour et doit être traitée comme un prérequis juridique, pas un détail technique, avant toute extension au-delà de CAO/IFC (qui sont déjà utilisés).

**Recommandation** : rester sur CAO + IFC pour la phase post-MVP immédiate (déjà outillé, déjà validé métier, déjà dans le même référentiel PS). Traiter Banque Mondiale/BAD/BEI/BERD comme un chantier séparé et plus tardif, conditionné à une vérification juridique et à un travail de mapping taxonomique — pas un simple "en plus" de l'Axe 1.

---

## 5. Le plus gros risque : le biais du corpus

Le brief a raison de s'inquiéter — et le risque est concret, pas théorique, ici :

- **Biais de sélection** : CAO est un mécanisme de plainte. Un projet y arrive parce qu'une communauté ou une ONG a *déjà* engagé une procédure formelle — l'extrémité la plus visible de la distribution. Le système apprendrait à reconnaître "à quoi ressemble un projet qui a fini en plainte CAO", ce qui est une tâche différente de "quels signaux précoces indiquent un risque avant toute plainte" — exactement l'écart de départ qui a motivé la refonte (CBG : 78/100 outil vs 30-40/100 réel, projet classé "A – Significant" par l'IFC).
- **Biais de survivant documentaire** : seuls les projets suffisamment scrutinés (souvent parce que déjà signalés) génèrent une documentation riche et publique. Les projets "normaux" qui restent normaux sont sous-documentés par construction — ils n'ont jamais eu de raison de produire un rapport d'investigation détaillé.
- **Biais institutionnel/géographique** : le corpus actuel est à 100% IFC/CAO — un seul bailleur, un seul jeu de standards. Le vocabulaire des 12 questions est calé sur les Performance Standards IFC ; l'élargir à d'autres bailleurs sans adapter la grille produirait des faux négatifs systématiques (des risques réels non formulés dans le vocabulaire attendu).
- **Biais "contrôle" trompeur** : les projets `_CTRL` du corpus actuel (utilisés comme contrepoids "normal") ne sont pas nécessairement représentatifs de "sans risque" — ce sont simplement des projets IFC sans plainte connue *au moment de l'extraction*, ce qui n'est pas la même chose qu'un audit indépendant confirmant l'absence de risque.

**Stratégie concrète de mitigation** :
1. Définir explicitement, avant tout scraping, des **quotas cibles** par (secteur, région, statut CAO) plutôt que d'aspirer "tout ce qui est disponible" — ex. viser un ratio minimum 40/60 plainte/contrôle au lieu du 28/18 actuel qui penche déjà vers la plainte.
2. Étiqueter explicitement chaque projet du corpus avec sa **provenance de sélection** (`source_selection_bias: "cao_complaint" | "ifc_disclosure_random" | ...`) dans les métadonnées — pour pouvoir un jour mesurer/corriger la composition, pas juste la subir.
3. Ne jamais présenter un taux de "détection" mesuré sur ce corpus comme une mesure de performance générale du produit sans mentionner explicitement ce biais de composition (cohérent avec la règle CLAUDE.md sur le ground truth).

---

## 6. Évaluation du wiki

Le mot "wiki" mélange au moins quatre objets différents, avec des besoins d'infrastructure totalement différents :

| Terme du brief | Ce que c'est réellement | Bonne implémentation |
|---|---|---|
| "Données factuelles vérifiables par projet" (Couche 1) | Une base de faits structurés, interrogeable | **Table SQL** (Section 5 bis), pas un wiki texte |
| "Synthèses/patterns transversaux" (Couche 2) | Une analyse humaine périodique, éventuellement outillée par des requêtes SQL + LLM d'appoint | Un **document de synthèse versionné**, écrit avec l'aide d'un analyste — pas un texte généré en continu et jamais revu |
| "Exemples few-shot" (Couche 3) | Un jeu d'exemples de prompt, pas de la "connaissance" au sens documentaire | Une **bibliothèque d'exemples curée et versionnée**, séparée (Section 6) |
| Implicite : mémoire du système pour du RAG | Un besoin de retrieval sémantique | **Déjà couvert par FAISS** — pas un nouveau composant |

**Un wiki généraliste (type Confluence/MediaWiki) est la mauvaise abstraction ici** : personne dans l'équipe (2 développeurs, 1 analyste) n'a la bande passante pour maintenir un wiki à jour, et un texte libre non structuré est précisément ce qui est le plus difficile à auditer/versionner/tracer — à l'opposé du besoin réel (traçabilité de la preuve, cf. invariant "verbatim justificatif" déjà dans la grille V4).

**Recommandation** : abandonner le terme et le concept de "wiki". Le remplacer par : une base de faits structurée (SQLite, Section 5 bis) + un document de synthèse court, versionné et écrit à la main à partir de requêtes sur cette base (pas généré en continu) + une bibliothèque few-shot séparée avec ses propres règles de gouvernance (Section 6). Trois objets, trois responsables, trois cycles de mise à jour — pas un objet monolithique.

---

## 7. Attention au few-shot

"Chaque correction d'Elisa devient un exemple few-shot" est une phrase séduisante et une **mauvaise architecture si elle est prise littéralement**. Risques concrets ici :

- **Accumulation non bornée** : avec 12 questions × dizaines de corrections, le prompt de chaque question grossirait sans limite naturelle — coût et latence en hausse, alors que `OLLAMA_CONFIGS`/le choix de `num_predict`/`num_ctx` courts est déjà une contrainte de conception assumée du projet.
- **Contradictions** : deux corrections d'Elisa sur des cas voisins mais nuancés différemment (cf. le débat B.2.2 CBG — "l'airshed dégradé compte-t-il comme rejet eau ?") produiraient des exemples few-shot qui se contredisent littéralement si les deux sont injectés sans arbitrage.
- **Contamination corpus d'éval/few-shot** : si un exemple few-shot vient d'un projet qui est *aussi* dans le jeu de test, le LLM "a vu la réponse" — la mesure de qualité devient invalide (voir Section 8, ce n'est pas hypothétique).
- **Dérive silencieuse** : sans versionnement, on ne peut plus dire "quels exemples ont produit ce score" ni revenir en arrière si un exemple s'avère mauvais.

**Meilleure architecture, concrète** :
1. **Aucune promotion automatique**. Une correction d'Elisa devient d'abord une ligne dans une table `review_corrections` (Section 5 bis) — un fait tracé, pas un exemple de prompt.
2. Un **curateur humain** (Elisa/Archange) sélectionne périodiquement, à la main, un petit nombre d'exemples représentatifs par question (10-20 max par code de question) pour la bibliothèque few-shot — versionnée (`few_shot_v1`, `v2`...).
3. **Sélection dynamique à l'inférence** : ne pas empiler tous les exemples dans chaque prompt — sélectionner par retrieval (le plus proche sémantiquement du document en cours, filtré par code de question) parmi la bibliothèque curée. C'est un usage naturel du FAISS déjà en place.
4. **Jeu d'évaluation strictement disjoint** de la bibliothèque few-shot — aucun projet ne doit jamais apparaître dans les deux (Section 7bis ci-dessous).

---

## 8. Distinguer connaissance, entraînement et évaluation — le risque de fuite de données

**Explication simple** : si le système apprend ses réponses à partir des mêmes documents sur lesquels on mesure ensuite s'il répond bien, la mesure ne prouve rien — c'est comme donner à un élève l'énoncé ET le corrigé avant l'examen, puis le féliciter d'avoir eu 20/20 au même examen. Le score mesure la mémorisation, pas la compétence sur un cas nouveau.

**Ce risque existe déjà, en miniature, dans le repo** : Mundra et CBG servent À LA FOIS d'ancrage de calibration du barème ET de preuve démo de la qualité de l'outil. Ce n'est pas grave à l'échelle actuelle (2 ancrages, usage explicitement documenté comme "calibration", pas prétendu comme "évaluation indépendante"), mais si la même logique s'applique à 100+ projets sans séparation formelle, la distinction se perd et le risque de fuite devient réel et invisible.

**Architecture recommandée** (répond à la demande A-G du brief, simplifiée à ce qui est réellement utile ici) :

- **Corpus de calibration** : sert à ajuster le barème, la formulation des questions, les prompts. Explicitement documenté comme tel — Mundra/CBG y sont aujourd'hui.
- **Corpus de validation** (jeu d'évaluation) : **jamais utilisé pour ajuster quoi que ce soit** — ni prompt, ni few-shot, ni seuil. Sert uniquement à mesurer. Doit être choisi maintenant, avant que le corpus grossisse, et gelé (versionné, `eval_set_v1`).
- **Bibliothèque few-shot** : disjointe du jeu de validation par construction (vérification automatique possible : même `project_id` ne doit jamais apparaître dans les deux tables).
- **Production** : tout document uploadé par un analyste en usage réel — jamais réinjecté automatiquement dans le calibration/few-shot sans passer par la case "correction tracée puis curation humaine" (Section 6).

Pas besoin de 7 corpus distincts au stade actuel (sur-ingénierie) — 4 suffisent : **calibration, validation (gelé), few-shot (curé), production**. C'est la distinction calibration/validation qui est le vrai prérequis manquant aujourd'hui, pas le nombre de catégories.

---

## 9. Méthodologie de mesure

Le scoring final étant 100% déterministe une fois les réponses (R, A) connues, **la vraie question à mesurer n'est pas le score final — c'est la justesse de chaque extraction R/A, question par question**. Le diagnostic CBG le montre déjà en pratique : l'écart de score final (40 vs 28, soit 12 points) est entièrement dû à UNE SEULE question mal extraite (B.1.2), mais deux autres questions avaient elles-mêmes des désaccords non résolus sur la définition attendue (B.2.2, B.3.2) — un score final "proche" aurait pu masquer un vrai problème d'extraction si les erreurs s'étaient annulées au lieu de s'additionner.

**Métriques recommandées** :
- **Par question de la grille (primaire)** : matrice de confusion OUI/NON/NA/INCONNU vs réponse Elisa, sur le jeu de validation gelé — précision/rappel par question, pas juste globaux (une question peut être fiable et une autre non, la moyenne le cache).
- **Sur le statut de mitigation (A)** : même logique, une fois R confirmé correct.
- **Sur le score final (secondaire, agrégé)** : erreur absolue moyenne (score outil − score Elisa) + accord de zone de couleur (VERT/JAUNE/ORANGE/ROUGE) — utile pour la démo, insuffisant seul pour piloter le développement (peut masquer des erreurs qui s'annulent, cf. ci-dessus).
- **Qualité du verbatim justificatif** : le verbatim cité correspond-il réellement au passage source (pas halluciné) ? Vérifiable automatiquement par recherche exacte de sous-chaîne dans le document — pas besoin de jugement humain pour cette partie.
- **Stabilité** : même document, même version de grille → même résultat (le pipeline a des appels LLM à température non nulle sur certaines tâches — à vérifier qu'un re-run ne fait pas flipper une réponse OUI/NON).

**Protocole concret V1 → V2** :
1. Geler `eval_set_v1` (15-20 projets du corpus actuel, avec réponses Elisa complètes sur les 12 questions — pas juste un score final).
2. Faire tourner la grille V4 actuelle dessus → publier la matrice de confusion par question comme **baseline chiffrée** (n'existe pas aujourd'hui).
3. Toute modification (prompt, few-shot, grille) devient "V2" seulement si elle est re-testée sur le **même** `eval_set_v1` — jamais sur un sous-ensemble différent.
4. Comparaison V1 vs V2 = delta sur la matrice de confusion par question, pas un chiffre unique. Une V2 qui améliore 3 questions et en dégrade 2 n'est pas un progrès net évident — c'est une décision à documenter, pas juste "V2 > V1".

C'est ce protocole, pas le volume du corpus, qui répond réellement à "le système s'améliore-t-il ?" — et il **doit exister avant** de commencer l'Axe 1/2/3, sinon il n'y a aucun moyen de savoir si le travail d'enrichissement a servi à quelque chose.

---

## 10. Évaluer le LLM (correction : 9B, pas 14B)

Le pipeline actuel utilise **Qwen3.5-9B** (Together, cloud, défaut MVP) ou **Qwen3 4B-instruct** (Ollama, repli local) — pas un 14B. Cet écart n'est pas cosmétique :

- **Bien adapté à la tâche actuelle** : extraction courte et structurée sur un seul document (R=OUI/NON + verbatim, JSON à 5 champs pour les métadonnées) — tâche fermée, contexte borné (`num_ctx` 512-2048), sortie courte. C'est exactement le régime où un modèle 9B (voire 4B) cloud/local est fiable et rapide.
- **Mal adapté, en l'état, à ce que l'Axe 2/3 sous-entend** : "détecter des patterns transversaux", "comparer des dizaines de projets", "produire une fiche projet riche avec leçons apprises" sont des tâches de **synthèse/raisonnement cross-document à large contexte** — un registre différent et nettement plus exigeant que l'extraction question-par-question actuelle. Un 9B (a fortiori 4B) sans fine-tuning ni longue fenêtre de contexte gérée soigneusement produira des synthèses plausibles mais peu fiables si on lui demande de comparer 50 documents en une fois.

**Ce qui doit rester déterministe/retrieval, pas LLM** : les statistiques par secteur/région (SQL), la sélection des exemples few-shot (retrieval + curation humaine), le calcul du score (déjà le cas). **Ce qui reste raisonnablement au LLM** : extraction question-par-question sur UN document (déjà le cas, fonctionne), génération de synthèse courte sur UN document (déjà le cas, `grid_analyze._generate_synthesis`). **Ce qui doit être explicitement humain, pas LLM** : la synthèse de "patterns sectoriels" (Couche 2 du wiki) — un 9B qui "découvre des patterns" sur un corpus de 100 documents sans validation produira des généralisations invérifiables ; cette tâche revient à un analyste qui interroge la base structurée (Section 5 bis) et rédige lui-même la synthèse.

**Éviter explicitement l'architecture "le LLM fait tout"** — le projet a déjà cette discipline pour le scoring (barème arithmétique, pas de LLM) ; elle doit être étendue à la couche connaissance, pas relâchée au moment où le périmètre s'élargit.

---

## 11. Analyse de l'ordre des opérations proposé

| Étape proposée | Verdict |
|---|---|
| 1. 46 → 80-100 projets | **Prématuré** — voir Section 3. À repousser après la Section 8. |
| 2. Analyser tous avec le LLM | Risqué en l'état — sans jeu de validation gelé au préalable, on ne peut pas dire si le résultat est bon. |
| 3. Elisa corrige | Bon principe, mais **aucune infrastructure de capture des corrections n'existe** — à construire avant, pas pendant. |
| 4. Construire le wiki | Prématuré et mal nommé — voir Section 6. |
| 5. Construire les few-shot | Prématuré tant que la bibliothèque n'est pas curée/versionnée séparément de l'éval (Section 7). |
| 6. Tester sur 10-15 nouveaux projets | **Bonne idée, mais placée trop tard** — c'est l'étape 1, pas l'étape 6. |
| 7. Attendre les données bancaires | Correct de ne pas bloquer dessus. |
| 8. Spécialiser | Correct comme direction finale. |

**Ce qui manque avant d'augmenter le corpus** : (a) fermer les questions PENDING_ELISA de calibration ouvertes sur la grille actuelle (B.1.2 root cause déjà identifiée — erreur d'extraction LLM sur documents longs à mentions multiples, pas un bug de retrieval ; B.2.2/B.3.2 en attente d'arbitrage) ; (b) geler un jeu de validation et publier une baseline chiffrée par question (Section 9/10) ; (c) construire la structure minimale de traçabilité des corrections (Section 5 bis) — sans quoi l'étape 3 ("Elisa corrige") ne produit rien de réutilisable.

**Roadmap corrigée (ordre)** : Stabilisation grille → Mesure/baseline sur l'existant → Structuration minimale (SQLite) → Croissance ciblée du corpus (combler 46→76, puis stratifier) → Bibliothèque few-shot curée → Validation métier élargie → Pilote bancaire → Spécialisation.

---

## 12. Roadmap post-MVP corrigée

**PHASE 1 — Stabilisation (post-25/08, semaines 1-2)**
Objectif : fermer les incertitudes de calibration connues avant de bâtir dessus.
Travail : trancher B.2.2/B.3.2 avec Elisa, revalider le verrou B.2.1→B.2.2 sur le corpus courant, migration tests vers pytest, correctifs F4/F5 si le temps le permet, nettoyage code mort déclaré (`reranker.py`, Cox).
Livrables : grille V4 "gelée" (version taguée), suite pytest exécutable à froid.
Critère de réussite : 0 question PENDING_ELISA ouverte sur les 2 ancrages existants.
Risque : Elisa indisponible juste après une présentation → prévoir un délai réaliste, pas une semaine.
Effort : **faible-moyen**.

**PHASE 2 — Mesure (semaines 2-4) — LA VRAIE PRIORITÉ**
Objectif : rendre "le système s'améliore-t-il ?" mesurable.
Travail : geler `eval_set_v1` (15-20 projets, réponses Elisa complètes par question, disjoint de tout usage few-shot futur), instrumenter la matrice de confusion par question, publier une baseline.
Livrables : `eval_set_v1` figé + rapport de baseline chiffré (par question, pas juste score final).
Critère de réussite : baseline publiée et reproductible (même run = même chiffres, ou variance documentée).
Risque : découvrir que la précision par question est plus faible qu'espéré → c'est le but, mieux vaut le savoir maintenant.
Effort : **moyen**.

**PHASE 3 — Structuration minimale (semaines 3-5, en parallèle fin Phase 2)**
Objectif : sortir des fichiers JSON/CSV plats avant que `list_analyses()` (déjà marqué FRAGILE dans le code) devienne un vrai problème.
Travail : SQLite (Section 5 bis) — `projects`, `documents`, `analyses`, `question_answers`, `review_corrections`, `eval_cases`/`eval_results`. Migration des JSON existants (peu nombreux, migration triviale).
Livrables : schéma SQLite versionné, script de migration.
Critère de réussite : les requêtes "combien de projets par secteur", "quelles questions Elisa corrige le plus" sont possibles en une requête SQL, plus en script ad hoc.
Effort : **moyen**.

**PHASE 4 — Croissance ciblée du corpus (semaines 4-8)**
Objectif : combler 46→76 (déjà référencé), puis extension stratifiée par quotas secteur/région/statut (Section 5), CAO+IFC uniquement.
Livrables : corpus élargi avec métadonnées de provenance/biais tracées.
Gate d'entrée : Phase 2 terminée (sinon on ne peut pas mesurer l'effet de la croissance).
Effort : **moyen** (le scraper existe déjà, à réorienter).

**PHASE 5 — Bibliothèque few-shot curée (semaines 6-9, chevauche Phase 4)**
Objectif : bibliothèque petite, versionnée, sélectionnée à la main à partir de `review_corrections`.
Gate d'entrée : Phase 3 (table `review_corrections` existe) ET au moins une itération de comparaison V1/V2 déjà faite avec succès en Phase 2 (preuve que la mesure fonctionne avant d'ajouter une variable de plus).
Effort : **moyen**.

**PHASE 6 — Validation métier élargie (semaines 8-10)**
Objectif : Elisa valide sur le corpus élargi, pas seulement les 2 ancrages initiaux.
Effort : **moyen-élevé** (consommateur du temps d'Elisa, ressource rare).

**PHASE 7 — Pilote bancaire (T+1, quand les données banque arrivent)**
Objectif : petit périmètre, isolation stricte des données confidentielles dès le schéma (Section 14).
Effort : **élevé** (dépend d'un facteur externe hors contrôle du projet).

**PHASE 8 — Spécialisation/industrialisation**
Objectif : comparaison patterns publics vs patterns bancaires, éventuel multi-tenant.
Effort : **élevé**.

---

## 13. Gates GO / NO-GO

- **NO-GO croissance corpus (Phase 4)** tant que `eval_set_v1` n'est pas gelé et qu'une baseline par question n'est pas publiée. *Justification : sans ça, aucune décision de croissance n'est vérifiable — c'est le cœur du problème diagnostiqué par l'écart CBG initial (78 vs 30-40) qui a motivé toute la refonte.*
- **NO-GO few-shot (Phase 5)** tant que la table de corrections tracées (Phase 3) n'existe pas ET qu'aucune comparaison V1/V2 n'a encore été faite avec succès sur `eval_set_v1`. *Justification : ajouter du few-shot sans savoir mesurer son effet reproduit l'erreur de méthode qu'on cherche à éviter.*
- **NO-GO pilote bancaire (Phase 7)** tant que les items PENDING_ELISA de calibration ne sont pas fermés et que le verrou B.2.1→B.2.2 n'est pas revalidé. *Déjà décidé par l'utilisateur le 2026-08-20 pour ne pas y toucher avant la soutenance — cette règle doit simplement être reconduite après, pas oubliée.*
- **ITERATE, pas GO**, si la précision par question mesurée en Phase 2 est hétérogène (certaines questions fiables, d'autres non) : ne pas moyenner et déclarer "assez bon" — traiter question par question, comme le cas CBG l'a montré (une seule question explique tout l'écart).
- Pas de seuil numérique de précision minimale imposé ici (ex. "80%") — aucune baseline n'existe encore pour le justifier ; le premier livrable de la Phase 2 EST ce seuil, à fixer avec Elisa une fois la baseline connue, pas avant.

---

## 14. Valeur stratégique pour la banque

L'argument "nous avons déjà construit une base de connaissance publique avant les données bancaires" **est un avantage réel s'il est formulé honnêtement**, et **un risque de crédibilité s'il est survendu**.

**Ce qu'il ne faut surtout pas dire** : *"Notre système est déjà entraîné sur les données de l'industrie."* C'est faux au sens strict (aucun fine-tuning, `Qwen3.5-9B` est un modèle générique, non ré-entraîné sur ce corpus) et vérifiable par n'importe quelle équipe technique bancaire qui demanderait une fiche modèle. Une banque de financement de projet a des équipes conformité/risque modèle habituées à challenger ce type de claim — se faire prendre en défaut sur un mot ("entraîné") coûte plus cher en crédibilité que ce que l'affirmation rapporte.

**Formulation techniquement et commercialement correcte** : *"Le système applique une grille d'évaluation calibrée et validée sur un corpus public structuré et documenté (rapports CAO/IFC), avec extraction assistée par LLM et validation systématique par un analyste. Les données de la banque serviront à spécialiser et enrichir ce référentiel, pas à le construire depuis zéro."* — même message stratégique, sans mentir sur ce que "entraîné" signifierait.

**Ce qui pourrait au contraire inquiéter la banque** : un corpus 100% IFC/CAO peut donner l'impression que l'outil est calé sur les standards d'un seul bailleur alors que la banque finance des projets sous des cadres variés — anticiper la question, pas la laisser surgir en réunion.

---

## 15. Transition vers les données bancaires

- **Isolation dès la conception, pas en rattrapage** : même schéma SQLite (Section 5 bis) mono-tenant aujourd'hui, ajouter une colonne `tenant_id`/`source_scope` (`"public"` vs `"bank_X"`) dès maintenant sur `projects`/`documents`/`analyses` — gratuit à ajouter maintenant, coûteux à retrofitter plus tard.
- **Ce qui reste commun** : le barème (`grid_questions.py`, `grid_scoring.py`), le moteur d'extraction, la bibliothèque few-shot publique curée.
- **Ce qui devient spécifique** : les documents bancaires eux-mêmes (jamais mélangés au corpus public sur disque — répertoires physiquement séparés), toute correction faite sur des données bancaires (jamais promue automatiquement vers la bibliothèque few-shot publique).
- **Confidentialité** : aucune donnée `tenant_id="bank_X"` ne doit jamais alimenter un few-shot ou une synthèse visible par un autre tenant — règle simple à vérifier automatiquement par un test (aucune ligne `few_shot_examples` ne doit référencer une source `tenant_id != "public"` sans validation explicite).
- **Multi-banque (si le produit devient multi-client)** : c'est l'endroit précis où PostgreSQL avec des rôles/permissions par tenant devient justifié — SQLite n'a pas de gestion d'accès native multi-utilisateur (Section 5 bis.4). Ne pas anticiper cette bascule maintenant ; concevoir juste le schéma pour qu'elle soit possible sans réécriture complète (clé `tenant_id` partout).

---

## 16. Potentiel d'avantage compétitif

**Ce qui n'est PAS un moat** : le corpus public brut (n'importe quel concurrent peut scraper CAO/IFC, le CSV export est public) ; le texte du "wiki" généré par un LLM générique (reproductible en un après-midi par un concurrent avec le même modèle) ; le fait d'avoir "beaucoup de documents" (pas une barrière si la donnée est publique).

**Ce qui EST potentiellement un moat, honnêtement évalué** : la **grille elle-même et ses règles de calibration fines** (les verrous B.2.1→B.2.2, les 4 statuts de mitigation, les seuils de couleur — accumulés au fil d'itérations réelles avec une analyste métier senior) ; **l'historique tracé des corrections d'Elisa** (Section 5 bis, `review_corrections`) — c'est du jugement d'expert capturé, pas reproductible sans avoir accès à une analyste équivalente pendant le même nombre d'heures ; et, plus tard, les **données bancaires propriétaires** une fois obtenues. Un concurrent peut recréer un corpus public en une semaine ; il ne peut pas recréer 6 mois de corrections d'Elisa question par question sans passer par le même travail humain. **Le moat est le processus de calibration humaine tracé, pas le corpus ni le wiki.**

---

## 17. Notes

| Critère | Note /10 | Justification courte |
|---|---|---|
| Pertinence produit | 6 | Direction juste, séquence à corriger |
| Faisabilité technique | 6 | Briques déjà là (scraper, extraction), mais mesure/structure manquantes |
| Valeur métier | 5 | Valeur réelle mais conditionnée à la fermeture des calibrations ouvertes |
| Qualité des données | 4 | Biais CAO significatif, GT quasi inexistant à ce jour |
| Scalabilité | 5 | Fichiers plats déjà signalés comme limite par le code lui-même |
| Robustesse IA | 5 | LLM 9B correctement scopé pour l'extraction, mal scopé pour "patterns" |
| Mesurabilité | 3 | Aucun jeu de validation gelé, aucune baseline aujourd'hui — le vrai trou |
| Valeur stratégique | 6 | Bon argument s'il est formulé sans survente |
| Risque | 5 | Risque de figer du savoir sur une grille encore mouvante |
| Rapport effort/valeur | 4 | Tel que proposé : effort élevé (Axe 1-3) pour valeur non mesurable |

**Note globale : 5/10 telle que proposée.**

**Ce qui ferait passer la stratégie à 9/10** : (1) geler un jeu de validation et publier une baseline par question — c'est le changement individuel à plus fort effet de levier de tout ce rapport ; (2) fermer les 2 items PENDING_ELISA de calibration avant toute extension ; (3) construire la structure minimale (SQLite, Section 5 bis) avant le wiki/few-shot, pas après ; (4) remplacer "wiki" par les 3 objets distincts de la Section 6 ; (5) traiter le few-shot comme une bibliothèque curée et versionnée, jamais comme une accumulation automatique. Aucun de ces 5 points ne nécessite d'attendre les données bancaires ni un corpus plus grand — ils sont tous faisables sur le corpus actuel de 46 projets.

---

# 5 BIS. SQLite

## 5 bis.1 — Architecture actuelle

| Donnée | Où | Forme | Relié comment | Recherché comment | Versionné |
|---|---|---|---|---|---|
| Résultats d'analyse (grille V4) | `data/analyses/*.json` | 1 fichier JSON/analyse | Par nom de fichier (`slug_document`) | `list_analyses()` relit **tous** les fichiers à chaque appel (documenté FRAGILE) | Non — écrasement implicite si même document ré-analysé sous un nom proche |
| Chunks/embeddings | `data/processed/chunks.csv`, `models/embeddings.npy`, `models/faiss_index.bin`, `models/chunks_metadata.pkl` | CSV + binaires numpy/FAISS | Par index positionnel entre les 4 fichiers (couplage implicite fragile) | Recherche vectorielle FAISS ; recherche structurée = script pandas ad hoc | Non |
| Métadonnées corpus | `data/raw/corpus_cao_ifc.xlsx` (76 lignes), `cao_cases_metadata.csv`, `ifc_controls_metadata.csv` | xlsx + CSV | Aucun lien formel entre les 3 fichiers (recoupement manuel par nom de projet/numéro IFC) | Ouverture manuelle Excel | Non |
| Caches LLM | `models/llm_confirm_cache.json`, `models/deep_analysis_cache.json` | JSON, clé = hash(backend:modèle+contenu) | Aucun lien à un projet, juste une clé de cache | Lookup direct par clé | Implicite (hash inclut la config) |
| Corrections humaines | **Nulle part** | — | — | — | — |

## 5 bis.2 — Problèmes déjà présents (pas hypothétiques)

- **Pas d'identifiant projet unique** : un même projet IFC peut avoir plusieurs numéros de cas CAO (documenté dans `scrape_cao.py` lui-même : "un même numéro de projet IFC peut apparaître dans plusieurs cas CAO distincts"), et rien dans le repo ne déduplique/relie ça aujourd'hui.
- **`list_analyses()` relit tout le dossier à chaque appel** — déjà signalé FRAGILE par le code, correct à "dizaines" d'analyses, va casser en usage réel dès que le Portfolio Dashboard est utilisé quotidiennement.
- **Aucune trace de correction humaine** — impossible aujourd'hui de répondre à "qu'est-ce qu'Elisa a corrigé sur ce document" ou "quelle a été l'erreur la plus fréquente ce mois-ci".
- **Aucun lien formalisé** entre `corpus_cao_ifc.xlsx` (76 lignes déclarées), `corpus/` (46 fichiers réels), et `cao_cases_metadata.csv`/`ifc_controls_metadata.csv` (quasi vides, 2 lignes chacun) — ces 3 sources devraient décrire le même univers de projets et divergent silencieusement.
- **Aucune stat croisée possible sans script ad hoc** : "combien de projets hydroélectriques", "quel est le taux de OUI sur B.1.2" nécessitent aujourd'hui d'écrire un script Python à la main à chaque question.

## 5 bis.3 — Modèle de données proposé (minimal, pas le schéma à 17 tables du brief)

```
projects(id, ifc_project_number, name, country, sector, sub_sector,
         source_scope, selection_bias_tag, created_at)

documents(id, project_id FK, file_path, doc_type, source_institution,
          disclosed_date, ingested_at)

analyses(id, project_id FK, document_id FK, grid_version, model_backend,
         model_name, run_at, score, color, saturation)

question_answers(id, analysis_id FK, question_code, status,
                  mitigation_status, verbatim, verbatim_span_start,
                  verbatim_span_end)

review_corrections(id, question_answers_id FK, reviewer, corrected_status,
                    corrected_mitigation_status, reason, corrected_at)

eval_cases(id, project_id FK, question_code, expected_status,
           expected_mitigation_status, validated_by, validated_at,
           eval_set_version)

eval_results(id, eval_case_id FK, analysis_id FK, match_status,
             match_mitigation, run_version)

few_shot_examples(id, question_code, project_id FK, verbatim_excerpt,
                   expected_answer, curated_by, curated_at, library_version)
```

**Pourquoi cette séparation, pas les 17 tables du brief** : `risks`/`risk_categories`/`findings`/`red_flags`/`mitigations` sont déjà représentés dans `question_answers` (les 12 questions de la grille SONT la taxonomie de risque — pas besoin d'une taxonomie parallèle tant qu'elle n'existe pas ailleurs) ; `knowledge_articles` est explicitement écarté (Section 6, "wiki" mal nommé) ; `model_versions`/`analysis_versions` sont couverts par les colonnes `grid_version`/`model_backend`/`model_name` sur `analyses`, pas des tables séparées tant qu'il n'y a qu'un historique linéaire simple à suivre.

## 5 bis.4 — SQLite est-il adapté ?

**Oui, largement, pour ce produit dans les 12-18 prochains mois** : 50 à quelques milliers de projets, un seul processus Streamlit écrivain à la fois (analyste unique par session), lectures fréquentes/écritures rares — c'est exactement le profil pour lequel SQLite est conçu. Ses limites réelles (accès concurrent en écriture, multi-utilisateur simultané, accès réseau distant natif) ne se manifestent pas dans ce contexte : le déploiement actuel est un VPS unique (`docker-compose` : app/ollama/caddy), pas un service multi-instance.

**Où SQLite cesserait d'être adapté** : plusieurs analystes de plusieurs banques écrivant simultanément sur la même base, ou un besoin d'accès réseau depuis plusieurs services indépendants — ce n'est pas le cas avant, au plus tôt, la Phase 7 (pilote bancaire) et probablement pas avant la Phase 8 (multi-tenant).

## 5 bis.5 — Comparaison

| | Fichiers plats (actuel) | SQLite | PostgreSQL |
|---|---|---|---|
| Adapté au volume actuel (46-150 projets) | Limite (déjà signalé fragile) | Oui | Oui, mais surdimensionné |
| Coût d'introduction | Nul | Faible (stdlib Python, aucune dépendance externe, aucun service à opérer) | Élevé (service à déployer/opérer/sauvegarder, ajout au `docker-compose`) |
| Requêtes croisées (secteur/pays/risque) | Scripts ad hoc à chaque fois | Une requête SQL | Une requête SQL |
| Cohérent avec la stack actuelle (pas de service DB) | Oui | Oui — reste un simple fichier, zéro service supplémentaire | Non — introduit un service que le projet n'a jamais eu (`docker-compose.yml` actuel : 3 services, aucun DB) |
| Multi-tenant bancaire à terme | Non | Limité (à surveiller Phase 7-8) | Oui, nativement |

**Ne pas recommander PostgreSQL "parce que plus professionnel"** — ce serait ajouter un service, une opération de sauvegarde, une dépendance réseau à un produit dont le déploiement actuel est volontairement simple (3 services Docker, pas de DB). Rien dans le besoin actuel (un analyste, un VPS, des dizaines-centaines de projets) ne justifie ce coût.

## 5 bis.6 — Quand introduire SQLite

**Après la stabilisation (Phase 1), au début de la Phase 3 — pas maintenant, pas après 100 projets, pas en attendant les données bancaires.** Le déclencheur n'est pas un nombre de projets, c'est le fait que le code documente déjà lui-même le seuil de bascule (`analysis_store.py` : "si le volume grossit, un index éviterait de tout relire — pas fait ici, prématuré"). Ce seuil est en train d'être atteint par la Phase 4 (croissance corpus) — introduire la structure juste avant, pas pendant ni après, évite une migration de données en pleine croissance.

## 5 bis.7 — Ce qui reste hors de SQLite

Les PDF/documents sources **restent des fichiers** (`corpus/`, comme aujourd'hui) — jamais insérés en base. SQLite contient les métadonnées, les réponses structurées, les corrections, les liens (`file_path` en référence, pas le contenu binaire). Schéma de flux :

```
Document source (PDF)
  → fichiers sur disque (corpus/, inchangé)
  → métadonnées dans SQLite (projects, documents)
  → analyse structurée dans SQLite (analyses, question_answers)
  → verbatim = référence (span + doc_id), pas duplication du texte source
  → corrections dans SQLite (review_corrections)
  → embeddings/FAISS restent binaires sur disque (models/), référencés par chunk_id
```

## 5 bis.8 — SQLite comme source de vérité structurée

Oui, et c'est là que la valeur est concrète et immédiate : toutes les questions listées dans le brief ("combien de projets hydroélectriques", "quels risques par région", "quelles corrections Elisa a-t-elle faites", "quelle version a produit ce score", "le système s'améliore-t-il") deviennent des requêtes SQL d'une ligne au lieu de scripts ad hoc ou, aujourd'hui, de réponses tout simplement impossibles à donner (aucune trace de correction n'existe). C'est le gain le plus tangible et le moins coûteux de toute la roadmap proposée.

## 5 bis.9 — Impact sur l'IA

SQLite ne remplace pas FAISS (retrieval sémantique) — il le complète en séparant proprement : `question_answers` = connaissance validée/structurée, `few_shot_examples` = exemples curés (Section 7), `eval_cases`/`eval_results` = évaluation, le tout requêtable indépendamment de la recherche vectorielle. C'est une bonne couche intermédiaire avant tout futur système RAG plus élaboré : le RAG répond "quel passage est pertinent", SQLite répond "qu'est-ce qui a été validé à ce sujet" — deux questions différentes, aujourd'hui confondues faute de structure.

## 5 bis.10 — Architecture cible

```
Documents sources (PDF, CAO/IFC)
        │
        ▼
Pipeline ingestion (ingest.py, inchangé)
        │
        ▼
   ┌─────────────────────────────┐
   │          SQLite             │
   │  projects · documents       │
   │  analyses · question_answers│
   │  review_corrections         │
   │  eval_cases · eval_results  │
   │  few_shot_examples          │
   └──────────────┬───────────────┘
                  │
     ┌────────────┼─────────────┐
     ▼            ▼             ▼
Dashboard/    Harnais         Sélection
requêtes SQL  d'évaluation    few-shot
(secteur,     (Phase 2)       (retrieval
région, ...)                  + curation)
                                    │
                                    ▼
                          Prompts grid_prompts.py
                          (LLM d'extraction, inchangé)
```

Pas de "wiki" ni de "knowledge base" comme boîte séparée — c'est SQLite + FAISS + un document de synthèse versionné écrit à la main (Section 6), pas un cinquième composant.

## 5 bis.11 — Recommandation finale

**OPTION B — Introduire SQLite après le MVP, au début de la Phase 3 (post-stabilisation, avant la croissance du corpus).** Pas maintenant (le MVP actuel n'en a pas besoin pour la soutenance du 25/08, et le risque de régression 3 jours avant une démo n'en vaut pas la peine) ; pas Option A (le code documente déjà lui-même la limite de l'architecture fichiers) ; pas Option C (PostgreSQL, sur-dimensionné, ajoute un service que la stack n'a jamais eu, sans besoin multi-tenant avant la Phase 7-8).

> **Niveau minimal de structuration nécessaire, sans sur-ingénierie** : un fichier SQLite unique, 8 tables (Section 5 bis.3), sans service séparé, sans ORM lourd (le module `sqlite3` de la bibliothèque standard suffit), migré depuis les JSON existants en une opération ponctuelle. C'est suffisant pour tracer les sources, enregistrer les analyses et les corrections, mesurer les performances, remplacer le "wiki" par des requêtes, et préparer — sans la construire prématurément — l'isolation multi-tenant bancaire via une seule colonne (`tenant_id`) ajoutée dès la conception.

---

# VERDICT

**OUI, MAIS.**

La direction (corpus public vérifiable → structuration → spécialisation bancaire) est la bonne direction long terme, et le code montre que l'équipe y pense déjà implicitement (scrapers existants, `analysis_store.py` qui anticipe lui-même le besoin d'index). Mais la stratégie proposée, **telle que séquencée**, répète à petite échelle l'erreur qui a motivé toute la refonte de cet été : optimiser un chiffre (volume de corpus, score final) sans avoir d'abord construit le moyen de vérifier que ce chiffre reflète une vraie amélioration. L'écart CBG (78 vs 30-40) n'était pas un problème de volume de données — c'était un problème de méthodologie de scoring et de mesure. Reproduire "plus de données, plus de connaissance accumulée" sans d'abord fermer les calibrations en attente et sans jeu de validation gelé, c'est le même risque sous une autre forme.

Ne pas suivre la stratégie telle que proposée (46→100-150 puis wiki puis few-shot puis test). La suivre dans l'ordre corrigé : **mesurer d'abord sur l'existant, structurer ensuite, grossir le corpus seulement une fois qu'on sait ce que "meilleur" veut dire.** Le corpus de 46 projets actuels, correctement instrumenté (Sections 8-9, 5 bis), suffit à démarrer ce travail dès maintenant — rien de tout cela n'attend le 25/08 ni les données bancaires.
