# User Stories — Correctifs suite au test d'un rapport réel (2026-08-14)

Perspective : Elisa, analyste crédit, utilisatrice finale de l'outil. Chaque story
suit le format `En tant que / Je veux / Afin de` + critères d'acceptation en
Given/When/Then. À lire avec `SPECS_CORRECTIFS_RAPPORT_TEST.md` (détail technique)
et `PRIORISATION_CORRECTIFS_RAPPORT_TEST.md` (ordre de traitement).

---

## US-F1 — Ne pas compter la table des matières comme un signal de risque

**En tant qu'** analyste crédit consultant la carte "Detected Signals",
**je veux** que le nombre de mentions affiché reflète uniquement du texte analytique réel,
**afin de** ne pas surestimer la gravité d'un signal à cause de titres de section répétés dans le sommaire du document.

### Contexte métier
Sur le rapport testé, des signaux comme "Community" ou "Pollution" affichaient des
centaines de "mentions du terme" — en grande partie des titres de section dans la
table des matières, pas du texte décrivant un vrai risque. Ce comptage gonflé peut
faire percevoir un document comme plus problématique qu'il ne l'est réellement, ou
inversement noyer les vraies mentions à risque dans du bruit lors d'une lecture rapide.

### Critères d'acceptation
- **Given** un document contenant une table des matières qui répète des mots-clés de signaux ESG,
  **When** j'analyse ce document,
  **Then** le compte de "N mention(s) du terme" affiché pour chaque signal n'inclut pas les lignes de sommaire/liste de figures.
- **Given** ce même document,
  **When** je consulte "Annotated Document",
  **Then** aucune ligne de table des matières n'apparaît surlignée.
- **Given** un document sans table des matières (texte continu),
  **When** je l'analyse,
  **Then** le comportement de détection des signaux reste identique à aujourd'hui (pas de régression sur les cas déjà corrects).

---

## US-F2 — Toujours lire l'analyse en français, même sur un document source en anglais

**En tant qu'** analyste crédit lisant la section "Deep Analysis" et le tableau "Findings",
**je veux** que le texte généré par l'IA soit systématiquement en français,
**afin de** pouvoir le citer ou le coller directement dans un mémo de comité de crédit sans retraduction manuelle, et de donner une impression de produit fini en démo.

### Contexte métier
Le corpus de référence (IFC/CAO) est en anglais. Sur le rapport testé, certains
findings Pass 1 étaient en français, d'autres en anglais, dans la même liste —
gênant à la fois pour la lecture et pour l'usage direct dans un document interne
en français.

### Critères d'acceptation
- **Given** un document source rédigé en anglais,
  **When** j'analyse ce document,
  **Then** tous les findings de la table "Findings" (types Incident/Évasif/Engagement) sont rédigés en français.
- **Given** ce même document,
  **When** je lis la carte "Deep Analysis" (synthèse),
  **Then** la synthèse est intégralement en français, sans phrase ou fragment en anglais.
- **Given** un document déjà rédigé en français,
  **When** je l'analyse,
  **Then** le comportement reste inchangé (déjà en français aujourd'hui).

---

## US-F3 — Comprendre à quoi se comparent les scores du Radar ESG

**En tant qu'** analyste crédit consultant le "ESG Radar" d'un document analysé,
**je veux** voir sur quoi se base concrètement chaque score (quels projets historiques, quels passages),
**afin de** pouvoir justifier le score auprès d'un comité de crédit plutôt que de présenter un chiffre abstrait sans preuve associée visible immédiatement.

### Contexte métier
"76 en Community Risk" n'est pas actionnable seul : l'analyste doit aujourd'hui
déplier un `<details>` sous chaque barre de "Flag Scores" pour voir les projets
similaires qui justifient ce chiffre — l'information existe mais n'est pas mise
en avant à côté du radar lui-même.

### Point ouvert (à trancher avant d'écrire les critères d'acceptation définitifs)
Deux directions possibles, voir `PRIORISATION...md` pour la décision à prendre :
(a) rendre l'évidence déjà calculée plus visible à côté du radar (changement de mise en page), ou
(b) remplacer le radar par un bloc "Projets les plus similaires" qui devient le point d'entrée principal (changement plus large, proche d'une nouvelle fonctionnalité).

### Critères d'acceptation (provisoires — à ajuster selon la décision retenue)
- **Given** un document analysé avec un flag_score élevé sur un des 3 flags,
  **When** je regarde la zone du Radar/Flag Scores,
  **Then** je vois, sans avoir à déplier quoi que ce soit, au moins un projet historique similaire avec un résumé d'une phrase expliquant le lien.
- **Given** un flag_score bas sur les 3 flags,
  **When** je regarde cette même zone,
  **Then** l'absence de projets similaires à risque élevé est explicite (pas une zone vide non expliquée).

---

## US-F4 — Comprendre ce que veut dire le score "Document Specificity"

**En tant qu'** analyste crédit qui n'est pas familière avec les détails techniques du NLP,
**je veux** comprendre immédiatement ce que mesure le pourcentage "Document Specificity" et pourquoi il m'intéresse,
**afin de** pouvoir m'en servir comme argument dans mon évaluation sans avoir à demander une explication technique à chaque fois.

### Contexte métier
Le score est correct (il mesure la précision/le concret du langage du document,
un signal de greenwashing potentiel) mais son libellé actuel ("Document
Specificity", "Niveau de précision du rapport") ne rend pas ce lien explicite
pour quelqu'un qui découvre l'écran.

### Critères d'acceptation
- **Given** un document dont le score de spécificité est bas (< 40%),
  **When** je consulte la carte "Document Specificity",
  **Then** le texte affiché m'indique explicitement que ce chiffre est un indicateur de langage vague/potentiellement évasif du rapport lui-même, pas un score de risque ESG au même titre que les Flag Scores.
- **Given** n'importe quel score de spécificité,
  **When** je survole ou lis la description à côté du pourcentage,
  **Then** je comprends sans effort la différence entre ce score et les 3 Flag Scores (Community/Pollution/Compliance).

*(Le libellé exact reste à valider avec Elisa avant implémentation — cf. `SPECS...md`.)*

---

## US-F5 — Ne pas être troublée par deux lignes quasi-identiques pour le même passage

**En tant qu'** analyste crédit consultant le tableau "Findings",
**je veux** comprendre immédiatement pourquoi un même passage du document apparaît deux fois (une fois "Incident", une fois "Évasif"),
**afin de** ne pas perdre de temps à me demander si c'est une erreur de l'outil ou une information dupliquée par erreur.

### Contexte métier
Ce n'est PAS un bug — un passage peut légitimement décrire un vrai incident tout
en étant formulé de façon évasive ("des mesures seront envisagées si
approprié"). Les deux findings sont réels et distincts, mais leur présentation
actuelle (deux lignes de tableau séparées référençant le même chunk source) peut
donner l'impression d'un doublon.

### Critères d'acceptation
- **Given** un chunk source détecté à la fois comme "Incident" et "Évasif" par l'analyse,
  **When** je consulte le tableau "Findings",
  **Then** je vois clairement que les deux findings proviennent du même passage source (regroupement visuel, ou indication explicite du lien), sans avoir l'impression d'un doublon d'affichage.
- **Given** un chunk détecté avec un seul type de finding,
  **When** je consulte le tableau,
  **Then** l'affichage reste aussi simple qu'aujourd'hui (pas de complexité ajoutée pour le cas majoritaire à un seul type).
