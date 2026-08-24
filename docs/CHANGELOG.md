# Changelog

## 2026-08-24 — Suppression d'analyse, désactivation Pattern Library/Settings, annexe méthodologique, reformulation R5

**Portfolio Dashboard — suppression d'une analyse sauvegardée** :
`scripts/analysis_store.py::delete_analysis()` (fail-open, même style que
`save_analysis`/`load_analysis`) + modal de confirmation native
(`@st.dialog`, `app.py`) sur la page Portfolio Dashboard (pipeline V4
uniquement — historique de session du pipeline legacy non concerné,
comme pour la persistance elle-même). Irréversible, "Annuler"/"Supprimer"
explicites, rafraîchissement automatique de la liste après suppression
(`st.rerun()`), sans toucher l'aperçu chargé sauf si c'est justement
l'analyse supprimée.

**Pattern Library et Settings retirés de la navigation** : Elisa n'utilise
ni l'une ni l'autre (confirmé par Archange). `_nav_sections` réduit à
Transaction Analysis / Portfolio Dashboard dans `app.py`. Les blocs
`elif page == "📚 Pattern Library":` / `elif page == "⚙️ Settings":`
restent dans le code (convention CODE MORT — jamais de suppression
silencieuse), désormais inatteignables. Settings ne pilotait de toute
façon que les seuils de grade A/B/C/D du pipeline legacy (`risk_
thresholds`), sans aucun effet sur le pipeline V4 par défaut.

**Reformulation de l'explication B.3.1/B.3.2 (silence = risque)** :
`scripts/grid_analyze.py::_SILENCE_CONFIRMS_ABSENCE_NOTE` renvoyait à
"(cf. règle R5)", un code de règle interne incompréhensible côté métier
(retour direct : "les gars ne savent pas ce que ça signifie cette
phrase"). Remplacé par une explication en clair du mécanisme (pourquoi
CE silence précis pénalise, contrairement aux autres questions où rien
trouvé ne pénalise pas) — source unique, propagée automatiquement au
résumé UI, au détail de la grille, au PDF et à l'Excel.

**Annexe méthodologique statique dans les exports PDF/Excel** :
`scripts/export.py::_METHODOLOGY_CONTENT` (constante unique, réutilisée
par `build_grid_v4_pdf` et `build_grid_v4_excel`) — barème de scoring
(dont les 4 seuils de verdict VERT≥75/JAUNE 50-74/ORANGE 25-49/ROUGE<25),
règle du silence par type de question, critères de validation de la
mitigation (filtres temporel + preuve, cas OUI-défaillante sans gain),
limites de l'analyse. Contenu identique pour tous les dossiers — objectif
auditabilité (CHOIX documenté dans `export.py`). PDF : nouvelle dernière
page. Excel : nouvelle feuille "Methodologie" après "Detail" (le classeur
passe donc de 3 à 4 feuilles).

