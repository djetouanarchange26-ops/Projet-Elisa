# Synthèse — Retour sur l'autopsie par couches (PDF) + audit du repo réel

Ce document complète la réflexion menée dans une conversation précédente avec
Claude (document PDF "autopsie par couches" — couches 1 à 5 du pipeline :
ingestion, embedding, retrieval, cascade LLM, modèle de risque). Cette
conversation-ci a repris ce PDF, l'a confronté au code réel du repo
(`scripts/`, `app.py`, `checklist.md`, logs de run), et en tire trois choses :
ce que le PDF a apporté, ce qu'il n'a pas vu, et les décisions qui en
découlent.

À lire avec `checklist.md` (journal de bord, état réel du projet) et
`CORRECTIONS.md` (bugs déjà corrigés) — ce document ne les remplace pas.

---

## 1. Ce que le PDF a apporté

Le PDF est un exercice d'auto-critique par couche (proposition → 3 faiblesses
→ ce qui manque → angle alternatif → version corrigée), répété pour les 6
couches du pipeline. Ce qui en ressort de solide et que je retiens :

- **Le raisonnement circulaire du centroïde de corpus** comme filtre de
  qualité (couche 1) : le corpus contient déjà du boilerplate non filtré, donc
  le centroïde est pollué, donc un filtre basé sur la distance à ce centroïde
  garde le boilerplate et rejette les chunks atypiques informatifs. Correct.
- **Les pondérations `0.3/0.4/0.3` inventées sans justification empirique**
  et non normalisées (couche 1) — vrai problème, jamais mesuré.
- **La PCA et le fine-tuning contrastif sont hors sujet pour ce corpus** :
  4000 vecteurs, FAISS `IndexFlatIP` déjà <5ms (la PCA gagne des millisecondes
  invisibles) ; 2000 paires propres après nettoyage contre les 500k+ des
  papiers de référence sur le fine-tuning contrastif (le gap est de deux
  ordres de grandeur). Écarté à raison pour le MVP.
- **Les prototypes de risque par flag** (couche 3) : remplacer le scoring
  FAISS + pré-filtre mots-clés + `confirm_risk` par une distance aux
  centroïdes des chunks historiquement confirmés RISK par flag. Idée
  directionnellement bonne — simplifie beaucoup, réduit le nombre d'appels
  LLM, sépare proprement les 3 flags.
- **Le rôle du LLM redéfini : rédacteur, pas analyste** (couche 4). Les
  couches 1-3 produisent déjà les données structurées (specificity_score,
  flag scores, omissions) ; le LLM 4B n'a qu'à les mettre en prose, avec un
  fallback template si la génération échoue. Cohérent avec les limites
  réelles d'un modèle 4B.
- **`@st.cache_resource` identifié comme le bug de perf potentiellement le
  plus grave**, traité en une ligne dans le PDF alors qu'il aurait dû être en
  tête de liste (couche 5).
- **`embed.py` identifié comme code mort** — confirmé par grep, zéro import
  nulle part dans le repo.
- **Détection d'omissions déterministe par matrice de matérialité IFC**
  plutôt que de demander à un LLM 4B de deviner ce qui manque (couche 4) —
  plus fiable, instantané, zéro appel LLM.

Ces éléments sont solides et j'ai gardé la logique du PDF pour construire la
liste de tâches ci-dessous.

---

## 2. Ce que le PDF n'a pas vu — vérifié dans le repo réel

Le PDF raisonne en architecture théorique, sans avoir lu le code ni les logs.
En allant vérifier, plusieurs points changent le diagnostic :

### 2.1 Les prototypes de risque ne suppriment pas la circularité, ils la déplacent

Le PDF affirme que les prototypes éliminent le pré-filtre mots-clés et que
« la polarité est intégrée dans les prototypes ». Faux en l'état :

- `chunks_metadata["event"]` est un vrai label terrain (une plainte CAO a-t-elle
  eu lieu pour ce **projet**, oui/non) — ça, c'est solide.
- Mais `chunks_metadata["flag_type"]` (quel flag un **chunk** représente) vient
  de `signals.flags_mentioned_in_text()` — le même filtre par mots-clés que
  la couche 3 voulait supprimer (voir `scripts/signals.py`, `scripts/annote.py`).
- Donc « chunks confirmés RISK pour flag N » = chunks dont le texte matche
  les mots-clés du flag N **ET** appartenant à un projet où `event == 1`.
  C'est un proxy à deux niveaux (mots-clés + événement projet), pas une
  polarité propre. Le PDF vend ça comme une solution pure ; ce n'en est pas
  une — bonne direction quand même, mais à documenter honnêtement, pas comme
  un problème résolu.
