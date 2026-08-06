# Journal de bord — NLP ESG Risk Intelligence

Dernière mise à jour : 2026-08-06 (déploiement VPS Hostinger réussi — corpus/models transférés hors git par scp, Docker fonctionnel, ajout de Caddy en reverse proxy pour l'authentification (accès non protégé jugé insuffisant). Voir section dédiée.)

Dernière mise à jour précédente : 2026-08-06 (audit perf complet — cause réelle des 20-30 min sur un rapport de 45-70 pages identifiée par mesure directe sur un document réel : PAS le thinking mode Qwen, mais un doublon de re-ranking cross-encoder + un bug de parsing qui faisait planter Pass 3. Voir section dédiée.)

Dernière mise à jour précédente : 2026-08-06 (DIRECTIVE_CLAUDE_CODE_ESG_V3, Jour 2 fait — sévérité dynamique par signal, métrique "Signaux détectés" en tête de page, voir section dédiée)

Dernière mise à jour précédente : 2026-08-06 (retour terrain réel — rapport CAO Mundra CGPL : filtre boilerplate/table des matières dans chunk_text(), num_predict Pass 3 corrigé, libellé "occurrences" clarifié — voir section dédiée)

Dernière mise à jour précédente : 2026-08-06 (DIRECTIVE_CLAUDE_CODE_ESG_V3, Tier 1 fait — plafond confirm_risk à 30 appels, st.status() dans app.py, voir section dédiée)

Dernière mise à jour précédente : 2026-08-06 (DIRECTIVE_CLAUDE_CODE_ESG_V3, Tier 0 fait — cache/lazy-loading vérifié, config Ollama plafonnée, code mort supprimé, voir section dédiée)

Dernière mise à jour précédente : 2026-07-31 (PROMPT_CLAUDE_CODE_ESG_V2 — Chantiers 1 à 4 faits et commités : métadonnées chunks, re-ranker cross-encoder, pipeline LLM multi-pass, refonte UI Streamlit — voir sections dédiées)

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

## ✅ Déploiement VPS Hostinger (2026-08-06)

Premier déploiement réel, VPS Hostinger KVM 2 (2 vCPU, 8 Go RAM, Ubuntu 24.04 LTS, `docker`/`docker compose` déjà installés via la fonctionnalité "Gestionnaire Docker" de Hostinger — pas besoin d'`apt install docker.io`).

**Piège n°1 — `corpus/` et `models/` ne sont pas dans git** (`.gitignore` les exclut volontairement — PDF/binaires trop lourds pour l'historique). `git clone` sur le VPS ne les ramène pas. Transférés manuellement par `scp -r models corpus root@<ip>:~/Projet-Elisa/` depuis la machine locale — 80 Mo, tailles vérifiées identiques (`du -sh`) des deux côtés après transfert. `data/processed/chunks.csv` et `data/raw/corpus_cao_ifc.xlsx`, eux, sont bien suivis par git (transfert compressé donc taille de clone trompeuse — un `git clone` à "1,29 Mio" ne veut pas dire "fichiers manquants", un CSV se compresse énormément).

**Piège n°2 — aucun fichier Docker n'était committé.** Le Dockerfile/docker-compose.yml/.dockerignore/docker_init.sh créés plus tôt dans la session existaient seulement en local, jamais poussés sur GitHub — le premier `docker compose up -d` sur le VPS échouait ("no configuration file provided"). Committé + poussé (commit `e5f437f`) avant de pouvoir continuer.

**Deux échecs réseau ponctuels pendant le `ollama pull qwen3:4b-instruct`** (timeout à 45% puis timeout sur le manifeste) — résolus par une simple reconnexion + nouvelle tentative (Ollama reprend le pull interrompu, pas de re-téléchargement complet). Pas creusé plus loin, pas reproduit une 3e fois.

**Vérifié fonctionnel de bout en bout** : upload d'un vrai document sur `http://187.124.209.94:8501`, analyse complète en 10-12 min (cohérent avec les 4-18 min mesurées en local — plus lent ici, logique avec 2 vCPU contre 8 sur la machine de dev).

### Nom de domaine (`esg-risk-intelligence.tech`) — bloqué, mis en pause

Domaine gratuit Hostinger configuré, DNS pointe bien vers le VPS via un enregistrement A (`187.124.209.94`) — **mais aussi un enregistrement AAAA (IPv6, `2a02:4780:f:d8ab::1`)** qui semble injoignable sur le port 8501 (`curl` direct en IPv6 échoue en 0ms — signal fort mais pas certain à 100%, l'environnement de test n'a peut-être pas d'IPv6 sortant non plus). Les navigateurs modernes essaient l'IPv6 en premier quand un AAAA existe → le domaine ne charge pas alors que l'IP brute fonctionne. **Décision (2026-08-06) : mis en pause**, pas réglé cette session — l'IP brute suffit pour l'instant.

### Sécurisation — Caddy en reverse proxy (2026-08-06)

Accès direct sans authentification jugé insuffisant dès qu'un document réel a été testé avec succès (voir échange avec l'utilisateur) — n'importe qui avec le lien pouvait utiliser l'outil. Décision : HTTPS reporté (dépend du problème AAAA/domaine non résolu ci-dessus), mais authentification ajoutée immédiatement, indépendante du domaine.

`Caddyfile` (nouveau) : bloc `:80` (pas de nom de domaine — évite tout déclenchement automatique de Let's Encrypt, qui buterait sur le problème AAAA), `basic_auth` avec 2 comptes (`zelensky`/`boudini`, même mot de passe, hashé en bcrypt via `docker run --rm caddy:2 caddy hash-password` — jamais stocké en clair), puis `reverse_proxy app:8501`.

`docker-compose.yml` modifié : nouveau service `caddy` (image `caddy:2`, publie 80 ET 443 — 443 déjà prêt pour le jour où le domaine sera réglé, pas de retouche du compose nécessaire à ce moment-là, juste le `Caddyfile`). Le service `app` **ne publie plus le port 8501 directement** (`ports:` retiré) — il reste joignable pour Caddy via le réseau Docker interne (nom de service), mais plus accessible de l'extérieur en contournant l'authentification. Nettoyage au passage : ligne `version: "3.8"` retirée (attribut obsolète, provoquait un warning inoffensif à chaque `docker compose up`).

⚠️ **Limite assumée** : authentification unique partagée (2 comptes, même mot de passe), pas de vrai système multi-utilisateurs — suffisant pour un accès Stacy/Elisa/utilisateur, pas conçu pour scaler à plus de monde. Transport toujours en HTTP (pas de chiffrement) tant que le domaine/AAAA n'est pas réglé — mot de passe et documents uploadés circulent en clair sur le réseau.

---

## ✅ Audit perf — cause réelle des 20-30 min sur un rapport de 45-70 pages (2026-08-06)

**Contexte** : hypothèse proposée (par une autre session) — le thinking mode de `qwen3:4b` ferait 29s/appel LLM au lieu de 2s, cause de 20-50 min sur un document réel. Avant d'appliquer les correctifs proposés (changer de modèle, ajouter `/no_think`), vérification du code réel :
- `MODEL_NAME` était déjà `qwen3:4b-instruct` (pas `qwen3:4b`) dans `llm_confirm.py` ET `deep_analysis.py` — c'est justement la variante SANS thinking mode (confirmé via `ollama list` : `qwen3:4b-instruct` n'a pas la capability `"thinking"`, `qwen3:4b` l'a).
- `num_predict`/`num_ctx` par usage déjà en place depuis le Tier 0 (`config.OLLAMA_CONFIGS`).
- 3 appels `confirm_risk` réels mesurés isolément : ~4.2s chacun, pas 29s.
- `ollama ps` : le modèle est bien résident en mémoire (`keep_alive` fonctionne).

**Diagnostic honnête : le problème décrit (thinking mode actif) n'existe pas dans ce code.** Plutôt que d'appliquer un fix qui n'aurait rien changé, audit chronométré réel : `analyze()` décomposé étape par étape, exécuté sur un vrai document du corpus (`CAO_Serbia_Morava_Corridor_Motorway_05_Compliance_Appraisal_Report.pdf`, 63 pages, 171 chunks après filtre boilerplate — dans la fourchette cible 45-70 pages).

**Résultat AVANT correctif — 1065.8s (17.8 min), cohérent avec le "20-30 min" rapporté :**

| Étape | Temps | % | Contenu |
|---|---|---|---|
| `get_flag_scores` | 453.6s | 43% | confirm_risk×30 (plafonné, Tier 1) + FAISS/rerank sur 171 chunks |
| `search_similar` | 246.6s | 23% | FAISS/rerank sur les MÊMES 171 chunks — **zéro appel LLM** |
| `_find_signals_in_document` | 28.4s | 3% | ≤10 confirm_risk sur pdf_text brut |
| `generate_recommendation` | 11.1s | 1% | 1 appel |
| `deep_analysis` (Pass1×20 + Pass2) | 288.5s | 27% | Pass 3 **a planté** (voir bug ci-dessous) |
| `summarize_passage`×11 (app.py) | 28.1s | 3% | similar_cases + evidence_by_flag |

**Cause réelle #1 (46% du temps) : re-ranking cross-encoder calculé DEUX FOIS.** `analyze.py` appelait `search.get_flag_scores(pdf_text, ...)` PUIS `search.search_similar(pdf_text, ...)` séparément — chacun refaisait indépendamment tout le pipeline embedding + FAISS + re-ranking cross-encoder sur les MÊMES 171 chunks du même document. `search_similar` (246.6s, zéro appel LLM) est la preuve directe : c'est du travail 100% recalculé pour rien. Cette machine n'a pas de GPU (`torch.cuda.is_available() == False`, CPU Intel Core Ultra 7 258V 8 cœurs) — le cross-encoder tourne intégralement sur CPU, donc ce doublon coûte particulièrement cher ici.

**Fix** : refactor de `search.py` — nouvelle fonction interne `_rerank_all_chunks()` (embedding + FAISS + rerank, factorisée), nouvelle fonction publique `analyze_chunks()`/`analyze_query()` qui calcule le re-ranking UNE SEULE FOIS et en dérive à la fois `flag_scores` ET `similar_passages`. `get_flag_scores_from_chunks`/`search_similar_from_chunks` restent utilisables seules avec un comportement identique (vérifié : mêmes résultats qu'avant, `assert scores_only == scores_combined` passé) — `model.build_training_data` (qui n'a besoin que de `flag_scores`) n'est pas affectée. `analyze.py` bascule sur `search.analyze_query()` à la place des deux appels séparés.

**Cause réelle #2 (27% du temps, MAX_CHUNKS_PASS1=20 conservé sur décision explicite) : `deep_analysis` Pass 1 fait 20 appels LLM séquentiels**, un par chunk. Inhérent au design actuel (une question à la fois, jamais de batching). Pas touché cette session (arbitrage vitesse/profondeur explicitement tranché : garder les 20 chunks).

**Bug trouvé en creusant Pass 3 : `_parse_pass1_response` laissait un champ à `None` (pas `{"present": False}`) quand une des 3 lignes attendues (ENGAGEMENT/INCIDENT/EVASIF) n'était pas trouvée dans la réponse du LLM — probablement une troncature liée à `num_predict=100` sur cette passe (français, comme le bug Pass 3 de la veille). `run_pass3` fait `f.get("incident", {}).get("present")` — `.get(..., {})` ne protège PAS contre une valeur `None` existante (seulement contre une clé absente) → `AttributeError` → Pass 3 échoue silencieusement (fail-open, aucune exception visible, mais la carte "🧠 Deep Analysis" reste vide sans explication). Confirmé dans l'audit AVANT : `[WARN] deep_analysis Pass 3 : erreur inattendue ('NoneType' object has no attribute 'get')`.

**Fix** : `_parse_pass1_response` initialise maintenant `result` avec `{"present": False}` pour les 3 clés (au lieu de `None`) — un champ jamais matché reste un dict valide, plus jamais un trou. `config.OLLAMA_CONFIGS["deep_extract"]` remonté de 100 à 180 (réduit la fréquence des troncatures à la racine, pas juste le symptôme).

**Vérifié** : `test.py --unit` 15/15, `--integ` 8/8, `--business` 4/5 (mêmes résultats qu'avant refactor — comportement inchangé). API équivalence testée explicitement : `get_flag_scores()` seule vs `analyze_query()` combinée → résultats identiques (`assert scores_only == scores_combined` passé).

**Re-mesure APRÈS fix — deux runs, résultat contre-intuitif à prendre au sérieux :**

1er run après fix (même document, cache LLM encore chaud de la veille) : **267.0s (4.4 min)**. Chiffre flatteur mais **faussé** — `confirm_risk`/`deep_analysis` réutilisaient le cache disque de l'audit AVANT (même texte exact = mêmes clés de cache). Repéré et signalé avant de le prendre pour argent comptant.

Pour un chiffre honnête, caches mis de côté (sauvegardés, restaurés après coup — rien perdu) et re-run à froid sur le MÊME document :

| Étape | Avant | Après (à froid) |
|---|---|---|
| Rerank + confirm_risk (fusionné) | 453.6s + 246.6s = 700.2s (2 passages) | 506.9s (1 seul passage) |
| `_find_signals_in_document` | 28.4s | 31.7s |
| `generate_recommendation` | 11.1s | 9.7s |
| `deep_analysis` | 288.5s (**Pass 3 a planté**) | 468.9s (**Pass 3 a expiré : timeout Ollama 60s dépassé**) |
| `summarize_passage`×11 | 28.1s | 89.3s |
| **TOTAL** | **1065.8s (17.8 min)** | **1115.2s (18.6 min)** |

**Le total à froid n'a PAS baissé — légèrement pire, malgré la suppression prouvée d'un doublon de 246.6s.** Explication : le doublon de re-ranking (246.6s de travail 100% inutile, prouvé par construction — l'étape fusionnée ne PEUT plus le refaire deux fois) est bien éliminé, mais ce gain est masqué par un problème préexistant et déjà documenté : **le débit d'Ollama se dégrade sous charge séquentielle soutenue** (`checklist.md`, section "Chantier ouvert — préchauffage du cache LLM", 25/07/2026 — jamais résolu, volontairement mis en pause à l'époque). Un `analyze()` complet enchaîne ~50-60 appels LLM séquentiels (confirm_risk×30 + signaux×≤10 + recommandation×1 + Pass1×20 + Pass2×1 + Pass3×1 + summarize×≤11) — sur cette machine CPU sans GPU, ce volume soutenu fait dériver la latence par appel bien au-delà des ~4.2s mesurés isolément (`summarize_passage` est passé de 28.1s à 89.3s pour le même nombre d'appels — 3× plus lent en fin de chaîne qu'en isolation).

**Conséquence concrète, bug distinct trouvé** : `deep_synthesize` (Pass 3, `num_predict=450` depuis le fix de la veille) a dépassé le timeout par défaut de 60s (`_call_ollama`, `deep_analysis.py`) — 450 tokens à un débit dégradé (~7 tokens/s ou moins en fin de chaîne) frôle ou dépasse 60s. Le fix de troncature de la veille (augmenter `num_predict`) a mécaniquement augmenté le risque de timeout sans que le timeout soit remonté en conséquence. **Fix** : `run_pass3` passe maintenant `timeout=150` explicitement à `_call_ollama` (au lieu du défaut 60s partagé par toutes les passes).

**Ce qui reste vrai malgré tout** : le doublon de re-ranking éliminé est un gain garanti, indépendant du cache et de la charge Ollama (246.6s de travail CPU pur qui ne peut structurellement plus se reproduire). Le vrai facteur limitant sur cette machine n'est ni le thinking mode (absent), ni le doublon (corrigé), mais la dégradation de débit Ollama sous charge soutenue — **déjà identifiée en juillet, déjà mise en pause à l'époque, confirmée à nouveau aujourd'hui indépendamment**. Piste non explorée cette session (cohérent avec la décision de juillet) : `OLLAMA_NUM_PARALLEL`, réduire le nombre total d'appels séquentiels par analyse (ex: MAX_CHUNKS_PASS1 plus bas), ou tester sur le serveur de déploiement prévu (l'utilisateur prévoit de redéployer et retester — cette dégradation sous charge soutenue est plus probablement un facteur RAM/CPU de cette machine spécifique que du code, à confirmer une fois sur le serveur).

**Tests de non-régression après le fix de timeout** : `test.py --unit` 15/15, `--integ` 8/8.

---

## ✅ DIRECTIVE_CLAUDE_CODE_ESG_V3 — Jour 2 : sévérité + métriques (2026-08-06)

§1.2 de la directive ("ce que Stacy a demandé") : signaux visibles, colorés par flag, avec un niveau de sévérité. Audit avant de coder : la carte "Detected Signals" faisait déjà l'essentiel de ça depuis le Tier 1 des retours Elisa (2026-07-26) — groupement par flag, icône/couleur par sévérité, extraits dépliés. Pas de réécriture depuis zéro façon `st.expander` générique de la directive (aurait régressé la UX déjà validée). Deux vrais gaps identifiés et corrigés :

**1. Sévérité dynamique par signal** (déjà noté "Item E" dans checklist.md, non résolu jusqu'ici) : `SEVERITY_BY_FLAG` était une constante par flag (Flag1=high/Flag2=medium/Flag3=low) totalement indépendante du contenu réel — un flag3/compliance mentionné 20 fois dans un document restait "low" au même titre qu'une seule mention isolée. Nouvelle fonction `_group_severity()` (`app.py`) : escalade d'UN cran (jamais de désescalade) depuis la sévérité de base du flag si le document montre un volume de preuve conséquent pour ce flag (≥5 occurrences ET ≥2 thèmes distincts, pas juste le même mot-clé répété). Escalade seulement, jamais de descente — une mention isolée d'un thème grave ne doit pas être discrètement rétrogradée juste parce qu'elle n'apparaît qu'une fois. SEUIL choisi par jugement métier (comme `SEVERITY_BY_FLAG` lui-même), pas calibré statistiquement — à ajuster avec le retour réel de Stacy. Les groupes de signaux sont maintenant triés par sévérité décroissante (HIGH en premier) plutôt que par numéro de flag, cohérent avec l'objectif "voit immédiatement les signaux critiques sans cliquer".

**2. Métrique "Signaux détectés" en tête de page** : ajoutée dans la carte "Risk Assessment Summary" (entre le badge Grade/Score et le Risk Label), via `st.metric` avec delta "N critique(s)" en rouge si au moins un groupe est sévérité HIGH. Compte les CATÉGORIES de signaux distinctes détectées (`n_signal_types`), pas les occurrences brutes — cohérent avec le fix du jour précédent sur le libellé "occurrences" trompeur. Probabilité 12 mois volontairement PAS remontée en tête (décision déjà actée le 2026-07-26 : l'outil doit se lire comme un instrument d'alerte, pas d'abord un prédicteur de défaut — pas de raison de revenir dessus).

Vérifié en conditions réelles (Playwright) sur un texte synthétique conçu pour déclencher l'escalade (17 mentions de "compliance", 3 thèmes distincts — Esap delays/Biodiversity threat/PS non-conformance) : le groupe Structural Compliance Risk passe bien de 🔵 LOW à 🟡 MEDIUM, la métrique "Signaux détectés : 4" s'affiche correctement en tête. `test.py --unit` 15/15, `--integ` 8/8, aucune régression.

---

## ✅ Retour terrain — rapport CAO Mundra CGPL réel (2026-08-06)

Premier vrai document (pas un texte de test synthétique) passé dans l'app depuis le déploiement Tier 0/1. Trois bugs réels remontés par capture d'écran, tous vérifiés avant correction (pas juste appliqués sur confiance) :

**1. Table des matières traitée comme du contenu analytique** *[mesuré]* : `chunk_text()` (`scripts/search.py`) découpait aveuglément, y compris les pages de sommaire/liste de figures d'un PDF (lignes à leaders de points type `"Effort and Rate ... 156 Figure 29: ... 88"`). Conséquences observées : Pass 1 de `deep_analysis.py` détectait des "formulations évasives" sur des titres de section ("CAO's compliance function follows a three-step approach", "Conclusions on Fishing Community Impacts" — des HEADERS, pas du texte), et `_compute_document_specificity` (specificity_score) était gonflé à 91% par les numéros de page comptés comme marqueurs concrets.

Fix : nouvelle fonction `_is_boilerplate()` dans `search.py`, appelée dans `chunk_text()` en plus du filtre `min_words` déjà existant (3 heuristiques bon marché : ≥3 leaders de points, ratio de points >15%, diversité lexicale <25%). Comme `ingest.py` importe `chunk_text` directement depuis `search.py` (une seule implémentation, pas une copie séparée malgré un ancien commentaire qui le laissait penser — corrigé au passage), le fix s'applique automatiquement partout où `chunk_text()` est utilisé : `deep_analysis.py` (Pass 1/2), `search.get_flag_scores`/`search_similar` (scoring/pattern library), ET `app._compute_document_specificity` (spécificité du document affichée).

**Vérifié avant d'appliquer** (pas sur confiance) :
- Sur le corpus réel existant (4203 chunks) : 1.6% flaggés (66 chunks), 100% des chunks échantillonnés (10) confirmés comme du vrai bruit (leaders de sommaire ou glyphes de puces mal extraits du PDF) — 0 faux positif observé sur l'échantillon.
- Sur un texte synthétique TOC + contenu réel : les 2 fenêtres de table des matières sont bien exclues, seule la fenêtre de contenu analytique est retenue.

⚠️ **Ce qui n'est PAS corrigé par ce fix** : les 66 chunks de boilerplate déjà présents dans le corpus existant (`chunks.csv`/`embeddings.npy`/`faiss_index.bin`/`cox_model.pkl`) ne sont pas retirés rétroactivement — `ingest.py` ne retraite que les documents pas encore vus (dédup par `project_id`). Purger le corpus existant nécessiterait un ré-ingest complet (`chunks.csv` reconstruit de zéro) + `pipeline.py` (ré-embedding + FAISS + Cox, ~15-20 min, cf. repères techniques en bas de ce fichier) — pas fait ici, décision à prendre avec l'utilisateur (impact sur `cox_model.pkl`/les baselines Pattern Library, opération longue).

**2. Synthèse Pass 3 tronquée en plein milieu de phrase** *[mesuré, régression du Tier 0]* : le plafond `num_predict=200` posé sur `deep_synthesize` (config Ollama, Tier 0) coupait la synthèse avant la fin — observé texto : *"Ces lacunes rendent impossible une évaluation f"*. Cause : le prompt demande 3-5 phrases EN FRANÇAIS, plus coûteux en tokens que l'anglais pour un texte équivalent ; 200 était insuffisant. Remonté à 450 dans `config.OLLAMA_CONFIGS["deep_synthesize"]`. Revérifié avec un appel Pass 3 réel (findings similaires au cas Mundra, texte inédit pour éviter un hit de cache) : réponse de 914 caractères, se termine par une ponctuation finale — plus de troncature.

**3. Libellé "N occurrence(s)" trompeur** (`app.py`, carte Detected Signals) : `analyze._find_signals_in_document()` compte TOUTES les occurrences brutes d'un pattern regex dans le document entier (`pdf_text`, pas les chunks) — seule la PREMIÈRE occurrence de chaque signal est vérifiée par le LLM (`confirm_risk`), pas chacune individuellement (coût prohibitif : jusqu'à 158 appels pour un seul signal sur un document réel). Le nombre affiché n'est donc pas "158 signaux confirmés" mais "158 mentions du terme, dont la première a été jugée pertinente par l'IA" — la distinction n'était pas claire dans l'UI. **Diagnostic important** : ce n'est PAS corrigé par le fix boilerplate ci-dessus, parce que `_find_signals_in_document` travaille sur le texte brut du document, pas sur les chunks filtrés — une table des matières qui répète les mots "Community"/"Pollution"/"Compliance" comme titres de section continue de gonfler ce compteur.

Fix appliqué (le seul réaliste sans réintroduire le problème de perf du Tier 1 — vérifier CHAQUE occurrence par LLM coûterait autant que ce qu'on vient de plafonner) : libellé changé de "N occurrence(s)" à "N mention(s) du terme", avec un tooltip HTML (`title=`) explicite sur la limite (une seule occurrence vérifiée par IA, pas toutes).

⚠️ **Limite non résolue, documentée pour référence future** : le compteur brut reste gonflé par le bruit de table des matières côté `_find_signals_in_document` (contrairement à `flag_scores`/`specificity_score`, qui bénéficient du fix chunk_text ci-dessus). Un vrai fix nécessiterait soit de faire tourner `_find_signals_in_document` sur les chunks filtrés plutôt que sur `pdf_text` brut (perd la position exacte pour le surlignage, à repenser), soit de stripper les zones de type TOC du texte brut avant la détection de signaux — pas fait ici, hors périmètre d'un fix "libellé".

Vérifié : `test.py --unit` 15/15, `--integ` 8/8 (0 warning), `--business` 4/5 (0 échec, warning déjà connu).

---

## ✅ DIRECTIVE_CLAUDE_CODE_ESG_V3 — Tier 1 (2026-08-06)

Fix perf pour documents 45-70 pages (§1.1 de la directive).

**1. Plafond de 30 appels `confirm_risk` par analyse** (`scripts/search.py`, `get_flag_scores_from_chunks`) : sur un document de 100-200 chunks, le nombre de paires (chunk, flag topicalement matché par `signals.py`) pouvait monter à 50-100, chacune un appel LLM séquentiel (~2-4s) — 2 à 5 min sur un document réel. La fonction est restructurée : la recherche FAISS + re-ranking tourne maintenant AVANT le filtre LLM (au lieu d'après), ce qui permet de prioriser les paires (chunk, flag) par leur meilleur score FAISS/rerank déjà obtenu — les plus susceptibles de peser sur le `max()` final de `flag_scores` — plutôt que par ordre d'apparition dans le document. Seules les `MAX_CONFIRM_RISK_CALLS` (30) paires les mieux classées sont vérifiées par LLM ; le reste retombe sur le comportement pré-filtre (pas gated), cohérent avec le fail-open déjà appliqué partout ailleurs à ce filtre. Bonus : la recherche/rerank n'est plus recalculée une seconde fois après le filtre (était dupliquée avant ce chantier), donc moins de travail cross-encoder aussi.

Vérifié directement (pas seulement via les tests existants) : script de vérification avec `confirm_risk` mocké (compté, pas appelé) sur un texte synthétique de 76 chunks touchant les 3 flags — **30 appels exactement**, jamais plus, quel que soit le nombre de paires candidates (228 dans ce cas). `test.py --unit` 15/15, `--integ` 8/8 (0 warning cette fois, `analyze()` mesuré à 10.1s vs 60.4s avant — comparaison partiellement biaisée par le cache LLM déjà chaud sur ce texte de test précis depuis la vérification Tier 0, donc pas un chiffre à citer tel quel, mais cohérent avec l'attendu), `--business` 4/5 (0 échec, le seul warning est le manque de discrimination du grade déjà documenté §4 CORRECTIONS.md, pas une régression).

**2. `st.status()` autour de l'appel à `analyze()`** (`app.py`) : remplace le `st.spinner()` générique par un conteneur `st.status()` expansible, avec un vrai sous-état mesurable ("Extraction du texte..." → "✓ Texte extrait (N caractères)") suivi d'un message unique pour la partie scoring/signaux/LLM ("Analyse ESG en cours...") — PAS de fausse progression étape par étape à l'intérieur de `analyze()` : la fonction reste un seul appel bloquant (`analyze.py` n'est pas encore restructuré en étapes, §2.5 de la directive, pas fait ici), donc afficher des coches "✓ Scores calculés"/"✓ Signaux détectés" PENDANT l'appel aurait été un mensonge d'UI. À la fin, le statut se réduit avec un ✓ et le libellé "Analyse terminée" (`state="complete"`) ; en cas d'exception, `state="error"` avant de laisser `analyze_error` suivre son chemin existant vers `st.error()`.

Testé en conditions réelles (Playwright, chromium headless, app relancée sur le port 8502) : upload d'un `.txt`, capture pendant l'analyse (le conteneur expansé montre bien "Extraction du texte..." → "✓ Texte extrait (499 caractères)" → "Analyse ESG en cours...") et après (conteneur réduit, "✓ Analyse terminée", résultats affichés normalement en dessous — Deep Analysis, Flag Scores, Detected Signals). 0 erreur.

⚠️ **Pas fait** (hors périmètre Tier 1, dans les tiers suivants de la directive) : UI flags/sévérité/surlignage (§1.2), Docker/déploiement VPS (§1.3), pré-analyse des documents de Stacy (§1.4).

---

## ✅ DIRECTIVE_CLAUDE_CODE_ESG_V3 — Tier 0 (2026-08-06)

Suite à `SYNTHESE_AUDIT_PIPELINE.md` (confrontation de l'"autopsie par couches" au code réel) et `DIRECTIVE_CLAUDE_CODE_ESG_V3.md` (plan Phase 1 — déployer). Tier 0 = fixes gratuits, zéro risque, avant tout le reste.

**1. `@st.cache_resource` — vérifié, PAS ajouté** *[mesuré]* : la directive listait ça comme une hypothèse à vérifier dans `app.py`. En réalité, `app.py` n'appelle jamais `search.load_search_components()`/`load_cox_model()` directement — tout passe par `analyze()` → `analyze._ensure_loaded()`, qui charge déjà les modèles une seule fois par process via des variables globales au module (singleton), l'équivalent fonctionnel de `@st.cache_resource`. Empiler un vrai `@st.cache_resource` par-dessus aurait chargé les modèles en double sans bénéfice. Seul vrai trou trouvé : `_ensure_loaded()` n'était pas thread-safe (deux premières requêtes concurrentes pouvaient toutes les deux voir `_model is None` et charger en double) — corrigé avec un `threading.Lock` (`scripts/analyze.py`), pertinent pour le déploiement VPS multi-utilisateurs (§1.3 de la directive).

**2. Config Ollama** : nouveau `config.OLLAMA_CONFIGS` (num_predict/num_ctx par usage : confirm_risk=5/512, summarize=80/768, recommend=150/1024, deep_extract=100/1024, deep_synthesize=200/2048), branché dans `llm_confirm.py` (3 appels) et `deep_analysis.py` (Pass 1/3 seulement — voir écart ci-dessous). `"keep_alive": -1` ajouté à chaque requête (plutôt que la variable d'environnement `OLLAMA_KEEP_ALIVE` côté serveur suggérée par la directive — un paramètre par requête est plus portable, ne nécessite pas de redémarrer Ollama ni de config OS, et fonctionnera pareil une fois Ollama dans son propre container Docker, §1.3).
Températures déjà tunées par appel (confirm_risk=0 pour la déterminisme, summarize=0.2, recommend=0.3) **laissées inchangées** — la directive proposait d'autres valeurs mais sans les justifier, alors que celles en place sont documentées ; seuls num_predict/num_ctx (le vrai levier de perf) ont été touchés.

⚠️ **Écart volontaire par rapport à la directive** : Pass 2 de `deep_analysis.py` (détection d'omissions) est **exclue** du plafond `num_predict`. La directive proposait de la traiter comme "deep_extract" (100 tokens) au même titre que Pass 1. Mais `run_pass2()` ne fonctionne correctement que parce que le modèle qwen3:4b-instruct se répète plusieurs fois avant de conclure proprement (bug déjà documenté et corrigé le 2026-07-31, section Chantier 3 : jusqu'à 29 lignes pour 6 sujets, seul le DERNIER bloc de répétition est retenu). Plafonner à 100 tokens aurait tronqué la réponse avant cette dernière répétition et fait régresser un bug déjà corrigé. Pass 2 tourne donc sans plafond de longueur (comportement inchangé), seule l'URL Ollama configurable et `keep_alive` s'y appliquent.

**3. URL Ollama configurable** : `llm_confirm.py` codait `http://localhost:11434` en dur — bascule vers `config.OLLAMA_HOST` (lit `OLLAMA_HOST`, déjà utilisé par `deep_analysis.py`), nécessaire pour Docker (§1.3 de la directive, Ollama dans un autre container).

**4. `batch_size=64`/`normalize_embeddings=True`** *[mesuré, déjà fait pour moitié]* : `pipeline.py` les avait déjà (corpus complet). `search._encode_texts` (requête live) faisait une normalisation manuelle (`embeddings / np.linalg.norm(...)`), mathématiquement équivalente mais dupliquée — remplacée par `model.encode(texts, batch_size=64, normalize_embeddings=True)`, un seul appel.

**5. Code mort supprimé** *[mesuré]* : `scripts/embed.py` (confirmé mort par grep — aucun import nulle part, remplacé par `pipeline.py`). `scripts/explain.py` (SHAP) — confirmé mort dans le pipeline de prod (jamais importé par `app.py`/`analyze.py`, cohérent avec le retrait de SHAP du 2026-07-24 déjà noté dans ce journal) mais encore utilisé par un bloc de test isolé (`test.py`, section 2.3 "SHAP") qui testait `explain.py` directement, pas la sortie de `analyze()`. Supprimé avec son bloc de test associé (dead code cascadé, pas juste le fichier) et la dépendance `shap` retirée de `requirements.txt`. Message d'avertissement obsolète dans `test.py` ("réduire SHAP n_background") mis à jour pour pointer vers le vrai chantier perf actuel.

**Vérification** : `test.py --unit` 15/15 ✅. `test.py --integ` 7/8 ✅ (le seul warning est `analyze() < 45s`, actuellement 60.4s — attendu, c'est exactement le "Chantier ouvert" perf déjà documenté, pas une régression de ce Tier 0 ; Tier 1 de la directive s'y attaque via le plafonnement des appels `confirm_risk` à top-30 chunks).

**Pas encore fait** (Tier 1+ de la directive, pas dans le périmètre "gratuit") : plafonnement top-30 des appels `confirm_risk` dans `get_flag_scores_from_chunks`, barre de progression `st.status()`, UI flags/sévérité/surlignage, Docker/déploiement VPS.

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

⚠️ **Bug trouvé et corrigé en testant dans l'app réelle (2026-07-31)** : `run_pass2` (détection d'omissions) comptait chaque ligne non-vide de la réponse LLM comme une omission distincte, sans dédupliquer ni filtrer. Un 4B ne respecte pas toujours "un sujet par ligne, rien d'autre" — mesuré : jusqu'à **29 lignes en réponse pour 6 sujets possibles** (le modèle rappelle d'abord la liste complète des 6 sujets en écho du prompt, raisonne à voix haute, puis répète 2-3 fois une liste affinée avant de conclure). Résultat avant correction : 22 "omissions" comptées au lieu de 4 réelles, visible dans la colonne Portfolio Dashboard du Chantier 4. **Correction** : la réponse est découpée en blocs (séparés par ligne vide), seul le DERNIER bloc contenant au moins un sujet reconnu est retenu (mesuré : c'est systématiquement la répétition la plus propre), et chaque ligne n'est acceptée que si elle correspond à un des 6 sujets canoniques (`_CRITICAL_TOPICS`), jamais du texte libre. Validé après correction (même réponse en cache, sans re-solliciter Ollama) : 4 omissions correctes, la "consultation des parties prenantes" et le "mécanisme de plainte" exclus à raison (le modèle avait explicitement raisonné qu'ils étaient couverts).

## ✅ Chantier 4 — Refonte de l'affichage Streamlit (2026-07-31)

Nouvelles cartes dans Transaction Analysis, dans l'ordre demandé par le prompt V2 (avant tout score/grade) : 🧠 **Deep Analysis** (synthèse Pass 3 en langage naturel), 📋 **Findings** (tableau structuré Pass 1 + Pass 2, sévérité colorée, extraits source dépliables), 📐 **Document Specificity** (jauge, moyenne des `specificity_score` du document analysé comparée à la moyenne du corpus), 🕸️ **ESG Radar** (5 axes : 3 flag scores + spécificité + couverture ESG, plotly `Scatterpolar`, palette CA-CIB existante). La section "Evidence behind this score" (Flag Scores) affiche désormais `chunk_type`/`specificity_score` à côté de chaque passage cité — déjà portés par les candidats re-rankés du Chantier 2, aucun nouveau calcul. Portfolio Dashboard : colonnes Spécificité/Findings/Omissions ajoutées à la vue comparative, triables nativement (`st.dataframe`).

Nouvelle dépendance `plotly` (requirements.txt) — uniquement pour le radar chart, `st.plotly_chart` s'intègre nativement à Streamlit.

Testé en conditions réelles (Playwright, headless Chromium, `chromium-cli` indisponible sur cette machine → script Playwright direct) : app lancée sur le port 8502 (8501 potentiellement occupé, cf. piège déjà documenté plus bas), texte collé analysé de bout en bout, toutes les nouvelles cartes vérifiées visuellement (captures d'écran), 0 erreur console. `test.py --unit` 15/15 après les changements.

⚠️ **Piège rencontré en testant** : après avoir corrigé un bug dans `deep_analysis.py` (voir ci-dessus), le serveur Streamlit déjà lancé continuait de servir l'ANCIEN code — `import deep_analysis` n'est pas re-exécuté par le rechargement à chaud de Streamlit pour un module importé indirectement. Redémarrer le process Streamlit après toute modification d'un fichier dans `scripts/` (pas seulement `app.py`) avant de re-tester, sous peine de valider un correctif qui n'est en réalité jamais exécuté (même piège que celui déjà documenté plus bas sur le port 8501 fantôme).

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
