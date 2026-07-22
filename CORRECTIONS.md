# Corrections apportées & améliorations proposées

Ce document explique, en clair, ce qui a été corrigé dans le code suite à la
vérification de `checklist.md`, comment le blocage `time_to_event` a été
résolu, et ce que je recommande comme prochaines étapes. Le pipeline
complet (`pipeline.py` → `search.py` → `model.py` → `analyze.py` →
`app.py`) tourne maintenant de bout en bout.

---

## 1. Ce qui était cassé

Avant ces corrections, la chaîne `pipeline.py` → `search.py` → `model.py` →
`analyze.py` ne pouvait pas fonctionner : chaque étape appelait des fonctions
ou des noms de colonnes qui n'existaient pas dans l'étape précédente.

### 1.1 `search.py` n'exportait pas ce qu'attendaient les autres fichiers

`model.py`, `explain.py`, `analyze.py` et `test.py` importent tous
`search.py` et appellent :

```python
search.load_search_components()
search.get_flag_scores(text, model, index, metadata, k=15)
search.search_similar(text, model, index, metadata, k=15)
```

Or dans l'ancien `search.py` :

- `load_search_components()` **n'existait pas** — le chargement du modèle,
  de l'index FAISS et des métadonnées était fait directement au niveau du
  fichier (pas dans une fonction appelable).
- `search_similar()` **n'existait pas** — il y avait une fonction
  `recherche()` avec un nom et une sortie différents.
- `get_flag_scores()` retournait les clés `"Flag 1"`, `"Flag 2"`, `"Flag 3"`,
  alors que tout le reste du code attend `"flag1_community"`,
  `"flag2_pollution"`, `"flag3_compliance"` → `KeyError` garanti dès le
  premier appel.
- Le fichier exécutait aussi 3 `print(get_flag_scores(...))` **au niveau
  module** (pas protégés par `if __name__ == "__main__":`). Résultat : à
  chaque `import search` fait par un autre script, tout le modèle
  d'embedding et l'index se rechargeaient inutilement, et 3 prédictions de
  test s'affichaient dans la console.

**Correction** : réécriture de `search.py` avec les 3 fonctions demandées,
les bonnes clés, et le code de test déplacé sous `if __name__ == "__main__":`.

### 1.2 Format des métadonnées incompatible entre `pipeline.py` et `search.py`

- `pipeline.py` sauvegardait `metadata` comme une **liste de dictionnaires**
  Python (`pickle.dump(metadata, f)`).
- `search.py` traite `metadata` comme un **DataFrame pandas**
  (`metadata.iloc[idx][...]`).
- Résultat : `AttributeError: 'list' object has no attribute 'iloc'` dès la
  première recherche après un `python pipeline.py`.

En plus, `pipeline.py` faisait `int(row["flag_type"])`. Or les valeurs
réelles de `flag_type` dans `chunks.csv` sont des **chaînes de caractères**
(`"Flag 1"`, `"Flag 2 + Flag 3"`, `"Flag 1 + Flag 2"`...), pas des entiers
1/2/3 comme le supposait la checklist. `int("Flag 1")` lève une
`ValueError` → **`pipeline.py` plantait avant même d'arriver à
l'entraînement du modèle Cox.**

**Correction** : `pipeline.py` sauvegarde maintenant `metadata` comme un
DataFrame (copie directe de `chunks_df`), sans caster `flag_type`.

### 1.3 `model.py` lisait `corpus_cao_ifc.xlsx` avec de mauvais noms de colonnes

La checklist supposait que `corpus_cao_ifc.xlsx` contient des colonnes
`project_name`, `project_id`, `time_to_event`, `event`, `flag_type`. En
réalité, le fichier a des en-têtes complètement différents :

```
['sa', 'B — Numéro IFC', 'C — Pays', 'D — Secteur', 'E — Date ESRS (T0)',
 'F — Date plainte CAO (T_event)', "G — Type d'événement", 'H — Flag',
 'I — Censored', 'J — Category', 'K — Notes']
```

`model.py` faisait `ann["project_name"]`, `ann["time_to_event"]`,
`ann["event"]` → `KeyError` immédiat. Seul `annote.py` gérait correctement
ce fichier (via un accès positionnel aux colonnes).

**Correction** : `build_training_data()` ne relit plus le xlsx. Elle
s'appuie sur `chunks.csv`, qui contient déjà `flag_type` et `event` par
chunk (remplis par `annote.py` à partir du xlsx). C'est plus simple et ça
évite de dupliquer la logique de parsing déjà écrite dans `annote.py`.