- Fait intéressant : `annote.py` documente un bug quasi identique déjà corrigé
  le 2026-07-24 (hériter le `flag_type` en bloc du projet entier polluait
  FAISS). L'équipe a donc déjà affronté cette classe de problème une fois.

### 2.2 Le double appel LLM redondant, présent dans le code aujourd'hui

`scripts/analyze.py` : `_find_signals_in_document()` appelle
`llm_confirm.confirm_risk()` une fois par extrait matché par mots-clés, **puis**
`deep_analysis.run_deep_analysis()` tourne en plus (Pass1/Pass2/Pass3) sur des
zones du même document. Deux couches LLM indépendantes, potentiellement
redondantes. Le PDF (couche 4) identifie que `confirm_risk` « n'a plus de
raison d'exister » dans l'architecture révisée, mais ne montre jamais le
code de remplacement pour `_find_signals_in_document` spécifiquement — cette
fonction reste un point mort du PDF. **Hypothèse non mesurée** : c'est
probablement une bonne partie du coût réel sur un document de 10 Mo, mais il
faut instrumenter avant de trancher.

### 2.3 `compare_embeddings.py` a déjà tourné — le PDF pose la question sans savoir que la réponse existe

`checklist.md` (ligne 13) : mpnet donne un C-index de **0.746** contre
**0.758** pour MiniLM (légèrement meilleur), mais le coefficient
`flag1_community` est plus significatif avec mpnet (p<0.005 contre p=0.01
avec MiniLM). **Décision déjà prise le 2026-07-25** de garder mpnet pour
cette raison. Le PDF recommande de « vérifier les résultats de
`compare_embeddings.py` » comme si la question était ouverte — elle ne l'est
plus.

### 2.4 Le vrai frein à la pertinence des analyses : la puissance statistique du Cox, pas le retrieval

Log réel (`pipeline_mpnet_run.log`, run du 2026-07-24) :

```
47 projets, 4203 chunks, 29 événements / 18 censurés
C-index : 0.746
flag1_community    z=3.15   p<0.005   → significatif
flag2_pollution    z=-0.52  p=0.60    → bruit
flag3_compliance   z=1.34   p=0.18    → non significatif
```

Deux des trois flags ne discriminent rien avec les données actuelles. Aucune
des 6 couches du PDF ne corrige ça — c'est un problème de volume
d'événements (règle empirique : ~10-15 événements par covariable ; on en a
29 pour 3 covariables, donc déjà limite). Le PDF le sait et le dit lui-même
en couche 3 (à propos d'ajouter `confidence`/`breadth` comme covariables
supplémentaires), mais range ça sous "Chantier 0 / phase banque" sans
l'intégrer comme facteur limitant de tout le reste de la refonte proposée.
Améliorer le retrieval peut réduire le bruit dans les flag scores, mais ne
transforme pas 29 événements en 200.

### 2.5 Le train/serve mismatch sur le Cox est déjà connu et mis en pause délibérément

`checklist.md` (lignes 158, 193) : `cox_model.pkl` actuel **n'est pas
ré-entraîné** sur les scores filtrés par `confirm_risk` — décision du
2026-07-25, documentée sous "Chantier ouvert — préchauffage du cache LLM",
parce que le réentraînement complet (4203 chunks × appel LLM) est
instable/trop lent en l'état. Le PDF ne mentionne jamais ce chantier ouvert,
alors qu'il est directement lié à sa proposition de prototypes (qui, elle
aussi, nécessite de reconstruire des artefacts sur tout le corpus).

### 2.6 Fichiers morts non repérés par le PDF

