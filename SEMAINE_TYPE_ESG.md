# Semaine type — ESG Risk Intelligence (post-acceptation)

Base : 4h/semaine, modulable selon cours et autres projets.
Principe : chaque heure a un rôle clair, rien n'est perdu si
tu en rates une, et tu sais toujours par quoi reprendre.

---

## LE DÉCOUPAGE

```
4h/semaine réparties en 3 blocs :

┌─────────────────────────────────────────────────┐
│  BLOC 1 — Feedback & Priorisation    (30 min)   │
│  BLOC 2 — Développement             (2h30)      │
│  BLOC 3 — Apprentissage & Veille    (1h)        │
└─────────────────────────────────────────────────┘
```

Tu places ces blocs OÙ TU VEUX dans la semaine. Lundi soir,
mercredi entre deux cours, samedi matin — peu importe. La seule
règle : Bloc 1 en premier dans la semaine, toujours.

---

## BLOC 1 — Feedback & Priorisation (30 min)

**Quand** : premier créneau dispo de la semaine
**Où** : Claude Chat (ici)
**Objectif** : savoir exactement quoi faire cette semaine

Le rituel :

1. **Lire les retours d'Elisa** (Google Sheet, Slack, mail — 10 min)
   S'il n'y a rien de nouveau, passer à l'étape 2.

2. **Trier** (10 min) — chaque retour dans une case :
   - P0 : l'outil plante ou donne un résultat faux → cette semaine
   - P1 : l'info est là mais mal présentée → cette semaine si le
     temps le permet
   - P2 : feature request ou amélioration → backlog, pas cette semaine

3. **Décider l'objectif de la semaine** (10 min)
   UN SEUL objectif. Exemples :
   - "Corriger le bug X remonté par Elisa"
   - "Ajouter la feature Y validée ensemble"
   - "Améliorer la perf de l'analyse sur les gros documents"
   - "Ré-entraîner le Cox avec les nouveaux projets"

   Viens ici et dis : "Cette semaine, l'objectif c'est [X]. Voici
   le contexte. On écrit la directive ensemble."

   On produit la directive pour Claude Code en 10 min. Tu repars
   avec un document précis.

---

## BLOC 2 — Développement (2h30)

**Quand** : un ou deux créneaux dans la semaine (1×2h30 ou 2×1h15)
**Où** : Claude Code + ton terminal
**Objectif** : implémenter l'objectif de la semaine

Le cycle à chaque session :

```
1. git pull                              (30s)
2. Donner la directive à Claude Code     (5 min)
3. Claude Code implémente                (30-60 min)
4. Toi : lire le diff, comprendre        (15-20 min)
5. pytest tests/ -v                      (2 min)
6. Test manuel dans l'app                (10 min)
7. Si OK → commit + redéploiement        (5 min)
8. Si KO → revenir ici pour diagnostic   (15 min)
   → nouvelle directive → retour en 2.
```

**La règle des 15 minutes** : si Claude Code produit quelque chose
que tu ne comprends pas après 15 min de lecture, ne merge pas.
Viens ici avec le code et on l'explique ensemble. Le but n'est pas
d'aller vite, c'est de garder le contrôle.

**L'étape 4 est non-négociable.** Même si les tests passent, même
si ça marche. Tu lis le diff. Tu comprends ce qui a changé. C'est
ce qui te distingue d'un opérateur de prompt.

Si l'objectif de la semaine est petit (bug fix, ajustement UI),
tu finis en 1h et tu bascules le temps restant sur le Bloc 3.

---

## BLOC 3 — Apprentissage & Veille (1h)

**Quand** : dernier créneau de la semaine (idéalement)
**Où** : Claude Chat (ici)
**Objectif** : monter en compétence, progressivement

Deux modes, en alternance :

**Mode A — Approfondir une brique (1 semaine sur 2)**

Choisis un sujet et viens ici :
- "Explique-moi le re-ranker cross-encoder de mon projet"
- "Pourquoi le C-index a baissé quand j'ai changé d'embedding ?"
- "Comment fonctionne le cache disque LLM et quand il invalide ?"
- "Si je voulais passer à un modèle 7B, qu'est-ce qui change ?"

On fait une session Q&A ancrée dans ton code réel. Tu écris
la synthèse dans `docs/notes_theoriques.md`.

**Mode B — Veille technique (1 semaine sur 2)**

Viens ici et dis :
- "Quoi de neuf en scoring ESG / NLP financier ?"
- "Y a-t-il des alternatives à FAISS que je devrais connaître ?"
- "Quels papiers récents sur l'analyse ESG par LLM ?"
- "Comment les autres outils de due diligence fonctionnent ?"

Je cherche, je synthétise, on voit si quelque chose est pertinent
pour ton outil. Si oui, on le note dans le backlog — on ne
l'implémente pas maintenant.

---

## SI TU AS PLUS DE 4H

Quand tu as du temps libre ou qu'un chantier est urgent :

**6h/semaine** (+2h) :
- Bloc 2 passe à 4h30 (deux objectifs au lieu d'un, ou un
  objectif plus ambitieux)