---

### 1.4 `analyze.py` : les signaux détectés ne matchaient jamais

Conséquence indirecte de la correction 1.2 : une fois `metadata` remis au
format `chunks.csv` (où `flag_type` est la chaîne `"Flag 1"`, `"Flag 2 +
Flag 3"`, ...), `analyze._extract_signals()` comparait toujours cette
chaîne à des clés entières (`1`, `2`, `3`) — la comparaison ne matchait
jamais, donc **`detected_signals` était systématiquement vide**, quel que
soit le texte analysé.

**Correction** : `_extract_signals()` matche maintenant `flag_type` par
sous-chaîne (`"Flag 1" in flag_type`), comme le fait déjà `search.
get_flag_scores()` — et gère au passage les flags combinés ("Flag 2 + Flag
3" déclenche les deux catégories de signaux).

---

## 2. `time_to_event` — résolu (option 1 : vraies dates IFC)

`time_to_event` (durée en mois avant l'événement, nécessaire au modèle de
survie Cox) n'existait nulle part : ni dans `chunks.csv`, ni dans
`corpus_cao_ifc.xlsx` (colonne T0 vide sur les 60 lignes). Plutôt que
d'inventer une durée synthétique (qui aurait rendu le modèle Cox
trompeur), j'ai sourcé les **vraies dates d'approbation IFC ("Board
Date")**, publiques, pour les projets du corpus.

### Comment

1. **Identification** : 23 numéros de projet IFC uniques sont présents
   dans `chunks.csv` (sur les 60 lignes du tableur — les ~37 autres sont
   encore marquées "à vérifier" et hors corpus).
2. **Recherche** : pour chacun, récupération de la date "Approved" listée
   dans la section "Previous Events" de sa page de divulgation publique
   (`disclosures.ifc.org/project-detail/...`), un projet à la fois.
   Consignées avec leur source dans
   [scripts/ifc_board_dates.py](scripts/ifc_board_dates.py)
   (`IFC_BOARD_DATES`).
3. **Traçabilité** : [scripts/fill_t0_dates.py](scripts/fill_t0_dates.py)
   écrit ces dates dans la colonne "E — Date ESRS (T0)" de
   `corpus_cao_ifc.xlsx` (déjà exécuté).
4. **Calcul** : `annote.py` calcule maintenant `time_to_event` par numéro
   IFC :
   - **event = 1** (plainte CAO) → mois entre T0 et la date de la colonne F
     (`"14 Jun 2011"`, `"Mar 2011"`, `"~2015"` — parsées avec repli sur le
     mois/l'année quand le jour manque).
   - **event = 0** (projet "propre"/censuré) → mois entre T0 et
     aujourd'hui.
   - Sans T0 connu ou date d'événement illisible → `time_to_event` reste
     vide, et `model.build_training_data()` exclut ce projet avec un
     avertissement explicite plutôt que de planter.
5. Un cas a été détecté par ce garde-fou : **Bujagali 2 (Refi)**
   (IFC 39102) est marqué `event=1` (Censored=False) mais n'a **aucune**
   date d'événement dans le tableur — incohérence de données à vérifier
   avec ton associée. Le projet est exclu de l'entraînement en attendant.

### Résultat

```
python pipeline.py
...
Dataset : 30 projets, 28 événements
...
Concordance = 0.63
C-index      : 0.627
Modèle sauvegardé → models/cox_model.pkl
```

`models/cox_model.pkl` existe désormais. `analyze()` tourne de bout en
bout (~11s au premier appel, chargement des modèles inclus).

---

## 3. Vérifications faites après correction

- `python pipeline.py` : tourne jusqu'au bout (5/5 étapes), C-index = 0.627
  (> 0.6, seuil "acceptable MVP" de la checklist).
- `python test.py` (unitaires + intégration) : **25/25 passés, 0 échec**.
- `python test.py --business` (cohérence métier) : 3/7 passés, 1 échec, 3
  warnings — voir section 4, c'est un problème de volume/déséquilibre de
  données, pas de code.
- `analyze()` testé manuellement sur un texte "community opposition" :
  grade + probabilité + 7 signaux détectés + 15 passages similaires
  retournés correctement.
- `app.py` démarre sans erreur (`streamlit run app.py` → HTTP 200), et
  "Run Analysis" avec un vrai document produit maintenant un vrai résultat
  au lieu du message d'erreur "modèle manquant".

---

## 4. Limite restante : le modèle Cox discrimine faiblement

Les tests de cohérence métier (`test.py --business`) montrent un modèle
qui **tourne** mais dont le pouvoir prédictif est faible :

```
covariate           coef  exp(coef)   p
flag1_community    -0.00       1.00  0.90
flag2_pollution     0.01       1.01  0.38
flag3_compliance    0.01       1.01  0.37
```

Aucun des 3 coefficients n'est statistiquement significatif (p > 0.35), et
le test "risque élevé (Cas 1) > projet propre (Cas 4)" échoue de justesse
(7% vs 8%). **Ce n'est pas un bug** — c'est la conséquence directe du
déséquilibre déjà identifié :

| Critère checklist | Réalité constatée |
|---|---|
| ≥30 projets | ✅ 30 projets exploitables (31 - Bujagali2Refi) |
| ≥15 projets avec `event=1` | ✅ 28 projets |
| Chaque flag ≥5 projets représentatifs | ⚠️ Flag 1 : 24, Flag 2 : 7, **Flag 3 : 4** |
| 15-20 projets "propres" (`event=0`) | ⚠️ **2 seulement** (les deux `_CTRL`) |

Avec 28 événements pour seulement 2 témoins "propres", le modèle Cox n'a
presque aucun contraste pour apprendre ce qui distingue un projet à
risque d'un projet sain — quasiment tous les projets du corpus ont connu
un événement. Le C-index de 0.627 vient probablement plus du volume de
texte par projet que des flag scores eux-mêmes.

**Recommandation** : enrichir le corpus avec plus de projets "propres"
(event=0) et plus de cas Flag 3 avant de considérer le C-index/les hazard
ratios comme fiables pour une vraie décision de crédit.

---

## 5. Améliorations proposées (non faites, à discuter)

Par ordre de priorité :

1. **Enrichir le corpus** — plus de projets "propres" (`event=0`) et plus
   de cas Flag 3 (voir section 4 — c'est maintenant le principal facteur
   limitant la qualité du modèle, devant tout problème de code).
2. **Clarifier Bujagali 2 (Refi)** (IFC 39102) — `event=1` sans date
   d'événement dans le tableur, incohérence à vérifier.
3. **Chemins absolus codés en dur** (`C:/Users/djeto/Desktop/Projet-Elisa`)
   dans presque tous les scripts (`search.py`, `model.py`, `pipeline.py`,
   `explain.py`, `analyze.py`, `test.py`, `annote.py`, `app.py`). Ça
   fonctionne tant que le projet reste sur cette machine à cet emplacement
   précis, mais ça casse dès qu'on déplace le dossier ou qu'on le partage.
   Une amélioration simple : dériver `BASE` depuis
   `Path(__file__).resolve().parent.parent` au lieu d'un chemin en dur.
4. **`embed.py` est maintenant redondant** avec l'étape 1-3 de
   `pipeline.py` (même logique d'embedding + FAISS, en plus simple). Pas
   bloquant, mais à clarifier : est-ce un script exploratoire à garder à
   part, ou à supprimer une fois que `pipeline.py` est la référence ?
5. **`app.py` n'a pas d'extraction OCR** — `_extract_uploaded_text()` ne
   branche pas le fallback `pytesseract` que `ingest.py` a pour les PDF
   scannés sans texte. Un PDF scanné uploadé dans l'app donnera un texte
   vide (voir aussi la question sur les fichiers arbitraires ci-dessous).

---

## 6. Robustesse face à un fichier arbitraire

Le filtre `type=["pdf", "txt"]` de `st.file_uploader` n'est **qu'une
suggestion côté navigateur** (attribut HTML `accept`) — il n'est pas
réellement imposé côté serveur. N'importe qui peut donc uploader n'importe
quoi renommé en `.pdf`/`.txt`. Concrètement :

| Cas | Ce qui se passe |
|---|---|
| **Fichier `.txt` avec du contenu binaire/non-UTF-8** (ex. un `.exe` renommé) | `bytes.decode("utf-8", errors="ignore")` ne plante pas — il jette silencieusement les octets invalides et produit du texte tronqué/inintelligible. `analyze()` tourne quand même dessus et renvoie un résultat **sans signification**, sans avertissement. |
| **Fichier `.pdf` invalide** (image renommée, fichier corrompu) | `pdfplumber.open()` lève une exception. Elle est interceptée par le `try/except` ajouté dans `app.py` → message d'erreur clair affiché (`st.error`), repli sur les données de démo. **Pas de crash de l'app.** |
| **PDF scanné sans couche texte** | `page.extract_text()` renvoie `None`/vide pour chaque page → texte extrait = chaîne vide. `analyze("")` ne plante pas mais produit un résultat creux (l'OCR de secours de `ingest.py` n'est pas branché dans l'app — voir point 5 ci-dessus). |
| **Fichier vide (0 octet)** | Pareil que ci-dessus selon l'extension : `.txt` → texte vide sans erreur ; `.pdf` → erreur `pdfplumber` interceptée proprement. |
| **Fichier énorme** | Streamlit a sa propre limite d'upload (200 Mo par défaut, configurable) — au-delà, Streamlit refuse *avant* d'atteindre le code de l'app. En dessous, le modèle d'embedding tronque de toute façon le texte aux ~256 premiers tokens (limite native de `all-MiniLM-L6-v2`) — le reste du document n'est simplement jamais lu. |
| **Pas de fichier, clic sur "Run Analysis"** | Le bouton ne déclenche rien (`if uploaded_file and analyze_clicked`) — retombe sur les données de démo avec le message d'invite. |

**En clair** : rien ne fait planter l'app (grâce au `try/except`), mais un
fichier non-conforme peut produire un résultat silencieusement dénué de
sens plutôt qu'une erreur explicite. Amélioration possible : valider qu'un
minimum de texte a bien été extrait avant de lancer `analyze()`, et
avertir si le texte est suspicieusement court.

---

## 7. Fichiers de test recommandés

Testés manuellement avec `analyze()` (résultats réels, pas une estimation).
⚠️ Ces fichiers du corpus ont servi à **entraîner** le modèle — ce n'est
donc pas un vrai test "à l'aveugle", plutôt une vérification que la
mécanique tourne. Et comme noté en section 6, le modèle tronque à ~256
tokens : seul le **début** du document compte réellement pour le score.

| Fichier | Contenu attendu | Grade / Prob. 12m | Flag scores | Signaux |
|---|---|---|---|---|
| [corpus/IFC_24408_Bujagali_ESIA.pdf](corpus/IFC_24408_Bujagali_ESIA.pdf) | Flag 1 (communauté), Uganda hydro | **D Vigilance**, 3.6% | community=**100**, pollution=0, compliance=0 | 0 |
| [corpus/IFC_25797_TataUltraMega_EIA.pdf](corpus/IFC_25797_TataUltraMega_EIA.pdf) | Flag 1+2, Inde, coal power | **D Vigilance**, 3.6% | community=**99**, pollution=0, compliance=0 | 4 |
| [corpus/IFC_35349_DaehanWind_ESIA.pdf](corpus/IFC_35349_DaehanWind_ESIA.pdf) | Flag 2+3 (pollution/biodiversité), Jordanie wind | **D Vigilance**, 12.4% | community=0, pollution=**99**, compliance=**99** | 2 |
| [corpus/IFC_32874_GulpurHydro_CTRL.txt](corpus/IFC_32874_GulpurHydro_CTRL.txt) | Projet "propre" (témoin) | **D Vigilance**, 7.5% | community=64, pollution=62, compliance=62 | 1 |
| [test.pdf](test.pdf) | **Hors-sujet** — statistiques d'armes à feu US, aucun rapport ESG | **D Vigilance**, 5.9% | community=44, pollution=37, compliance=37 | 1 |

**Ce que ça montre :**
- ✅ **Les flag scores sont cohérents** : le fichier communautaire ressort à
  99-100 sur "Community", le fichier pollution/biodiversité à 99 sur les
  deux autres flags. La recherche FAISS fonctionne bien.
- ⚠️ **Le grade final est toujours "D Vigilance"** — confirme la limite de
  la section 4 (modèle Cox peu discriminant). Même le fichier témoin et le
  fichier communautaire à risque donnent le même grade.
- ⚠️ **Aucun garde-fou de pertinence** : le fichier d'armes à feu
  (`test.pdf`, complètement hors-sujet) reçoit quand même un score et un
  grade, comme un vrai document ESG — le système ne détecte pas qu'un
  document n'a rien à voir avec le domaine. Bon test pour vérifier que
  rien ne plante sur un fichier "n'importe quoi", mais à garder en tête :
  aucune alerte n'est levée sur la pertinence du contenu.
