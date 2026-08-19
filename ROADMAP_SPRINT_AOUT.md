# Roadmap Sprint Août — ESG Risk Intelligence

Date : 6 août 2026
Présentation : 25 août 2026
Objectif : déployer pour Elisa, se mettre à niveau, poser la pipeline

---

## ÉTAT RÉEL DU PROJET (résumé du journal de bord)

Ce qui marche :
- App Streamlit complète, 4 onglets branchés sur de vraies données
- Pipeline bout en bout : PDF → chunking → embedding (mpnet) →
  FAISS → re-ranker cross-encoder → LLM multi-pass (qwen3:4b-instruct)
  → Cox scoring → UI avec flags/sévérité/exports
- 46 projets, 4203 chunks, C-index 0.746
- Exports PDF/Excel, multi-documents, traçabilité des preuves
- Deep analysis 3 passes (extraction, omissions, synthèse)
- Fail-open partout, cache disque LLM, tests unit/integ/business

Ce qui bloque :
- Elisa ne peut pas accéder à l'outil (tunnel Cloudflare = pis-aller)
- Perf : ~18 min par analyse à froid sur ta machine (CPU, pas de GPU)
  → doublon re-ranking corrigé mais dégradation Ollama sous charge
  soutenue non résolue
- Docker spécifié (V3.1) mais pas encore déployé
- Cox pas ré-entraîné sur les scores filtrés LLM
- Pass 3 deep_analysis timeout sous charge

Ce que tu ne comprends pas encore assez bien :
- Pourquoi le code est structuré comme ça (tu as délégué à Claude Code)
- Les choix de modèles (pourquoi mpnet, pourquoi Cox, pourquoi FAISS
  IVF vs Flat)
- Comment debugger quand quelque chose casse

---

## SEMAINE 1 (6-10 août) — DÉPLOYER + SE METTRE À NIVEAU

Le principe : deux rails en parallèle. Le matin tu déploies (actions
concrètes, Claude Code exécute). L'après-midi tu apprends (sessions
avec Claude Chat, pas de code).

### JOUR 1 (jeudi 7 août) — Déploiement

**Matin : Docker local → VPS**

Directive à donner à Claude Code (copier tel quel) :

```
Contexte : le journal de bord (checklist.md) documente tout l'état
du projet. Le Dockerfile et docker-compose.yml de la directive V3.1
ne sont pas encore créés.

Tâche :
1. Crée Dockerfile, docker-compose.yml, .dockerignore, et
   scripts/docker_init.sh exactement comme spécifié dans la
   directive V3.1 (section "Chantier Docker")
2. Ajoute le warmup Ollama dans app.py (la fonction existe déjà
   dans la directive, l'appeler au démarrage avant le rendu Streamlit)
3. Vérifie que OLLAMA_HOST est bien lu depuis l'environnement
   partout (llm_confirm.py migré vers config.OLLAMA_HOST — fait
   au Tier 0, confirmer que deep_analysis.py aussi)
4. Teste `docker compose up -d` en local
5. NE TOUCHE À RIEN D'AUTRE

Ce qu'il ne faut PAS faire :
- Modifier le pipeline d'analyse
- Changer de modèle
- Toucher à l'UI
- Ajouter des features
```

Une fois Docker qui tourne en local, déploie sur le VPS :

```bash
# Sur le VPS (Ubuntu, 8 Go RAM minimum)
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
git clone <ton-repo> && cd esg-risk-intelligence
docker compose up -d
bash scripts/docker_init.sh
# Vérifier :
docker compose ps          # 2 containers running/healthy
curl http://localhost:8501  # Streamlit répond
docker exec esg-ollama ollama list  # qwen3:4b-instruct listé
```

Donne l'URL (IP:8501) à Elisa. C'est tout pour le déploiement Jour 1.

**Après-midi : session théorique #1 — Le pipeline bout en bout**

Viens ici (Claude Chat) et dis :
"Explique-moi le pipeline complet de mon outil ESG, étape par étape,
en me disant POURQUOI chaque étape existe et ce qui se passe si on
la retire."

