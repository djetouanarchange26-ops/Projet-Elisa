# Audit de pertinence — Note de Cadrage Archange + Corpus Sources

Vérification en lecture seule de l'état réel du repo (branche `main`, commit `c502220`) sur les 7 points signalés. Fichiers inspectés : `grid_analyze.py`, `grid_scoring.py`, `grid_prompts.py`, `grid_questions.py`, `grid_result.py`, `grid_sections.py`, `app.py`, `export.py`, `search.py`, `scripts/test.py`.

---

## 1. R12 — Non-double-comptage

**ÉTAT : partiel**

**OÙ :**
- `grid_prompts.py:86-109` — `_ARTICULATION_B23_B41` (règle R2bis)
- `grid_scoring.py:204-235` — `_apply_shared_cap` / `SHARED_CAP_PENALTY`
- `grid_questions.py:88-105` — `shared_cap_group="A.1"` sur A.1.1/A.1.3

Il n'existe **aucun mécanisme général** de type « ce fait a déjà répondu à la question X, ne pas le recompter pour Y ». Ce qui existe est du cas-par-cas :
- **R2bis** (`grid_prompts.py`) : règle textuelle injectée uniquement dans les prompts B.2.3/B.4.1, qui dit au LLM de ne pas faire déclencher les deux questions sur le même verbatim sauf cas explicite. C'est une instruction de prompt, pas un contrôle vérifiable en Python — rien n'empêche le LLM de l'ignorer, et rien côté `grid_scoring.py` ne vérifie a posteriori que les verbatims de B.2.3 et B.4.1 diffèrent.
- **shared_cap_group** (`grid_scoring._apply_shared_cap`) : ne prévient pas le double comptage du *fait*, il plafonne la *pénalité combinée* de A.1.1+A.1.3 à −25 si les deux sont OUI. Le mécanisme est en aval (sur le score), pas en amont (sur l'attribution du fait à une seule question), et concerne seulement A.1/A.1.3.

Le cas d'origine cité (Mundra, refus de partage de données) correspond au few-shot B.3.1 « REFUS DE MONITORING » (`grid_prompts.py:388-391`) — un exemple isolé, pas une règle transversale anti-doublon.

**CE QUI MANQUE :** un principe R12 général (instruction de prompt commune à toutes les questions, ou vérification post-hoc en Python comparant les `evidence_r` entre questions) qui empêche un même verbatim de pénaliser deux questions distinctes en dehors des deux cas déjà couverts (B.2.3/B.4.1, A.1.1/A.1.3).

**PRIORITÉ SUGGÉRÉE :** à faire après le 25/08 — les deux cas concrets connus (Mundra, B.2.3/B.4.1) sont déjà couverts par des règles ad hoc ; une règle générale est un raffinement, pas un bloqueur pour la présentation.

---

## 2. Polarité de l'opposition communautaire

**ÉTAT : partiel, avec un décalage de code par rapport à l'énoncé de l'audit**

**Point important à signaler avant tout : dans le code actuel, A.1.1 n'est PAS la question d'opposition communautaire.**

| Code | `sous_theme` (grid_questions.py) |
|------|-----------------------------------|
| A.1.1 | Opposition sociale — **personnel** (grève des employés) |
| A.1.3 | Opposition **communautaire** (blocage par riverains) |

C'est **A.1.3** qui correspond au cas décrit dans l'audit (Mundra, route d'accès fermée). Ceci est cohérent avec une divergence déjà connue (cf. mémoire `project_grid_v3_directive_test_mismatches` : les codes du code source ne correspondent pas toujours 1:1 à ceux attendus par une directive/note externe).

**OÙ :**
- `grid_prompts.py:246-267` — few-shot A.1.1 et A.1.3
- `grid_questions.py:92-106` — définition A.1.3

Prompt A.1.1 (few-shot, personnel) :
```
FAUX POSITIF — droit vs fait (CBG) :
« CBG workers have the right to freely associate in unions as well as a right to strike. »
« strike » = droit, pas événement → NON
```
Aucune règle de direction (qui bloque qui) — n'est pas pertinent puisque A.1.1 porte sur les employés du projet, pas sur la communauté.

Prompt A.1.3 (few-shot, communautaire) :
```
PIÈGE DE POLARITÉ — qui bloque qui ? :
Si c'est le PROJET qui bloque l'accès de la communauté (routes fermées, forces de sécurité) → B.1.1, JAMAIS A.1.3.
Si c'est la COMMUNAUTÉ qui bloque le projet → A.1.3.
```
La distinction de direction **existe bel et bien**, mais :
- elle vit uniquement dans le **few-shot** (exemple illustratif), pas dans la formulation de `question_r` elle-même (`grid_questions.py:96` : « Blocage physique du site... par des riverains ou communautés tierces » — cette formulation précise déjà que c'est la communauté qui bloque, donc le risque d'ambiguïté est partiellement limité par le libellé, mais rien n'empêche le LLM de mal lire un passage où c'est l'inverse sans le few-shot).
- la redirection proposée vers **B.1.1** est douteuse : `B.1.1` (`grid_questions.py:153-166`) porte sur « perte de moyens de subsistance / déplacement involontaire non compensé », ce qui ne correspond pas nécessairement à une fermeture de route par le projet pour raisons sécuritaires. Aucune question de la grille V4 actuelle ne semble être un réceptacle naturel pour « le projet restreint l'accès de la communauté » — ce few-shot pointe peut-être vers une question qui n'existe plus sous ce nom en V4.

**CE QUI MANQUE :**
- Confirmer avec l'auteur de la Note de Cadrage que le point concerne bien A.1.3 (pas A.1.1) dans le code actuel.
- Vérifier/refaire la redirection vers B.1.1 du few-shot A.1.3, qui semble imprécise dans le libellé V4 actuel.

**PRIORITÉ SUGGÉRÉE :** à faire après le 25/08 pour la correction de la redirection B.1.1 (raffinement de few-shot) ; le décalage de numérotation A.1.1/A.1.3 est à signaler à Elisa/Stacy avant toute nouvelle directive pour éviter une confusion de référence.

---

## 3. N/A argumenté vs silence

**ÉTAT : n'existe pas (au niveau statut structuré)**

**OÙ :**
- `grid_prompts.py:190-191` (template standard) et `227-228` (B.3.1) — format de réponse attendu
- `grid_prompts.py:499` — `_LINE_PATTERNS["status"]` : `r"^STATUS\s*:[ \t]*(OUI|NON|INCONNU)\b"`
- `grid_questions.py:327` — `RESPONSE_VALUES = {"OUI", "NON", "INCONNU", "NA"}`
- `grid_analyze.py:184-197` — `_na_answer` (seul point d'entrée de `status="NA"`)

Statuts réellement possibles par question aujourd'hui :
- **Au niveau LLM (parsing)** : uniquement `OUI`, `NON`, `INCONNU` — le regex de parsing du STATUS n'accepte même pas `NA`, donc le LLM ne peut structurellement jamais renvoyer NA pour une question individuelle.
- **Au niveau `NA`** : n'existe que via `grid_analyze._na_answer`, déclenché uniquement quand toute la question appartient à un `na_module` désactivé manuellement par l'analyste (aujourd'hui seulement `B.2`) — exactement le mécanisme « module entier désactivé » que l'audit distingue du N/A argumenté attendu.

Le concept de N/A argumenté existe seulement à l'état d'**exemple few-shot**, jamais comme statut structuré :
- `grid_prompts.py:306-308` (few-shot B.1.1) : « N/A ARGUMENTÉ — exemplaire (Indorama)... C'est le modèle. »
- `grid_prompts.py:393-395` (few-shot B.3.1) : « N/A VALIDE — pas d'habitat critique (Indorama) »

Dans les deux cas, comme le format de réponse n'a pas de case NA, le LLM est censé (implicitement, via le few-shot) répondre **NON** pour ces cas — un N/A argumenté finit donc encodé comme un NON ordinaire, indiscernable d'un vrai NON risque ou d'un NON par silence dans `grid_result.py` (le champ `atteste` distingue NON+verbatim de NON sans verbatim, mais ne distingue pas « NON car risque absent » de « NON car N/A argumenté »).

**CE QUI MANQUE :**
- Un statut ou un champ structuré distinct (`N/A_ARGUMENTE` ou un booléen `na_argumente` porté par `evidence_r`) séparé de `NON`.
- Extension du parsing (`_LINE_PATTERNS["status"]`) et du format de prompt pour permettre au LLM de le signaler explicitement, plutôt que de compter sur le few-shot pour orienter vers NON.
- `grid_scoring.py`/`grid_result.py` ne gèrent donc pas ce cas — rien à corriger côté scoring tant que le statut n'existe pas en amont.

**PRIORITÉ SUGGÉRÉE :** à faire après le 25/08 — l'effet pratique actuel (NON, 0 pénalité) est déjà le bon comportement de scoring pour un N/A argumenté ; ce qui manque est la **traçabilité/lisibilité** pour l'analyste, pas la justesse du score. Non bloquant pour la soutenance, mais à noter comme limite connue si Elisa pose la question en démo.

---

## 4. Phase de la mesure (baseline ≠ projet)

**ÉTAT : partiel — pas de règle R2 dédiée, couverture uniquement par few-shot B.2.2**

**OÙ :**
- `grid_prompts.py:150` — texte exact de R2
- `grid_prompts.py:366-372` — few-shot B.2.2 (Indorama)

Texte exact de R2 (`_STANDARD_PROMPT_TEMPLATE`, `grid_prompts.py:150`) :
```
R2 — MATÉRIALISATION : seul un FAIT DATÉ, SURVENU, ATTRIBUÉ AU PROJET déclenche un OUI.
Un droit, une politique, une procédure, une vulnérabilité future = NON.
Vérifier : verbe au passé accompli + fait daté + attribution causale au projet.
```
Il n'y a **aucune mention explicite de la notion de baseline / état initial** dans R2. La clause « ATTRIBUÉ AU PROJET » est censée couvrir implicitement le cas (une mesure d'état initial n'est pas causalement attribuable au projet), mais ce n'est pas énoncé — R2 ne dit jamais « exclure les mesures de la phase antérieure au projet » ni le mot « exceeded »/« baseline ».

La couverture réelle vient exclusivement du few-shot **B.2.2** (`grid_prompts.py:366-372`) :
```
FAUX POSITIF — dépassement état initial (Indorama) :
« At night-time, measured LAeq exceeded the 45 dB IFC criterion at location N9 only »
Dépassement mesuré dans le chapitre état initial, AVANT travaux. Le projet n'en est pas la cause. → NON

FAUX POSITIF — dépassement géogénique (Indorama) :
« observed exceedances are likely attributable to natural background conditions typical of the regional geology »
Origine naturelle, pas anthropique. → NON
```
Cette instruction n'est injectée **que dans le prompt B.2.2** (few-shot par question, `_FEW_SHOT_EXAMPLES["B.2.2"]`) — elle n'apparaît dans aucune autre question qui pourrait pourtant être exposée au même piège (ex. B.2.3 déversement, B.4.1 impacts sanitaires géogéniques).

**CE QUI MANQUE :** une règle R2-baseline générique dans le corps commun `_STANDARD_PROMPT_TEMPLATE` (comme R1/R2/R5/R10 le sont déjà), plutôt qu'un few-shot localisé à une seule question — pour couvrir aussi B.2.3/B.4.1 si un rapport mentionne un dépassement/impact d'état initial sur ces thèmes.

**PRIORITÉ SUGGÉRÉE :** à faire après le 25/08, sauf si un rapport de test avant la soutenance produit effectivement un faux positif baseline sur B.2.3/B.4.1 — auquel cas bloquant.

---

## 5. Quatre champs manuels obligatoires

**ÉTAT : n'existe pas**

**OÙ vérifié :** `app.py:738-800` (sidebar complète), `grid_analyze.py` (signature de `analyze_grid`/`analyze_grid_auto`), `grid_result.py` (format de résultat), `export.py` (grep sans résultat).

La sidebar Grille V4 (`app.py:775-800`) contient exactement deux contrôles :
1. `st.selectbox("Type de document (R11)", ...)` — le type de document (1-4), pas une classification Equator Principles.
2. `st.multiselect("Modules N/A", options=["B.2"], ...)` — désactivation du module pollution.

Aucun des 4 champs demandés n'existe nulle part dans le repo :

| Champ | Présent ? |
|-------|-----------|
| Classification Equator Principles (A/B/C) | ❌ absent |
| Statut de sensibilité | ❌ absent |
| Montant du financement | ❌ absent |
| Rôle de CACIB dans le deal | ❌ absent |

- `grid_analyze.analyze_grid()`/`analyze_grid_auto()` ne reçoivent que `chunks`, `na_modules`, `document_type` — pas de paramètre pour ces 4 champs.
- `grid_result.build_grid_result()` ne les inclut pas dans le format de sortie.
- `export.py` ne les référence pas (grep vide).
- Rien dans le code n'empêche de lancer une analyse sans ces informations (pas de blocage, puisqu'il n'y a pas de saisie du tout).

**CE QUI MANQUE :** tout — saisie sidebar (probablement 4 `st.text_input`/`st.selectbox` bloquants avant le bouton "Run Analysis"), passage de ces valeurs à travers l'orchestrateur, inclusion dans `grid_result`, affichage dans `export.py` (PDF/Excel).

**PRIORITÉ SUGGÉRÉE :** **bloquant soutenance** si la Note de Cadrage exige ces 4 champs comme prérequis d'usage — c'est une fonctionnalité UI simple (formulaire bloquant + pass-through) mais absente à 100%, et son absence est immédiatement visible en démo si Elisa s'attend à les voir.

---

## 6. Exclusion des plans d'urgence

**ÉTAT : n'existe pas**

**OÙ vérifié :** `grid_sections.py` (fichier entier, lu intégralement), recherche `emergency|contingency|response.plan|urgence` sur tout `scripts/` → aucune occurrence.

Exclusions actuellement implémentées dans `grid_sections.py` (liste exhaustive, `classify_chunks`) :
1. **ESAP** (`ESAP_TITLE_PATTERNS`, `grid_sections.py:44-48`) — items d'action plan, exclus de la mitigation uniquement (gardés pour le risque, R7bis).
2. **Section plaintes IFC** (`COMPLAINTS_SECTION_PATTERNS`, `grid_sections.py:51-55`) — texte type de fin d'ESRS, exclu du risque ET de la mitigation.
3. **Couches temporelles** (`TEMPORAL_LAYER_PATTERNS`, `grid_sections.py:87-103`) — marquage informatif seulement, n'exclut rien (documents Type 3).

Aucun pattern « emergency », « contingency », « response plan », ni équivalent français « plan d'urgence » n'existe. Un rapport contenant une section de plan d'urgence contenant des scénarios de déversement/incendie/explosion serait traité comme du texte normal, exposé tel quel au LLM comme n'importe quel passage — le vocabulaire hypothétique de ces sections (« in case of… », « scenario », des verbes au conditionnel/infinitif) est censé être filtré par R2 (« seul un fait daté, survenu ») côté prompt, mais **pas au niveau chunking/section** comme le sont ESAP et plaintes IFC.

**CE QUI MANQUE :** un `EMERGENCY_TITLE_PATTERNS` + logique de continuation analogue à ESAP (`grid_sections.py:41-79`), avec exclusion du risque (pas seulement de la mitigation, puisque le problème ici est un faux positif R, pas un faux positif A).

**PRIORITÉ SUGGÉRÉE :** à évaluer selon le risque réel observé sur les rapports de test — si aucun faux positif "emergency plan" n'a été constaté dans les 4 dossiers annotés (CBG/Mundra/Aysha/Indorama) contrairement à ESAP/plaintes IFC (qui, eux, ont motivé une correction dédiée CC-09), ce point est probablement **non pertinent immédiat** ; sinon bloquant.

---

## 7. Score Aysha dans les tests de calibration

**ÉTAT : divergence confirmée entre Note de Cadrage et code**

**OÙ :**
- `scripts/test.py:1723-1730` — `test_calibration_aysha()`
- `scripts/test.py:1677-1685` — `_aysha_answers_v4()`
- `grid_questions.py:76-257` — `QUESTIONS`

**Score Aysha attendu dans les tests actuels : 73 (JAUNE)**, pas 61 comme indiqué dans la Note de Cadrage Archange :
```python
def test_calibration_aysha():
    """Aysha I Wind — Type 1, score attendu 73, JAUNE."""
    ...
    _test("Aysha : score = 73", result["score"] == 73, ...)
    _test("Aysha : color = JAUNE", result["color"] == "JAUNE", ...)
```
Détail du calcul encodé (`_aysha_answers_v4`, commentaire ligne 1685) :
```
Pénalités : B.1.1(-15) B.3.1(-15) = -30 ; Gains : B.1.1(+3) = +3 ; score = 100 - 30 + 3 = 73
```
Ceci correspond au « panachage B.1.1 adapté / B.3.1 strict » mentionné dans l'audit, confirmant que **73 est bien le résultat du panachage**, pas de 61.

**Liste exacte des 12 codes de questions dans le code** (`grid_questions.QUESTIONS`) :
```
A.1.1, A.1.3, A.2.1, A.3.1, A.4.1, B.1.1, B.1.2, B.2.1, B.2.2, B.2.3, B.3.1, B.4.1
```
Comparaison avec la Maquette Vierge citée dans l'audit (`A.1.1, A.1.2, A.2.1, A.2.2, A.3.1, A.3.2, B.1.1, B.1.2, B.2.1, B.2.2, B.3.1, B.3.2`) :

| Maquette (audit) | Code actuel | Écart |
|---|---|---|
| A.1.1 | A.1.1 | même code, **sous_theme différent** (maquette = communautaire probable ; code = personnel/grève, cf. point 2) |
| A.1.2 | **A.1.3** | code renuméroté |
| A.2.1 | A.2.1 | identique |
| A.2.2 | *(absent)* | supprimé/fusionné |
| A.3.1 | A.3.1 | identique |
| A.3.2 | *(absent)* | supprimé/fusionné |
| *(absent)* | **A.4.1** | ajouté (force majeure) |
| B.1.1 | B.1.1 | identique |
| B.1.2 | B.1.2 | identique |
| B.2.1 | B.2.1 | identique |
| B.2.2 | B.2.2 | identique |
| *(absent)* | **B.2.3** | ajouté (déversement/fuite) |
| B.3.1 | B.3.1 | identique (mais polarité changée, cf. `a_condition="r_non"`) |
| B.3.2 | *(absent)* | supprimé/fusionné |
| *(absent)* | **B.4.1** | ajouté (impacts sanitaires) |

Le module documente lui-même ces écarts comme volontaires (`grid_questions.py:18-32`, section « Changements V3 -> V4 ») : ajout de A.1.3 et B.4.1, changement de polarité B.3.1. Ceci est cohérent avec la mémoire déjà enregistrée (`project_grid_v3_directive_test_mismatches`) indiquant que les exemples de test CC-0X peuvent diverger de la Maquette Vierge sans que ce soit une erreur.

**CE QUI MANQUE :** rien côté code — les tests sont internement cohérents et documentés. Ce qui manque est un **alignement explicite validé par Elisa** entre (a) la Maquette Vierge originale, (b) la Note de Cadrage Archange (qui suppose encore un score Aysha=61 et implicitement l'ancienne numérotation A.1.2/A.2.2/A.3.2/B.3.2), et (c) le code V4 actuel (numérotation A.1.3/A.4.1/B.2.3/B.4.1, Aysha=73). Ces deux documents sources semblent référencer une version de la grille antérieure aux décisions V4 déjà actées dans le code.

**PRIORITÉ SUGGÉRÉE : bloquant soutenance** — si la Note de Cadrage Archange doit servir de référence en présentation le 25/08 et cite 61 alors que l'outil produira 73, c'est un écart visible et potentiellement déstabilisant en démo. Nécessite une clarification rapide : soit la Note de Cadrage est obsolète (à corriger/retirer avant la présentation), soit le panachage V4 encodé dans les tests est erroné (à revoir avec Elisa avant le 25/08).

---

## Résumé priorités

| # | Point | Priorité |
|---|-------|----------|
| 5 | 4 champs manuels obligatoires | **Bloquant soutenance** |
| 7 | Score Aysha (61 vs 73) + numérotation questions | **Bloquant soutenance** (clarification urgente, pas forcément code) |
| 2 | Polarité opposition communautaire | À faire après / signaler le décalage A.1.1↔A.1.3 |
| 4 | Phase baseline (R2) | À faire après, sauf régression observée sur B.2.3/B.4.1 |
| 6 | Exclusion plans d'urgence | Non pertinent probable, à confirmer sur corpus de test |
| 1 | R12 non-double-comptage | À faire après (cas connus déjà couverts ad hoc) |
| 3 | N/A argumenté vs silence | À faire après (score déjà correct, traçabilité manquante) |
