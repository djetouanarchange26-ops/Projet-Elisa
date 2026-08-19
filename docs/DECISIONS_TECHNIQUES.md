# Décisions techniques (ADR) — ESG Risk Intelligence

Choix d'architecture significatifs, pourquoi ils ont été pris, et ce qu'ils
excluent. Objectif : ne pas re-proposer une alternative déjà écartée sans
nouvelle information. Historique détaillé et mesures chiffrées dans
`checklist.md` — ce fichier ne garde que la décision et sa justification.

---

## ADR-001 — Re-ranking unique par analyse (`search.analyze_query`)

**Contexte** : `analyze()` avait besoin à la fois des `flag_scores` et des
`similar_passages` sur le même document — deux appels séparés
(`get_flag_scores` puis `search_similar`) recalculaient chacun tout le
retrieval/re-ranking sur les mêmes chunks.

**Décision** : une seule fonction (`analyze_chunks`/`analyze_query`) calcule
le re-ranking une fois et en dérive les deux résultats.

**Conséquence** : mesuré à ~46% du temps total d'`analyze()` gaspillé en
travail dupliqué sur un document réel de 171 chunks, avant fix. **Ne jamais
réintroduire deux appels séparés** — c'est l'invariant le plus explicitement
protégé du projet (répété dans `CLAUDE.md`, `COPILOT_CONTEXT.md`, et en
commentaire dans `search.py`).

---

## ADR-002 — Fail-open systématique pour tout appel LLM

**Contexte** : l'outil doit rester utilisable même si Ollama/le backend cloud
est injoignable — un déploiement local sans réseau, ou un service cloud en
panne, ne doit pas bloquer une analyse.

**Décision** : chaque appel LLM (`confirm_risk`, `summarize_passage`,
`generate_recommendation`, les 3 passes de `deep_analysis`) est enveloppé
d'un `try/except` qui retourne une valeur de repli sûre plutôt que de lever
une exception. Le repli est spécifique à l'usage (`confirm_risk` → `True`,
c'est-à-dire "ne pas filtrer" — comportement identique à avant l'ajout du
filtre).

**Conséquence** : aucun appel LLM individuel ne peut faire planter une
analyse. Limite connue : ce principe n'est pas encore étendu à la couche
cache disque qui entoure ces appels (`_load_cache()` sans `try/except`) —
chantier ouvert, pas encore traité.

---

## ADR-003 — Filtre de polarité LLM (`confirm_risk`) au-dessus du scoring FAISS

**Contexte** : un chunk qui mentionne un sujet à risque ("ESAP action plan")
matche les mêmes voisins FAISS qu'il décrive un problème ("shows delays") ou
une situation résolue ("completed ahead of schedule") — l'embedding capture
le sujet, pas la polarité. Vérifié en reproduisant l'écart avec deux modèles
d'embedding différents (pas une limite propre à un modèle).

**Décision** : pour chaque chunk où `signals.flags_mentioned_in_text()`
repère un flag candidat par mot-clé, un LLM local confirme si le passage
décrit vraiment un risque avant de le laisser contribuer au score.

**Conséquence** : coût en appels LLM proportionnel au nombre de chunks
candidats — voir ADR-004 pour le plafond qui en découle.

---

## ADR-004 — Plafond de 30 appels `confirm_risk` par analyse (`MAX_CONFIRM_RISK_CALLS`)

**Contexte** : un document de 45-70 pages (~100-200 chunks) où ~50 déclenchent
un match mots-clés ferait 50 appels LLM séquentiels (2-5 minutes) sans
plafond.

**Décision** : plafonner à 30 appels, priorisés par le meilleur score
FAISS/rerank déjà obtenu pour ce chunk sur ce flag (les paires les plus
susceptibles de peser sur le `max()` final, pas par ordre d'apparition dans
le document). Les paires sous le plafond retombent sur le comportement
pré-filtre (pas gated) — cohérent avec le fail-open déjà en place ailleurs.

**Limite connue** : ce plafond ne couvre que le scoring FAISS
(`search._gate_flags_with_llm`). Un deuxième site d'appel indépendant
(`analyze._find_signals_in_document`, jusqu'à 10 appels, un par catégorie de
`signals.py`) n'est pas comptabilisé par cette même constante.

---

## ADR-005 — Retrait du cross-encoder (`reranker.py`) — 2026-08-08

**Contexte** : le cross-encoder (`ms-marco-MiniLM-L-6-v2`) représentait ~90%
du temps CPU d'une analyse (5100+ paires chunk×candidat sur un document de
171 chunks), même après la migration vers un backend LLM cloud.

**Décision** : retiré du pipeline actif plutôt qu'optimisé. La pondération
par métadonnées (spécificité/récence/chunk_type) est conservée mais appliquée
directement sur le score FAISS brut (`search._weight_candidates`, logique
reprise de `reranker.rerank()` sans la composante cross-encoder).
`reranker.py` reste sur disque (code mort), non importé.

**Conséquence** : `config.RERANKER_ENABLED` a été retiré de `config.py` ;
`reranker.py` y fait toujours référence — référence orpheline inoffensive
tant que le module n'est pas réimporté (documenté dans `docs/CHANGELOG.md`).

