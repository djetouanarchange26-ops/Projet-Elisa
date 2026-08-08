# Changelog

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
