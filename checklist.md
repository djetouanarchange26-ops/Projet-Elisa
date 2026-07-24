# Journal de bord — NLP ESG Risk Intelligence

Dernière mise à jour : 2026-07-25

## État général

- App Streamlit fonctionnelle en local (`streamlit run app.py`), déployée (Render puis migration Streamlit Cloud en cours de réglage d'accès public)
- Corpus : 4203 chunks, 46 projets annotés (28 événements CAO / 18 contrôles), 82 documents dans `corpus/`
- Modèle Cox : C-index 0.758 (k=15, `all-MiniLM-L6-v2`) — mais la différenciation sur un texte externe reste un problème ouvert, voir "Chantier ouvert"
- **Les 4 onglets sont maintenant branchés sur de vraies données** (plus aucun mockup) :
  - **Transaction Analysis** : pipeline complet (extraction → FAISS → Cox → signaux)
  - **Portfolio Dashboard** : historique des analyses de la session (`st.session_state`)
  - **Pattern Library** : fréquences et temps moyens réels calculés depuis le corpus
  - **Settings** : seuils de risk grade et k FAISS réellement fonctionnels, stats corpus en direct

---

## ✅ Bugs corrigés

| Bug | Fichier(s) | Impact |
|---|---|---|
| Chemins Windows codés en dur | 9 scripts | Bloquait tout déploiement hors Windows local |
| Troncature FAISS à 256 tokens (train + inférence) | `search.py` | Le modèle ne "voyait" que les ~175 premiers mots de n'importe quel document |
| Fuite de données (auto-matching projet↔lui-même) | `search.py`, `model.py` | Gonflait artificiellement les scores d'entraînement |
| `annote.py` : valeur "Censored" ambiguë | `annote.py` | Plantait silencieusement `time_to_event` au lieu d'exclure le projet |
| Recommandation figée sur "Escalade immédiate" | `app.py` | Affichait le pire message quel que soit le grade réel |
| `flag_type` hérité du projet entier, pas du contenu du chunk | `annote.py`, `signals.py` | Bruitait l'index FAISS avec des chunks administratifs étiquetés à tort |
| Résultats de Transaction Analysis perdus au moindre autre clic | `app.py` | Aucune persistance — corrigé via `st.session_state["last_analysis"]` |
| `.severity-low` (CSS) inexistant | `app.py` | Les signaux "low" de Pattern Library s'affichaient en orange (classe "med") au lieu de teal |

## ✅ Transaction Analysis — refonte complète

- Détection de signaux : cherche dans le document uploadé lui-même (pas les passages historiques), avec positions exactes pour le surlignage
- Zone de texte collée en alternative à l'upload de fichier
- Mockup/données fictives entièrement retirées
- Survival Curve + SHAP retirés (UI + calcul backend) → chargement ~15s → ~4-5s
- Cas similaires enrichis avec les vraies données (event/time_to_event + extrait du passage)
- Résultat persistant en session (`st.session_state["last_analysis"]`) — ne disparaît plus en changeant de widget/onglet
- Chaque analyse alimente `st.session_state["analysis_history"]` (→ Portfolio Dashboard + sidebar "Recent Analyses")

## ✅ Settings — seuils et paramètres réellement fonctionnels

- Seuils de risk grade (Vigilance/Attention/Alerte/Escalade) branchés sur `model.predict_risk` via `st.session_state["risk_thresholds"]` — avant : purement visuels
- `FAISS Top-K` configurable, propagé jusqu'à `analyze(pdf_text, k=...)`
- Stats corpus calculées en direct depuis `chunks.csv` (avant : chiffres fictifs "21 projets/939 chunks")
- Retiré : sélecteur de modèle d'embedding fictif (options inexistantes), "SHAP Background Samples" (fonctionnalité supprimée), "Cox Penalizer" (paramètre d'entraînement, pas d'inférence — trompeur en Settings)

## ✅ Pattern Library — statistiques réelles du corpus

- Calcul par catégorie de signal (`signals.SIGNAL_KEYWORDS`, 11 catégories) : nombre de projets à événement connu (event=1) qui la mentionnent, occurrences totales, temps moyen avant événement
- Résultat notable : temps moyens réels ~60-71 mois (5-6 ans), pas 6-24 mois comme le mockup fictif le suggérait — T0 = date d'approbation IFC, pas date de démarrage travaux
- Sévérité recalculée en tertiles sur les données réelles (un seuil absolu type "<10 mois = high" ne différenciait plus rien à cette échelle)
- Signal le plus fréquent : "consultation gaps" (28/46 projets), suivi de "community opposition" et "pollution risk" (27 chacun)
- Mis en cache (`@st.cache_data`) — scanne l'intégralité du corpus contre 11 patterns

## ✅ Portfolio Dashboard — historique de session

- Remplace le tableau fictif de 8 projets par l'historique réel des analyses lancées dans Transaction Analysis (`st.session_state["analysis_history"]`)
- Colonnes : Document, Risk Grade, Risk Label, P(event 12m), Dominant Flag (dérivé du flag_score le plus élevé), horodatage
- Filtre par grade, métriques résumé (total, grade A, grade B, grade C-D)
- Décision actée : historique de session uniquement, pas de persistance base de données pour l'instant — perdu à la fermeture du navigateur

## ✅ Corpus — rééquilibrage (scraping 2026-07-23/24)

- Point de départ : 30 projets (28 événements / 2 contrôles) → modèle quasi aléatoire (C-index 0.587 une fois la fuite de données corrigée)
- 16 nouveaux projets "contrôle" (IFC sans plainte CAO) trouvés et vérifiés via disclosures.ifc.org + cao-ombudsman.org, intégrés au corpus (`corpus/`, `corpus_cao_ifc.xlsx`, `ifc_board_dates.py`)
- Un candidat (New Liberty Gold, Libéria) écarté : pollution/abus RH rapportés par la presse malgré l'absence de plainte CAO formelle
- Un candidat (NSL Wind, Inde) abandonné : page IFC non scrapable
- Résultat : 46 projets (28 événements / 18 contrôles)

## ✅ Ré-annotation des chunks par contenu réel (2026-07-24)

- Nouveau module `scripts/signals.py` : source unique des mots-clés par flag (`SIGNAL_KEYWORDS`, `SIGNAL_PATTERNS`, `flags_mentioned_in_text()`), partagée entre `analyze.py` (détection live), `annote.py` (ré-annotation du corpus) et `app.py` (Pattern Library)
- `annote.py` ne fait plus hériter `flag_type` du projet entier à tous ses chunks : un chunk ne garde le flag du projet que si son texte contient réellement les mots-clés correspondants (intersection, pas invention de nouveaux flags)
- Résultat : ~66% des chunks (pages de garde, procédures génériques) n'ont plus de flag_type ; C-index corpus 0.740 → **0.758**

---

## 🔍 Chantier ouvert — différenciation du scoring FAISS sur texte externe

**Constat** : même après la ré-annotation par contenu, un texte neutre de test (rapport de routine) obtient un score quasi identique à un texte décrivant un risque réel, quel que soit k (testé de 3 à 30). Le C-index du corpus s'améliore avec la ré-annotation et avec k, mais ça ne se traduit pas en différenciation sur un nouveau document.

| Version | k=15 : Texte "Flag1 risque" | k=15 : Texte neutre | C-index corpus |
|---|---|---|---|
| Avant ré-annotation (flag hérité du projet) | 62/55/0 | 61/61/58 | 0.740 |
| Après ré-annotation (flag par contenu) | 62/54/0 | 61/57/57 | 0.758 |

**Diagnostic actuel** : le goulot d'étranglement n'est plus le bruit des labels ni k — c'est probablement la capacité du modèle d'embedding (`all-MiniLM-L6-v2`, 22M paramètres) à distinguer des textes courts (~150 mots) qui partagent le même registre "rapport ESG formel" même quand leur contenu diffère.

**Test embedding en cours (INTERROMPU, à relancer)** : comparaison `all-MiniLM-L6-v2` vs `all-mpnet-base-v2` vs `paraphrase-multilingual-mpnet-base-v2`, script `test_embedding_model.py` dans le scratchpad (non versionné dans le repo — à recréer si besoin, logique décrite ci-dessous).

- **all-MiniLM-L6-v2 (actuel)** : confirmé C-index=0.758 à k=15 (cohérent avec la prod)
- **all-mpnet-base-v2** : test lancé deux fois, interrompu les deux fois avant la fin (coupures de session) — dimension 384... non, 768 confirmé au démarrage, mais résultat C-index/différenciation jamais obtenu. **À relancer.**
- **paraphrase-multilingual-mpnet-base-v2** : téléchargement confirmé OK, 768 dimensions, mais **fenêtre de seulement 128 tokens** (plus courte que MiniLM à 256, et plus courte que le chunking actuel de 175 mots) — si retenu, il faudra réduire `CHUNK_SIZE` dans `search.py`/`ingest.py` pour ce modèle spécifiquement. Comparatif C-index/différenciation pas encore lancé.

**Pourquoi retester le modèle d'embedding** : le corpus contient des documents non-anglophones (ex: le premier PDF de test était en français, "REPUBLIQUE TOGOLAISE") — `all-MiniLM-L6-v2` est majoritairement anglophone, ce qui pourrait contribuer au problème de différenciation en plus de la limite de capacité déjà identifiée.

---

## 🗺️ Feuille de route décidée (2026-07-24)

Ordre validé par l'utilisateur :

1. **Choisir le modèle d'embedding** (EN COURS — comparatif interrompu, à relancer : MiniLM vs mpnet vs multilingue)
2. **Intégrer un modèle d'IA open source local** (LLM via Ollama — voir `migration-signaux-ollama.md`, plan pour plus tard). Ajustements déjà discutés à appliquer le moment venu :
   - Approche **hybride regex+LLM** : `signals.py` localise les candidats, le LLM confirme/infirme selon contexte et négation (pas un remplacement total du regex) — règle la latence (un appel par signal candidat, pas par page) ET le problème de surlignage (position déjà connue via regex)
   - `annote.py` reste sur le regex pur (job batch, pas latence-sensible) — une seule définition de référence pour "c'est quoi un signal Flag X"
   - Cache de détection à indexer sur `hash(texte + définitions de signaux)`, pas juste le texte seul, pour ne pas servir des résultats périmés si `SIGNAL_KEYWORDS` change
   - Vérifier la disponibilité réelle du tag de modèle Ollama choisi avant de lancer (`ollama list`), privilégier un petit modèle (1-4B) vu la contrainte CPU
3. **Cas d'usage LLM prioritaires (points 1-3)** :
   - Confirmation de signaux (regex localise, LLM confirme/infirme selon contexte et négation)
   - Cas similaires enrichis (résumé généré plutôt qu'extrait brut)
   - Recommandation contextualisée (basée sur les signaux réellement détectés, pas un template fixe par grade)
4. **Construire l'interface graphique définitive** — inclut maintenant les 4 nouvelles fonctionnalités validées (voir section dédiée ci-dessous)
5. **Optimiser le temps de calcul**
6. Une fois 1-5 stabilisés : **points 4-5** (résumé de document long/page par page, Pattern Library en insights narratifs générés)
7. Nouvelle passe d'optimisation
8. Quand le MVP est complet : **point 6** — Q&A libre sur le document uploadé (RAG/chat), le plus gros chantier, mis de côté pour la fin

---

## 🆕 Fonctionnalités validées pour l'étape 4 (interface graphique)

Décidées le 2026-07-24, pas encore implémentées :

| # | Fonctionnalité | Note |
|---|---|---|
| 1 | **Support multilingue** | Lié au choix du modèle d'embedding en cours (voir "Chantier ouvert") |
| 2 | **Export du résultat** (PDF/Excel) | Pour joindre l'analyse à un mémo de comité de crédit |
| 3 | **Upload multi-documents** | Une due diligence croise plusieurs documents (ESIA + ESAP + monitoring), pas un seul PDF |
| 4 | **Traçabilité des preuves derrière un score** | Afficher les vrais passages historiques (voisins FAISS) qui ont influencé un flag_score — de l'explicabilité concrète depuis le retrait de SHAP |

**Sur "faire apprendre les modèles à partir des docs fournis"** (question posée, réponse actée) :
- Le modèle Cox **ne peut pas** apprendre automatiquement d'un document tout juste uploadé — son issue (event/time_to_event) n'est pas encore connue au moment de l'analyse. Pas de raccourci technique à ça.
- Ce qui est faisable : enrichir la bibliothèque de référence FAISS (Pattern Library / Historical Similar Cases) avec les documents uploadés, sans label — améliore la richesse de comparaison, pas la prédiction.
- Piste retenue pour plus tard : mécanisme de mise à jour manuelle d'issue ("ce projet a eu un incident ESG") qui ferait entrer un projet dans le corpus d'entraînement au prochain ré-entraînement — boucle de rétroaction humaine, pas un apprentissage automatique.

---

## 📋 Autres chantiers identifiés (non séquencés dans la feuille de route ci-dessus)

| # | Chantier | Portée | Statut |
|---|---|---|---|
| B | Annotation page par page | Extraction page-aware, détection de signaux par page, UI groupée par page | En pause |
| C | Score par page/flag | "Community risk piloté par les pages 7, 12" | Dépend de B |
| D | Plafond de chunks pour gros documents | Éviter une latence excessive sur des PDF de 100+ pages | Idée |
| E | Incohérence sévérité (Transaction Analysis) | `SEVERITY_BY_FLAG` fixe (Flag1=high/Flag2=medium/Flag3=low), indépendant du nombre d'occurrences réel | À valider si voulu |
| F | Modèle de survie alternatif (Random Survival Forest, Gradient Boosting) | Probablement pas pertinent avec seulement 46 projets (sur-apprentissage) | Écarté |
| G | Fine-tuning du modèle d'embedding sur le corpus | Écarté pour l'instant, même raison que F (trop peu de données) | Écarté |

---

## 💭 Réflexion stratégique (discussion du 2026-07-24, pas un chantier technique)

L'utilisateur a partagé une vision "AI Due Diligence Copilot" — étendre l'outil au-delà des Equator Principles vers Real Estate, Infrastructure, Energy et d'autres métiers de financement (Export/Aviation/Shipping/Leveraged Finance), avec plusieurs scénarios de monétisation (développement financé, cession, licence, spin-off).

**Retour donné** : distinguer clairement deux couches dans le pitch —
- **Intelligence documentaire (RAG/LLM)** : extraction, vérification de conformité à une checklist, détection d'infos manquantes, synthèse, Q&A traçable — **vraiment réutilisable** d'un métier à l'autre (juste changer la checklist de référence : Equator Principles → BREEAM/HQE/LEED pour Real Estate, etc.)
- **Scoring prédictif (Cox/survie)** : nécessite un corpus labellisé avec issues réelles connues par métier (l'équivalent de la base CAO) — **pas transposable rapidement**, c'est justement la partie qui nous a pris le plus de temps et qui reste fragile même pour Equator Principles

Recommandation : vendre la vérification de conformité par checklist comme le moteur transversal, pas le scoring prédictif ; faire un audit de faisabilité data avant de promettre une extension à un nouveau métier.

---

## Repères techniques utiles

```
cd scripts/
python ingest.py      # chunke corpus/*.pdf et *.txt vers chunks.csv
python annote.py      # applique flag_type (par contenu réel)/event/time_to_event depuis corpus_cao_ifc.xlsx
python pipeline.py    # re-embed + FAISS + entraîne Cox (tout, ~3min)
python model.py       # ré-entraîne Cox seul (réutilise embeddings/FAISS existants)
python analyze.py     # test end-to-end du pipeline d'analyse
cd ..
streamlit run app.py
```

- Seuils de risk grade par défaut (`model.DEFAULT_RISK_THRESHOLDS`) : D<25% / C 25-55% / B 55-80% / A>80% de probabilité d'événement à 12 mois — surchageables depuis Settings (session uniquement).
- `scripts/signals.py` : source unique des mots-clés de signaux (`SIGNAL_KEYWORDS`), utilisée par `analyze.py` (détection live), `annote.py` (ré-annotation du corpus) ET `app.py` (Pattern Library) — toute modification des mots-clés doit rester cohérente entre les trois usages.
- `st.session_state` clés utilisées dans `app.py` : `last_analysis` (résultat actif affiché), `analysis_history` (liste pour Portfolio Dashboard + sidebar), `risk_thresholds`, `faiss_k` (réglages Settings).
- `analyze(pdf_text, risk_thresholds=None, k=15)` — les deux derniers paramètres permettent à l'UI de surcharger le comportement par défaut sans redémarrer l'app.