`embed.py` est bien mort (le PDF l'a vu). `explain.py` ne l'est probablement
pas moins — importé seulement par `test.py`, jamais par `app.py`,
vraisemblablement remplacé par `deep_analysis.py` (Chantier 3) sans avoir été
retiré. Le PDF ne l'a pas identifié parce qu'il raisonne en architecture, pas
en audit fichier par fichier.

### 2.7 La priorité "features avant perf" a déjà été tranchée

`checklist.md` ligne 20 : *« Perf non optimisée [...] accepté pour l'instant,
priorité aux fonctionnalités (décision utilisateur du 2026-07-25) »*. Le PDF
propose une refonte assez lourde des couches 2 et 4, en grande partie motivée
par la perf — cohérent avec cette décision seulement si on garde bien la
distinction entre "bug de perf/correctness" (cache_resource, doublons LLM) et
"optimisation qu'on peut différer" (PCA, fine-tuning, classifieur distillé —
que le PDF écarte lui-même).

---

## 3. Mes décisions

En combinant le PDF et l'audit du repo, voici comment je hiérarchise le
travail :

### Tier 0 — Gratuit, aujourd'hui, zéro risque
1. Vérifier/ajouter `@st.cache_resource` sur tous les chargements de modèles
   dans `app.py`.
2. Supprimer `embed.py` (mort, confirmé). Vérifier et supprimer `explain.py`
   s'il est bien mort.
3. Paramètres d'encode (`batch_size=64`, `normalize_embeddings=True`) et
   config Ollama (`num_predict`, `num_ctx`, `OLLAMA_KEEP_ALIVE`).

### Tier 1 — Mesures obligatoires avant tout le reste
4. Timers réels dans `analyze.py` (confirm_risk vs deep_analysis vs
   embedding vs FAISS) pour confirmer ou infirmer le double appel LLM
   redondant (§2.2) — hypothèse non prouvée à ce stade.
5. Ratio boilerplate réel sur 5-10 rapports du corpus.
6. Recall du pré-filtre mots-clés `signals.py` sur 5 rapports.
7. `compare_embeddings.py` : déjà fait, voir §2.3 — pas besoin de refaire,
   juste documenter la décision dans le futur travail sur la couche 2.

### Tier 2 — Cœur de la refonte (après les mesures)
8. Prototypes de risque par flag, **en documentant explicitement leur
   dépendance résiduelle au `flag_type` par mots-clés** (§2.1) — ne pas
   vendre ça comme une solution pure à la circularité.
9. Scoring hybride prototypes (score) + FAISS (evidence uniquement),
   dédoublonnage par projet.
10. Détection d'omissions déterministe par matrice de matérialité.
11. Pass 1 réduite (8-12 chunks) + un seul appel de synthèse finale, fallback
    template.
12. Refactorer `_find_signals_in_document` pour retirer les appels
    `confirm_risk` résiduels — absent du PDF, à faire nous-mêmes (§2.2).
13. `core.py` pour les fonctions partagées entre `pipeline.py` et
    `analyze.py`.
14. `analyze.py` restructuré en étapes avec `session_state` + `st.status`.
15. `pipeline.py` simplifié, fichier d'état léger (skip ré-embedding si
    inchangé), pas de manifeste JSON.
16. Reconnecter cette refonte au "Chantier ouvert — préchauffage du cache
    LLM" déjà documenté dans `checklist.md` (§2.5) plutôt que de le
    redécouvrir : le réentraînement Cox sur corpus complet doit rester
    praticable après la refonte.

### Tier 3 — Hors scope du PDF, seule vraie réponse à "analyses non pertinentes"
17. Décider quoi faire de `flag2_pollution` (p=0.60) et `flag3_compliance`
    (p=0.18), non significatifs faute d'événements (§2.4). Deux options :
    enrichir le corpus (plus de projets annotés), ou afficher une confiance
    différenciée par flag dans l'UI en attendant. Aucune des couches 1-5 ne
    résout ça seule.

### Explicitement écarté (le PDF le dit lui-même, et ça colle avec la décision du 2026-07-25)
PCA, fine-tuning contrastif, classifieur distillé, ColBERT (multi-vecteurs),
manifeste JSON, dataclass `AnalysisResult`, machine à états complète. À
logger comme "connu, pas maintenant" — pas à faire.

---

## 4. Ce qu'il faut garder en tête en implémentant

- Les prototypes (Tier 2) amélioreront le **bruit** dans les analyses
  (chunks hors-sujet, synthèses vagues, omissions fantômes), pas la
  **profondeur** (limite du modèle 4B) ni la **validité statistique** de
  flag2/flag3 (limite du volume de données). Ne pas confondre les trois en
  évaluant le résultat.
- Ne rien construire sur les artefacts (prototypes, embeddings) sans
  regarder d'abord si le réentraînement complet reste dans un temps
  raisonnable — le "Chantier ouvert" de `checklist.md` a déjà buté là-dessus
  une fois.
- Toute affirmation chiffrée de ce document vient soit d'un log réel
  (`pipeline_mpnet_run.log`), soit d'un `grep`/import check sur le code
  actuel, soit de `checklist.md` — pas d'une estimation. Les chiffres du PDF
  (temps LLM, ratio boilerplate, etc.) restent des hypothèses tant qu'ils
  n'ont pas été mesurés (Tier 1).