Ce que tu dois savoir répondre après cette session :
- Pourquoi on ne peut pas juste faire "ctrl+F" dans un PDF au lieu
  de tout ce pipeline ?
- Qu'est-ce que l'embedding apporte que la recherche par mots-clés
  ne fait pas ?
- Pourquoi FAISS seul ne suffit pas (d'où le re-ranker) ?
- Pourquoi le LLM seul ne suffit pas (d'où FAISS + LLM ensemble) ?

Écris tes réponses dans `docs/notes_theoriques.md`, section
"Pipeline — pourquoi chaque brique".

---

### JOUR 2 (vendredi 8 août) — Premier test Elisa + Embedding & FAISS

**Matin : accompagner Elisa sur son premier test**

Appelle-la ou envoie-lui un message avec :
- L'URL de l'outil
- Un document de test qu'elle connaît bien (un des Mundra ou un
  qu'elle a déjà analysé manuellement)
- La consigne : "Analyse ce document, regarde les flags détectés,
  la sévérité, les preuves, la deep analysis. Note tout ce qui te
  semble faux, manquant, ou mal présenté."

Prépare le Google Sheet de feedback :

| Document | Ce qui est bien | Flag manqué | Flag faux | Sévérité incorrecte | UI confuse | Commentaire |
|----------|----------------|-------------|-----------|---------------------|------------|-------------|

Elle remplit, toi tu lis.

Si le déploiement a échoué hier, c'est le matin pour debug avec
Claude Code. Pas d'autre feature — juste que l'app soit accessible.

**Après-midi : session théorique #2 — Embeddings et FAISS**

Viens ici et dis :
"Explique-moi les embeddings et FAISS dans le contexte de mon
projet ESG. Mon modèle est all-mpnet-base-v2, 768 dimensions,
et j'utilise IndexFlatL2."

Ce que tu dois savoir répondre après cette session :
- Si Elisa demande "pourquoi l'outil a trouvé CE passage et pas
  un autre ?", tu sais expliquer
- La différence entre similarité cosinus et euclidienne, et
  laquelle tu utilises (et pourquoi)
- Pourquoi mpnet plutôt que MiniLM (et pourquoi ça n'a finalement
  pas été le vrai problème de différenciation)
- Ce que fait le cross-encoder de re-ranking et pourquoi le score
  composite (0.5×cross-encoder + 0.2×specificity + 0.2×récence +
  0.1×chunk_type) est structuré comme ça

Écris dans `docs/notes_theoriques.md`, section "Embeddings & FAISS".

---

### JOUR 3 (lundi 11 août) — Modèle de Cox + premiers retours Elisa

**Matin : session théorique #3 — Le modèle de Cox**

Viens ici et dis :
"Explique-moi le modèle de Cox de mon projet ESG. J'ai 46 projets
(28 événements, 18 contrôles), un C-index de 0.746, et les
covariables sont les flag_scores filtrés par LLM."

Ce que tu dois savoir répondre après cette session :
- Ce que signifie "probabilité d'événement à 12 mois" et comment
  elle est calculée
- Pourquoi 46 projets c'est peu et ce que ça implique (pas de
  Random Survival Forest, pas de fine-tuning embedding)
- Ce que veut dire "flag1_community significatif à p<0.005" et
  pourquoi c'est important
- Pourquoi le Cox n'est pas encore ré-entraîné sur les scores
  filtrés LLM (et ce que ça change en pratique)
- Ce que tu répondrais si quelqu'un demande "votre modèle est
  fiable à combien de % ?" (C-index, calibration, limites)

Écris dans `docs/notes_theoriques.md`, section "Modèle de Cox".

**Après-midi : traiter les premiers retours d'Elisa**

Elle aura eu le week-end pour tester. Lis le Google Sheet.
Classe ses retours en 3 catégories :

1. BUG — l'outil plante ou affiche quelque chose de faux
   → Directive immédiate pour Claude Code, fix et redéploiement
2. UX — l'info est là mais mal présentée ou difficile à trouver
   → Note, on traitera en semaine 2
3. FEATURE — elle veut quelque chose qui n'existe pas encore
   → Note, on priorisera après la présentation du 25

Viens ici avec les retours, on trie ensemble et on écrit les
directives pour Claude Code.

---

### JOUR 4 (mardi 12 août) — LLM + Architecture du code

**Matin : session théorique #4 — Le LLM et le pipeline multi-pass**

Viens ici et dis :
"Explique-moi comment le LLM est utilisé dans mon projet ESG.
J'ai qwen3:4b-instruct via Ollama, avec confirm_risk, deep_analysis
(3 passes), summarize_passage, et generate_recommendation."

Ce que tu dois savoir répondre après cette session :
- Pourquoi qwen3:4b-instruct et pas qwen3:4b (le bug du thinking
  mode que tu as déjà vécu)
- Pourquoi 4B et pas 7B ou 13B (trade-off RAM/qualité sur ta machine)
- Ce que fait chaque pass de deep_analysis et pourquoi cet ordre
- Pourquoi le LLM ne remplace pas FAISS (et vice versa)
- Le problème de dégradation Ollama sous charge soutenue — ce que
  tu sais, ce que tu ne sais pas, et ce que tu dirais à la banque

Écris dans `docs/notes_theoriques.md`, section "LLM & pipeline
multi-pass".

**Après-midi : audit de l'architecture du code**

C'est le moment de créer `docs/ARCHITECTURE.md`. Ouvre chaque
fichier du projet et écris sa fiche (rôle, entrées, sorties,
dépendances, décisions clés). Pas besoin de tout comprendre
ligne par ligne — juste le QUOI et le POURQUOI de chaque module.

Ordre de lecture recommandé (du plus simple au plus complexe) :

```
1. config.py          → constantes, feature flags, configs Ollama
2. signals.py         → mots-clés ESG, source unique de vérité
3. ingest.py          → PDF → chunks.csv
4. chunk_metadata.py  → métadonnées enrichies des chunks
5. pipeline.py        → embed + FAISS + Cox (tout le training)
6. search.py          → requête → chunks pertinents (FAISS + rerank)
7. reranker.py        → cross-encoder, score composite
8. llm_confirm.py     → filtre de polarité LLM
9. deep_analysis.py   → les 3 passes d'analyse profonde
10. analyze.py        → orchestrateur (appelle tout le reste)
11. model.py          → Cox model, prédiction
12. export.py         → PDF/Excel
13. app.py            → UI Streamlit (le plus gros fichier)
```

Si tu bloques sur un fichier, viens ici avec le fichier et je
t'explique. Ou demande à Claude Code :
"Explique-moi le rôle de ce module, ses entrées/sorties, et
pourquoi il est structuré comme ça. Ne modifie rien."

---

## SEMAINE 2 (13-17 août) — PIPELINE DE DEV + ITÉRATIONS

Tu as maintenant la compréhension théorique ET l'outil déployé.
Elisa a testé et donné du feedback. On passe en mode structuré.

### JOUR 5 (mercredi 13 août) — Mettre en place la pipeline

**Matin : structure du repo**

Directive Claude Code :

```
Tâche : restructurer le repo pour le développement structuré.
Ne modifie AUCUNE logique, seulement l'organisation.

1. Crée docs/ARCHITECTURE.md (je fournis le contenu)
2. Crée docs/CHANGELOG.md avec l'historique des versions
3. Vérifie que logs/ existe avec le logger centralisé
   (utils/logger.py) — si pas de logger centralisé, en créer un
   qui utilise le module logging de Python (PAS des print)
4. Crée un Makefile ou un script run.sh avec les commandes
   courantes :
   - make test → pytest tests/ -v
   - make test-quality → python -m scripts.test_quality
   - make deploy → docker compose up -d --build
   - make logs → tail -f logs/$(date +%Y-%m-%d).log
5. Remplace TOUS les print() du codebase par des appels logger
   (INFO pour les messages normaux, WARNING pour les fallbacks,
   DEBUG pour les détails techniques)
6. NE TOUCHE À RIEN D'AUTRE
```

**Après-midi : fichier de traçabilité par analyse**

Directive Claude Code :

```
Tâche : ajouter un fichier de trace JSON par analyse dans
logs/traces/.

Dans analyze.py, après le return de analyze(), sauvegarder un
JSON avec :
- timestamp
- document name (ou "pasted text")
- pipeline version (lire depuis un __version__ dans config.py)
- chunking stats (n_chunks, avg_size)
- retrieval stats (faiss_top_k, reranked_top_k, top_score)
- llm stats (model, nombre d'appels par type, tokens estimés,
  temps total)
- flags détectés (flag, severity, confidence)
- cox score et hazard ratio
- deep_analysis summary (passes exécutées, passes en échec)

Format : logs/traces/{date}T{heure}_{doc_name_safe}.json
Ne pas bloquer l'analyse si l'écriture de la trace échoue
(try/except, log un warning).
```

---

### JOUR 6 (jeudi 14 août) — Tests gold standard

**Matin : construire le corpus de tests de qualité**

Avec les retours d'Elisa + tes propres tests, construis le
fichier de ground truth :

```python
# tests/gold_standard.py

CASES = [
    {
        "name": "Mundra CGPL - risque community connu",
        "file": "fixtures/mundra_sample.txt",
        "expected_flags": ["flag1_community"],
        "expected_min_severity": {"flag1_community": "HIGH"},
        "must_detect_signals": ["community_opposition",
                                 "displacement_risk"],
        "expected_grade_range": ["C", "D"],
    },
    {
        "name": "Projet propre IFC - pas de risque",
        "file": "fixtures/clean_project_sample.txt",
        "expected_flags": [],
        "expected_grade_range": ["A", "B"],
    },
    # Ajouter les cas d'Elisa ici au fur et à mesure
]
```

Directive Claude Code :

```
Tâche : créer tests/test_gold_standard.py qui :
1. Lit CASES depuis tests/gold_standard.py
2. Pour chaque cas, lance analyze() sur le fichier
3. Vérifie :
   - Les flags attendus sont détectés
   - Les flags non-attendus ne sont PAS détectés
   - La sévérité minimale est respectée
   - Le grade est dans la fourchette attendue
4. Produit un rapport : cas passés, cas échoués, détail
5. pytest-compatible (chaque cas = un test paramétré)

Ne modifie PAS analyze.py ni aucun autre fichier.
Mets les fixtures de test dans tests/fixtures/.
```

**Après-midi : itération sur les retours d'Elisa (bugs)**

Prends les retours de catégorie 1 (BUG) du Google Sheet.
Pour chaque bug :
1. Viens ici, décris le bug
2. On diagnostique ensemble (est-ce le retrieval ? le LLM ?
   le Cox ? l'UI ?)
3. On écrit une directive précise pour Claude Code
4. Claude Code corrige
5. Tu vérifies le fix avec `pytest` + test manuel
6. Tu redéploies (`docker compose up -d --build`)
7. Tu préviens Elisa que c'est corrigé

---

### JOUR 7 (vendredi 15 août) — Itération UX + perf serveur

**Matin : retours UX d'Elisa**

Prends les retours de catégorie 2 (UX). Viens ici, on priorise :
- Qu'est-ce qui gêne le plus son travail quotidien ?
- Qu'est-ce qui se corrige en < 1h de travail Claude Code ?

On écrit les directives, Claude Code implémente, tu redéploies.

**Après-midi : mesurer la perf sur le VPS**

Le problème de dégradation Ollama sous charge est peut-être
spécifique à ta machine. Teste sur le VPS :

```bash
# Sur le VPS, dans le container app
docker exec -it esg-app python -c "
import time
from scripts.analyze import analyze

# Document de test (même que l'audit perf du 6 août)
with open('corpus/CAO_Serbia_Morava_sample.txt') as f:
    text = f.read()

start = time.time()
result = analyze(text)
elapsed = time.time() - start
print(f'Temps total: {elapsed:.1f}s')
print(f'Grade: {result[\"risk_grade\"]}')
print(f'Flags: {result[\"flag_scores\"]}')
"
```

Si le VPS est nettement plus rapide (RAM, CPU différent),
le problème est bien machine-spécifique. Si c'est pareil,
on sait que c'est Ollama sous charge séquentielle et il
faudra réduire le nombre d'appels (baisser MAX_CHUNKS_PASS1,
batching, ou accepter la latence).

Note le résultat dans le journal de bord.

---

### JOURS 8-9 (18-19 août) — Polish pré-présentation

**Lundi 18 : deuxième vague de retours Elisa + fixes**

Même cycle que Jour 6 : trier les retours, diagnostiquer,
directives Claude Code, fix, redéployer, vérifier.

**Mardi 19 : préparer la démo du 25**

Viens ici et dis : "Aide-moi à préparer la présentation du 25
août. Voici ce que l'outil fait, voici les retours d'Elisa,
voici les limites connues."

On prépare ensemble :
- Le scénario de démo (quel document, dans quel ordre)
- Les points forts à mettre en avant
- Les questions difficiles anticipées et tes réponses
- Le pitch "voilà ce qu'on fait avec un 4B sur un laptop,
  imaginez avec votre infra"

---

## RÉSUMÉ VISUEL

```
SEMAINE 1 — Déployer + Apprendre
╔══════════════╦═══════════════════════════════════════╗
║              ║  MATIN            APRÈS-MIDI          ║
╠══════════════╬═══════════════════════════════════════╣
║ Jour 1 (J7)  ║  Docker + VPS     Théorie: Pipeline   ║
║ Jour 2 (V8)  ║  Test Elisa #1    Théorie: Embedding  ║
║ Jour 3 (L11) ║  Théorie: Cox     Retours Elisa #1    ║
║ Jour 4 (M12) ║  Théorie: LLM     Audit architecture  ║
╚══════════════╩═══════════════════════════════════════╝

SEMAINE 2 — Pipeline + Itérations
╔══════════════╦═══════════════════════════════════════╗
║              ║  MATIN            APRÈS-MIDI          ║
╠══════════════╬═══════════════════════════════════════╣
║ Jour 5 (Me13)║  Structure repo   Traces JSON         ║
║ Jour 6 (J14) ║  Tests gold std   Fix bugs Elisa      ║
║ Jour 7 (V15) ║  Fix UX Elisa     Perf sur VPS        ║
║ Jour 8 (L18) ║  Retours Elisa #2 + fixes             ║
║ Jour 9 (M19) ║  Préparation démo du 25 août          ║
╚══════════════╩═══════════════════════════════════════╝

25 AOÛT — PRÉSENTATION
```

---

## RÈGLES PENDANT CE SPRINT

1. **Aucune nouvelle feature.** Zéro. Pas de Q&A RAG, pas de
   multilingue, pas de nouveau modèle. On déploie, on stabilise,
   on comprend ce qui existe.

2. **Claude Code ne touche au code que sur directive écrite.**
   Pas de "fais ce que tu veux pour améliorer". Chaque directive
   dit quels fichiers modifier, quel comportement attendu, et
   quels tests vérifier.

3. **Chaque modification = redéploiement + test Elisa.** Si elle
   ne voit pas le changement, il n'existe pas.

4. **Les sessions théoriques ne sont pas optionnelles.** C'est ce
   qui te permet de défendre l'outil le 25. Si tu ne fais que le
   code, tu arriveras en démo sans pouvoir répondre à "pourquoi
   vous avez choisi ce modèle ?"

5. **Le journal de bord continue.** Chaque jour, 5 lignes max :
   ce qui a été fait, ce qui a bloqué, ce qui change demain.

---

## CE QU'ON NE FAIT PAS PENDANT CE SPRINT

- Ré-entraîner le Cox sur les scores filtrés LLM (pas bloquant
  pour la démo, le filtre fonctionne déjà en inférence)
- Résoudre la dégradation Ollama sous charge (on la mesure sur
  le VPS, c'est tout — le fix viendra après la présentation)
- Enrichir le corpus (pas le moment d'ajouter des projets)
- Changer de modèle LLM ou d'embedding
- Ajouter des features demandées par Elisa qui ne sont pas des
  bugs ou des corrections UX critiques

Tout ça est légitime et planifié — mais APRÈS le 25 août.
