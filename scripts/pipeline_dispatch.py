"""
Point d'entrée UNIQUE pour lancer une analyse ESG depuis app.py.
=====================================================================
Directive "V4 canonique et unique" : avant ce module, app.py appelait
`analyze()` (ancien pipeline — search.analyze_query, llm_confirm,
deep_analysis, model.compute_grade) PUIS, dans la même action "Run
Analysis", `grid_analyze.analyze_grid()` (Grille V4) — deux pipelines,
deux jeux d'appels LLM, pour le même document. Ce module remplace les
deux appels dispersés dans app.py par un unique point de décision :
run_active_pipeline() appelle EXACTEMENT un des deux pipelines, jamais les
deux, selon config.ACTIVE_PIPELINE.

CHOIX: fonction pure (pas de dépendance Streamlit) — testable depuis
scripts/test.py sans lancer l'app (cf. test_pipeline_dispatch_single_execution),
et réutilisable telle quelle par app.py. C'est le seul endroit du code
applicatif qui importe à la fois analyze.py (legacy) et grid_analyze.py
(V4) — aucun autre module ne devrait avoir besoin des deux.

Fail-loud sur mauvaise configuration (config.ACTIVE_PIPELINE ni "v4" ni
"legacy") : PAS de repli silencieux sur un pipeline par défaut — un
déploiement mal configuré doit échouer bruyamment, pas mélanger les deux
pipelines par accident (cf. "Ce qu'il ne faut PAS faire" : jamais de
fallback silencieux vers l'ancien pipeline).
"""

import logging

import config

logger = logging.getLogger(__name__)


def run_active_pipeline(
    extracted_text,
    chunks_for_grid=None,
    na_modules=None,
    document_type_override=None,
    document_label="Document analysé",
    risk_thresholds=None,
    k=15,
):
    """Lance EXACTEMENT un pipeline d'analyse (jamais les deux), selon
    config.ACTIVE_PIPELINE.

    extracted_text : texte intégral du document (les deux pipelines en
        ont besoin — legacy pour son propre chunking interne, V4 pour la
        détection de type R11).
    chunks_for_grid : liste de dicts {"text": str, "page": int|None},
        requis seulement si ACTIVE_PIPELINE="v4" (cf. app.py::_chunks_with_pages).
    na_modules, document_type_override : passés tels quels à
        grid_analyze.analyze_grid_auto() (V4 seulement).
    risk_thresholds, k, document_label : passés tels quels à analyze()
        (legacy seulement).

    Retourne {"pipeline": "v4"|"legacy", "result": dict|None,
              "result_v4": dict|None} — exactement un des deux résultats
    est non-None (l'autre reste None, jamais calculé).
    """
    pipeline = config.ACTIVE_PIPELINE

    if pipeline == "v4":
        if not config.GRID_V4_ENABLED:
            raise RuntimeError(
                "config.ACTIVE_PIPELINE='v4' mais config.GRID_V4_ENABLED=False — "
                "configuration incohérente. Corriger l'un des deux flags plutôt que de "
                "retomber silencieusement sur l'ancien pipeline."
            )
        import grid_analyze

        result_v4 = grid_analyze.analyze_grid_auto(
            chunks_for_grid or [],
            extracted_text,
            na_modules=na_modules,
            document_type_override=document_type_override,
        )
        return {"pipeline": "v4", "result": None, "result_v4": result_v4}

    if pipeline == "legacy":
        logger.warning(
            "pipeline_dispatch: ACTIVE_PIPELINE='legacy' — ancien pipeline (analyze.py) "
            "utilisé à la place de la Grille V4 canonique. Réservé à une comparaison "
            "technique ponctuelle, jamais le défaut de production."
        )
        from analyze import analyze

        result = analyze(
            extracted_text,
            risk_thresholds=risk_thresholds,
            k=k,
            document_label=document_label,
        )
        return {"pipeline": "legacy", "result": result, "result_v4": None}

    raise ValueError(
        f"pipeline_dispatch: config.ACTIVE_PIPELINE invalide : {pipeline!r} "
        f"(attendu 'v4' ou 'legacy') — refus de deviner un défaut pour éviter "
        f"une double exécution accidentelle."
    )
