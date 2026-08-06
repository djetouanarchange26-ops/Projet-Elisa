#!/bin/bash
# DIRECTIVE_CLAUDE_CODE_ESG_V3, §1.3 — 2 corrections par rapport au texte brut
# de la directive, vérifiées contre le code réel avant application :
#   1. "qwen3:4b" -> "qwen3:4b-instruct" : c'est le modèle réellement utilisé
#      par llm_confirm.py/deep_analysis.py (MODEL_NAME) depuis le 2026-07-25 —
#      qwen3:4b (variante hybride) a un thinking mode qui le rend 15-45x plus
#      lent (checklist.md). Pull "qwen3:4b" tel quel laisserait l'app appeler
#      un modèle jamais téléchargé dans le container Ollama.
#   2. "python -m scripts.pipeline" -> "python scripts/pipeline.py" : scripts/
#      n'est pas un package Python (pas de __init__.py, imports relatifs bruts
#      type "from model import ..." dans pipeline.py) — invoqué en -m depuis
#      /app, sys.path ne contiendrait pas /app/scripts et l'import échouerait
#      (ModuleNotFoundError: No module named 'model'). "python scripts/pipeline.py"
#      est la même invocation que documentée partout ailleurs dans le projet
#      (checklist.md, "Repères techniques utiles").
echo "=== Pulling qwen3:4b-instruct ==="
docker exec esg-ollama ollama pull qwen3:4b-instruct
if [ ! -f models/faiss_index.bin ]; then
    echo "=== Running pipeline ==="
    docker exec esg-app python scripts/pipeline.py
fi
echo "=== Ready: http://localhost:8501 ==="
