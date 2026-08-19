# Priorisation — Correctifs suite au test d'un rapport réel (2026-08-14)

Contrainte de sprint active à cette date (cf. mémoire de session) : **gel de
nouvelles fonctionnalités jusqu'à la présentation du 25/08/2026** — seuls les
correctifs dirigés par une directive explicite sont dans le périmètre du sprint
en cours. Cette contrainte structure la priorisation ci-dessous : les items
proches d'un pur bug fix passent devant ceux qui touchent à la disposition/au
contenu de l'UI, même si leur valeur perçue est comparable.

Grille reprise du même système P0/P1/P2 déjà utilisé pour le triage des retours
d'Elisa sur ce sprint.

---

## Tableau de priorisation

| ID | Titre | Priorité | Nature | Effort estimé | Bloquant démo 25/08 ? |
|----|-------|----------|--------|----------------|------------------------|
| F1 | Table des matières comptée comme signaux | **P0** | Bug (données fausses affichées) | Moyen (nouvelle logique de filtrage + tests) | Oui — chiffres visiblement faux à l'écran |
| F2 | Mélange français/anglais dans les sorties LLM | **P0** | Bug (qualité de sortie) | Faible (2 lignes de prompt) | Oui — très visible en démo devant la banque |
| F5 | Incident + Évasif sur le même chunk | **P1** | Clarification UX (pas un bug) | Faible (regroupement d'affichage) | Non — n'affiche pas d'info fausse, juste redondante |
| F4 | Document Specificity peu actionnable | **P1** | Clarification produit (wording) | Très faible (texte à l'écran) | Non — mais rapide à faire si le wording est validé vite |
| F3 | Radar ESG peu interprétable | **P2** | Redesign UI (proche d'une nouvelle fonctionnalité) | Moyen à élevé selon la piste retenue | Non — risque de régression si fait dans l'urgence |

---

## Justification par item

### F1 — P0
La donnée affichée est objectivement fausse (des titres de sommaire comptés
comme des mentions de risque). C'est un bug de données, pas de présentation —
rentre clairement dans le périmètre "correctif dirigé par directive" du gel de
sprint, et c'est le seul des 5 items qui fausse un chiffre présenté comme fiable
à un comité de crédit. Déjà documenté comme dette dans `checklist.md` depuis le
2026-08-06 — le corriger maintenant referme un item de dette technique connu et
explicitement laissé ouvert à l'époque faute de temps.

### F2 — P0
Effort très faible (ajout d'une instruction dans 2 templates de prompt),
impact élevé sur la crédibilité perçue de l'outil en démo — un mélange de
langues dans un mémo à moitié généré donne une impression de prototype non fini.
Bon rapport effort/impact, à traiter juste après F1.

### F5 — P1
Ce n'est pas un bug (voir `SPECS...md`) — c'est une clarification d'affichage.
Utile mais pas critique : un analyste qui comprend que ce sont deux findings
distincts sur le même passage n'est pas induit en erreur, juste
temporairement surpris. À faire si le temps le permet avant le 25/08, sinon
juste après.

### F4 — P1
Changement de texte pur, effort minimal — mais **dépend d'une validation avec
Elisa sur le wording exact** avant implémentation (cf. `SPECS...md`), donc le
délai réel dépend de la disponibilité de ce retour, pas de l'effort technique.
À lancer en parallèle des items P0 (préparer le brouillon de libellé pendant
que F1/F2 sont en cours), pour ne pas bloquer sur la disponibilité d'Elisa.

### F3 — P2, avec une question ouverte à trancher avant tout travail dessus
C'est l'item le plus proche d'une **nouvelle fonctionnalité** plutôt que d'un
correctif : remplacer ou réorganiser significativement un bloc d'affichage
existant. Compte tenu du gel de sprint jusqu'au 25/08, ce point ne devrait pas
être commencé avant la présentation, sauf décision explicite contraire.

**Question ouverte à poser avant de lancer F3, quelle que soit la date retenue** :
> Veut-on (a) un ajustement de mise en page minimal (afficher l'évidence déjà
> calculée sans la replier par défaut), qui reste un correctif d'ergonomie
> mineur et pourrait éventuellement rentrer dans le gel de sprint, ou (b) un
> redesign plus large qui fusionne "Evidence behind this score" et "Historical
> Similar Cases" en un seul bloc, qui est clairement une nouvelle
> fonctionnalité et devrait attendre le 25/08 ?

Ne pas trancher cette question par défaut dans le code — elle est explicitement
laissée ouverte dans `SPECS_CORRECTIFS_RAPPORT_TEST.md`.

---

## Séquencement recommandé

1. **F1** seul en premier — le plus gros effort des deux P0, et le seul qui
   touche à une logique de détection partagée (`analyze.py`/`search.py`) ; le
   traiter isolément limite le risque de confusion avec d'autres changements
   en cours.
2. **F2** ensuite ou en parallèle — indépendant de F1, aucun fichier partagé
   (F1 touche `analyze.py`/`search.py`, F2 touche uniquement les templates de
   `deep_analysis.py`), donc pas de conflit à séquencer un après l'autre si un
   seul développeur/une seule session Claude Code traite les deux directives.
3. **F4** — préparer le brouillon de libellé en parallèle de 1-2, implémenter
   dès validation par Elisa (changement trivial une fois le texte arrêté).
4. **F5** — après F1/F2, si le temps le permet avant le 25/08 ; sinon reporté
   juste après sans risque (n'affecte pas la crédibilité des chiffres affichés,
   contrairement à F1/F2).
5. **F3** — non commencé avant la décision produit ci-dessus, et probablement
   pas avant le 25/08 sauf arbitrage explicite en faveur de l'option (a)
   minimale.

## Dépendances entre items
Aucune dépendance technique croisée entre F1, F2, F4, F5 — chacun touche des
fichiers/fonctions différents et peut être livré indépendamment. F3 est
indépendant des 4 autres mais dépend d'une décision produit préalable, pas d'un
autre correctif.