**Tests** : `python scripts/test.py --unit --integ --business` —
466/466 passés (mise à jour d'une assertion préexistante qui vérifiait
encore l'ancien nombre de feuilles Excel, et ajout de nouvelles
assertions ciblées sur l'annexe méthodologique et la reformulation R5).

## 2026-08-19 — Restauration Maquette Vierge (12 questions) + R2 conditionnelle + 4 champs manuels (directive CC-V4-11)

**Contexte** : 3 dossiers testés, 3 scores faux (CBG 85 au lieu de 28-31,
Mundra 0 au lieu de 16, Aysha 85 au lieu de 73). Deux causes racines
identifiées : (1) les 12 questions du code V4 précédent (A.1.1, A.1.3,
A.2.1, A.3.1, A.4.1, B.1.1, B.1.2, B.2.1, B.2.2, B.2.3, B.3.1, B.4.1)
n'étaient pas celles de la Maquette Vierge (référence : `1_Maquette_
Vierge_Grille_ESG (1).pdf`) — 4 codes n'existaient pas dans le document
source (A.1.3, A.4.1, B.2.3, B.4.1) et 4 questions réelles manquaient
(A.1.2, A.2.2, A.3.2, B.3.2) ; (2) R2 (matérialisation) était appliquée de
façon trop stricte sur les documents Type 1 (due diligence), traitant des
constats d'ESRS comme des "vulnérabilités futures".

**BLOC A — `scripts/grid_questions.py`** : QUESTIONS entièrement
remplacée par les 12 codes exacts de la Maquette Vierge (vérifiés page par
page contre le PDF), 6 Cat A / 6 Cat B (au lieu de 5/7), formulations R/A
reprises mot pour mot. **B.3.1 passe en polarité STANDARD** (`inverted_
polarity=False`, `a_condition="r_oui"`) — la Maquette Vierge formate
B.3.1 ("Absence de données de référence baseline socio-économiques ?")
exactement comme les 11 autres questions, contrairement à l'ancien B.3.1
(biodiversité, inversé). `shared_cap_group` n'est plus porté par aucune
question (A.1.1/A.1.3 fusionnées en un seul A.1.1) — le mécanisme de
plafond partagé (`grid_scoring._apply_shared_cap`) reste en place,
dormant, pas supprimé (convention code mort). `na_module="B.2"` réduit à
2 questions (B.2.1/B.2.2) au lieu de 3.

**BLOC B — `scripts/grid_prompts.py`** : R2 devient conditionnelle au
`reading_mode` (nouveau : `_MATERIALISATION_INSTRUCTION` vs `_SUIVI`) —
un constat documenté (état existant, legacy issue, écart relevé) déclenche
OUI en mode instruction (Type 1/2), la règle stricte (fait daté survenu,
attribué au SPV) reste pour le mode suivi (Type 3/4). Few-shot entièrement
reconstruit pour les 12 nouveaux codes (voir docstring `_FEW_SHOT_
EXAMPLES` pour le détail du remappage — notamment l'exemple Indorama
airshed/WHO limits, fourni par la directive sous l'étiquette "B.2.2", en
réalité replacé sous B.2.1/Air puisque B.2.2 porte désormais sur l'Eau).
`_B31_PROMPT_TEMPLATE` et `_ARTICULATION_B23_B41` (R2bis) deviennent CODE
MORT DORMANT (plus jamais atteints), conservés.

**BLOC C — vérification** : la logique R7 (deux portes + garde-fou
statut 4 exigeant double verbatim, y compris rejet explicite d'une simple
conjonction concessive isolée) était déjà correctement encodée dans le
prompt — aucun changement de code nécessaire.

**BLOC D — 4 champs manuels obligatoires** : `app.py` (sidebar,
bloquants avant "Run Analysis"), `grid_result.build_grid_result()` /
`grid_analyze.analyze_grid()` / `analyze_grid_auto()` / `pipeline_
dispatch.run_active_pipeline()` (nouveau paramètre `context`, pass-through
jusqu'au résultat), `export.py` (affichés en en-tête PDF/Excel, avant le
score).

**PENDING_ELISA (non résolu)** : `scripts/test.py::_mundra_answers_v4` —
avec les 12 codes Maquette Vierge, les réponses Mundra données par la
directive elle-même (BLOC A §3) calculent 29/ORANGE, pas 16/ROUGE comme
visé ailleurs dans la directive. L'écart correspond à l'ancien B.4.1
(irritations cutanées liées au rejet de la centrale, fait réel du dossier
CGPL/Tata Mundra) qui n'a plus de question d'accueil évidente dans les 12
codes actuels. Décision requise : où reloger ce fait (B.1.1 ? B.2.2 ?
aucune question ?) avant de pouvoir recalibrer sur 16. Cf. `AUDIT_
PERTINENCE_NOTE_CADRAGE.md` pour l'audit complet (Aysha=61 vs 73, A.1.1
≠ opposition communautaire dans le code, etc.).

**Tests** : `python scripts/test.py --unit --integ --business` —
364/364 passés.

## 2026-08-08 — Simplification du pipeline : retrait Cox + cross-encoder

**Contexte** : même après la migration LLM (Together), une analyse restait à
194% CPU pendant plusieurs minutes sur un document réel (Mundra CGPL) — pas
du fallback Ollama (0% CPU côté `esg-ollama`), mais le cross-encoder
(`reranker.py`, ~90% du temps CPU estimé : 5100+ paires chunk×candidat sur
un document de 171 chunks) et un modèle Cox fragile (46 projets,
coefficients flag2/flag3 non significatifs, décalage train/serve non
résolu). Décision : les retirer tous les deux plutôt que les optimiser.
Exception explicite au sprint (roadmap : "pas de fix perf avant le 25 août"),
étendue au-delà de la seule exception LLM déjà accordée — voir memory
`feedback_prioritize_features_over_perf`.

**Changements** :
- `scripts/reranker.py` : plus importé nulle part (reste sur disque tel
  quel, avec un bug latent inoffensif : `config.RERANKER_ENABLED`
  n'existe plus — ne se déclenche jamais puisque le module n'est plus
  appelé).
- `scripts/search.py` : `_rerank_all_chunks()` ne passe plus par le
  cross-encoder — nouvelle fonction `_weight_candidates()` (logique
  reprise de `reranker.rerank()`, spécificité/récence/chunk_type
  conservées) pondère directement le score FAISS brut
  (`ALPHA_FAISS=0.5` remplace `ALPHA_CROSS_ENCODER`). Le pool FAISS
  revient à `k` direct (plus besoin d'élargir à 30 pour un cross-encoder
  qui n'existe plus).
- `scripts/config.py` : `RERANKER_ENABLED`/`ESG_RERANKER_ENABLED` retirés.
- `scripts/model.py` : nouvelle fonction `compute_grade()` — grade/label à
  partir de `max(flag_scores)` (0-100) et de seuils simples
  (`DEFAULT_RISK_THRESHOLDS`, valeurs initiales 15/35/60, **à calibrer**
  via `scripts/calibrate_thresholds.py` sur les 46 cas connus). Convention
  conservée : A = pire (Escalade), D = meilleur (Vigilance), comme avec le
  Cox — pas d'inversion pour ne pas dérouter Elisa/le Portfolio Dashboard.
  `build_training_data()`/`train_cox()`/`predict_risk()`/`load_cox_model()`/
  `save_cox_model()` conservés en code mort (pas supprimés, plus appelés).
- `scripts/analyze.py` : `_ensure_loaded()` ne charge plus `cox_model.pkl`
  (plus de `_cox`). `analyze()` appelle `compute_grade()` au lieu de
  `predict_risk()`. `result["prediction"]` n'a plus `probability_12m`/
  `survival_curve`/`hazard_ratios` — juste `risk_score`/`risk_label`/
  `risk_grade`.
- `scripts/pipeline.py` : `retrain()` n'entraîne plus le Cox (étapes 4-5
  retirées, docstring/logs renumérotés 1-3). Plus d'appel à
  `get_flag_scores_from_chunks` sur les 4203 chunks du corpus à chaque
  ré-entraînement.
- `scripts/deep_analysis.py` : `run_pass3()`/`run_deep_analysis()` ne
  prennent plus `probability_12m` — prompt Pass 3 garde `risk_grade` seul.
- `scripts/llm_confirm.py` : `generate_recommendation()` ne prend plus
  `probability_12m` (signature + prompt adaptés). Nécessaire malgré
  "aucun lien" avec Cox/reranker dans la directive initiale — cette
  fonction dépendait directement de `probability_12m` dans son prompt,
  sans ajustement l'appel depuis `analyze.py` aurait levé une exception
  (`None:.0%`).
- `app.py` : carte "Risk Assessment Summary" (`risk_score` dérivé de
  `compute_grade`, plus de probabilité), carte "Probability & Recommendation"
  renommée "📈 Recommendation" (probabilité retirée), Portfolio Dashboard
  (colonne "P(event 12m)" → "Score"), Settings (sliders 0-100 au lieu de
  0.0-1.0, seuils sur score pas probabilité), message d'erreur (ne mentionne
  plus le Cox). Radar ESG déjà sans axe probabilité — rien à changer.
- `scripts/export.py` : PDF et Excel (feuille Summary) — ligne "Probability
  of ESG event" retirée.
- `scripts/test.py` : `--unit` teste `compute_grade()` (au lieu du Cox),
  `--integ`/`--business` adaptés (`risk_score` au lieu de `probability_12m`).
  **31/31 tests passent** (validé en local avec les vraies données du
  corpus + backend Together).
- `scripts/calibrate_thresholds.py` (nouveau) : vérifie la séparation
  événements/contrôles avec les seuils actuels sur les 46 projets connus —
  pas encore exécuté (40+ min d'appels LLM), à lancer après déploiement.

**Mesuré** : `analyze()` sur le cas de test standard passe de ~18 min
(baseline pré-Together) à **21.7s** en local (Together + sans
reranker/Cox). À confirmer sur un document réel (Mundra, 60-70 pages) sur
le VPS après déploiement — objectif directive : < 3 min.

**Non fait** : calibration réelle des seuils 15/35/60 sur les 46 cas
(script prêt, pas encore lancé) ; test de perf sur un document réel de
60-70 pages (fait seulement sur les 4 cas de test courts de `test.py`).

## 2026-08-08 — Abstraction du backend LLM (llm_backend.py)

**Contexte** : Ollama en local (CPU) dégrade sous charge soutenue (~17 ->
<7 tok/s après ~50 appels séquentiels, cause non identifiée) et le Pass 3
de `deep_analysis.py` timeout régulièrement — incompatible avec une démo
live devant la banque le 25 août. Exception explicite accordée au sprint
"pas de nouveau modèle / pas de fix perf avant le 25" pour ce chantier
précis (voir `checklist.md`).

**Changements** :
- Nouveau module `scripts/llm_backend.py` : fonction unique `call_llm()`
  qui route vers Ollama local ou un backend cloud compatible OpenAI
  (Together) selon `config.LLM_BACKEND`. Fail-open partout (None en cas
  d'échec, jamais d'exception), fallback automatique configurable
  (`LLM_FALLBACK`), rate limiter simple pour les backends cloud.
- `scripts/config.py` : nouvelles variables `LLM_BACKEND` (défaut
  `"ollama"` — ne change rien aux déploiements existants),
  `LLM_MODEL`/`LLM_MODEL_BY_BACKEND`, `TOGETHER_API_KEY`, `LLM_FALLBACK`
  (défaut `"ollama"`), `LLM_RATE_LIMIT`.
- `scripts/llm_confirm.py` et `scripts/deep_analysis.py` : les appels HTTP
  directs à Ollama sont remplacés par `llm_backend.call_llm()`. Invariants
  préservés : Pass 2 de `deep_analysis` toujours sans plafond `num_predict`
  (`config_key=None`), Pass 3 toujours `timeout=150`.
- Clé de cache LLM (`llm_confirm.py`, `deep_analysis.py`) étendue pour
  inclure `LLM_BACKEND`/`LLM_MODEL` — évite de servir une réponse
  Together/Qwen3.5-9B comme si elle venait d'Ollama/qwen3:4b-instruct (ou
  l'inverse). Effet de bord attendu : le cache existant est invalidé au
  premier changement de backend/modèle (première analyse plus lente le
  temps de reconstituer le cache, comportement correct, pas un bug).
- `requirements.txt` : ajout de `openai` (SDK utilisé pour l'API
  compatible OpenAI de Together).
- `docker-compose.yml` : nouvelles variables d'environnement passées au
  service `app`, lues depuis `.env` (gitignored).
- `.env.example` créé, `.gitignore` mis à jour pour exclure `.env`.

**Modèle choisi** : `Qwen/Qwen3.5-9B` sur Together — pas `Qwen3.7 Max`, dont
le dashboard Together affiche explicitement "deep thinking enabled by
default".

**BUG TROUVÉ ET CORRIGÉ (2026-08-08, smoke test réel post-déploiement)** :
`Qwen/Qwen3.5-9B` raisonne AUSSI par défaut sur Together, malgré l'absence
de badge "deep thinking" dans le dashboard — l'UI ne l'affiche que pour
certains modèles, ce n'est pas un signal fiable. Mesuré : avec
`confirm_risk` (max_tokens=5), 100% des réponses revenaient vides
(`finish_reason="length"`, tout le budget de tokens consommé par
`reasoning_content`, `message.content` vide) — silencieux, sans exception,
donc fail-open partout (`confirm_risk` toujours `True`) sans jamais
apparaître comme une erreur. Corrigé dans `llm_backend._call_openai_compatible`
: `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` (convention
vLLM/Qwen3, pas un paramètre OpenAI standard) désactive le raisonnement,
gated sur `"qwen" in model.lower()` pour ne pas l'envoyer à un modèle d'une
autre famille. Même famille de bug que `qwen3:4b` vs `qwen3:4b-instruct`
déjà documentée dans `llm_confirm.py`, cause différente (paramètre API vs
choix de variante de modèle).

**Validé après le fix** : `confirm_risk` sur les 4 cas RISK/CLEAN du bloc
`if __name__ == "__main__"` de `llm_confirm.py` (tous corrects,
1.3-5.3s/appel) et `summarize_passage` (résumé cohérent, 2.3s) — appels
réels contre Together, pas mockés. Nettement plus rapide que les 25-95s/appel
mesurés par endroits sur Ollama CPU sous charge.

Format Pass 1 (`ENGAGEMENT/INCIDENT/EVASIF`) également vérifié avec le même
prompt que `deep_analysis._PASS1_PROMPT_TEMPLATE` (`config_key="deep_extract"`) :
sortie conforme, parsable par `_parse_pass1_response` sans modification.

**Non fait dans ce chantier** : validation empirique complète Together vs
Ollama sur un document réel de bout en bout (`analyze()`, avec FAISS/Cox —
pas testé ici, ce venv de test n'a pas `faiss-cpu`/`sentence-transformers`
installés) ; Pass 2/Pass 3 de `deep_analysis` pas testées en conditions
réelles (Pass 1 et `llm_confirm.py` oui) ; pas de tests gold standard encore
(prévus Jour 6 du roadmap) ; `docs/ARCHITECTURE.md` (audit complet du repo,
prévu Jour 4/5 du roadmap).
