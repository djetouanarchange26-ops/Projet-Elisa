# Changelog

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