---

## ADR-006 — Retrait du modèle Cox (`model.py`) — 2026-08-08

**Contexte** : le modèle Cox (entraîné sur 46 projets, 28 événements/18
contrôles) avait des coefficients flag2/flag3 non significatifs et un
décalage train/serve non résolu — fragile pour un usage en production.

**Décision** : remplacé par `model.compute_grade()`, une règle simple sur
`max(flag_scores)` vs seuils (`DEFAULT_RISK_THRESHOLDS`, valeurs initiales
15/35/60, **pas encore calibrées** — `calibrate_thresholds.py` existe mais
n'a pas encore été lancé en confirmation finale). Convention conservée : A =
pire (Escalade), D = meilleur (Vigilance), pour ne pas inverser la lecture du
grade pour Elisa/le Portfolio Dashboard.

**Conséquence** : `build_training_data()`/`train_cox()`/`predict_risk()`
conservés en code mort, toujours utilisés par 2 scripts de maintenance
(`calibrate_thresholds.py`, `compare_embeddings.py`) — pas totalement morts,
juste sortis du chemin `analyze()`.

---

## ADR-007 — Abstraction backend LLM Ollama/Together (`llm_backend.py`) — 2026-08-07

**Contexte** : Ollama en local sur CPU se dégrade sous charge soutenue
(~17 → <7 tok/s après ~50 appels séquentiels, cause non identifiée) et la
Pass 3 de `deep_analysis` timeoutait régulièrement — bloquant pour une démo
live devant la banque.

**Décision** : une couche d'abstraction (`call_llm()`) route vers Ollama
(par défaut, comportement inchangé) ou Together AI (cloud, opt-in via
`LLM_BACKEND=together`), avec fallback automatique si le backend principal
échoue (`LLM_FALLBACK`, défaut `ollama`). Défaut conservé sur `ollama` pour
ne rien changer aux déploiements existants sans configuration explicite.

**Conséquence** : envoyer des documents à Together signifie qu'ils quittent
la machine locale — acceptable pour le corpus IFC/CAO public, **pas** pour
des documents bancaires confidentiels sans validation explicite (avertissement
répété dans `.env.example`).

**Piège corrigé au passage** : Qwen3 (y compris la variante "9B" sans badge
"deep thinking" sur Together) raisonne par défaut, produisant des réponses
vides pour les appels à `max_tokens` court (`confirm_risk`) — corrigé par
`chat_template_kwargs.enable_thinking=False`, appliqué seulement si "qwen"
est dans le nom du modèle.

---

## ADR-008 — Modèle d'embedding : all-mpnet-base-v2 (pas all-MiniLM-L6-v2)

**Contexte** : bascule effectuée sans confirmation chiffrée complète que ça
règle le problème de différenciation sur texte externe (comparatif interrompu
volontairement, cf. `checklist.md`).

**Décision** : `all-mpnet-base-v2` (768 dim), plus précis mais plus lent à
l'entraînement que MiniLM (384 dim) — l'inférence live reste quasi
instantanée. Fenêtre de troncature du modèle (~260-280 mots) suffisamment
large pour les chunks de 175 mots utilisés par le projet.

**Statut** : décision active mais pas définitivement validée — un modèle
fine-tuné sur du texte ESG/finance reste une alternative envisagée, pas
explorée.

---

## ADR-009 — Escalade de sévérité uniquement, jamais de désescalade (`app._group_severity`)

**Contexte** : la sévérité par flag était figée (`SEVERITY_BY_FLAG`),
indépendante du volume réel de preuve dans le document analysé — un flag3
mentionné 20 fois restait "low" au même titre qu'une seule mention.

**Décision** : escalade d'un cran depuis la sévérité de base du flag si le
document montre un volume de preuve conséquent (≥5 occurrences ET ≥2 thèmes
distincts) — jamais de descente. Une mention isolée d'un thème grave (ex.
"child labor") ne doit jamais être rétrogradée silencieusement.

**Justification métier** : mieux vaut sur-alerter que sous-alerter sur un
outil d'aide à la décision crédit. Seuil (5 occurrences / 2 thèmes) est un
jugement métier non calibré statistiquement, à ajuster avec le retour
d'Elisa.

---

## ADR-010 — Caddy en reverse-proxy, pas d'exposition directe du port Streamlit

**Contexte** : l'app exposée directement (port 8501) sans authentification a
été jugée insuffisante pour un usage réel (`checklist.md`, 2026-08-06).

**Décision** : `docker-compose.yml` ne publie plus `8501` sur `app` — seul
`caddy` (basic auth, ports 80/443) est exposé, et atteint `app` via le réseau
Docker interne. `ollama` n'est jamais exposé au host.

**Limite connue** : Caddy sert encore en HTTP simple (`:80`), pas de domaine
DNS configuré pour activer HTTPS via Let's Encrypt — les identifiants Basic
Auth transitent en clair tant que ce n'est pas branché. Port 443 déjà exposé
pour ne pas avoir à retoucher ce fichier le jour où un domaine sera
disponible.
