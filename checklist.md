# Journal de bord — NLP ESG Risk Intelligence

Dernière mise à jour : 2026-07-31 (PROMPT_CLAUDE_CODE_ESG_V2 — Chantier 1 (métadonnées chunks) et Chantier 2 (re-ranker cross-encoder) faits et commités, voir sections dédiées)

Dernière mise à jour précédente : 2026-07-26 (Tier 1 des retours Elisa — items 1, 2, 3 faits, voir section dédiée ; le travail du 25/07, jusqu'ici non commité, a été commité ce jour)

Dernière mise à jour précédente : 2026-07-25 (points 3 ET 4 avancés — LLM branché, export PDF/Excel, multi-documents, traçabilité ; + retours réunion Elisa du 25/07 consignés, propositions Tier 1-3 en attente d'arbitrage, présentation calée au 25 août)

## État général

- App Streamlit fonctionnelle en local (`streamlit run app.py`), déployée (Render puis migration Streamlit Cloud en cours de réglage d'accès public)
- Corpus : 4203 chunks, 46 projets annotés (28 événements CAO / 18 contrôles), 82 documents dans `corpus/`
- Modèle d'embedding : bascule vers `all-mpnet-base-v2` (768 dim) le 2026-07-25 — C-index 0.746 (contre 0.758 avec MiniLM, légère baisse), mais coefficient `flag1_community` plus significatif (p<0.005 contre p=0.01). Le vrai problème de différenciation n'était **pas** l'embedding — voir "Chantier ouvert" résolu ci-dessous.
- **Intégration LLM (Ollama, `qwen3:4b-instruct`) terminée sur les 4 usages prévus** (`scripts/llm_confirm.py`, 2026-07-25) :
  1. Filtre de polarité sur `flag_scores` (corrige le vrai bug de différenciation)
  2. Filtre de polarité sur `detected_signals`/surlignage
  3. Résumé des cas similaires (`app.py`, remplace l'extrait brut tronqué)
  4. Recommandation contextualisée (remplace le template fixe par grade)
  Toutes validées en conditions réelles via l'app Streamlit (tests Playwright, voir sections dédiées). Fail-open partout : si Ollama est injoignable, repli sur l'ancien comportement plutôt qu'un plantage.
- ⚠️ Perf non optimisée : le débit LLM se dégrade sous charge soutenue (voir "Chantier ouvert — préchauffage du cache LLM") — accepté pour l'instant, priorité aux fonctionnalités (décision utilisateur du 2026-07-25).
- **3 des 4 fonctionnalités UI de l'étape 4 terminées** (2026-07-25) : export PDF/Excel (`scripts/export.py`, nouvelle dépendance `fpdf2`), upload multi-documents, traçabilité des preuves par flag. Support multilingue reporté. Voir section dédiée.
- **Les 4 onglets sont maintenant branchés sur de vraies données** (plus aucun mockup) :
  - **Transaction Analysis** : pipeline complet (extraction → FAISS → Cox → signaux)
  - **Portfolio Dashboard** : historique des analyses de la session (`st.session_state`)
  - **Pattern Library** : fréquences et temps moyens réels calculés depuis le corpus
  - **Settings** : seuils de risk grade et k FAISS réellement fonctionnels, stats corpus en direct

---

## ✅ PROMPT_CLAUDE_CODE_ESG_V2 — Chantier 1 (métadonnées chunks) et Chantier 2 (re-ranker) (2026-07-31)

Suite à `AUDIT_ESG.md` (audit complet du codebase) et `PROMPT_CLAUDE_CODE_ESG_V2.md` (plan d'amélioration "MVP Impact", 8 chantiers). Chantier 0 (enrichissement du corpus CAO/IFC) mis en pause à la demande de l'utilisateur — `scrape_cao.py`/`scrape_ifc.py` écrits et validés (vrais téléchargements réussis) mais non commités, aucun run massif lancé.

**Chantier 1 — Métadonnées enrichies des chunks** (commit `ca233b7`) :
- Nouveau `scripts/chunk_metadata.py` : `extract_doc_date` (regex + repli sur `ifc_board_dates.py`), `classify_section_type` (environmental/social/governance/general, mots-clés pondérés à partir de `signals.py`), `classify_chunk_type` (metric/commitment/incident/narrative, regex), `compute_specificity_score` (0-1, ratio marqueurs concrets/hedging words).
- `scripts/ingest.py` peuple ces champs pour les nouveaux documents. `search.chunk_text()` **non modifié** (cohérence train/serve préservée, comme l'exigeait le prompt).
- `scripts/backfill_chunk_metadata.py` : rétro-rempli les 4203 chunks existants. 100% ont désormais un `doc_date`, répartition section_type cohérente (environmental 1472, general 1426, social 988, governance 317), specificity_score moyen 0.70.
- `test.py --unit` : 15/15 toujours au vert après le changement de schéma.

**Chantier 2 — Re-ranker cross-encoder post-FAISS** :
- Nouveau `scripts/reranker.py` : `cross-encoder/ms-marco-MiniLM-L-6-v2`, score composite (0.5×cross-encoder + 0.2×specificity + 0.2×récence + 0.1×boost chunk_type), normalisation **min-max par lot** (pas une sigmoïde fixe — les logits bruts du cross-encoder varient de -9 à +5.6 selon la requête, une sigmoïde les écraserait tous près de 0 et rendrait le poids cross-encoder inopérant).
- Nouveau `scripts/config.py` : feature flags par variable d'environnement (`ESG_RERANKER_ENABLED`, etc.) — désactivation = repli exact sur le comportement pré-Chantier 2.
- Branché dans `search.py` (`search_similar_from_chunks`, `get_flag_scores_from_chunks`) : pool FAISS élargi à 30 candidats quand actif, re-ranké, puis réduit à `k`.
- Validé : le passage analytiquement pertinent remonte en tête même sans le meilleur score FAISS brut (testé sur un cas réel community/fishing complaint vs. passages hors-sujet). `analyze()` en usage réel (modèles déjà chargés) : **3.6s**, acceptable pour la démo.

⚠️ **Nouveau constat de perf** : `get_flag_scores_from_chunks` est aussi appelée par `model.build_training_data` (entraînement Cox, tourne sur les 4203 chunks du corpus entier) — y ajouter un appel cross-encoder par chunk rend `test.py` (tests d'intégration, qui construisent l'explainer SHAP) nettement plus lent qu'avant ce chantier. Même catégorie de problème que le goulot d'étranglement `llm_confirm` déjà documenté ci-dessous ("Chantier ouvert — préchauffage du cache LLM") : acceptable en inférence live (une poignée de chunks par document), pas encore mesuré/optimisé pour un ré-entraînement complet (`pipeline.py`). À garder en tête pour le Chantier 5 (train/serve) — envisager de désactiver le re-ranker pendant `build_training_data` (feature flag déjà en place, `ESG_RERANKER_ENABLED=0`) si le ré-entraînement devient trop lent en pratique.

## ✅ Chantier 3 — Pipeline d'analyse LLM multi-pass (2026-07-31)

Nouveau `scripts/deep_analysis.py` — Pass 1 (extraction chunk par chunk : engagement chiffré/incident/formulation évasive, format ligne-par-ligne parsé par splits, pas de JSON), Pass 2 (détection d'omissions sectorielles, une fois par document, à partir des `section_type` des chunks du Chantier 1), Pass 3 (synthèse d'alerte 3-5 phrases pour comité de crédit, à partir des findings agrégés + `risk_grade`/`probability_12m`/`detected_signals` déjà calculés). PAS de Pass 4 (scénarios contrefactuels), conformément au prompt : un 4B inventerait des chiffres d'impact non fiables. `llm_confirm.py` non modifié — reste le filtre de polarité utilisé par `search.py`.

- Cache disque dédié (`models/deep_analysis_cache.json`), même pattern que `llm_confirm.py`. Fail-open à chaque passe (Ollama injoignable → passe ignorée, log un warning, les autres passes/le reste d'`analyze()` continuent normalement) — testé en coupant volontairement l'URL Ollama, confirmé : `pass1_findings=[]`, `omissions=None`, `synthesis=None`, aucune exception.
- Branché dans `analyze.py` (nouvelle clé `result["deep_analysis"]`), désactivable via `config.DEEP_ANALYSIS_ENABLED`.
- **Bug trouvé et corrigé en testant** : `guess_project_type()` (heuristique de secteur pour le prompt Pass 2) utilisait des motifs regex sans `\b` de tête — `ore\b` matchait "expl**ore**", et surtout `PV\b` matchait "S**PV**" (special purpose vehicle, très fréquent dans ce corpus project finance) → un projet classé à tort "solaire". Tous les motifs de `_PROJECT_TYPE_KEYWORDS` ont été passés en revue et corrigés.
- Validé sur un cas réel (accident du travail lors d'un montage d'échafaudage, sans mot-clé `signals.py` correspondant) : Pass 1 a correctement identifié l'incident là où le système de signaux par mots-clés existant ne l'aurait pas forcément capté — première preuve concrète de valeur ajoutée d'une vraie analyse LLM par rapport au matching de similarité (le problème de fond identifié dans `AUDIT_ESG.md`).

⚠️ **Coût de perf mesuré** : `analyze()` sur un document inédit (jamais mis en cache), modèles déjà chargés — **~60s** (3 nouveaux appels LLM minimum : Pass 1 ×nb chunks jusqu'à `MAX_CHUNKS_PASS1`=20, Pass 2 ×1, Pass 3 ×1 — en plus des appels `llm_confirm` déjà existants pour `flag_scores`/`detected_signals`). Nettement au-dessus des ~3.6s mesurés après le Chantier 2 seul. Cohérent avec la latence par appel déjà documentée pour `qwen3:4b-instruct` (~2-4s "à chaud") multipliée par le nombre d'appels cumulés sur un même document. Accepté pour l'instant (MVP démo, pas de budget de latence strict fixé par le prompt pour ce chantier, contrairement au Chantier 2) — à surveiller si un document plus long (plusieurs dizaines de chunks) pousse Pass 1 vers son plafond `MAX_CHUNKS_PASS1`.

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
| `test.py` référençait `shap_explanations` dans `analyze()` | `test.py` | Clé retirée du retour de `analyze()` lors du retrait de SHAP (24/07) sans mettre à jour le test — `KeyError` systématique en intégration/business. Assertions SHAP obsolètes supprimées de `test.py` |
| `dominant_flag` stocké avec la mauvaise clé | `app.py` | Repéré par l'utilisateur (2026-07-25, capture d'écran) : `analysis_history` stockait `max(display_result["flag_scores"], ...)` — les clés de `display_result["flag_scores"]` sont déjà les libellés humains ("Community & Stakeholder Risk"), pas les clés brutes ("flag1_community") attendues par `FLAG_LABELS[...]` dans Portfolio Dashboard → `KeyError` systématique dès la 1ère analyse. Corrigé en utilisant `result["flag_scores"]` (clés brutes) |
| Jargon technique exposé à l'analyste dans Settings | `app.py` | Repéré par l'utilisateur (2026-07-25) : section "Model Configuration" (nom du modèle d'embedding, dimensions, réglage FAISS Top-K) et "Embedding dimension" dans Corpus Info — détails d'implémentation sans valeur pour un analyste crédit. Section retirée, `k` FAISS revient à une valeur fixe (15) non exposée en UI |
| Spinner `@st.cache_data` affichait le nom de fonction Python | `app.py` | Repéré par l'utilisateur (2026-07-25) : Pattern Library affichait "Running _compute_pattern_library()..." (comportement par défaut de `@st.cache_data`). `show_spinner="Chargement des patterns..."` ajouté |

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

## ✅ RÉSOLU — différenciation du scoring FAISS sur texte externe (2026-07-25)

**Constat initial** : même après la ré-annotation par contenu, un texte neutre de test (rapport de routine) obtient un score quasi identique à un texte décrivant un risque réel, quel que soit k (testé de 3 à 30).

**Fausse piste explorée en premier — le modèle d'embedding** : hypothèse que `all-MiniLM-L6-v2` (22M paramètres) manquait de capacité pour distinguer des textes courts au même registre "rapport ESG formel". Bascule vers `all-mpnet-base-v2` (768 dim, décision prise sans comparatif chiffré complet — voir historique dans le diff git de ce fichier si besoin). **Résultat : le problème s'est reproduit à l'identique avec mpnet** (Cas 4 "projet propre" du test business scorait 78/67/71 sur les 3 flags, presque autant qu'un vrai cas à risque) — la preuve que ce n'était pas une question de capacité du modèle d'embedding.

**Vrai diagnostic** : l'embedding capture le *sujet* d'un passage, pas sa *polarité*. Exemple mesuré : `"The ESAP action plan shows delays"` (risque réel) et `"ESAP actions completed ahead of schedule"` (positif) matchent les mêmes voisins FAISS historiques, parce qu'ils partagent le même vocabulaire technique ESAP — aucun modèle de similarité sémantique pure ne fait cette distinction, quelle que soit sa taille. Un chunk qui *mentionne* un sujet à risque en le décrivant comme résolu/conforme gonflait `flag_scores` presque autant qu'un chunk qui décrit un vrai problème.

**Fix implémenté** : filtre de confirmation par LLM local (`scripts/llm_confirm.py`, Ollama + `qwen3:4b-instruct`), branché dans `search.get_flag_scores_from_chunks` (donc utilisé à la fois par `analyze.py` en live et par `model.build_training_data` à l'entraînement — cohérence train/serve). Voir section dédiée ci-dessous pour le détail.

**Résultat mesuré** (`test.py --business`, cas 1 = community opposition réel, cas 4 = projet propre) :

| | flag1 | flag2 | flag3 | Cox `probability_12m` |
|---|---|---|---|---|
| Cas 1 (risque), avant | 71 | 0 | 0 | 1.31% |
| Cas 4 (propre), **avant filtre** | 78 | 67 | 71 | 2.97% (> Cas 1 !) |
| Cas 4 (propre), **après filtre** | 0 | 0 | 0 | 0.02% (< Cas 1 ✅) |

`test.py --business` : 4/5 passés, 0 échec (le 5e est un warning déjà documenté : Cas 3 biodiversité reste bas car les coefficients Cox pour flag2/flag3 sont peu significatifs — data imbalance déjà connu, voir CORRECTIONS.md §4, pas lié à ce chantier).

⚠️ **Le `cox_model.pkl` actuel n'est pas ré-entraîné sur les scores filtrés** (il date d'avant le filtre LLM) — le gain ci-dessus s'observe déjà en inférence (c'est ce qui compte pour l'usage réel), mais il reste un léger décalage train/serve tant que `pipeline.py` n'a pas retourné avec le filtre actif. **Décision du 2026-07-25 : mis en pause délibérément**, voir "Chantier ouvert — préchauffage du cache LLM" ci-dessous pour le pourquoi.

---

## ✅ Filtre de polarité LLM — implémentation (2026-07-25)

**Architecture** : `scripts/llm_confirm.py`, une seule fonction `confirm_risk(chunk_text, flag_num) -> bool`.
- `signals.flags_mentioned_in_text(chunk)` sert de filtre regex bon marché en amont — ne sollicite le LLM que sur les (chunk, flag) où le vocabulaire du flag est topicalement présent, pas sur tous les chunks
- Branché dans `search.get_flag_scores_from_chunks(..., llm_confirm=True)` (défaut) : pour chaque chunk, les flags candidats jugés "CLEAN" par le LLM sont exclus de la contribution de CE chunk à l'agrégation max — les autres chunks/flags contribuent normalement
- Cache disque `models/llm_confirm_cache.json`, clé = `hash(flag_num + définition du flag + texte du chunk)` — invalide automatiquement si `FLAG_LABELS` change, pas seulement si le texte change
- **Fail-open** : si Ollama est injoignable, `confirm_risk()` retourne `True` (comportement identique à avant le filtre) plutôt que de planter l'analyse — un warning s'affiche une fois par process

**Choix du modèle Ollama — leçon importante** :
- `qwen3:4b` (variante "hybride") **inutilisable** : insiste pour produire 400 à 1400 tokens de raisonnement interne (`<think>...</think>`) même avec `think:false` (API) ou `/no_think` (suffixe prompt, convention native Qwen3) — mesuré 25 à 95 secondes par appel
- `qwen3:4b-instruct` (variante dédiée, sans raisonnement étendu) : répond directement en 1 mot, **~2s/appel à chaud** (modèle déjà résident en mémoire), correct sur les 4 cas de test manuels (`python llm_confirm.py`)
- **Leçon générale** : le débit brut de génération sur ce CPU n'est pas le problème (~17 tokens/s, correct pour un 4B) — c'est la longueur de la réponse qui détermine la latence. Toujours vérifier qu'un modèle "thinking" n'ajoute pas un raisonnement cascade avant de le jeter comme "trop lent".

**Usage live (analyze.py/app.py) validé et fonctionnel** — chaque document uploadé ne déclenche qu'une poignée d'appels LLM (proportionnel à ses propres chunks), latence ~2-4s/appel, sans souci observé.

**Ce qui reste ouvert** :
- `predict_risk` (Cas 3 biodiversité) sous-pondère flag2/flag3 — data imbalance connu (§4 CORRECTIONS.md), pas réglé par ce filtre
- Le filtre LLM ne s'applique qu'aux flags topicalement candidats via regex (`signals.py`) — un chunk sémantiquement proche d'un flag sans en partager le vocabulaire littéral n'est pas soumis au filtre (angle mort assumé, cohérent avec l'architecture hybride regex+LLM déjà actée)

## ✅ Confirmation LLM sur `detected_signals` (2026-07-25)

Branché dans `analyze._find_signals_in_document()` (`scripts/analyze.py`) — même mécanique que `flag_scores` : un appel LLM par (flag_num, signal_name) candidat via regex, sur l'extrait affiché à l'utilisateur (contexte autour de la première occurrence). Si le LLM juge "CLEAN", le signal est exclu à la fois de `detected_signals` (carte "Detected Signals") ET de `signal_spans` (surlignage du document).

Validé : texte "risque" → 9 signaux détectés (inchangé) ; texte "propre" (mentionne stakeholder/ESAP/biodiversity de façon positive) → **0 signal détecté** (en aurait déclenché plusieurs avant, par simple présence des mots-clés).

⚠️ Limite assumée : un seul appel par (flag_num, signal_name), basé sur la première occurrence seulement — si le même mot-clé apparaît une fois en négatif et une fois en positif ailleurs dans le document, le verdict du premier extrait s'applique aux deux occurrences.

⚠️ **Nouveau constat de perf (2026-07-25)** : le débit des appels LLM se dégrade aussi en **séquentiel soutenu**, pas seulement en parallèle — observé pendant `test.py` (~25 appels/min → ~7 appels/min après quelques minutes). Comme `analyze()` peut désormais déclencher jusqu'à ~15-20 appels LLM séquentiels par document (signals + flag_scores), une session avec plusieurs documents enchaînés pourrait ralentir progressivement. **Décision : pas d'investigation pour l'instant** (priorité au reste des fonctionnalités, voir feuille de route) — à reprendre si ça devient gênant en usage réel.

---

## 🔍 Chantier ouvert — préchauffage du cache LLM pour le ré-entraînement complet

**Objectif initial** : appeler `confirm_risk` sur tout le corpus (3962 paires (chunk, flag), 46 projets exploitables) pour ré-entraîner `cox_model.pkl` sur des scores cohérents avec le filtre LLM. En séquentiel : ~132 min, jugé trop long.

**Tentative de parallélisation — instable, cause non identifiée avec certitude** :
- Un premier test court (24-41 appels, quelques dizaines de secondes) à 16 threads montrait un débit qui **démarre bien puis se dégrade progressivement** sur la durée : ~5s/appel au début, jusqu'à ~90s/appel après ~1min30 de charge soutenue.
- Un test court à 4 threads semblait stable (~74 appels/min, aucune dégradation sur 12-26s) — **conclusion prématurée**. Un run réel de plusieurs minutes à 4 threads via `scripts/warm_llm_cache.py` s'est avéré tout aussi lent (~11 appels/min), y compris après avoir supprimé un point de contention identifié (écriture disque du cache à chaque appel sous verrou — corrigé mais sans effet sur le débit).
- Test de confirmation : appeler `confirm_risk` directement via le module (pas seulement des requêtes HTTP brutes), à petite échelle (16 tâches), reste rapide (78/min) — donc ce n'est ni la fonction elle-même, ni le verrou/cache.
- **Hypothèse retenue, non vérifiée** : accumulation de pression mémoire/contexte côté Ollama sur charge *soutenue* (au-delà d'1-2 min), indépendamment du niveau de concurrence — 16 threads atteint le mur plus vite que 4, mais les deux semblent y arriver. Pistes non explorées : `OLLAMA_KEEP_ALIVE`, `OLLAMA_NUM_PARALLEL`, redémarrage périodique du service Ollama pendant le batch.
- Un premier run à 15s de timeout a échoué silencieusement (fail-open partout, cache resté bloqué à 21 entrées) à cause de ce ralentissement dépassant le timeout — corrigé en remontant le timeout à 60s, mais ça ne règle que le symptôme (échec silencieux), pas le ralentissement lui-même.

**Décision (2026-07-25)** : mis en pause. Le fix qui compte réellement — le filtre en direct sur `analyze()`/`app.py` — est déjà validé et fonctionnel (voir section précédente), et n'est pas affecté par ce problème (usage en courtes rafales, pas de charge soutenue). Le ré-entraînement complet du Cox sur scores filtrés reste à faire, mais n'est pas bloquant. **Ne pas relancer `scripts/warm_llm_cache.py` sur tout le corpus avant d'avoir diagnostiqué la cause racine** — risque de tourner des heures pour un résultat imprévisible.

---

## 🗺️ Feuille de route décidée (2026-07-24)

Ordre validé par l'utilisateur :

1. **Choisir le modèle d'embedding** (FAIT le 2026-07-25, sur `all-mpnet-base-v2` — **s'est avéré ne pas être le vrai problème**, voir section résolue ci-dessus. Gardé en prod car légèrement meilleur sur la significativité de flag1, pas de raison de revenir en arrière.)
2. **Intégrer un modèle d'IA open source local** — Ollama installé, `qwen3:4b-instruct` retenu (voir section dédiée ci-dessus pour le pourquoi de ce tag précis plutôt que `qwen3:4b`). Note : `migration-signaux-ollama.md` référencé ici auparavant **n'a jamais existé comme fichier** — le contenu du plan est directement dans ce document. Architecture effectivement appliquée (hybride regex+LLM, cache par hash, fail-open) : voir "Filtre de polarité LLM" ci-dessus.
3. **Cas d'usage LLM prioritaires (points 1-3)** :
   - ✅ **Confirmation de signaux — FAIT sur `flag_scores`/Cox ET sur `detected_signals`** (les deux, 2026-07-25). La portée initiale ne visait que l'affichage UI (`detected_signals`) ; le vrai bug reproductible (Cas 4 "propre" scorait 78/67/71) venait de `flag_scores`, corrigé en premier, puis le même mécanisme branché sur `detected_signals`/`signal_spans` (voir sections dédiées ci-dessus).
   - ✅ **Cas similaires enrichis — FAIT** (2026-07-25) : `llm_confirm.summarize_passage()`, branché dans `app.py._map_result_to_display()` (pas dans `analyze.py` — seulement calculé sur les 5 cas finaux affichés, pas sur tous les voisins FAISS bruts, pour borner le coût à 5 appels max). Testé en conditions réelles via l'app Streamlit (Playwright) : résumés cohérents en une phrase à la place de l'extrait tronqué en plein milieu de phrase. Fail-open : repli sur l'ancien extrait tronqué si Ollama est injoignable.
   - ✅ **Recommandation contextualisée — FAIT** (2026-07-25) : `llm_confirm.generate_recommendation()`, branché dans `analyze()` (fait partie de `result["recommendation"]`, persisté dans `st.session_state["last_analysis"]`). `app.py` utilise `result["recommendation"] or RECOMMENDATION_BY_GRADE[grade]` (fallback si Ollama injoignable). Testé en conditions réelles (Playwright) : cas "propre" → *"Given no specific ESG risk signals and a 0% probability of an ESG event, approve the transaction with no mitigation requirements"* ; cas "risque" → recommandation citant PS non-conformance, community opposition, consultation gaps — bien plus utile que l'ancien template unique "Vigilance — monitoring standard" par grade.

**Point 3 de la feuille de route (cas d'usage LLM) intégralement terminé.**
4. **Construire l'interface graphique définitive** — 3 des 4 fonctionnalités validées FAITES le 2026-07-25 (export, multi-documents, traçabilité), 1 reportée (multilingue) — voir section dédiée ci-dessous
5. **Optimiser le temps de calcul**
6. Une fois 1-5 stabilisés : **points 4-5** (résumé de document long/page par page, Pattern Library en insights narratifs générés)
7. Nouvelle passe d'optimisation
8. Quand le MVP est complet : **point 6** — Q&A libre sur le document uploadé (RAG/chat), le plus gros chantier, mis de côté pour la fin

---

## 🆕 Fonctionnalités validées pour l'étape 4 (interface graphique)

Décidées le 2026-07-24 :

| # | Fonctionnalité | Statut |
|---|---|---|
| 1 | **Support multilingue** | **Reporté** (2026-07-25) — était lié au choix du modèle d'embedding, mais on a fini sur mpnet (anglophone), pas sur le multilingue (écarté, voir "Chantier ouvert" résolu). Corpus quasi tout anglophone, pas jugé prioritaire pour l'instant. |
| 2 | **Export du résultat** (PDF/Excel) | ✅ **FAIT** (2026-07-25) |
| 3 | **Upload multi-documents** | ✅ **FAIT** (2026-07-25) |
| 4 | **Traçabilité des preuves derrière un score** | ✅ **FAIT** (2026-07-25) |

### ✅ Export PDF/Excel (2026-07-25)

Nouveau module `scripts/export.py` : `build_pdf_report()` (fpdf2, nouvelle dépendance pure Python, pas de wkhtmltopdf/weasyprint) et `build_excel_report()` (openpyxl, déjà utilisé). Boutons `st.download_button` dans `app.py`, juste au-dessus de "Risk Assessment Summary" — génération à la volée à chaque rerun (pas de nouvel appel FAISS/LLM, juste mise en forme des données déjà calculées par `analyze()`, donc quasi instantané).
- PDF : 1 page, sections Summary/Flag Scores (+ preuves)/Detected Signals/Historical Similar Cases
- Excel : 4 feuilles (Summary, Detected Signals, Similar Cases, Evidence by Flag)
- FRAGILE : fpdf2 core fonts (Helvetica) sont limitées à Latin-1 — `_safe()` remplace la ponctuation Unicode courante (tirets, guillemets courbes, ellipse) par un équivalent ASCII avant fallback. Piège rencontré : `pdf.set_y(-15)` pour ancrer un footer en bas de page déclenche un saut de page intempestif dans fpdf2 sur un contenu court — remplacé par un footer "en flux" (`pdf.ln()` + `cell()` sans position absolue).
- Testé en conditions réelles (Playwright) : téléchargement PDF + Excel déclenchés depuis l'app, fichiers relus et vérifiés (contenu, Unicode correct, 4 feuilles Excel).

### ✅ Upload multi-documents (2026-07-25)

`st.file_uploader(..., accept_multiple_files=True)` + nouvelle fonction `_extract_multi_doc_text()` dans `app.py` : concatène le texte de plusieurs fichiers (séparateur `=== nom_fichier ===`) en un seul texte passé à `analyze()`.
CHOIX : concaténation en un seul texte, pas une analyse séparée par document — garde `analyze()` inchangé (un seul jeu de chunks/flag_scores). Limite assumée : les signaux détectés/le surlignage ne distinguent pas de quel document ils viennent (cohérent avec le chantier "annotation page par page", déjà en pause, item B ci-dessous).
`doc_label` devient `"N documents (a.pdf, b.pdf, ...)"` — `_safe_filename()` ajouté pour nettoyer ce genre de libellé avant de servir de nom de fichier d'export.
Testé en conditions réelles (Playwright, 2 fichiers .txt uploadés ensemble) : les deux apparaissent dans l'uploader, l'analyse tourne sur le texte combiné, flag_scores reflètent bien le contenu des deux documents.

### ✅ Traçabilité des preuves derrière un score (2026-07-25)

Dans `app._map_result_to_display()` : nouveau champ `evidence_by_flag`, dérivé de `result["similar_passages"]` (les mêmes voisins FAISS que `search.get_flag_scores` a utilisés pour calculer `flag_scores` — pas de nouvel appel FAISS). Pour chaque flag, les 2 projets historiques (un passage chacun, meilleur score) dont le `flag_type` correspond, triés par score, avec résumé LLM (`summarize_passage`, déjà utilisé pour Historical Similar Cases — bénéficie du même cache).
Affiché sous chaque barre de score dans la carte "Flag Scores" via un `<details>/<summary>` HTML repliable (pas de widget Streamlit imbriqué dans les cards en `unsafe_allow_html`, pattern déjà utilisé partout ailleurs dans `app.py`).
Testé en conditions réelles (Playwright) : 3 blocs "Evidence behind this score" trouvés et dépliés avec succès, contenu cohérent avec les scores affichés.

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
| H | `flag_type` affiché "nan" dans Historical Similar Cases | Repéré le 2026-07-25 (test UI Playwright) sur `IFC_36402_KTDAHydro_CTRL` — un chunk sans `flag_type` (NaN pandas) remonte quand même comme voisin FAISS ; `p["flag_type"] or "—"` ne suffit pas (`float('nan')` est truthy en Python), il faut un vrai `pd.isna()` côté `app.py._map_result_to_display` | Cosmétique, pas corrigé |

---

## 📼 Retours réunion Elisa/Archange (2026-07-25, notes Gemini) — propositions, non implémentées

Contexte : compte-rendu d'une session de démo/travail avec Elisa (associée). Calendrier arrêté : finalisation semaine du **20 août**, présentation officielle le **25 août** (repoussée depuis le 5 août). Elisa consacre 1h-1h30/jour au projet.

### Déjà réglé par le travail du 2026-07-25 (avant même lecture des notes)

- **Paragraphe "restauration des moyens de subsistance" flaggé à tort comme risque** — exactement le bug de polarité diagnostiqué et corrigé ce jour (voir "Filtre de polarité LLM").
- **Proposition d'Elisa** : *"si un risque communautaire est suivi dans le paragraphe par du vocabulaire de mitigation, réduire automatiquement le poids"* — c'est l'architecture `llm_confirm.confirm_risk` construite ce jour (LLM plutôt que règle de proximité de mots-clés).
- **"Export Excel seulement, il faudrait du PDF"** — fait ce jour (`scripts/export.py`).
- **Confidentialité / IA externe** — déjà vrai (Ollama 100% local), à confirmer explicitement à Elisa dans la présentation puisque c'était son objection principale sur l'usage d'IA open source.

### Propositions faites (2026-07-25) — PAS IMPLÉMENTÉES, à trancher avec Elisa avant de coder

**Tier 1 — gains rapides, indépendants les uns des autres :**
1. ✅ **FAIT (2026-07-26)** — Regrouper l'affichage des signaux détectés par flag (pas par signal individuel) — corrige le "l'outil a dupliqué son alerte sur un même paragraphe" repéré par Elisa en démo.
2. ✅ **FAIT (2026-07-26)** — Score chiffré 0-100 en complément du grade lettre (D/C/B/A) — Elisa juge le grade lettre peu explicite sur la gravité/l'échelle.
3. ✅ **FAIT (2026-07-26)** — Réagencer l'écran de résultat pour faire remonter Flag Scores/Signaux/Preuves au-dessus du % de probabilité — répond à "l'outil ne doit pas être qu'un prédicteur de défaut, mais un instrument d'alerte et de justification décisionnelle". Voir section dédiée ci-dessous.
4. Migration vers un hébergement permanent (engagement pris auprès d'Elisa en réunion — le tunnel Cloudflare mis en place le 25/07 est un pis-aller temporaire, pas ce qui a été promis) — à caler explicitement avant le 20 août.

**Tier 2 — nécessitent une décision de design avec Elisa d'abord :**
5. Pondération manuelle du risque ("aligner les paramètres avec le ressenti analytique") — deux options proposées : (a) garder 100% statistique (Cox apprend déjà les poids depuis l'historique), ou (b) ajouter un champ "note/justification de l'analyste" qui capture le désaccord sans toucher au modèle (option recommandée si une décision est nécessaire avant la présentation — audit trail, pas de dilution de la rigueur statistique).
6. Grades trop souvent "D" (peu de contraste) — cause déjà connue : trop peu de projets Flag 3 dans le corpus (§4 CORRECTIONS.md). Pas un bugfix — proposition : intégrer explicitement la recherche de projets Flag 2/Flag 3 supplémentaires dans la tâche d'Elisa "analyser les 46 projets disponibles".

**Tier 3 — cosmétique, non bloquant :**
7. Nom du projet non tranché (Archange : "CBG Risk Intelligence"/"Zelenski Bini" ; Elisa : "ESG Data Room"/"Due Diligence Room").

### Autres actions issues de la réunion (hors périmètre code, pour mémoire)

- Elisa : valider la taxonomie sémantique (`signals.py`), tester l'outil sur 6 rapports de référence pour lister les anomalies (échéance 1er août).
- Elisa : enquête interne aupres des analystes (entretien avec "Hugo") sur les tâches les plus fastidieuses — pour prioriser les prochaines fonctionnalités.
- Elisa : recherche sur les critères ESG spécifiques au secteur immobilier — lien avec la réflexion stratégique ci-dessous (extension à d'autres métiers).
- Archange : centraliser les rapports d'analyse dans un Drive partagé.
- Positionnement produit à confirmer avec Elisa : instrument d'alerte/justification de décision (mapper les fréquences de signaux, anticiper les revues périodiques), pas un prédicteur de défaut ESG pur — cohérent avec la réflexion stratégique ci-dessous.

---

## ✅ Tier 1 des retours Elisa — implémentation (2026-07-26)

**1. Signaux regroupés par flag** (`app._map_result_to_display`) : au lieu d'une carte par `signal_name` individuel (11 catégories possibles), les signaux détectés sont regroupés par flag (1/2/3) — une seule carte par flag avec la liste des thèmes touchés (ex. "Community opposition · Displacement risk · Consultation gaps") et les extraits dédupliqués (texte identique uniquement — pas de dédup sémantique, un paragraphe reformulé différemment sur le même sujet donnera quand même 2 extraits, limite assumée). Plafonné à 3 extraits par flag pour ne pas surcharger la carte.

**2. Score chiffré 0-100** : nouveau champ `display["risk_score"] = round(probability_12m * 100)` — même mesure que `probability_12m`, juste présentée en entier 0-100 à côté du badge de grade lettre plutôt qu'en pourcentage dans le texte. Ajouté aussi au résumé PDF/Excel (`scripts/export.py`) pour rester cohérent entre l'app et les exports.

**3. Réagencement de l'écran** : la carte "Risk Assessment Summary" en tête d'écran ne montre plus que le Grade + le Score (repère visuel immédiat) — la probabilité en % et la recommandation textuelle sont déplacées dans une nouvelle carte "📈 Probability & Recommendation", positionnée après Flag Scores/Evidence et Detected Signals/Annotated Document, juste avant Historical Similar Cases. Nouvel ordre de l'écran : Grade+Score → Flag Scores (+ preuves) → Detected Signals + Annotated Document → Probability & Recommendation → Historical Similar Cases.

Testé en conditions réelles (Playwright, cas "risque" avec les 3 flags touchés) : regroupement par flag confirmé (3 cartes au lieu de 11 signaux individuels), score "2/100" affiché à côté du grade "D", carte Probability & Recommendation bien positionnée après les preuves.

⚠️ **Piège rencontré pendant le test** : `analyze._ensure_loaded()` fait un `print("⏳ Chargement des modèles...")` qui plante (`UnicodeEncodeError`/`charmap`) si le processus Streamlit a son stdout redirigé vers un fichier sans forcer l'encodage UTF-8 (`PYTHONIOENCODING=utf-8`) — spécifique à Windows quand la sortie standard n'est pas un vrai terminal. Pas un bug introduit aujourd'hui, mais à garder en tête si un lancement en arrière-plan (`streamlit run app.py > log.txt`) échoue silencieusement sur la toute première analyse : vérifier `PYTHONIOENCODING` avant de chercher ailleurs.

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
python ingest.py               # chunke corpus/*.pdf et *.txt vers chunks.csv
python annote.py               # applique flag_type (par contenu réel)/event/time_to_event depuis corpus_cao_ifc.xlsx
python warm_llm_cache.py       # préchauffe le cache LLM sur tout le corpus — INSTABLE, voir "Chantier ouvert" avant d'utiliser sur un run long
python pipeline.py             # re-embed + FAISS + entraîne Cox (tout, ~15-20min avec mpnet ; le Cox actuel n'est PAS ré-entraîné sur les scores filtrés LLM, voir "Chantier ouvert")
python model.py                # ré-entraîne Cox seul (réutilise embeddings/FAISS existants)
python analyze.py              # test end-to-end du pipeline d'analyse
python compare_embeddings.py   # comparatif modèles d'embedding (C-index + gap risque/neutre), résultats dans models/embedding_comparison.json
python llm_confirm.py          # auto-test du filtre de polarité (4 cas RISK/CLEAN connus)
cd ..
streamlit run app.py
```

- **Ollama doit tourner** (`ollama serve`, démarré automatiquement au login sur Windows après install) pour que le filtre de polarité fonctionne — sinon fail-open silencieux (comportement pré-filtre, un seul warning affiché). Modèle utilisé : `qwen3:4b-instruct` (PAS `qwen3:4b`, voir "Filtre de polarité LLM" — le hybride est ~15-45x plus lent).
- **Playwright installé dans `venv/`** (2026-07-25, `pip install playwright` + `playwright install chromium`) pour vérifier visuellement l'app dans un vrai navigateur headless plutôt que juste tester les fonctions Python isolément — utile vu que les changements récents (résumés/recommandation LLM) ne se voient que dans le rendu Streamlit. Pas de script de driver committé pour l'instant (tests ad hoc), à formaliser si réutilisé souvent.
- **Piège vécu (2026-07-25)** : `streamlit run app.py` gardait un process fantôme sur le port 8501 après un run précédent (fermé sans libérer le port proprement) — les tests suivants pointaient sur l'ANCIEN code sans erreur ni avertissement, donnant l'impression qu'un correctif ne marchait pas alors qu'il n'était juste jamais exécuté. `netstat -ano | grep 8501` pour vérifier qu'un seul process écoute avant de conclure qu'un test "confirme" quoi que ce soit. Si l'app tourne déjà dans un terminal (le tien), ne pas le tuer à l'aveugle — relancer une vérification sur un autre port (`--server.port 8502`) et te laisser redémarrer le tien pour récupérer le correctif.
- `scripts/export.py` (`build_pdf_report`/`build_excel_report`) prend `result` (sortie brute de `analyze()`) ET `display` (sortie de `app._map_result_to_display()`) — utilise les deux car `display` a déjà les résumés LLM/agrégations par projet (évite de les recalculer), mais certains champs texte y sont `html.escape()` pour Streamlit (`_unescape()` les repasse en clair pour le PDF/Excel).
- Seuils de risk grade par défaut (`model.DEFAULT_RISK_THRESHOLDS`) : D<25% / C 25-55% / B 55-80% / A>80% de probabilité d'événement à 12 mois — surchageables depuis Settings (session uniquement).
- `scripts/signals.py` : source unique des mots-clés de signaux (`SIGNAL_KEYWORDS`), utilisée par `analyze.py` (détection live), `annote.py` (ré-annotation du corpus), `app.py` (Pattern Library) ET `llm_confirm.py` (filtre de candidats) — toute modification des mots-clés doit rester cohérente entre ces usages.
- `st.session_state` clés utilisées dans `app.py` : `last_analysis` (résultat actif affiché), `analysis_history` (liste pour Portfolio Dashboard + sidebar), `risk_thresholds`, `faiss_k` (réglages Settings).
- `analyze(pdf_text, risk_thresholds=None, k=15)` — les deux derniers paramètres permettent à l'UI de surcharger le comportement par défaut sans redémarrer l'app.