**8h/semaine** (+4h) :
- Bloc 2 passe à 4h30
- Ajouter un Bloc 4 — "Chantier de fond" (2h30) : les trucs
  qui ne sont pas urgents mais qui comptent
  - Ré-entraîner le Cox sur les scores filtrés
  - Enrichir le corpus (scraping + annotation)
  - Investiguer la dégradation Ollama
  - Écrire les tests gold standard sur les nouveaux cas d'Elisa

**10h+/semaine** (semaine de vacances, deadline) :
- Tout ce qui précède + un chantier feature majeur (Q&A RAG,
  extension à un nouveau métier, refonte UI)

---

## SI TU AS MOINS DE 4H

Semaine chargée, partiels, autres projets :

**2h/semaine** (mode survie) :
- Bloc 1 (30 min) — lire les retours, prioriser
- Bloc 2 (1h30) — un seul fix, le plus critique
- Pas de Bloc 3 cette semaine

**0h/semaine** (semaine morte) :
- Envoie un message à Elisa : "Pas dispo cette semaine, je
  reprends [date]." C'est tout. L'outil tourne sur le VPS, il
  ne va pas s'arrêter.

---

## LE BACKLOG — OÙ VONT LES IDÉES

Tout ce qui n'est pas l'objectif de cette semaine va dans un
fichier `docs/BACKLOG.md` :

```markdown
# Backlog ESG Risk Intelligence

## P0 — Bugs bloquants
(vide = tout va bien)

## P1 — Améliorations prioritaires
- [ ] Ré-entraîner Cox sur scores filtrés LLM
- [ ] Fix dégradation Ollama sous charge soutenue
- [ ] Item H : flag_type "nan" dans Similar Cases

## P2 — Features validées avec Elisa
- [ ] Q&A libre sur document (RAG/chat)
- [ ] Support multilingue
- [ ] Mécanisme de feedback analyste ("ce flag est faux")

## P3 — Idées / Veille
- [ ] Random Survival Forest (quand corpus > 100 projets)
- [ ] Extension Real Estate (checklist BREEAM/HQE)
- [ ] Fine-tuning embedding sur le corpus ESG

## Écarté
- Annotation page par page (trop de travail, valeur incertaine)
- SHAP (retiré, pas assez de données)
```

Chaque lundi (Bloc 1), tu parcours le backlog et tu choisis
l'objectif de la semaine depuis P0 d'abord, puis P1, puis P2.
P3 ne devient jamais un objectif de semaine — c'est de la veille.

---

## LA COLLABORATION AVEC LA BANQUE

Si le projet est accepté, la dynamique change : tu n'es plus seul
à décider quoi faire. Voici comment gérer ça :

**Point hebdo avec Elisa (15 min, inclus dans le Bloc 1)** :
- Ce que tu as fait cette semaine
- Ce que tu prévois la semaine prochaine
- Ce dont tu as besoin d'elle (feedback, données, décision)

**Ce qu'Elisa fait de son côté** :
- Teste l'outil sur ses vrais cas
- Remplit le Google Sheet de feedback
- Valide les priorités (est-ce que P1-item-3 est vraiment
  plus important que P1-item-7 ?)
- Fournit les données métier (nouveaux rapports, cas connus,
  checklists de conformité)

**Ce que tu ne fais PAS** :
- Promettre des deadlines que tu ne peux pas tenir avec 4h/semaine
- Ajouter des features sans validation d'Elisa
- Travailler sur un truc juste parce que c'est techniquement
  intéressant (le Bloc 3 veille est là pour ça, séparé du dev)

**Ce que tu dis quand on te demande "c'est pour quand ?"** :
"Je travaille [X]h par semaine sur le projet. Cette semaine je
fais [objectif]. La semaine prochaine, [suivant dans le backlog].
Si c'est urgent, on peut reprioriser ensemble."

---

## EXEMPLE D'UNE SEMAINE CONCRÈTE

**Lundi — Bloc 1 (30 min, entre deux cours)**

Tu ouvres le Google Sheet : Elisa a noté "le flag community
s'affiche sur un rapport qui parle de compensation réussie —
faux positif". Tu classes ça en P0 (résultat faux). Tu viens
ici : "Elisa a un faux positif sur un rapport de compensation.
Voici le texte. On diagnostique ?"

On identifie ensemble : c'est le filtre de polarité qui laisse
passer un cas limite. On écrit la directive pour Claude Code.

**Mercredi — Bloc 2 (2h30, soirée)**

Tu donnes la directive à Claude Code. Il modifie le prompt de
confirm_risk pour mieux gérer les cas de mitigation réussie.
Tu lis le diff (5 min). Tu lances pytest (OK). Tu testes
manuellement avec le texte d'Elisa (le flag disparaît). Tu
commit, tu redéploies, tu préviens Elisa.

Temps restant (1h) : tu attaques un P1 simple — le flag_type
"nan" dans Similar Cases. Directive rapide, fix, test, deploy.

**Samedi — Bloc 3 (1h, matin)**

Mode A cette semaine. Tu viens ici : "Explique-moi comment
confirm_risk décide si un chunk est RISK ou CLEAN. Je veux
comprendre le prompt et pourquoi il est formulé comme ça."

On décortique le prompt, les cas limites, et pourquoi le faux
positif d'Elisa est passé à travers. Tu notes dans
`docs/notes_theoriques.md`.

Total : 4h. Un bug corrigé, un P1 fermé, une brique mieux
comprise. Elisa voit le fix dès jeudi matin.
