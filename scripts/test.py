"""
SUITE DE TESTS MVP
==================
3 niveaux :
  1. Tests unitaires      — chaque fichier/composant isolé
  2. Tests d'intégration  — pipeline bout en bout
  3. Tests de cohérence   — les résultats ont-ils du sens métier ?

Usage :
    cd scripts/
    python tests.py              # lance tout
    python tests.py --unit       # unitaires seulement
    python tests.py --integ      # intégration seulement
    python tests.py --business   # cohérence métier seulement
"""

import sys
import time
import numpy as np
import pandas as pd
from pathlib import Path

# --- Chemins ---
BASE = Path(__file__).resolve().parent.parent
CHUNKS_PATH      = BASE / "data/processed/chunks.csv"
EMBEDDING_PATH   = BASE / "models/embeddings.npy"
METADATA_PATH    = BASE / "models/chunks_metadata.pkl"
FAISS_INDEX_PATH = BASE / "models/faiss_index.bin"
ANNOTATIONS_PATH = BASE / "data/raw/corpus_cao_ifc.xlsx"

# Compteurs globaux
_passed = 0
_failed = 0
_warnings = 0


def _test(name, condition, msg_fail="", warning_only=False):
    global _passed, _failed, _warnings
    if condition:
        print(f"  ✅ {name}")
        _passed += 1
    elif warning_only:
        print(f"  ⚠️  {name} — {msg_fail}")
        _warnings += 1
    else:
        print(f"  ❌ {name} — {msg_fail}")
        _failed += 1


# ============================================================================
# 1. TESTS UNITAIRES
# ============================================================================

def test_unit():
    print("\n--- 1. Tests unitaires ---\n")

    # 1.1 Fichiers nécessaires
    _test("chunks.csv existe",      CHUNKS_PATH.exists(),      f"Manquant : {CHUNKS_PATH}")
    _test("embeddings.npy existe",  EMBEDDING_PATH.exists(),   f"Manquant : {EMBEDDING_PATH}")
    _test("metadata.pkl existe",    METADATA_PATH.exists(),    f"Manquant : {METADATA_PATH}")
    _test("faiss_index.bin existe", FAISS_INDEX_PATH.exists(), f"Manquant : {FAISS_INDEX_PATH}")
    _test("annotations existe",     ANNOTATIONS_PATH.exists(), f"Manquant : {ANNOTATIONS_PATH}")

    # 1.2 Intégrité chunks.csv
    if CHUNKS_PATH.exists():
        chunks = pd.read_csv(CHUNKS_PATH)
        required_cols = ["project_name", "text", "chunk_id"]
        _test("chunks.csv colonnes requises",
              all(c in chunks.columns for c in required_cols),
              f"Colonnes : {list(chunks.columns)}")
        _test("chunks.csv > 100 lignes",
              len(chunks) > 100,
              f"Seulement {len(chunks)} lignes",
              warning_only=True)
        _test("Pas de texte vide",
              chunks["text"].notna().all() and (chunks["text"].str.len() > 10).all(),
              "Chunks avec texte vide ou trop court")

    # 1.3 Cohérence embeddings / chunks
    if EMBEDDING_PATH.exists() and CHUNKS_PATH.exists():
        embs = np.load(EMBEDDING_PATH)
        n_chunks = len(pd.read_csv(CHUNKS_PATH))
        _test("Embeddings shape cohérente",
              embs.shape[0] == n_chunks,
              f"embeddings={embs.shape[0]} vs chunks={n_chunks}")
        _test("Dimension = 768",
              embs.shape[1] == 768,
              f"Dimension = {embs.shape[1]}")
        norms = np.linalg.norm(embs[:10], axis=1)
        _test("Normalisés L2",
              np.allclose(norms, 1.0, atol=0.01),
              f"Norme moyenne = {norms.mean():.3f}")

    # 1.4 Grade ESG par règle (CHANTIER SIMPLIFICATION PIPELINE, 2026-08-08 —
    # remplace le Cox, retiré : coefficients flag2/flag3 non significatifs
    # sur 46 projets, décalage train/serve non résolu, cf. checklist.md).
    from model import compute_grade, DEFAULT_RISK_THRESHOLDS

    _test("DEFAULT_RISK_THRESHOLDS strictement croissant",
          all(DEFAULT_RISK_THRESHOLDS[i][0] < DEFAULT_RISK_THRESHOLDS[i + 1][0]
              for i in range(len(DEFAULT_RISK_THRESHOLDS) - 1)),
          f"Seuils : {DEFAULT_RISK_THRESHOLDS}")

    _low = compute_grade({"flag1_community": 5, "flag2_pollution": 5, "flag3_compliance": 5})
    _test("Score bas -> grade D (Vigilance)",
          _low["risk_grade"] == "D" and _low["risk_label"] == "Vigilance",
          f"Obtenu : {_low}")

    _high = compute_grade({"flag1_community": 90, "flag2_pollution": 5, "flag3_compliance": 5})
    _test("Score haut sur un seul flag -> grade A (Escalade), max() pas moyenne",
          _high["risk_grade"] == "A" and _high["risk_label"] == "Escalade",
          f"Obtenu : {_high}")

    # 1.5 llm_backend — abstraction backend LLM (2026-08-07, checklist.md).
    # Pas d'appel réseau réel ici (pas de dépendance à une clé API/à Ollama
    # actif) : on monkey-patche llm_backend._dispatch pour vérifier le
    # contrat (fail-open, fallback, plafond de longueur) indépendamment du
    # backend réellement configuré.
    import config
    import llm_backend

    _orig_dispatch = llm_backend._dispatch

    def _always_fails(*a, **kw):
        raise RuntimeError("backend simulé injoignable")

    llm_backend._dispatch = _always_fails
    try:
        result = llm_backend.call_llm("test", config_key="confirm_risk", timeout=1)
        _test("llm_backend.call_llm fail-open (backend injoignable -> None, jamais d'exception)",
              result is None,
              f"Résultat inattendu : {result!r}")
    finally:
        llm_backend._dispatch = _orig_dispatch

    _orig_backend, _orig_fallback = config.LLM_BACKEND, config.LLM_FALLBACK
    config.LLM_BACKEND, config.LLM_FALLBACK = "together", "ollama"
    calls = []

    def _fail_then_succeed(backend, prompt, model, options, timeout):
        calls.append(backend)
        if backend == "together":
            raise RuntimeError("primaire simulé injoignable")
        return "reponse de secours"

    llm_backend._dispatch = _fail_then_succeed
    try:
        result = llm_backend.call_llm("test", config_key="confirm_risk", timeout=1)
        _test("llm_backend.call_llm bascule sur LLM_FALLBACK si le backend principal échoue",
              result == "reponse de secours" and calls == ["together", "ollama"],
              f"Résultat={result!r}, backends appelés={calls}")
    finally:
        llm_backend._dispatch = _orig_dispatch
        config.LLM_BACKEND, config.LLM_FALLBACK = _orig_backend, _orig_fallback

    opts_capped = llm_backend._resolve_options("confirm_risk", 0.0)
    _test("_resolve_options applique le plafond num_predict pour un config_key connu",
          opts_capped["max_tokens"] == config.OLLAMA_CONFIGS["confirm_risk"]["num_predict"],
          f"max_tokens={opts_capped['max_tokens']}")

    opts_uncapped = llm_backend._resolve_options(None, 0.0)
    _test("_resolve_options NE plafonne PAS quand config_key=None (invariant Pass 2 deep_analysis)",
          opts_uncapped["max_tokens"] is None,
          f"max_tokens={opts_uncapped['max_tokens']}")

    # 1.6 Grille ESG V4 (grid_questions.py, directive CC-V4-01) — structure
    # seule, pas de scoring/LLM ici. Pipeline pas encore activé
    # (config.GRID_V4_ENABLED = False), ce test ne dépend d'aucun réseau.
    test_grid_questions_v4()

    # 1.7 Moteur de scoring V3 (grid_scoring.py, directive CC-02) et
    # 1.8 format de résultat V3 (grid_result.py, directive CC-03) — même
    # raison : purement déterministe, pas de dépendance réseau/LLM.
    test_grid_scoring()
    test_grid_result()

    # 1.7b Scoring V4 (grid_scoring.py, directive CC-V4-02) — 4 zones de
    # couleur, plafond partagé A.1.1/A.1.3, B.3.1 sous-question A quand
    # R=NON, mode de lecture par type de document. Purement déterministe.
    test_grid_scoring_v4()

    # 1.8b Format de résultat V4 (grid_result.py, directive CC-V4-03) —
    # document_type/reading_mode, garde-fou mitigation par a_condition,
    # champ qualifying. Purement déterministe.
    test_grid_result_v4()

    # 1.9 Prompts V4 complets (grid_prompts.py, directive CC-V4-05) —
    # construction/parsing de strings uniquement, aucun appel LLM.
    test_grid_prompts_v4()

    # 1.10 Mitigation à 4 statuts (grid_scoring.py/grid_questions.py,
    # directive CC-07, passe d'annotation CBG) — purement déterministe.
    test_mitigation_4_statuts()

    # 1.11-1.13 Silence événement/état, verrou B.2.1→B.2.2, flag attesté
    # (directive CC-08, passe CBG) — purement déterministe.
    test_silence_evenement_etat()
    test_verrou_b21_b22()
    test_flag_atteste()

    # 1.14 Exclusions parseur ESAP / section plaintes IFC (grid_sections.py,
    # directive CC-09, confirmée par CC-V4-04) — purement déterministe, pas de LLM.
    test_esap_exclusion()
    test_ifc_complaints_exclusion()
    test_no_sections_detected()

    # 1.14d Marquage best-effort des couches temporelles (grid_sections.py,
    # addition V4, directive CC-V4-04, bonus non bloquant) — déterministe.
    test_temporal_layer_marking()

    # 1.15 Orchestrateur Grille V4 (grid_analyze.py, directive CC-V4-06) —
    # backend LLM monkey-patché (même idiome que 1.5), pas d'appel réseau réel.
    test_grid_analyze_v4()

    # 1.16 Calibration V4 sur les 4 dossiers annotés (directive CC-V4-07) —
    # purement déterministe (grid_scoring.py seul), pas de LLM.
    test_calibration_cbg()
    test_calibration_mundra()
    test_calibration_aysha()
    test_calibration_indorama()
    test_calibration_ordering()
    test_calibration_shared_cap_mundra()
    test_calibration_b31_inverted()

    # 1.17 Export PDF/Excel de la Grille V4 (directive CC-V4-10) — purement
    # déterministe (fpdf2/openpyxl), pas de LLM.
    test_grid_v4_export()

    # 1.18 Détection automatique du type de document (R11, grid_doctype.py)
    # — backend LLM monkey-patché, pas d'appel réseau réel.
    test_grid_doctype()

    # 1.19 R10 — catégories étendues du filtre de sujet (AMBIGU, INDIRECT)
    # — string-only sur les prompts + parsing, pas de LLM.
    test_grid_prompts_r10_extended()


def test_grid_prompts_r10_extended():
    """Tests dédiés à l'extension R10 (grid_prompts.py) : 2 nouvelles
    catégories de sujet (AMBIGU, INDIRECT) en plus de SPV/PRÊTEUR/
    SUBSTITUTION, avec consigne explicite de ne jamais attribuer par
    défaut un manquement ambigu à la SPV. String-only, aucun appel LLM."""
    print("\n--- 1.19 R10 — filtre de sujet étendu (grid_prompts.py) ---\n")

    import grid_prompts

    prompt_a21 = grid_prompts.get_prompt("A.2.1", ["chunk"])
    _test("R10 : catégorie AMBIGU documentée dans le prompt", "AMBIGU" in prompt_a21)
    _test("R10 : catégorie INDIRECT documentée dans le prompt", "INDIRECT" in prompt_a21)
    _test("R10 : consigne explicite de ne pas attribuer un sujet ambigu à la SPV",
          "NE PAS" in prompt_a21 and "attribuer" in prompt_a21.lower())
    _test("R10 : le biais R1 ne s'applique jamais à l'attribution du sujet",
          "jamais" in prompt_a21.lower() and "sujet" in prompt_a21.lower())

    # Parsing : les 2 nouvelles catégories sont acceptées telles quelles,
    # sans réécriture (fail-open, cohérent avec SPV/PRÊTEUR/SUBSTITUTION).
    resp_ambigu = "STATUS: NON\nEVIDENCE_R:\nPAGE: inconnue\nMITIGATION_STATUS: N/A\nSUJET: AMBIGU\n"
    parsed_ambigu = grid_prompts.parse_response(resp_ambigu)
    _test("Parsing V4 : subject_filter='AMBIGU' accepté", parsed_ambigu["subject_filter"] == "AMBIGU",
          f"Obtenu : {parsed_ambigu['subject_filter']!r}")

    resp_indirect = "STATUS: NON\nEVIDENCE_R:\nPAGE: inconnue\nMITIGATION_STATUS: N/A\nSUJET: INDIRECT\n"
    parsed_indirect = grid_prompts.parse_response(resp_indirect)
    _test("Parsing V4 : subject_filter='INDIRECT' accepté", parsed_indirect["subject_filter"] == "INDIRECT",
          f"Obtenu : {parsed_indirect['subject_filter']!r}")


def test_grid_doctype():
    """Tests de la détection automatique du type de document (R11,
    grid_doctype.py). Backend LLM monkey-patché (même idiome que
    test_grid_analyze_v4), pas d'appel réseau réel."""
    print("\n--- 1.18 Détection automatique du type de document (grid_doctype.py) ---\n")

    import llm_backend
    import grid_doctype

    _orig_dispatch = llm_backend._dispatch

    def _make_fake_dispatch(doc_type, confidence="haute"):
        def _fake(backend, prompt, model, options, timeout):
            return f"TYPE: {doc_type}\nCONFIANCE: {confidence}\nEVIDENCE: extrait de justification\n"
        return _fake

    try:
        # --- 4 types, LLM simulé répond correctement pour chacun ---
        for expected_type in (1, 2, 3, 4):
            llm_backend._dispatch = _make_fake_dispatch(expected_type)
            result = grid_doctype.detect_document_type("Texte de test quelconque.")
            _test(f"Type {expected_type} : détecté correctement",
                  result["document_type"] == expected_type, f"Obtenu : {result}")
            _test(f"Type {expected_type} : source='llm'", result["source"] == "llm")
            _test(f"Type {expected_type} : confidence='haute'", result["confidence"] == "haute")
            _test(f"Type {expected_type} : evidence non vide", bool(result["evidence"]))

        # --- Fail-open : LLM injoignable -> repli heuristique lexical,
        # jamais un Type 1 muet indiscernable d'une vraie détection ---
        def _broken_dispatch(backend, prompt, model, options, timeout):
            raise RuntimeError("backend injoignable (simulation)")
        llm_backend._dispatch = _broken_dispatch

        result_fail = grid_doctype.detect_document_type(
            "Compliance Advisor Ombudsman (CAO) monitoring report — Third Monitoring Period."
        )
        _test("Fail-open : LLM injoignable -> pas d'exception, dict retourné",
              isinstance(result_fail, dict))
        _test("Fail-open : source='fallback_heuristique_lexicale' (pas un Type 1 muet)",
              result_fail["source"] == "fallback_heuristique_lexicale", f"Obtenu : {result_fail}")
        _test("Fail-open : indices CAO/monitoring period -> Type 3 par heuristique",
              result_fail["document_type"] == 3, f"Obtenu : {result_fail}")
        _test("Fail-open : confidence='faible' (signale une détection non fiable)",
              result_fail["confidence"] == "faible")

        # --- Fail-open sans aucun indice lexical -> Type 1, mais explicitement marqué ---
        result_no_hint = grid_doctype.detect_document_type("")
        _test("Fail-open sans indice : document_type=1 (repli prudent)",
              result_no_hint["document_type"] == 1)
        _test("Fail-open sans indice : source='fallback_heuristique_aucun_indice'",
              result_no_hint["source"] == "fallback_heuristique_aucun_indice")

        # --- Réponse LLM inexploitable (pas de ligne TYPE) -> repli heuristique ---
        def _garbage_dispatch(backend, prompt, model, options, timeout):
            return "réponse illisible sans le bon format"
        llm_backend._dispatch = _garbage_dispatch
        result_garbage = grid_doctype.detect_document_type("Annual Monitoring Report prepared by the client.")
        _test("Réponse LLM inexploitable -> repli heuristique (pas de crash)",
              result_garbage["source"].startswith("fallback"))
        _test("Réponse LLM inexploitable + indice AMR -> Type 2 par heuristique",
              result_garbage["document_type"] == 2, f"Obtenu : {result_garbage}")

    finally:
        llm_backend._dispatch = _orig_dispatch


def test_grid_prompts_v4():
    """Tests des prompts V4 (grid_prompts.py, directive CC-V4-05) : règles
    R1-R11 dynamiques selon document_type, few-shot des 4 dossiers annotés,
    parsing avec le champ SUJET (R10)."""
    print("\n--- 1.9 Prompts Grille V4 (grid_prompts.py) ---\n")

    import grid_prompts
    import grid_questions

    # 1. get_prompt("A.1.1", [...]) retourne un string non vide
    prompt_a11 = grid_prompts.get_prompt("A.1.1", ["chunk1", "chunk2"])
    _test("Test 1 : get_prompt('A.1.1', ...) -> string non vide",
          isinstance(prompt_a11, str) and len(prompt_a11) > 0)

    # 2. Le prompt contient la formulation R exacte d'A.1.1
    question_r_a11 = grid_questions.get_question("A.1.1")["question_r"]
    _test("Test 2 : formulation R exacte d'A.1.1 présente dans le prompt",
          question_r_a11 in prompt_a11, f"Attendu dans le prompt : {question_r_a11!r}")

    # 3. Le prompt contient "français" (instruction de langue)
    _test("Test 3 : instruction de langue ('français') présente", "français" in prompt_a11)

    # 4. Le prompt contient "ambiguïté" (R1, biais faux positifs — CC-04, non régressé)
    _test("Test 4 : instruction biais faux positifs ('ambiguïté') présente", "ambiguïté" in prompt_a11)

    # 5. get_prompt("B.3.1", [...]) ne contient pas "QUESTION DE RISQUE"
    # (polarité inversée — cf. grid_prompts.py)
    prompt_b31 = grid_prompts.get_prompt("B.3.1", ["chunk1"])
    _test("Test 5 : prompt B.3.1 ne contient PAS 'QUESTION DE RISQUE'",
          "QUESTION DE RISQUE" not in prompt_b31)
    _test("Test 5b : prompt B.3.1 contient 'POLARITÉ INVERSÉE'",
          "POLARITÉ INVERSÉE" in prompt_b31)
    _test("Test 5c : prompt B.3.1 mentionne la sous-question de mitigation",
          "mitigation" in prompt_b31.lower())

    # 6. get_prompt("Z.9.9", [...]) -> None (code inconnu, pas d'exception)
    _test("Test 6 : get_prompt code inconnu -> None", grid_prompts.get_prompt("Z.9.9", ["c"]) is None)

    # --- R11 : formes de preuve selon le type de document ---
    prompt_type1 = grid_prompts.get_prompt("B.1.1", ["chunk"], document_type=1)
    _test("R11 : document Type 1 -> 4ème forme de preuve mentionnée",
          "QUATRIÈME" in prompt_type1 or "plan détaillé" in prompt_type1)

    prompt_type3 = grid_prompts.get_prompt("B.1.1", ["chunk"], document_type=3)
    _test("R11 : document Type 3 -> seulement 3 formes ('plan seul reste au statut 2')",
          "plan seul reste au statut 2" in prompt_type3)

    # --- R8 : couches temporelles sur Type 3 seulement ---
    _test("R8 : 'Couche 1' présent sur Type 3", "Couche 1" in prompt_type3)
    _test("R8 : 'Couche 2' présent sur Type 3", "Couche 2" in prompt_type3)
    _test("R8 : 'Couche 1' ABSENT sur Type 1 (règle non universelle)",
          "Couche 1" not in prompt_type1)

    # --- R9 : hiérarchie des sources sur Types 2-3 seulement ---
    _test("R9 : 'auditeur indépendant' présent sur Type 3", "auditeur indépendant" in prompt_type3)
    _test("R9 : hiérarchie des sources ABSENTE sur Type 1",
          "HIÉRARCHIE DES SOURCES" not in prompt_type1)

    # --- R10 : filtre de sujet, universel (présent quel que soit le type) ---
    _test("R10 : 'institution financière' présent (Type 1 aussi)", "institution financière" in prompt_type1)
    _test("R10 : 'substitution' mentionné", "substitution" in prompt_type1.lower())

    # --- Few-shot des 4 dossiers annotés ---
    prompt_b22 = grid_prompts.get_prompt("B.2.2", ["chunk"])
    _test("Few-shot B.2.2 : cas CBG ('fugitive dust')", "fugitive dust" in prompt_b22)
    _test("Few-shot B.2.2 : cas Indorama ('LAeq exceeded'/'night-time')",
          "LAeq exceeded" in prompt_b22 or "night-time" in prompt_b22)

    prompt_a21 = grid_prompts.get_prompt("A.2.1", ["chunk"])
    _test("Few-shot A.2.1 : cas Mundra R10 ('Jam'/'SFI')",
          "Jam" in prompt_a21 or "SFI" in prompt_a21)

    prompt_a31 = grid_prompts.get_prompt("A.3.1", ["chunk"])
    _test("Few-shot A.3.1 : cas Aysha (permis obtenu vs projet retardé)",
          "MoWIE" in prompt_a31 or "Environmental Clearance" in prompt_a31)

    prompt_b11 = grid_prompts.get_prompt("B.1.1", ["chunk"])
    _test("Few-shot B.1.1 : cas Indorama (N/A argumenté)", "Indorama Free Zone" in prompt_b11)

    # Questions sans cas annoté -> pas de few-shot inventé (fallback "")
    _test("Pas de few-shot pour A.4.1 (aucun cas annoté)", "A.4.1" not in grid_prompts._FEW_SHOT_EXAMPLES)
    _test("Pas de few-shot pour B.2.1 (aucun cas annoté)", "B.2.1" not in grid_prompts._FEW_SHOT_EXAMPLES)
    _test("Pas de few-shot pour B.2.3 (aucun cas annoté)", "B.2.3" not in grid_prompts._FEW_SHOT_EXAMPLES)

    # --- Parsing V4 avec SUJET (R10) ---
    response_v4 = (
        "STATUS: OUI\n"
        'EVIDENCE_R: "test"\n'
        "PAGE: 5\n"
        "MITIGATION_STATUS: OUI_PROUVEE\n"
        'EVIDENCE_MESURE: "test"\n'
        "EVIDENCE_DEFAILLANCE:\n"
        "SUJET: SPV\n"
        "CONFIDENCE:"
    )
    parsed = grid_prompts.parse_response(response_v4)
    _test("Parsing V4 : dict valide", isinstance(parsed, dict), f"Obtenu : {parsed!r}")
    if isinstance(parsed, dict):
        _test("Parsing V4 : status='OUI'", parsed["status"] == "OUI", f"Obtenu : {parsed['status']!r}")
        _test("Parsing V4 : mitigation_status='OUI_PROUVEE'",
              parsed["mitigation_status"] == "OUI_PROUVEE", f"Obtenu : {parsed['mitigation_status']!r}")
        _test("Parsing V4 : subject_filter='SPV'", parsed["subject_filter"] == "SPV",
              f"Obtenu : {parsed['subject_filter']!r}")

    response_lender = (
        "STATUS: OUI\n"
        'EVIDENCE_R: "test"\n'
        "PAGE: 5\n"
        "MITIGATION_STATUS: N/A\n"
        "EVIDENCE_MESURE:\n"
        "EVIDENCE_DEFAILLANCE:\n"
        "SUJET: PRÊTEUR\n"
        "CONFIDENCE: Verbatim écarté par R10"
    )
    parsed_l = grid_prompts.parse_response(response_lender)
    _test("Parsing V4 : subject_filter='PRÊTEUR'", parsed_l["subject_filter"] == "PRÊTEUR",
          f"Obtenu : {parsed_l['subject_filter']!r}")
    _test("Parsing V4 : MITIGATION_STATUS='N/A' -> mitigation_status=None",
          parsed_l["mitigation_status"] is None, f"Obtenu : {parsed_l['mitigation_status']!r}")

    # SUJET absent ou invalide -> repli sûr "SPV" (fail-open, R10 jamais bloquant)
    response_no_sujet = "STATUS: NON\nEVIDENCE_R:\nPAGE: inconnue\nMITIGATION_STATUS: N/A\n"
    parsed_ns = grid_prompts.parse_response(response_no_sujet)
    _test("Parsing V4 : SUJET absent -> subject_filter='SPV' (repli sûr)",
          parsed_ns["subject_filter"] == "SPV", f"Obtenu : {parsed_ns['subject_filter']!r}")

    response_bad_sujet = "STATUS: NON\nEVIDENCE_R:\nPAGE: inconnue\nMITIGATION_STATUS: N/A\nSUJET: AUTRE\n"
    parsed_bs = grid_prompts.parse_response(response_bad_sujet)
    _test("Parsing V4 : SUJET invalide -> subject_filter='SPV' (repli sûr)",
          parsed_bs["subject_filter"] == "SPV", f"Obtenu : {parsed_bs['subject_filter']!r}")

    # 7. parse_response("garbage") retourne None (pas de ligne STATUS)
    _test("Test 7 : parse_response('garbage') -> None", grid_prompts.parse_response("garbage") is None)


def _zero_risk_grid_answers():
    """Jeu de réponses V3 où aucune question ne déclenche de pénalité :
    NON pour les 9 questions au schéma standard, OUI pour B.3.1 (schéma
    inversé — OUI est la réponse "sans risque" pour cette question, cf.
    grid_scoring.compute_grid_score). Partagée par test_grid_scoring et
    test_grid_result pour construire des cas de base à surcharger."""
    import grid_questions

    answers = {}
    for q in grid_questions.ESG_QUESTIONS:
        if q["inverted_polarity"]:
            answers[q["code"]] = {"status": "OUI", "mitigation": None}
        else:
            answers[q["code"]] = {"status": "NON", "mitigation": None}
    return answers


def test_grid_scoring():
    """Tests du moteur de scoring V3 (grid_scoring.py, directive CC-02)."""
    print("\n--- 1.7 Moteur de scoring Grille V3 (grid_scoring.py) ---\n")

    import grid_questions
    import grid_scoring

    # 1. Tout "sans risque" -> score=100, VERT
    result = grid_scoring.compute_grid_score(_zero_risk_grid_answers())
    _test("Test 1 : aucun risque -> score=100", result["score"] == 100, f"Obtenu : {result['score']}")
    _test("Test 1 : aucun risque -> VERT", result["color"] == "VERT", f"Obtenu : {result['color']}")

    # 2. Tout "à risque" (OUI standard / NON pour B.3.1 inversé), sans
    # mitigation -> plancher 0, ROUGE
    answers_all_risk = {}
    for q in grid_questions.ESG_QUESTIONS:
        if q["inverted_polarity"]:
            answers_all_risk[q["code"]] = {"status": "NON", "mitigation": None}
        else:
            answers_all_risk[q["code"]] = {"status": "OUI", "mitigation": None}
    result = grid_scoring.compute_grid_score(answers_all_risk)
    _test("Test 2 : tout à risque sans mitigation -> plancher 0", result["score"] == 0, f"Obtenu : {result['score']}")
    _test("Test 2 : tout à risque -> ROUGE", result["color"] == "ROUGE", f"Obtenu : {result['color']}")

    # 3. B.3.1 seul NON (schéma inversé : NON = risque) -> 100-15=85, VERT
    answers = _zero_risk_grid_answers()
    answers["B.3.1"] = {"status": "NON", "mitigation": None}
    result = grid_scoring.compute_grid_score(answers)
    _test("Test 3 : B.3.1 NON (inversé) -> score=85", result["score"] == 85, f"Obtenu : {result['score']}")
    _test("Test 3 : B.3.1 NON (inversé) -> VERT", result["color"] == "VERT", f"Obtenu : {result['color']}")

    # 4. B.3.1 seul OUI (favorable) -> 100, VERT
    answers = _zero_risk_grid_answers()
    answers["B.3.1"] = {"status": "OUI", "mitigation": None}
    result = grid_scoring.compute_grid_score(answers)
    _test("Test 4 : B.3.1 OUI (favorable) -> score=100", result["score"] == 100, f"Obtenu : {result['score']}")
    _test("Test 4 : B.3.1 OUI -> VERT", result["color"] == "VERT", f"Obtenu : {result['color']}")

    # 5. 3 questions B.2 en NA, reste sans risque -> 100 (N/A exclu du calcul)
    answers = _zero_risk_grid_answers()
    for code in ("B.2.1", "B.2.2", "B.2.3"):
        answers[code] = {"status": "NA", "mitigation": None}
    result = grid_scoring.compute_grid_score(answers)
    _test("Test 5 : 3 questions NA, reste sans risque -> score=100", result["score"] == 100, f"Obtenu : {result['score']}")
    _test("Test 5 : questions_na=3", result["questions_na"] == 3, f"Obtenu : {result['questions_na']}")
    # 12 questions V4 - 3 NA (B.2.x) = 9 actives (V3 avait 10-3=7).
    _test("Test 5 : questions_active=9", result["questions_active"] == 9, f"Obtenu : {result['questions_active']}")

    # 6. A.1.1 OUI + mitigation OUI -> pénalité -25, gain +5 -> score=80
    answers = _zero_risk_grid_answers()
    answers["A.1.1"] = {"status": "OUI", "mitigation": "OUI"}
    result = grid_scoring.compute_grid_score(answers)
    _test("Test 6 : A.1.1 OUI+mitigation OUI -> score=80", result["score"] == 80, f"Obtenu : {result['score']}")

    # 7. Cap d'atténuation : gain brut > 20 -> plafonné à 20.
    # (seules 4 questions Cat A existent, pas 5 comme suggéré par CC-02 —
    # 4 Cat A + 2 Cat B en OUI+mitigation OUI : 4*5 + 2*3 = 26 > 20, même
    # effet de cap que "5 mitigations".)
    answers = _zero_risk_grid_answers()
    for code in ("A.1.1", "A.2.1", "A.3.1", "A.4.1"):
        answers[code] = {"status": "OUI", "mitigation": "OUI"}
    for code in ("B.1.1", "B.1.2"):
        answers[code] = {"status": "OUI", "mitigation": "OUI"}
    result = grid_scoring.compute_grid_score(answers)
    _test("Test 7 : gain brut > 20", result["total_gain"] == 26, f"Obtenu : {result['total_gain']}")
    _test("Test 7 : gain plafonné à 20", result["total_gain_capped"] == 20, f"Obtenu : {result['total_gain_capped']}")
    _test("Test 7 : cap_applied=True", result["cap_applied"] is True, f"Obtenu : {result['cap_applied']}")

    # 8. Mundra simplifié (valeurs V3 arbitraires — PAS un ground truth
    # métier, juste un cas de calcul composite avec pénalités + 1 gain +
    # le schéma inversé B.3.1 en jeu simultanément).
    answers = _zero_risk_grid_answers()
    answers["A.2.1"] = {"status": "OUI", "mitigation": "OUI"}   # -25 +5
    answers["B.1.1"] = {"status": "OUI", "mitigation": "NON"}   # -15
    answers["B.2.1"] = {"status": "NON", "mitigation": None}    # 0
    answers["B.2.2"] = {"status": "OUI", "mitigation": "NON"}   # -15
    answers["B.3.1"] = {"status": "NON", "mitigation": None}    # -15 (inversé)
    result = grid_scoring.compute_grid_score(answers)
    # pénalités : -25-15-15-15 = -70 ; gain : +5 -> 100-70+5 = 35
    _test("Test 8 : Mundra simplifié -> score=35", result["score"] == 35, f"Obtenu : {result['score']}")
    # get_color V4 (CC-V4-02) : 4 zones (>=75 VERT, 50-74 JAUNE, 25-49
    # ORANGE, <25 ROUGE) au lieu des 3 zones V3 (<50 ROUGE) — 35 est
    # ORANGE en V4, pas ROUGE.
    _test("Test 8 : Mundra simplifié -> ORANGE (zones V4)", result["color"] == "ORANGE", f"Obtenu : {result['color']}")

    # 9. Code invalide -> ValueError
    answers = _zero_risk_grid_answers()
    answers["Z.9.9"] = {"status": "NON", "mitigation": None}
    try:
        grid_scoring.compute_grid_score(answers)
        _test("Test 9 : code invalide -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("Test 9 : code invalide -> ValueError", True)

    # 10. Status invalide -> ValueError
    answers = _zero_risk_grid_answers()
    answers["A.1.1"] = {"status": "PEUT-ÊTRE", "mitigation": None}
    try:
        grid_scoring.compute_grid_score(answers)
        _test("Test 10 : status invalide -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("Test 10 : status invalide -> ValueError", True)


def test_grid_scoring_v4():
    """Tests du scoring V4 (grid_scoring.py, directive CC-V4-02) : 4 zones
    de couleur, plafond partagé A.1.1/A.1.3, B.3.1 (sous-question A quand
    R=NON), métadonnées du mode de lecture (document_type)."""
    print("\n--- 1.7b Scoring Grille V4 (grid_scoring.py) ---\n")

    import grid_questions
    import grid_scoring

    # --- 4 zones de couleur ---
    _test("get_color(80) = VERT", grid_scoring.get_color(80) == "VERT", f"Obtenu : {grid_scoring.get_color(80)!r}")
    _test("get_color(75) = VERT", grid_scoring.get_color(75) == "VERT", f"Obtenu : {grid_scoring.get_color(75)!r}")
    _test("get_color(74) = JAUNE", grid_scoring.get_color(74) == "JAUNE", f"Obtenu : {grid_scoring.get_color(74)!r}")
    _test("get_color(50) = JAUNE", grid_scoring.get_color(50) == "JAUNE", f"Obtenu : {grid_scoring.get_color(50)!r}")
    _test("get_color(49) = ORANGE", grid_scoring.get_color(49) == "ORANGE", f"Obtenu : {grid_scoring.get_color(49)!r}")
    _test("get_color(25) = ORANGE", grid_scoring.get_color(25) == "ORANGE", f"Obtenu : {grid_scoring.get_color(25)!r}")
    _test("get_color(24) = ROUGE", grid_scoring.get_color(24) == "ROUGE", f"Obtenu : {grid_scoring.get_color(24)!r}")
    _test("get_color(0) = ROUGE", grid_scoring.get_color(0) == "ROUGE", f"Obtenu : {grid_scoring.get_color(0)!r}")

    # --- Plafond partagé A.1.1/A.1.3 ---
    answers_shared = _make_answers({
        "A.1.1": {"status": "OUI", "mitigation_status": "NON_INTENTION"},
        "A.1.3": {"status": "OUI", "mitigation_status": "NON_INTENTION"},
    })
    result_shared = grid_scoring.compute_grid_score(answers_shared)
    total_a1_penalty = sum(
        d["penalty"] for d in result_shared["details"] if d["code"] in ("A.1.1", "A.1.3")
    )
    _test("Plafond partagé A.1.1/A.1.3 : pénalité combinée = -25",
          total_a1_penalty == -25, f"Obtenu : {total_a1_penalty}")
    _test("Plafond partagé : une seule des deux questions marquée _shared_cap_applied",
          sum(1 for d in result_shared["details"]
              if d["code"] in ("A.1.1", "A.1.3") and d.get("_shared_cap_applied")) == 1)

    # --- B.3.1 : NON sans mitigation -> -15 ---
    answers_b31_non = _make_answers({"B.3.1": {"status": "NON"}})
    result_b31 = grid_scoring.compute_grid_score(answers_b31_non)
    detail_b31 = _find_detail(result_b31, "B.3.1")
    _test("B.3.1 NON sans mitigation : pénalité=-15", detail_b31["penalty"] == -15,
          f"Obtenu : {detail_b31['penalty']}")
    _test("B.3.1 NON sans mitigation : gain=0", detail_b31["gain"] == 0, f"Obtenu : {detail_b31['gain']}")

    # --- B.3.1 : NON + mitigation prouvée -> -15 + 3 ---
    answers_b31_mit = _make_answers({"B.3.1": {"status": "NON", "mitigation_status": "OUI_PROUVEE"}})
    result_b31_mit = grid_scoring.compute_grid_score(answers_b31_mit)
    detail_b31_mit = _find_detail(result_b31_mit, "B.3.1")
    _test("B.3.1 NON + mitigation prouvée : pénalité=-15", detail_b31_mit["penalty"] == -15,
          f"Obtenu : {detail_b31_mit['penalty']}")
    _test("B.3.1 NON + mitigation prouvée : gain=3", detail_b31_mit["gain"] == 3,
          f"Obtenu : {detail_b31_mit['gain']}")

    # --- B.3.1 : OUI (favorable) -> 0 ---
    answers_b31_oui = _make_answers({"B.3.1": {"status": "OUI"}})
    result_b31_oui = grid_scoring.compute_grid_score(answers_b31_oui)
    detail_b31_oui = _find_detail(result_b31_oui, "B.3.1")
    _test("B.3.1 OUI : pénalité=0", detail_b31_oui["penalty"] == 0, f"Obtenu : {detail_b31_oui['penalty']}")
    _test("B.3.1 OUI : gain=0 (mitigation non fournie ici)", detail_b31_oui["gain"] == 0,
          f"Obtenu : {detail_b31_oui['gain']}")

    # --- Score maximum = 100 (tout NON, B.3.1 OUI = favorable) ---
    answers_perfect = _make_answers({"B.3.1": {"status": "OUI"}})
    result_perfect = grid_scoring.compute_grid_score(answers_perfect)
    _test("Score maximum (tout NON, B.3.1 OUI) = 100", result_perfect["score"] == 100,
          f"Obtenu : {result_perfect['score']}")
    _test("Score maximum -> saturation=False", result_perfect["saturation"] is False,
          f"Obtenu : {result_perfect['saturation']}")

    # --- Drapeau de saturation (score plancher = 0) ---
    answers_saturation = {q["code"]: {"status": "OUI" if not q["inverted_polarity"] else "NON",
                                       "mitigation_status": None}
                          for q in grid_questions.QUESTIONS}
    result_saturation = grid_scoring.compute_grid_score(answers_saturation)
    _test("Score plancher (tout à risque) = 0", result_saturation["score"] == 0,
          f"Obtenu : {result_saturation['score']}")
    _test("Score plancher -> saturation=True", result_saturation["saturation"] is True,
          f"Obtenu : {result_saturation['saturation']}")
    _test("Score plancher -> color=ROUGE", result_saturation["color"] == "ROUGE",
          f"Obtenu : {result_saturation['color']!r}")

    # --- Statut INCONNU accepté, scoré comme NON ---
    answers_inconnu = _make_answers({"A.2.1": {"status": "INCONNU"}})
    result_inconnu = grid_scoring.compute_grid_score(answers_inconnu)
    detail_inconnu = _find_detail(result_inconnu, "A.2.1")
    _test("Statut INCONNU accepté sans ValueError", True)
    _test("INCONNU : pénalité=0", detail_inconnu["penalty"] == 0, f"Obtenu : {detail_inconnu['penalty']}")
    _test("INCONNU : conservé tel quel dans le détail (pas réécrit en NON)",
          detail_inconnu["status"] == "INCONNU", f"Obtenu : {detail_inconnu['status']!r}")

    # --- Document type dans le résultat (R11) — n'affecte PAS le score ---
    result_type1 = grid_scoring.compute_grid_score(_make_all_non())
    _test("document_type par défaut = 1", result_type1["document_type"] == 1,
          f"Obtenu : {result_type1['document_type']}")
    _test("reading_mode par défaut = 'instruction'", result_type1["reading_mode"] == "instruction",
          f"Obtenu : {result_type1['reading_mode']!r}")

    result_type3 = grid_scoring.compute_grid_score(_make_all_non(), document_type=3)
    _test("document_type=3 reporté dans le résultat", result_type3["document_type"] == 3,
          f"Obtenu : {result_type3['document_type']}")
    _test("document_type=3 : reading_mode='suivi'", result_type3["reading_mode"] == "suivi",
          f"Obtenu : {result_type3['reading_mode']!r}")
    _test("document_type n'affecte pas le score (mêmes réponses)",
          result_type1["score"] == result_type3["score"],
          f"type1={result_type1['score']} vs type3={result_type3['score']}")

    # --- Verrou B.2.1→B.2.2 (CC-08) toujours intégré en V4 ---
    answers_verrou = _make_answers({"B.2.1": {"status": "OUI"}, "B.2.2": {"status": "NON"}})
    result_verrou = grid_scoring.compute_grid_score(answers_verrou)
    detail_b22 = _find_detail(result_verrou, "B.2.2")
    _test("Verrou B.2.1→B.2.2 toujours actif en V4 : B.2.2 forcé à INCONNU",
          detail_b22["status"] == "INCONNU", f"Obtenu : {detail_b22['status']!r}")

    # --- CC-07 non régressé : MITIGATION_STATUTS / garde-fou statut 4 ---
    _test("MITIGATION_STATUTS non modifié par la V4 (4 statuts)",
          len(grid_questions.MITIGATION_STATUTS) == 4,
          f"Obtenu : {len(grid_questions.MITIGATION_STATUTS)}")

    answers_gf = _make_answers({"B.1.1": {
        "status": "OUI", "mitigation_status": "OUI_DEFAILLANTE",
        "evidence_a": {"verbatim_mesure": None, "verbatim_defaillance": None},
    }})
    result_gf = grid_scoring.compute_grid_score(answers_gf)
    detail_gf = _find_detail(result_gf, "B.1.1")
    _test("Garde-fou statut 4 (CC-07) toujours actif en V4 : retombe sur OUI_PROUVEE",
          detail_gf["mitigation_status"] == "OUI_PROUVEE", f"Obtenu : {detail_gf['mitigation_status']!r}")


def test_grid_result():
    """Tests du format de résultat V3 (grid_result.py, directive CC-03)."""
    print("\n--- 1.8 Format de résultat Grille V3 (grid_result.py) ---\n")

    import json

    import grid_scoring
    import grid_result

    def _question_results_from_answers(answers):
        return {
            code: {**ans, "evidence_r": None, "evidence_a": None, "confidence_note": None}
            for code, ans in answers.items()
        }

    # 1. build_grid_result avec des données valides -> validate_grid_result ne lève pas
    answers = _zero_risk_grid_answers()
    answers["A.1.1"] = {"status": "OUI", "mitigation_status": "OUI_PROUVEE"}
    scoring = grid_scoring.compute_grid_score(answers)
    result = grid_result.build_grid_result(_question_results_from_answers(answers), scoring)
    try:
        grid_result.validate_grid_result(result)
        _test("Test 1 : résultat valide -> pas d'exception", True)
    except ValueError as e:
        _test("Test 1 : résultat valide -> pas d'exception", False, str(e))

    # 2. Résultat avec code inconnu -> ValueError
    bad_result = json.loads(json.dumps(result))
    bad_result["questions"][0]["code"] = "Z.9.9"
    try:
        grid_result.validate_grid_result(bad_result)
        _test("Test 2 : code inconnu -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("Test 2 : code inconnu -> ValueError", True)

    # 3. Résultat avec status invalide -> ValueError
    bad_result = json.loads(json.dumps(result))
    bad_result["questions"][0]["status"] = "PEUT-ÊTRE"
    try:
        grid_result.validate_grid_result(bad_result)
        _test("Test 3 : status invalide -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("Test 3 : status invalide -> ValueError", True)

    # 4. Résultat avec mitigation sur une question NA -> ValueError
    bad_result = json.loads(json.dumps(result))
    for q in bad_result["questions"]:
        if q["code"] == "B.2.1":
            q["status"] = "NA"
            q["mitigation_status"] = "OUI_PROUVEE"
    try:
        grid_result.validate_grid_result(bad_result)
        _test("Test 4 : mitigation sur question NA -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("Test 4 : mitigation sur question NA -> ValueError", True)

    # 5. Résultat avec mitigation sur B.3.1 -> ValueError
    bad_result = json.loads(json.dumps(result))
    for q in bad_result["questions"]:
        if q["code"] == "B.3.1":
            q["mitigation_status"] = "OUI_PROUVEE"
    try:
        grid_result.validate_grid_result(bad_result)
        _test("Test 5 : mitigation sur B.3.1 -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("Test 5 : mitigation sur B.3.1 -> ValueError", True)

    # 6. json.dumps(result) fonctionne sans erreur
    try:
        json.dumps(result)
        _test("Test 6 : json.dumps sans erreur", True)
    except TypeError as e:
        _test("Test 6 : json.dumps sans erreur", False, str(e))

    # 7. B.3.1 avec status="NON" -> penalty = -15 dans le résultat
    answers_b31 = _zero_risk_grid_answers()
    answers_b31["B.3.1"] = {"status": "NON"}
    scoring_b31 = grid_scoring.compute_grid_score(answers_b31)
    result_b31 = grid_result.build_grid_result(_question_results_from_answers(answers_b31), scoring_b31)
    b31_entry = next(q for q in result_b31["questions"] if q["code"] == "B.3.1")
    _test("Test 7 : B.3.1 NON -> penalty=-15", b31_entry["penalty"] == -15, f"Obtenu : {b31_entry['penalty']}")

    # 8. OUI_DEFAILLANTE sans les deux verbatims -> ValueError (CC-07 —
    # validate_grid_result est STRICT ici, contrairement à
    # compute_grid_score qui corrige silencieusement, cf. grid_result.py)
    bad_result = json.loads(json.dumps(result))
    for q in bad_result["questions"]:
        if q["code"] == "B.2.2":
            q["mitigation_status"] = "OUI_DEFAILLANTE"
            q["evidence_a"] = {"verbatim_mesure": "filters installed", "verbatim_defaillance": ""}
    try:
        grid_result.validate_grid_result(bad_result)
        _test("Test 8 : OUI_DEFAILLANTE sans double verbatim -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("Test 8 : OUI_DEFAILLANTE sans double verbatim -> ValueError", True)

    # 9. evidence_a fournie alors que mitigation_status=None -> ValueError (CC-07)
    bad_result = json.loads(json.dumps(result))
    for q in bad_result["questions"]:
        if q["code"] == "B.2.2":
            q["mitigation_status"] = None
            q["evidence_a"] = {"verbatim_mesure": "filters installed", "verbatim_defaillance": None}
    try:
        grid_result.validate_grid_result(bad_result)
        _test("Test 9 : evidence_a sans mitigation_status -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("Test 9 : evidence_a sans mitigation_status -> ValueError", True)

    # 10. status=NA sans verbatim (evidence_r) -> ValueError (CC-08 —
    # cf. grid_questions.SILENCE_VALUES["NA"] : "verbatim obligatoire")
    bad_result = json.loads(json.dumps(result))
    for q in bad_result["questions"]:
        if q["code"] == "B.2.1":
            q["status"] = "NA"
            q["evidence_r"] = None
    try:
        grid_result.validate_grid_result(bad_result)
        _test("Test 10 : status=NA sans verbatim -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("Test 10 : status=NA sans verbatim -> ValueError", True)


def test_grid_result_v4():
    """Tests du format de résultat V4 (grid_result.py, directive CC-V4-03) :
    grid_version, document_type/reading_mode, garde-fou mitigation basé sur
    a_condition (B.3.1), champ qualifying optionnel."""
    print("\n--- 1.8b Format de résultat Grille V4 (grid_result.py) ---\n")

    import json

    import grid_questions
    import grid_scoring
    import grid_result

    def _question_results_from_answers(answers):
        return {
            code: {**ans, "evidence_r": None, "evidence_a": None, "confidence_note": None}
            for code, ans in answers.items()
        }

    base_answers = _make_all_non()
    scoring = grid_scoring.compute_grid_score(base_answers, document_type=2)
    result = grid_result.build_grid_result(_question_results_from_answers(base_answers), scoring)

    # 1. grid_version == "V4"
    _test("grid_version == 'V4'", result["grid_version"] == "V4", f"Obtenu : {result['grid_version']!r}")

    # 2. 12 questions dans le résultat
    _test("12 questions dans le résultat", len(result["questions"]) == 12,
          f"Obtenu : {len(result['questions'])}")

    # 3. document_type et reading_mode présents
    _test("document_type=2 reporté dans le résultat", result["document_type"] == 2,
          f"Obtenu : {result['document_type']}")
    _test("reading_mode='suivi' (document_type=2)", result["reading_mode"] == "suivi",
          f"Obtenu : {result['reading_mode']!r}")
    _test("reading_mode_label présent", bool(result["reading_mode_label"]))
    try:
        grid_result.validate_grid_result(result)
        _test("Résultat de base -> validate_grid_result ne lève pas", True)
    except ValueError as e:
        _test("Résultat de base -> validate_grid_result ne lève pas", False, str(e))

    # 4. B.3.1 avec status=NON et mitigation_status=OUI_PROUVEE -> valide
    answers_b31_valide = _make_answers({"B.3.1": {"status": "NON", "mitigation_status": "OUI_PROUVEE"}})
    scoring_b31_valide = grid_scoring.compute_grid_score(answers_b31_valide)
    result_b31_valide = grid_result.build_grid_result(
        _question_results_from_answers(answers_b31_valide), scoring_b31_valide
    )
    try:
        grid_result.validate_grid_result(result_b31_valide)
        _test("B.3.1 NON + mitigation OUI_PROUVEE -> valide", True)
    except ValueError as e:
        _test("B.3.1 NON + mitigation OUI_PROUVEE -> valide", False, str(e))
    b31_entry = next(q for q in result_b31_valide["questions"] if q["code"] == "B.3.1")
    _test("B.3.1 : a_condition='r_non' reporté dans le résultat",
          b31_entry["a_condition"] == "r_non", f"Obtenu : {b31_entry['a_condition']!r}")

    # 5. B.3.1 avec status=OUI et mitigation_status fourni -> ValueError
    bad_result = json.loads(json.dumps(result))
    for q in bad_result["questions"]:
        if q["code"] == "B.3.1":
            q["status"] = "OUI"
            q["mitigation_status"] = "OUI_PROUVEE"
    try:
        grid_result.validate_grid_result(bad_result)
        _test("B.3.1 OUI + mitigation -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("B.3.1 OUI + mitigation -> ValueError", True)

    # 6. json.dumps(result) fonctionne
    try:
        json.dumps(result)
        _test("json.dumps(result) sans erreur", True)
    except TypeError as e:
        _test("json.dumps(result) sans erreur", False, str(e))

    # 7. qualifying peut être None
    _test("qualifying=None par défaut (non fourni en entrée)",
          all(q["qualifying"] is None for q in result["questions"]))

    # 8. qualifying avec allegation remplie -> valide
    answers_qual = _make_answers({"A.2.1": {"status": "NON"}})
    question_results_qual = _question_results_from_answers(answers_qual)
    question_results_qual["A.2.1"]["qualifying"] = {
        "allegation": "ONG locale allègue un déversement, non confirmé par le rapport.",
        "access_denied": False,
    }
    scoring_qual = grid_scoring.compute_grid_score(answers_qual)
    result_qual = grid_result.build_grid_result(question_results_qual, scoring_qual)
    a21_entry = next(q for q in result_qual["questions"] if q["code"] == "A.2.1")
    _test("qualifying avec allegation remplie -> reporté tel quel",
          a21_entry["qualifying"] is not None and "allegation" in a21_entry["qualifying"],
          f"Obtenu : {a21_entry['qualifying']!r}")
    try:
        grid_result.validate_grid_result(result_qual)
        _test("qualifying avec allegation remplie -> validate_grid_result ne lève pas", True)
    except ValueError as e:
        _test("qualifying avec allegation remplie -> validate_grid_result ne lève pas", False, str(e))

    # --- document_type invalide -> ValueError ---
    bad_result = json.loads(json.dumps(result))
    bad_result["document_type"] = 99
    try:
        grid_result.validate_grid_result(bad_result)
        _test("document_type invalide (99) -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("document_type invalide (99) -> ValueError", True)

    # --- color V4 (JAUNE) accepté ---
    _test("_VALID_COLORS accepte JAUNE (zones V4)", "JAUNE" in grid_result._VALID_COLORS,
          f"Obtenu : {grid_result._VALID_COLORS}")

    # --- qualifying de type invalide -> ValueError ---
    bad_result = json.loads(json.dumps(result))
    bad_result["questions"][0]["qualifying"] = "pas un dict"
    try:
        grid_result.validate_grid_result(bad_result)
        _test("qualifying non-dict -> ValueError", False, "Aucune exception levée")
    except ValueError:
        _test("qualifying non-dict -> ValueError", True)


def _make_all_non():
    """Retourne un dict answers avec toutes les questions à NON.
    NOTE: pour B.3.1 (schéma inversé), status="NON" signifie RISQUE
    (-15 pts), pas "sans risque" — cf. grid_questions.py::inverted_polarity.
    Les tests qui utilisent ce helper pour un total agrégé en tiennent
    compte explicitement (cf. test_mitigation_4_statuts, "Score global CBG")."""
    import grid_questions
    return {q["code"]: {"status": "NON"} for q in grid_questions.ESG_QUESTIONS}


def _make_answers(overrides):
    """Retourne un dict answers avec toutes les questions à NON,
    sauf celles spécifiées dans overrides."""
    base = _make_all_non()
    base.update(overrides)
    return base


def _find_detail(result, code):
    """Trouve le détail d'une question dans le résultat."""
    for d in result["details"]:
        if d["code"] == code:
            return d
    raise ValueError(f"Code {code} non trouvé dans les détails")


def test_mitigation_4_statuts():
    """Tests des 4 statuts de mitigation (passe CBG, directive CC-07)."""
    print("\n--- 1.10 Mitigation à 4 statuts (passe CBG) ---\n")

    import grid_questions
    import grid_scoring

    # --- Structure ---
    _test("MITIGATION_STATUTS contient exactement 4 clés",
          len(grid_questions.MITIGATION_STATUTS) == 4,
          f"Obtenu : {len(grid_questions.MITIGATION_STATUTS)}")

    _test("Chaque statut a label/points_multiplier/description",
          all("label" in v and "points_multiplier" in v and "description" in v
              for v in grid_questions.MITIGATION_STATUTS.values()))

    _test("points_multiplier ∈ {0, 1} pour tous les statuts",
          all(v["points_multiplier"] in (0, 1) for v in grid_questions.MITIGATION_STATUTS.values()))

    _test("Seul OUI_PROUVEE a points_multiplier == 1",
          grid_questions.MITIGATION_STATUTS["OUI_PROUVEE"]["points_multiplier"] == 1)
    _test("NON_INTENTION/NON_FORME_INSUFFISANTE/OUI_DEFAILLANTE ont points_multiplier == 0",
          all(grid_questions.MITIGATION_STATUTS[k]["points_multiplier"] == 0
              for k in ("NON_INTENTION", "NON_FORME_INSUFFISANTE", "OUI_DEFAILLANTE")))

    # --- Scoring statut 1 : intention ---
    # "The company will implement..." -> NON_INTENTION
    answers_s1 = _make_answers({"B.1.1": {"status": "OUI", "mitigation_status": "NON_INTENTION"}})
    result_s1 = grid_scoring.compute_grid_score(answers_s1)
    detail_s1 = _find_detail(result_s1, "B.1.1")
    _test("Statut 1 (intention) : pénalité -15", detail_s1["penalty"] == -15, f"Obtenu : {detail_s1['penalty']}")
    _test("Statut 1 (intention) : gain 0", detail_s1["gain"] == 0, f"Obtenu : {detail_s1['gain']}")

    # --- Scoring statut 2 : forme insuffisante ---
    # "A complaints register was opened in 2015" -> NON_FORME_INSUFFISANTE
    answers_s2 = _make_answers({"B.1.2": {"status": "OUI", "mitigation_status": "NON_FORME_INSUFFISANTE"}})
    result_s2 = grid_scoring.compute_grid_score(answers_s2)
    detail_s2 = _find_detail(result_s2, "B.1.2")
    _test("Statut 2 (forme insuffisante) : gain 0", detail_s2["gain"] == 0, f"Obtenu : {detail_s2['gain']}")

    # --- Scoring statut 3 : prouvée ---
    # "24 of 31 complaints have been processed and closed" -> OUI_PROUVEE
    answers_s3 = _make_answers({"B.1.2": {"status": "OUI", "mitigation_status": "OUI_PROUVEE"}})
    result_s3 = grid_scoring.compute_grid_score(answers_s3)
    detail_s3 = _find_detail(result_s3, "B.1.2")
    _test("Statut 3 (prouvée) : gain +3 (Cat B)", detail_s3["gain"] == 3, f"Obtenu : {detail_s3['gain']}")

    # --- Scoring statut 4 : défaillante ---
    # Filtres installés MAIS poussières persistantes -> OUI_DEFAILLANTE
    answers_s4 = _make_answers({"B.2.2": {
        "status": "OUI",
        "mitigation_status": "OUI_DEFAILLANTE",
        "evidence_a": {
            "verbatim_mesure": "additional filters and scrubbers were installed",
            "verbatim_defaillance": "generated significant quantities of fugitive dust",
            "page": None,
        },
    }})
    result_s4 = grid_scoring.compute_grid_score(answers_s4)
    detail_s4 = _find_detail(result_s4, "B.2.2")
    _test("Statut 4 (défaillante, avec double verbatim) : gain 0", detail_s4["gain"] == 0, f"Obtenu : {detail_s4['gain']}")

    # --- Garde-fou : statut 4 sans double verbatim -> retour en statut 3 ---
    answers_gf = _make_answers({"B.2.2": {
        "status": "OUI",
        "mitigation_status": "OUI_DEFAILLANTE",
        "evidence_a": {
            "verbatim_mesure": "filters installed",
            "verbatim_defaillance": "",  # vide -> garde-fou
            "page": None,
        },
    }})
    result_gf = grid_scoring.compute_grid_score(answers_gf)
    detail_gf = _find_detail(result_gf, "B.2.2")
    _test("Garde-fou statut 4 sans double verbatim -> retombe OUI_PROUVEE (+3)",
          detail_gf["gain"] == 3, f"Obtenu : {detail_gf['gain']}")
    _test("Garde-fou : mitigation_status résolu = OUI_PROUVEE dans le détail",
          detail_gf["mitigation_status"] == "OUI_PROUVEE", f"Obtenu : {detail_gf['mitigation_status']!r}")

    # --- Scoring Cat A avec mitigation prouvée ---
    answers_a = _make_answers({"A.1.1": {"status": "OUI", "mitigation_status": "OUI_PROUVEE"}})
    result_a = grid_scoring.compute_grid_score(answers_a)
    detail_a = _find_detail(result_a, "A.1.1")
    _test("Cat A prouvée : pénalité -25", detail_a["penalty"] == -25, f"Obtenu : {detail_a['penalty']}")
    _test("Cat A prouvée : gain +5", detail_a["gain"] == 5, f"Obtenu : {detail_a['gain']}")

    # --- Score global CBG (vérifié manuellement) ---
    # B.1.1 OUI, mit=NON_INTENTION -> -15, +0
    # B.1.2 OUI, mit=OUI_PROUVEE -> -15, +3
    # B.2.1 OUI, mit=NON_FORME_INSUFFISANTE -> -15, +0
    # B.2.2 OUI, mit=OUI_DEFAILLANTE (avec 2 verbatims) -> -15, +0
    # B.3.1 NON (inversé = risque) -> -15
    # Reste = NON (standard, sans risque) -> 0
    # Total pénalités = -75, gains = +3, score = 100 - 75 + 3 = 28
    answers_cbg = _make_all_non()
    answers_cbg["B.1.1"] = {"status": "OUI", "mitigation_status": "NON_INTENTION"}
    answers_cbg["B.1.2"] = {"status": "OUI", "mitigation_status": "OUI_PROUVEE"}
    answers_cbg["B.2.1"] = {"status": "OUI", "mitigation_status": "NON_FORME_INSUFFISANTE"}
    answers_cbg["B.2.2"] = {
        "status": "OUI", "mitigation_status": "OUI_DEFAILLANTE",
        "evidence_a": {
            "verbatim_mesure": "additional filters and scrubbers were installed on the dryer stack in recent years",
            "verbatim_defaillance": "generated significant quantities of fugitive dust as well as particulate and gaseous emissions",
            "page": None,
        },
    }
    answers_cbg["B.3.1"] = {"status": "NON"}  # inversé = risque
    result_cbg = grid_scoring.compute_grid_score(answers_cbg)
    _test("Score global CBG = 28/100", result_cbg["score"] == 28, f"Obtenu : {result_cbg['score']}")
    # get_color V4 (CC-V4-02) : 28 est ORANGE (25-49) en V4, pas ROUGE (V3: <50).
    _test("Score global CBG -> ORANGE (zones V4)", result_cbg["color"] == "ORANGE", f"Obtenu : {result_cbg['color']}")

    # --- Rétro-compatibilité CC-02 : ancien champ "mitigation" OUI/NON ---
    answers_legacy = _make_answers({"A.1.1": {"status": "OUI", "mitigation": "OUI"}})
    result_legacy = grid_scoring.compute_grid_score(answers_legacy)
    detail_legacy = _find_detail(result_legacy, "A.1.1")
    _test("Rétro-compat : mitigation='OUI' (ancien format) -> converti en OUI_PROUVEE (+5)",
          detail_legacy["gain"] == 5, f"Obtenu : {detail_legacy['gain']}")
    _test("Rétro-compat : mitigation_status résolu = OUI_PROUVEE",
          detail_legacy["mitigation_status"] == "OUI_PROUVEE", f"Obtenu : {detail_legacy['mitigation_status']!r}")


def test_silence_evenement_etat():
    """Tests des règles de silence événement/état (passe CBG, directive CC-08)."""
    print("\n--- 1.11 Règles de silence événement/état (passe CBG) ---\n")

    import grid_questions
    import grid_scoring

    # --- Classification correcte (cf. tableau CC-08) ---
    _test("A.1.1 silence_type='evenement'",
          grid_questions.get_question("A.1.1")["silence_type"] == "evenement")
    _test("B.1.2 silence_type='etat'",
          grid_questions.get_question("B.1.2")["silence_type"] == "etat")
    _test("B.2.1 silence_type='etat'",
          grid_questions.get_question("B.2.1")["silence_type"] == "etat")
    _test("B.2.2 silence_type='etat'",
          grid_questions.get_question("B.2.2")["silence_type"] == "etat")
    _test("B.2.3 silence_type='evenement'",
          grid_questions.get_question("B.2.3")["silence_type"] == "evenement")
    _test("B.3.1 silence_type='etat'",
          grid_questions.get_question("B.3.1")["silence_type"] == "etat")
    _test("Toutes les questions ont silence_type ∈ {evenement, etat}",
          all(q["silence_type"] in ("evenement", "etat") for q in grid_questions.ESG_QUESTIONS))

    # --- Silence événement -> NON, aucune pénalité -> score=100.
    # FRAGILE: _make_all_non() met aussi B.3.1 à "NON", qui sous le schéma
    # inversé de B.3.1 signifie RISQUE (-15 pts), pas "sans risque" — cf.
    # commentaire de _make_all_non(). On force donc B.3.1="OUI" (sa vraie
    # valeur "sans risque") pour que ce test isole bien l'effet du silence
    # sur les 9 questions à schéma standard, sans le bruit de l'inversion.
    answers_evt = _make_answers({"B.3.1": {"status": "OUI"}})
    result_evt = grid_scoring.compute_grid_score(answers_evt)
    _test("Silence événement (NON sur les 9 questions standard) -> score=100",
          result_evt["score"] == 100, f"Obtenu : {result_evt['score']}")

    # --- Silence état -> INCONNU, pénalité 0 ---
    answers_etat = _make_answers({"B.2.1": {"status": "INCONNU"}})
    result_etat = grid_scoring.compute_grid_score(answers_etat)
    detail_etat = _find_detail(result_etat, "B.2.1")
    _test("Silence état (B.2.1=INCONNU) -> pénalité 0",
          detail_etat["penalty"] == 0, f"Obtenu : {detail_etat['penalty']}")

    # --- INCONNU ne se convertit jamais en NON (ni l'inverse) ---
    answers_inconnu = _make_answers({"B.1.2": {"status": "INCONNU"}})
    result_inconnu = grid_scoring.compute_grid_score(answers_inconnu)
    detail_inconnu = _find_detail(result_inconnu, "B.1.2")
    _test("INCONNU n'est jamais reconverti en NON",
          detail_inconnu["status"] == "INCONNU", f"Obtenu : {detail_inconnu['status']!r}")


def test_verrou_b21_b22():
    """Test du verrou logique B.2.1 -> B.2.2 (passe CBG, directive CC-08)."""
    print("\n--- 1.12 Verrou B.2.1→B.2.2 (passe CBG) ---\n")

    import grid_scoring

    # --- B.2.1 = OUI + B.2.2 = NON -> B.2.2 forcé à INCONNU ---
    answers_verrou = _make_all_non()
    answers_verrou["B.2.1"] = {"status": "OUI", "mitigation_status": "NON_INTENTION"}
    answers_verrou["B.2.2"] = {"status": "NON"}  # devrait être forcé à INCONNU
    result_verrou = grid_scoring.compute_grid_score(answers_verrou)
    detail_b22 = _find_detail(result_verrou, "B.2.2")
    _test("Verrou : B.2.1=OUI + B.2.2=NON -> B.2.2 forcé à INCONNU",
          detail_b22["status"] == "INCONNU", f"Obtenu : {detail_b22['status']!r}")
    _test("Verrou : B.2.2 forcé -> pénalité 0",
          detail_b22["penalty"] == 0, f"Obtenu : {detail_b22['penalty']}")
    _test("Verrou : verrou_applique=True pour B.2.2",
          detail_b22["verrou_applique"] is True, f"Obtenu : {detail_b22['verrou_applique']!r}")

    # --- B.2.1 = NON + B.2.2 = NON -> pas de verrou ---
    answers_no_verrou = _make_all_non()
    result_nv = grid_scoring.compute_grid_score(answers_no_verrou)
    detail_b22_nv = _find_detail(result_nv, "B.2.2")
    _test("Pas de verrou si B.2.1=NON : B.2.2 reste NON",
          detail_b22_nv["status"] == "NON", f"Obtenu : {detail_b22_nv['status']!r}")
    _test("Pas de verrou si B.2.1=NON : verrou_applique=False",
          detail_b22_nv["verrou_applique"] is False, f"Obtenu : {detail_b22_nv['verrou_applique']!r}")

    # --- B.2.1 = OUI + B.2.2 = OUI -> pas de verrou (le risque est documenté) ---
    answers_oui = _make_all_non()
    answers_oui["B.2.1"] = {"status": "OUI", "mitigation_status": "NON_INTENTION"}
    answers_oui["B.2.2"] = {"status": "OUI", "mitigation_status": "NON_INTENTION"}
    result_oui = grid_scoring.compute_grid_score(answers_oui)
    detail_b22_oui = _find_detail(result_oui, "B.2.2")
    _test("Pas de verrou si B.2.2=OUI (risque déjà documenté)",
          detail_b22_oui["status"] == "OUI", f"Obtenu : {detail_b22_oui['status']!r}")
    _test("Pas de verrou si B.2.2=OUI : pénalité -15 conservée",
          detail_b22_oui["penalty"] == -15, f"Obtenu : {detail_b22_oui['penalty']}")


def test_flag_atteste():
    """Test du flag attesté (NON + verbatim explicite), directive CC-08.
    Le flag est calculé dans build_grid_result (pas dans le scoring) —
    atteste = (status == "NON" and evidence_r is not None), cf. sa
    docstring. Ne change PAS le score, change seulement la lisibilité."""
    print("\n--- 1.13 Flag attesté (passe CBG) ---\n")

    import grid_scoring
    import grid_result

    def _question_results_from_answers(answers):
        return {
            code: {**ans, "evidence_a": None, "confidence_note": None}
            for code, ans in answers.items()
        }

    # --- NON + verbatim explicite -> atteste=True ---
    answers = _make_answers({"B.3.1": {"status": "OUI"}, "A.1.1": {"status": "NON"}})
    question_results = _question_results_from_answers(answers)
    question_results["A.1.1"]["evidence_r"] = {
        "passage": "Fieldwork confirmed the absence of any labor dispute.", "page": 12,
    }
    scoring = grid_scoring.compute_grid_score(answers)
    result = grid_result.build_grid_result(question_results, scoring)
    a11 = next(q for q in result["questions"] if q["code"] == "A.1.1")
    _test("NON + evidence_r non-None -> atteste=True", a11["atteste"] is True, f"Obtenu : {a11['atteste']!r}")

    try:
        grid_result.validate_grid_result(result)
        _test("Résultat avec atteste=True -> validate_grid_result ne lève pas", True)
    except ValueError as e:
        _test("Résultat avec atteste=True -> validate_grid_result ne lève pas", False, str(e))

    # --- NON sans verbatim (silence) -> atteste=False ---
    question_results_silence = _question_results_from_answers(answers)
    question_results_silence["A.1.1"]["evidence_r"] = None
    scoring_silence = grid_scoring.compute_grid_score(answers)
    result_silence = grid_result.build_grid_result(question_results_silence, scoring_silence)
    a11_silence = next(q for q in result_silence["questions"] if q["code"] == "A.1.1")
    _test("NON sans evidence_r -> atteste=False", a11_silence["atteste"] is False, f"Obtenu : {a11_silence['atteste']!r}")

    # --- OUI + verbatim -> atteste=False (atteste exige status=NON, pas juste une preuve) ---
    answers_oui = _make_answers({
        "B.3.1": {"status": "OUI"},
        "A.1.1": {"status": "OUI", "mitigation_status": "NON_INTENTION"},
    })
    question_results_oui = _question_results_from_answers(answers_oui)
    question_results_oui["A.1.1"]["evidence_r"] = {"passage": "A strike occurred on site in March.", "page": 3}
    scoring_oui = grid_scoring.compute_grid_score(answers_oui)
    result_oui = grid_result.build_grid_result(question_results_oui, scoring_oui)
    a11_oui = next(q for q in result_oui["questions"] if q["code"] == "A.1.1")
    _test("OUI + evidence_r -> atteste=False (atteste exige status=NON)",
          a11_oui["atteste"] is False, f"Obtenu : {a11_oui['atteste']!r}")


def test_esap_exclusion():
    """Test de l'exclusion ESAP (passe CBG, directive CC-09)."""
    print("\n--- 1.14a Exclusion ESAP (grid_sections.py) ---\n")

    import grid_sections

    chunks_with_esap = [
        {"text": "The project has significant impacts on biodiversity.", "page": 1},
        {"text": "Environmental and Social Action Plan\nItem 1: Prepare a Livelihood Restoration Plan", "page": 5},
        {"text": "Item 2: Finalize the Past Compensation Report (2010-2015)", "page": 5},
        {"text": "Item 3: Complete establishment of a data management system", "page": 6},
        {"text": "The project area includes critical habitat for chimpanzees.", "page": 8},
    ]
    classified = grid_sections.classify_chunks(chunks_with_esap)
    _test("Chunk avant ESAP : section_tag=None", classified[0]["section_tag"] is None,
          f"Obtenu : {classified[0]['section_tag']!r}")
    _test("Chunk titre ESAP (Item 1) : section_tag='esap'", classified[1]["section_tag"] == "esap",
          f"Obtenu : {classified[1]['section_tag']!r}")
    _test("Chunk ESAP (Item 2) : section_tag='esap'", classified[2]["section_tag"] == "esap",
          f"Obtenu : {classified[2]['section_tag']!r}")
    _test("Chunk ESAP (Item 3) : section_tag='esap'", classified[3]["section_tag"] == "esap",
          f"Obtenu : {classified[3]['section_tag']!r}")
    _test("Chunk après ESAP : section_tag=None", classified[4]["section_tag"] is None,
          f"Obtenu : {classified[4]['section_tag']!r}")

    # --- Question de risque (R) : les chunks ESAP sont INCLUS ---
    r_chunks = grid_sections.get_chunks_for_question(classified, "B.2.1")
    _test("Question R : chunks ESAP inclus (renseignent le risque)",
          len([c for c in r_chunks if c["section_tag"] == "esap"]) > 0)

    # --- Question de mitigation (A) : les chunks ESAP sont EXCLUS ---
    a_chunks = grid_sections.get_chunks_for_question(classified, "B.2.1", for_mitigation=True)
    _test("Question A (mitigation) : chunks ESAP exclus",
          len([c for c in a_chunks if c["section_tag"] == "esap"]) == 0)


def test_ifc_complaints_exclusion():
    """Test de l'exclusion de la section plaintes IFC (directive CC-09)."""
    print("\n--- 1.14b Exclusion section plaintes IFC (grid_sections.py) ---\n")

    import grid_sections

    chunks_with_complaints = [
        {"text": "The project has 31 unresolved complaints.", "page": 10},
        {"text": "Information on E&S Complaints and Grievance Mechanisms\nAffected communities have unrestricted access to the Compliance Advisor Ombudsman (CAO).", "page": 15},
        {"text": "The CAO is mandated to address complaints from people affected by IFC projects.", "page": 15},
    ]
    classified = grid_sections.classify_chunks(chunks_with_complaints)
    _test("Chunk avant section plaintes : section_tag=None", classified[0]["section_tag"] is None,
          f"Obtenu : {classified[0]['section_tag']!r}")
    _test("Chunk titre section plaintes : section_tag='ifc_complaints'",
          classified[1]["section_tag"] == "ifc_complaints", f"Obtenu : {classified[1]['section_tag']!r}")
    _test("Chunk suite section plaintes : section_tag='ifc_complaints'",
          classified[2]["section_tag"] == "ifc_complaints", f"Obtenu : {classified[2]['section_tag']!r}")

    # --- Chunks ifc_complaints exclus de TOUT (R et A) ---
    r_chunks = grid_sections.get_chunks_for_question(classified, "A.2.1")
    _test("Question R : chunks ifc_complaints exclus",
          all(c["section_tag"] != "ifc_complaints" for c in r_chunks))
    a_chunks = grid_sections.get_chunks_for_question(classified, "A.2.1", for_mitigation=True)
    _test("Question A : chunks ifc_complaints exclus",
          all(c["section_tag"] != "ifc_complaints" for c in a_chunks))


def test_no_sections_detected():
    """Si aucune section spéciale n'est détectée, tous les chunks passent
    inchangés (fail-open, cf. ADR-002 et grid_sections.py)."""
    print("\n--- 1.14c Aucune section détectée -> fail-open (grid_sections.py) ---\n")

    import grid_sections

    chunks_normal = [
        {"text": "Normal project description.", "page": 1},
        {"text": "Some environmental data.", "page": 2},
    ]
    classified = grid_sections.classify_chunks(chunks_normal)
    _test("Aucun chunk taggé", all(c["section_tag"] is None for c in classified))
    _test("get_chunks_for_question renvoie tous les chunks",
          len(grid_sections.get_chunks_for_question(classified, "A.1.1")) == 2,
          f"Obtenu : {len(grid_sections.get_chunks_for_question(classified, 'A.1.1'))}")


def test_temporal_layer_marking():
    """Test du marquage best-effort des couches temporelles (grid_sections.py,
    addition V4, directive CC-V4-04) — bonus non bloquant, cf. R8."""
    print("\n--- 1.14d Marquage couches temporelles (grid_sections.py, bonus V4) ---\n")

    import grid_sections

    # --- Détection + persistance jusqu'au titre suivant ---
    chunks = [
        {"text": "Introduction generale du rapport de suivi.", "page": 1},
        {"text": "Summary of First Monitoring Period\nNo major incidents reported.", "page": 3},
        {"text": "Water quality remained within permitted limits during this period.", "page": 4},
        {"text": "Third Monitoring Period\nA grievance was filed by local residents.", "page": 20},
        {"text": "The grievance was resolved through the community mechanism.", "page": 21},
    ]
    classified = grid_sections.classify_chunks(chunks)
    _test("Avant tout titre de période : section_tag=None",
          classified[0]["section_tag"] is None, f"Obtenu : {classified[0]['section_tag']!r}")
    _test("Titre 'First Monitoring Period' -> temporal_layer_1",
          classified[1]["section_tag"] == "temporal_layer_1", f"Obtenu : {classified[1]['section_tag']!r}")
    _test("Chunk suivant (même période) -> temporal_layer_1 persiste",
          classified[2]["section_tag"] == "temporal_layer_1", f"Obtenu : {classified[2]['section_tag']!r}")
    _test("Titre 'Third Monitoring Period' -> temporal_layer_3",
          classified[3]["section_tag"] == "temporal_layer_3", f"Obtenu : {classified[3]['section_tag']!r}")
    _test("Chunk suivant (période 3) -> temporal_layer_3 persiste",
          classified[4]["section_tag"] == "temporal_layer_3", f"Obtenu : {classified[4]['section_tag']!r}")

    # --- Fail-open : pas de titre de période -> tous None ---
    chunks_no_period = [
        {"text": "Le projet respecte les normes environnementales en vigueur.", "page": 1},
        {"text": "Aucune plainte n'a été enregistrée sur la période.", "page": 2},
    ]
    classified_no_period = grid_sections.classify_chunks(chunks_no_period)
    _test("Pas de titre de période détecté -> tous les chunks à None",
          all(c["section_tag"] is None for c in classified_no_period))

    # --- Priorité : exclusion ESAP/plaintes IFC toujours prioritaire ---
    chunks_esap_wins = [
        {"text": "Third Monitoring Period", "page": 20},
        {"text": "Environmental and Social Action Plan\nItem 1: Prepare a Livelihood Restoration Plan", "page": 21},
    ]
    classified_esap_wins = grid_sections.classify_chunks(chunks_esap_wins)
    _test("Titre ESAP après un titre de période -> 'esap' prioritaire (pas temporal_layer)",
          classified_esap_wins[1]["section_tag"] == "esap",
          f"Obtenu : {classified_esap_wins[1]['section_tag']!r}")

    # --- get_chunks_for_question n'exclut PAS les couches temporelles ---
    r_chunks = grid_sections.get_chunks_for_question(classified, "A.1.1")
    _test("Couches temporelles non exclues des chunks R",
          len([c for c in r_chunks if c["section_tag"] == "temporal_layer_1"]) > 0)
    a_chunks = grid_sections.get_chunks_for_question(classified, "A.1.1", for_mitigation=True)
    _test("Couches temporelles non exclues des chunks A (mitigation)",
          len([c for c in a_chunks if c["section_tag"] == "temporal_layer_3"]) > 0)


def test_grid_analyze_v4():
    """Tests d'intégration de l'orchestrateur V4 (grid_analyze.py, directive
    CC-V4-06). Backend LLM monkey-patché (même idiome que la section 1.5,
    llm_backend._dispatch) — pas d'appel réseau réel."""
    print("\n--- 1.15 Orchestrateur Grille V4 (grid_analyze.py) ---\n")

    import config
    import llm_backend
    import grid_result
    import grid_analyze

    # 1. GRID_V4_ENABLED=False -> None (renommé depuis GRID_V3_ENABLED, CC-V4-08)
    _orig_enabled = config.GRID_V4_ENABLED
    config.GRID_V4_ENABLED = False
    try:
        _test("GRID_V4_ENABLED=False -> analyze_grid() retourne None",
              grid_analyze.analyze_grid([{"text": "peu importe", "page": 1}]) is None)
    finally:
        config.GRID_V4_ENABLED = _orig_enabled

    # --- Backend LLM simulé, déterministe : NON partout, sauf B.3.1 (NON
    # = risque côté inversé) avec une mitigation prouvée. ---
    def _fake_dispatch(backend, prompt, model, options, timeout):
        if "POLARITÉ INVERSÉE" in prompt:
            return (
                "STATUS: NON\n"
                'EVIDENCE_R: "aucune mesure de compensation deployee"\n'
                "PAGE: 10\n"
                "MITIGATION_STATUS: OUI_PROUVEE\n"
                'EVIDENCE_MESURE: "verification tierce independante realisee"\n'
                "EVIDENCE_DEFAILLANCE:\n"
                "SUJET: SPV\n"
                "CONFIDENCE:\n"
            )
        return (
            "STATUS: NON\n"
            "EVIDENCE_R:\n"
            "PAGE: inconnue\n"
            "MITIGATION_STATUS: N/A\n"
            "EVIDENCE_MESURE:\n"
            "EVIDENCE_DEFAILLANCE:\n"
            "SUJET: SPV\n"
            "CONFIDENCE:\n"
        )

    chunks = [{"text": "Passage générique pertinent pour l'analyse du projet.", "page": 5}]

    _orig_dispatch = llm_backend._dispatch
    config.GRID_V4_ENABLED = True
    llm_backend._dispatch = _fake_dispatch
    try:
        result = grid_analyze.analyze_grid(chunks, document_type=2)

        # 2. document_type et reading_mode dans le résultat
        _test("document_type=2 reporté dans le résultat", result["document_type"] == 2,
              f"Obtenu : {result.get('document_type')}")
        _test("reading_mode='suivi' (document_type=2)", result["reading_mode"] == "suivi",
              f"Obtenu : {result.get('reading_mode')}")

        # 3. 12 questions dans le résultat
        _test("12 questions dans le résultat", len(result["questions"]) == 12,
              f"Obtenu : {len(result['questions'])}")

        # 5. B.3.1 NON -> sous-question A active dans le résultat
        b31 = next(q for q in result["questions"] if q["code"] == "B.3.1")
        _test("B.3.1 NON -> status='NON' dans le résultat", b31["status"] == "NON",
              f"Obtenu : {b31['status']!r}")
        _test("B.3.1 NON -> sous-question A active (mitigation_status='OUI_PROUVEE')",
              b31["mitigation_status"] == "OUI_PROUVEE", f"Obtenu : {b31['mitigation_status']!r}")
        _test("B.3.1 NON + mitigation prouvée -> gain=3", b31["gain"] == 3, f"Obtenu : {b31['gain']}")

        try:
            grid_result.validate_grid_result(result)
            _test("Résultat de analyze_grid() -> validate_grid_result ne lève pas", True)
        except ValueError as e:
            _test("Résultat de analyze_grid() -> validate_grid_result ne lève pas", False, str(e))

        # 4. na_modules=["B.2"] -> 3 questions NA
        result_na = grid_analyze.analyze_grid(chunks, na_modules=["B.2"], document_type=1)
        na_count = sum(1 for q in result_na["questions"] if q["status"] == "NA")
        _test("na_modules=['B.2'] -> 3 questions NA", na_count == 3, f"Obtenu : {na_count}")
        _test("na_modules=['B.2'] -> scoring.questions_na=3",
              result_na["scoring"]["questions_na"] == 3, f"Obtenu : {result_na['scoring']['questions_na']}")

        # --- Silence R5 : aucun chunk candidat -> repli sans appel LLM ---
        result_empty = grid_analyze.analyze_grid([], document_type=1)
        a11_empty = next(q for q in result_empty["questions"] if q["code"] == "A.1.1")
        _test("Aucun chunk -> repli silence (A.1.1, événement) -> status='NON'",
              a11_empty["status"] == "NON", f"Obtenu : {a11_empty['status']!r}")
        _test("Aucun chunk -> silence_applied=True", a11_empty["silence_applied"] is True)

        b21_empty = next(q for q in result_empty["questions"] if q["code"] == "B.2.1")
        _test("Aucun chunk -> repli silence (B.2.1, état) -> status='INCONNU'",
              b21_empty["status"] == "INCONNU", f"Obtenu : {b21_empty['status']!r}")

        try:
            grid_result.validate_grid_result(result_empty)
            _test("Résultat 100% silence -> validate_grid_result ne lève pas", True)
        except ValueError as e:
            _test("Résultat 100% silence -> validate_grid_result ne lève pas", False, str(e))

    finally:
        llm_backend._dispatch = _orig_dispatch
        config.GRID_V4_ENABLED = _orig_enabled


# ============================================================================
# Tests de calibration V4 — 4 dossiers de référence (directive CC-V4-07)
# ============================================================================

def _cbg_answers_v4():
    """CBG Expansion — Type 1. Score attendu : 28-31."""
    import grid_questions
    base = {q["code"]: {"status": "NON"} for q in grid_questions.QUESTIONS}
    base["B.1.1"] = {"status": "OUI", "mitigation_status": "NON_INTENTION"}
    base["B.1.2"] = {"status": "OUI", "mitigation_status": "OUI_PROUVEE"}
    base["B.2.1"] = {"status": "OUI", "mitigation_status": "NON_FORME_INSUFFISANTE"}
    base["B.2.2"] = {
        "status": "OUI", "mitigation_status": "OUI_DEFAILLANTE",
        "evidence_a": {
            "verbatim_mesure": "additional filters and scrubbers were installed on the dryer stack in recent years",
            "verbatim_defaillance": "generated significant quantities of fugitive dust as well as particulate and gaseous emissions",
            "page": None,
        },
    }
    base["B.3.1"] = {"status": "NON"}  # inversé = risque, -15
    # B.4.1 = NON (pas de dommage sanitaire documenté dans l'ESRS CBG)
    return base
    # Calcul : -15 -15 -15 -15 -15 = -75, gains = +3 (B.1.2), score = 28


def _mundra_answers_v4():
    """CGPL Mundra — Type 3. Score attendu : 16."""
    import grid_questions
    base = {q["code"]: {"status": "NON"} for q in grid_questions.QUESTIONS}
    # A.2.1 = NON après R10 (contentieux vise la SFI, pas la SPV)
    base["B.1.1"] = {
        "status": "OUI", "mitigation_status": "OUI_DEFAILLANTE",
        "evidence_a": {
            "verbatim_mesure": "livelihood restoration services provided",
            "verbatim_defaillance": "services interrupted in August 2017",
            "page": None,
        },
    }
    base["B.1.2"] = {"status": "OUI", "mitigation_status": "NON_FORME_INSUFFISANTE"}
    base["B.2.1"] = {"status": "OUI", "mitigation_status": "OUI_PROUVEE"}  # panneau public = +3
    base["B.2.2"] = {"status": "OUI", "mitigation_status": "OUI_PROUVEE"}  # ESP = +3
    base["B.3.1"] = {"status": "NON"}  # inversé = risque
    base["B.4.1"] = {"status": "OUI"}  # irritations cutanées, pas de mitigation
    return base
    # Pénalités : B.1.1(-15) B.1.2(-15) B.2.1(-15) B.2.2(-15) B.3.1(-15) B.4.1(-15) = -90
    # Gains : B.2.1(+3) B.2.2(+3) = +6 ; score = 100 - 90 + 6 = 16


def _aysha_answers_v4():
    """Aysha I Wind — Type 1. Score attendu : 73 (panachage R11)."""
    import grid_questions
    base = {q["code"]: {"status": "NON"} for q in grid_questions.QUESTIONS}
    base["B.1.1"] = {"status": "OUI", "mitigation_status": "OUI_PROUVEE"}  # date butoir = statut 3 (R11 adapté)
    base["B.3.1"] = {"status": "NON"}  # BAP absent = strict, -15
    # B.1.2 = NON (mécanisme en place) ; B.2.x = NON (pas d'installation) ; B.4.1 = NON
    return base
    # Pénalités : B.1.1(-15) B.3.1(-15) = -30 ; Gains : B.1.1(+3) = +3 ; score = 100 - 30 + 3 = 73


def _indorama_answers_v4():
    """Indorama IFF Line 2 — Type 1. Score attendu : 85 (lecture stricte B.3.1)."""
    import grid_questions
    base = {q["code"]: {"status": "NON"} for q in grid_questions.QUESTIONS}
    base["B.1.1"] = {"status": "NA"}  # N/A argumenté (PS5 non déclenchée)
    base["B.3.1"] = {"status": "NON"}  # strict : CHA aboutie mais lecture stricte encodée -> NON
    return base
    # Pénalités : B.3.1(-15) = -15 ; score = 100 - 15 = 85


def test_calibration_cbg():
    """CBG Expansion — Type 1, score attendu 28-31, ORANGE/ROUGE."""
    print("\n--- 1.16a Calibration CBG Expansion (Type 1) ---\n")
    import grid_scoring
    answers = _cbg_answers_v4()
    result = grid_scoring.compute_grid_score(answers, document_type=1)
    _test("CBG : score entre 28 et 31", 28 <= result["score"] <= 31, f"Obtenu : {result['score']}")
    _test("CBG : color = ORANGE ou ROUGE (zone critique)",
          result["color"] in ("ORANGE", "ROUGE"), f"Obtenu : {result['color']!r}")
    _test("CBG : reading_mode='instruction'", result["reading_mode"] == "instruction",
          f"Obtenu : {result['reading_mode']!r}")


def test_calibration_mundra():
    """CGPL Mundra — Type 3, score attendu 16, ROUGE."""
    print("\n--- 1.16b Calibration Mundra CGPL (Type 3) ---\n")
    import grid_scoring
    answers = _mundra_answers_v4()
    result = grid_scoring.compute_grid_score(answers, document_type=3)
    _test("Mundra : score = 16", result["score"] == 16, f"Obtenu : {result['score']}")
    _test("Mundra : color = ROUGE", result["color"] == "ROUGE", f"Obtenu : {result['color']!r}")
    _test("Mundra : reading_mode='suivi'", result["reading_mode"] == "suivi",
          f"Obtenu : {result['reading_mode']!r}")


def test_calibration_aysha():
    """Aysha I Wind — Type 1, score attendu 73, JAUNE."""
    print("\n--- 1.16c Calibration Aysha I Wind (Type 1) ---\n")
    import grid_scoring
    answers = _aysha_answers_v4()
    result = grid_scoring.compute_grid_score(answers, document_type=1)
    _test("Aysha : score = 73", result["score"] == 73, f"Obtenu : {result['score']}")
    _test("Aysha : color = JAUNE", result["color"] == "JAUNE", f"Obtenu : {result['color']!r}")


def test_calibration_indorama():
    """Indorama IFF Line 2 — Type 1, score attendu 85, VERT."""
    print("\n--- 1.16d Calibration Indorama IFF Line 2 (Type 1) ---\n")
    import grid_scoring
    answers = _indorama_answers_v4()
    result = grid_scoring.compute_grid_score(answers, document_type=1)
    _test("Indorama : score = 85", result["score"] == 85, f"Obtenu : {result['score']}")
    _test("Indorama : color = VERT", result["color"] == "VERT", f"Obtenu : {result['color']!r}")


def test_calibration_ordering():
    """L'ordre Indorama > Aysha > CBG > Mundra doit être respecté."""
    print("\n--- 1.16e Calibration : ordre relatif des 4 dossiers ---\n")
    import grid_scoring
    s_ind = grid_scoring.compute_grid_score(_indorama_answers_v4(), document_type=1)["score"]
    s_ays = grid_scoring.compute_grid_score(_aysha_answers_v4(), document_type=1)["score"]
    s_cbg = grid_scoring.compute_grid_score(_cbg_answers_v4(), document_type=1)["score"]
    s_mun = grid_scoring.compute_grid_score(_mundra_answers_v4(), document_type=3)["score"]
    _test("Ordre Indorama > Aysha > CBG > Mundra",
          s_ind > s_ays > s_cbg > s_mun, f"Obtenu : {s_ind}, {s_ays}, {s_cbg}, {s_mun}")


def test_calibration_shared_cap_mundra():
    """Sur Mundra, A.1.1 et A.1.3 sont tous les deux NON — pas de plafond partagé déclenché."""
    print("\n--- 1.16f Calibration Mundra : pas de plafond partagé A.1 ---\n")
    import grid_scoring
    answers = _mundra_answers_v4()
    _test("Mundra : A.1.1 = NON", answers["A.1.1"]["status"] == "NON")
    _test("Mundra : A.1.3 = NON", answers["A.1.3"]["status"] == "NON")
    result = grid_scoring.compute_grid_score(answers, document_type=3)
    _test("Mundra : aucun _shared_cap_applied sur A.1.1/A.1.3 (aucune pénalité à plafonner)",
          not any(d.get("_shared_cap_applied") for d in result["details"] if d["code"] in ("A.1.1", "A.1.3")))


def test_calibration_b31_inverted():
    """B.3.1 NON = risque sur les 4 dossiers sauf Indorama (adaptée en OUI dans cette encodage)."""
    print("\n--- 1.16g Calibration : B.3.1 sur les 4 dossiers ---\n")
    for fn, expected, label in [
        (_cbg_answers_v4, "NON", "CBG"),
        (_mundra_answers_v4, "NON", "Mundra"),
        (_aysha_answers_v4, "NON", "Aysha (strict : BAP absent)"),
    ]:
        _test(f"{label} : B.3.1 = {expected}", fn()["B.3.1"]["status"] == expected,
              f"Obtenu : {fn()['B.3.1']['status']!r}")

    _test("Indorama : B.3.1 = NON (lecture stricte encodée pour score=85)",
          _indorama_answers_v4()["B.3.1"]["status"] == "NON",
          f"Obtenu : {_indorama_answers_v4()['B.3.1']['status']!r}")


def _build_fake_v4_result():
    """Construit un result_v4 réaliste via grid_scoring + grid_result (pas
    un dict tapé à la main) — pour tester export.py sans jamais dériver du
    contrat réel de grid_result.build_grid_result (CC-V4-03). Couvre les
    cas intéressants pour l'export : OUI_DEFAILLANTE (double verbatim),
    B.3.1 avec mitigation prouvée, INCONNU (silence), qualifying (R10)."""
    import grid_questions
    import grid_scoring
    import grid_result

    answers = {q["code"]: {"status": "NON"} for q in grid_questions.QUESTIONS}
    answers["A.1.1"] = {"status": "OUI", "mitigation_status": "NON_INTENTION"}
    answers["A.2.1"] = {"status": "OUI", "mitigation_status": "OUI_PROUVEE"}
    answers["B.2.1"] = {"status": "INCONNU"}
    answers["B.2.2"] = {
        "status": "OUI", "mitigation_status": "OUI_DEFAILLANTE",
        "evidence_a": {
            "verbatim_mesure": "des filtres ont ete installes sur la cheminee",
            "verbatim_defaillance": "des poussieres persistent malgre les filtres",
            "page": 34,
        },
    }
    answers["B.3.1"] = {"status": "NON", "mitigation_status": "OUI_PROUVEE"}

    question_results = {}
    for code, ans in answers.items():
        entry = dict(ans)
        entry["evidence_r"] = (
            {"passage": f"Passage justificatif pour {code}.", "page": 12}
            if ans["status"] in ("OUI", "NON") else None
        )
        entry["confidence_note"] = "Formulation ambigue dans le rapport." if code == "A.1.1" else None
        entry["qualifying"] = (
            {"subject_filter": "lender", "lender_supervision": "Verbatim vise le preteur, pas la SPV."}
            if code == "A.2.1" else None
        )
        question_results[code] = entry

    scoring = grid_scoring.compute_grid_score(answers, document_type=1)
    return grid_result.build_grid_result(question_results, scoring)


def test_grid_v4_export():
    """Tests des exports PDF/Excel de la Grille V4 (export.py, directive
    CC-V4-10). Purement déterministe (fpdf2/openpyxl), pas de LLM."""
    print("\n--- 1.17 Export PDF/Excel Grille V4 (export.py) ---\n")

    import export
    import grid_result

    result = _build_fake_v4_result()
    try:
        grid_result.validate_grid_result(result)
        _test("Résultat factice V4 -> validate_grid_result ne lève pas", True)
    except ValueError as e:
        _test("Résultat factice V4 -> validate_grid_result ne lève pas", False, str(e))

    # --- PDF ---
    pdf_bytes = export.build_grid_v4_pdf(result, project_name="Test")
    _test("build_grid_v4_pdf : retourne des bytes non vides",
          pdf_bytes is not None and len(pdf_bytes) > 0)
    _test("build_grid_v4_pdf : signature %PDF", pdf_bytes[:4] == b"%PDF",
          f"Obtenu : {pdf_bytes[:4]!r}")

    pdf_bytes_no_name = export.build_grid_v4_pdf(result)
    _test("build_grid_v4_pdf : fonctionne aussi sans project_name",
          pdf_bytes_no_name[:4] == b"%PDF")

    # --- Excel ---
    xlsx_bytes = export.build_grid_v4_excel(result, project_name="Test")
    _test("build_grid_v4_excel : retourne des bytes non vides",
          xlsx_bytes is not None and len(xlsx_bytes) > 0)
    # Les fichiers .xlsx sont des archives ZIP -> signature "PK"
    _test("build_grid_v4_excel : signature PK (format ZIP/xlsx)",
          xlsx_bytes[:2] == b"PK", f"Obtenu : {xlsx_bytes[:2]!r}")

    # --- Contenu Excel : 4 feuilles, remplissage conditionnel ---
    import io
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(xlsx_bytes))
    _test("Excel : 4 feuilles (Synthese, Grille, Evidence, Qualifiants)",
          wb.sheetnames == ["Synthese", "Grille", "Evidence", "Qualifiants"],
          f"Obtenu : {wb.sheetnames}")

    ws_grille = wb["Grille"]
    _test("Excel/Grille : 12 lignes de données + 1 en-tête",
          ws_grille.max_row == 13, f"Obtenu : {ws_grille.max_row}")

    # A.1.1 est en ligne 2 (ordre de grid_questions.QUESTIONS) avec pénalité
    # -25 < 0 -> la cellule Pénalité (colonne 7) doit avoir le fond rouge clair.
    penalty_cell = ws_grille.cell(row=2, column=7)
    _test("Excel/Grille : fond rouge clair si pénalité < 0 (A.1.1)",
          penalty_cell.fill.start_color.rgb in ("00F8D7DA", "F8D7DA"),
          f"Obtenu : {penalty_cell.fill.start_color.rgb!r}")

    ws_evidence = wb["Evidence"]
    _test("Excel/Evidence : au moins une ligne de données",
          ws_evidence.max_row > 1, f"Obtenu : {ws_evidence.max_row}")
    _test("Excel/Evidence : colonne Sujet présente",
          [c.value for c in ws_evidence[1]] == ["Code", "Type", "Page", "Passage", "Sujet"])

    ws_qualif = wb["Qualifiants"]
    _test("Excel/Qualifiants : au moins une ligne de données (A.2.1)",
          ws_qualif.max_row > 1, f"Obtenu : {ws_qualif.max_row}")


def test_grid_questions_v4():
    """Vérifie la structure de QUESTIONS V4 (grid_questions.py, directive
    CC-V4-01) — 12 questions, poids par catégorie, cas particuliers B.2.x
    (module N/A), A.1 (plafond partagé) et B.3.1 (polarité inversée avec
    sous-question A conditionnée à R=NON)."""
    print("\n--- 1.6 Grille ESG V4 (grid_questions.py) ---\n")

    import grid_questions

    questions = grid_questions.QUESTIONS

    _test("GRID_VERSION='V4'", grid_questions.GRID_VERSION == "V4", f"Obtenu : {grid_questions.GRID_VERSION!r}")
    _test("12 questions exactement", len(questions) == 12, f"Obtenu : {len(questions)}")
    _test("ESG_QUESTIONS alias de QUESTIONS (rétro-compat V3)",
          grid_questions.ESG_QUESTIONS is grid_questions.QUESTIONS)

    cat_a = [q for q in questions if q["category"] == "A"]
    cat_b = [q for q in questions if q["category"] == "B"]
    _test("5 questions Cat A", len(cat_a) == 5, f"Obtenu : {len(cat_a)}")
    _test("7 questions Cat B", len(cat_b) == 7, f"Obtenu : {len(cat_b)}")

    _test("Pénalité -25 pour toutes les questions Cat A",
          all(q["penalty"] == -25 for q in cat_a),
          f"Pénalités Cat A : {[q['penalty'] for q in cat_a]}")
    _test("Pénalité -15 pour toutes les questions Cat B",
          all(q["penalty"] == -15 for q in cat_b),
          f"Pénalités Cat B : {[q['penalty'] for q in cat_b]}")

    # --- Plafond partagé A.1.1 / A.1.3 (nouveau V4) ---
    a11 = grid_questions.get_question("A.1.1")
    a13 = grid_questions.get_question("A.1.3")
    _test("A.1.1 existe", a11 is not None, "get_question('A.1.1') renvoie None")
    _test("A.1.3 existe (nouveau V4)", a13 is not None, "get_question('A.1.3') renvoie None")
    if a11 and a13:
        _test("A.1.1 : shared_cap_group='A.1'", a11["shared_cap_group"] == "A.1",
              f"Obtenu : {a11['shared_cap_group']!r}")
        _test("A.1.3 : shared_cap_group='A.1'", a13["shared_cap_group"] == "A.1",
              f"Obtenu : {a13['shared_cap_group']!r}")
    _test("get_questions_by_shared_cap('A.1') renvoie 2 questions",
          len(grid_questions.get_questions_by_shared_cap("A.1")) == 2,
          f"Obtenu : {len(grid_questions.get_questions_by_shared_cap('A.1'))}")
    _test("get_questions_by_shared_cap('nonexistent') renvoie []",
          len(grid_questions.get_questions_by_shared_cap("nonexistent")) == 0)

    # --- B.3.1 (modifié V4 : R+A séparés, a_condition="r_non") ---
    b31 = grid_questions.get_question("B.3.1")
    _test("B.3.1 existe", b31 is not None, "get_question('B.3.1') renvoie None")
    if b31:
        _test("B.3.1 : inverted_polarity=True", b31["inverted_polarity"] is True,
              f"Obtenu : {b31['inverted_polarity']}")
        _test("B.3.1 : has_separate_r=True (changement V3->V4)", b31["has_separate_r"] is True,
              f"Obtenu : {b31['has_separate_r']}")
        _test("B.3.1 : a_condition='r_non'", b31["a_condition"] == "r_non",
              f"Obtenu : {b31['a_condition']!r}")
        _test("B.3.1 : gain=3 (changement V3->V4, plus 0)", b31["gain"] == 3, f"Obtenu : {b31['gain']}")

    # --- B.4.1 (nouveau V4) ---
    b41 = grid_questions.get_question("B.4.1")
    _test("B.4.1 existe (nouveau V4)", b41 is not None, "get_question('B.4.1') renvoie None")
    if b41:
        _test("B.4.1 : penalty=-15", b41["penalty"] == -15, f"Obtenu : {b41['penalty']}")

    pollution_codes = {"B.2.1", "B.2.2", "B.2.3"}
    non_pollution = [q for q in questions if q["code"] not in pollution_codes]
    non_a1 = [q for q in questions if q["code"] not in ("A.1.1", "A.1.3")]

    _test("B.2.1/B.2.2/B.2.3 : na_module='B.2'",
          all(q["na_module"] == "B.2" for q in questions if q["code"] in pollution_codes),
          f"Obtenu : {[(q['code'], q['na_module']) for q in questions if q['code'] in pollution_codes]}")
    _test("Questions hors module B.2 : na_module=None",
          all(q["na_module"] is None for q in non_pollution),
          f"Obtenu : {[(q['code'], q['na_module']) for q in non_pollution]}")
    _test("Questions hors A.1.1/A.1.3 : shared_cap_group=None",
          all(q["shared_cap_group"] is None for q in non_a1),
          f"Obtenu : {[(q['code'], q['shared_cap_group']) for q in non_a1]}")

    # --- silence_type et a_condition sur toutes les questions ---
    _test("Toutes les questions ont un silence_type valide",
          all(q["silence_type"] in ("evenement", "etat") for q in questions),
          f"Obtenu : {[(q['code'], q['silence_type']) for q in questions]}")
    _test("Toutes les questions ont un a_condition valide",
          all(q["a_condition"] in ("r_oui", "r_non") for q in questions),
          f"Obtenu : {[(q['code'], q['a_condition']) for q in questions]}")
    _test("Seule B.3.1 a a_condition='r_non'",
          [q["code"] for q in questions if q["a_condition"] == "r_non"] == ["B.3.1"],
          f"Obtenu : {[q['code'] for q in questions if q['a_condition'] == 'r_non']}")

    _test("get_question('A.1.1') renvoie un dict",
          isinstance(grid_questions.get_question("A.1.1"), dict))
    _test("get_question('Z.9.9') renvoie None",
          grid_questions.get_question("Z.9.9") is None)

    _test("get_active_questions() renvoie 12 questions",
          len(grid_questions.get_active_questions()) == 12,
          f"Obtenu : {len(grid_questions.get_active_questions())}")
    _test("get_active_questions(na_modules=['B.2']) renvoie 9 questions",
          len(grid_questions.get_active_questions(na_modules=["B.2"])) == 9,
          f"Obtenu : {len(grid_questions.get_active_questions(na_modules=['B.2']))}")

    # --- DOCUMENT_TYPES / RESPONSE_VALUES / QUALIFYING_FLAGS (nouveau V4) ---
    _test("DOCUMENT_TYPES : 4 types", len(grid_questions.DOCUMENT_TYPES) == 4,
          f"Obtenu : {len(grid_questions.DOCUMENT_TYPES)}")
    _test("DOCUMENT_TYPES[1] : reading_mode='instruction'",
          grid_questions.DOCUMENT_TYPES[1]["reading_mode"] == "instruction",
          f"Obtenu : {grid_questions.DOCUMENT_TYPES[1]['reading_mode']!r}")
    _test("DOCUMENT_TYPES[3] : proof_forms=3",
          grid_questions.DOCUMENT_TYPES[3]["proof_forms"] == 3,
          f"Obtenu : {grid_questions.DOCUMENT_TYPES[3]['proof_forms']}")
    _test("RESPONSE_VALUES = {OUI, NON, INCONNU, NA}",
          grid_questions.RESPONSE_VALUES == {"OUI", "NON", "INCONNU", "NA"},
          f"Obtenu : {grid_questions.RESPONSE_VALUES}")
    _test("QUALIFYING_FLAGS contient ALLEGATION_NON_CONFIRMEE et NON_ATTESTE",
          {"ALLEGATION_NON_CONFIRMEE", "NON_ATTESTE"} <= set(grid_questions.QUALIFYING_FLAGS),
          f"Obtenu : {list(grid_questions.QUALIFYING_FLAGS)}")

    # --- CC-07 : MITIGATION_STATUTS / CONCESSIVE_MARKERS non supprimés ---
    _test("MITIGATION_STATUTS toujours présent (4 statuts, CC-07 non régressé)",
          len(grid_questions.MITIGATION_STATUTS) == 4,
          f"Obtenu : {len(grid_questions.MITIGATION_STATUTS)}")
    _test("CONCESSIVE_MARKERS toujours présent (CC-07 non régressé)",
          len(grid_questions.CONCESSIVE_MARKERS) > 0)
    _test("OUI_DEFAILLANTE : description mentionne la mitigation interrompue",
          "interrompue" in grid_questions.MITIGATION_STATUTS["OUI_DEFAILLANTE"]["description"])


# ============================================================================
# 2. TESTS D'INTÉGRATION
# ============================================================================

def test_integration():
    print("\n--- 2. Tests d'intégration ---\n")

    try:
        import search
        from model import compute_grade
        from analyze import analyze

        model, index, metadata = search.load_search_components()

        # 2.1 Flag scores
        test_text = """
        Community opposition around the project. Grievances filed regarding
        involuntary resettlement. Indigenous peoples rights not addressed.
        """
        scores = search.get_flag_scores(test_text, model, index, metadata)
        _test("Flag scores → 3 valeurs",  len(scores) == 3)
        _test("Flag scores 0–100",
              all(0 <= v <= 100 for v in scores.values()),
              f"Scores : {scores}")
        _test("Texte communautaire → flag1 domine",
              scores["flag1_community"] >= scores["flag2_pollution"],
              f"f1={scores['flag1_community']:.1f} vs f2={scores['flag2_pollution']:.1f}",
              warning_only=True)

        # 2.2 Grade ESG (compute_grade, remplace le Cox)
        pred = compute_grade(scores)
        expected_keys = ["risk_score", "risk_label", "risk_grade"]
        _test("Prédiction toutes les clés",
              all(k in pred for k in expected_keys))
        _test("Score ∈ [0, 100]",
              0 <= pred["risk_score"] <= 100,
              f"score = {pred['risk_score']}")
        _test("Grade valide",
              pred["risk_grade"] in ["A", "B", "C", "D"],
              f"grade = {pred['risk_grade']}")

        # 2.4 Pipeline complète
        t0 = time.time()
        result = analyze(test_text)
        dt = time.time() - t0
        expected_result_keys = [
            "flag_scores", "prediction", "similar_passages",
            "detected_signals", "signal_spans", "processing_time_s",
        ]
        _test("analyze() toutes les clés",
              all(k in result for k in expected_result_keys))
        _test(f"analyze() < 45s (actuel: {dt:.1f}s)",
              dt < 45,
              "Trop lent → voir checklist.md, chantier perf LLM/deep_analysis",
              warning_only=True)

    except Exception as e:
        print(f"  ❌ Erreur d'intégration : {e}")
        import traceback
        traceback.print_exc()

    # 2.5 Branchement chunks -> Grille V4 (directive CC-V4-09) — bloc séparé
    # du try ci-dessus : un échec de l'ANCIEN pipeline (corpus/FAISS
    # manquants) ne doit pas masquer ce test, qui ne dépend que de
    # search.chunk_text() (pas du corpus) et d'un backend LLM monkey-patché.
    try:
        test_integration_chunks_to_grid()
        test_integration_section_exclusion_real_chunking()
    except Exception as e:
        print(f"  ❌ Erreur d'intégration (chunks -> Grille V4) : {e}")
        import traceback
        traceback.print_exc()


def test_integration_chunks_to_grid():
    """Vérifie que le pipeline complet (search.chunk_text -> grid_analyze)
    fonctionne sur un texte réel (directive CC-V4-09). Backend LLM
    monkey-patché (même idiome que 1.5/1.15) — pas d'appel réseau réel,
    et le flag GRID_V4_ENABLED est restauré après le test (isolation)."""
    print("\n--- 2.5a Branchement chunks -> Grille V4 (search.chunk_text réel) ---\n")

    import config
    import llm_backend
    import search
    import grid_analyze

    # Texte synthétique simulant un ESRS — cf. directive CC-V4-09 (reprend
    # l'exemple fourni telle quelle : assez court pour tenir dans un seul
    # chunk de search.chunk_text(), cf. test_integration_section_exclusion_
    # real_chunking ci-dessous pour un texte assez long pour vérifier la
    # séparation ESAP/plaintes IFC sur plusieurs chunks).
    test_text = """
    Environmental and Social Review Summary
    The project involves the expansion of mining operations.
    There are significant ongoing resettlement impacts.

    Environmental and Social Action Plan
    Item 1: Prepare a Livelihood Restoration Plan
    Item 2: Finalize the compensation report

    Information on E&S Complaints and Grievance Mechanisms
    Affected communities have unrestricted access to the CAO.
    """

    chunks = search.chunk_text(test_text)
    _test("search.chunk_text() sur un texte réel produit au moins 1 chunk",
          len(chunks) >= 1, f"Obtenu : {len(chunks)} chunk(s)")

    chunks_for_grid = [{"text": c, "page": None} for c in chunks]

    def _fake_dispatch(backend, prompt, model, options, timeout):
        return (
            "STATUS: NON\nEVIDENCE_R:\nPAGE: inconnue\nMITIGATION_STATUS: N/A\n"
            "EVIDENCE_MESURE:\nEVIDENCE_DEFAILLANCE:\nSUJET: SPV\nCONFIDENCE:\n"
        )

    _orig_enabled = config.GRID_V4_ENABLED
    _orig_dispatch = llm_backend._dispatch
    config.GRID_V4_ENABLED = True
    llm_backend._dispatch = _fake_dispatch
    try:
        result = grid_analyze.analyze_grid(chunks_for_grid, document_type=1)

        _test("Pipeline complet : résultat non None", result is not None)
        if result is not None:
            _test("Pipeline complet : grid_version='V4'", result["grid_version"] == "V4",
                  f"Obtenu : {result.get('grid_version')!r}")
            _test("Pipeline complet : 12 questions", len(result["questions"]) == 12,
                  f"Obtenu : {len(result['questions'])}")
            _test("Pipeline complet : score >= 0", result["scoring"]["score"] >= 0,
                  f"Obtenu : {result['scoring']['score']}")
    finally:
        llm_backend._dispatch = _orig_dispatch
        config.GRID_V4_ENABLED = _orig_enabled


def test_integration_section_exclusion_real_chunking():
    """Vérifie que l'exclusion ESAP / plaintes IFC (grid_sections.py)
    fonctionne quand ESAP et la section plaintes tombent dans des chunks
    SÉPARÉS produits par le vrai search.chunk_text() — cf. directive
    CC-V4-09, "s'assurer que les exclusions fonctionnent sur un vrai
    document". Le texte de la directive (~50 mots) tient dans un seul
    chunk de search.chunk_text() (fenêtre de 175 mots) : ESAP et plaintes
    s'y retrouvent mélangés dans le MÊME chunk, ce qui ne teste pas la
    séparation. Ce test utilise un texte assez long (>500 mots, sections
    espacées de >175 mots) pour que le chunking réel les place dans des
    chunks distincts, condition réaliste sur un rapport de 45-70 pages.
    Purement déterministe (search.chunk_text + grid_sections), pas de LLM.
    """
    print("\n--- 2.5b Exclusion de sections sur chunking réel (search.chunk_text) ---\n")

    import search
    import grid_sections

    def _pad(label, n):
        return " ".join(f"{label}word{i}" for i in range(n))

    test_text = f"""
    Environmental and Social Review Summary. {_pad("context", 220)}

    Environmental and Social Action Plan
    Item 1: Prepare a Livelihood Restoration Plan for the affected households.
    Item 2: Finalize the compensation report for past resettlement.
    Item 3: Complete establishment of a data management system.

    {_pad("monitoring", 220)}

    Information on E&S Complaints and Grievance Mechanisms
    Affected communities have unrestricted access to the Compliance Advisor Ombudsman (CAO).
    The CAO is mandated to address complaints from people affected by IFC projects.

    {_pad("closing", 100)}
    """

    chunks = search.chunk_text(test_text)
    _test("Texte réaliste (~500+ mots) -> plusieurs chunks",
          len(chunks) > 1, f"Obtenu : {len(chunks)} chunk(s)")

    classified = grid_sections.classify_chunks([{"text": c, "page": None} for c in chunks])

    esap_tags = [c for c in classified if c["section_tag"] == "esap"]
    complaints_tags = [c for c in classified if c["section_tag"] == "ifc_complaints"]
    untagged = [c for c in classified if c["section_tag"] is None]

    _test("Au moins un chunk taggé 'esap' sur chunking réel", len(esap_tags) > 0,
          f"Obtenu : {len(esap_tags)}")
    _test("Au moins un chunk taggé 'ifc_complaints' sur chunking réel", len(complaints_tags) > 0,
          f"Obtenu : {len(complaints_tags)}")
    _test("Au moins un chunk normal (non taggé) sur chunking réel", len(untagged) > 0,
          f"Obtenu : {len(untagged)}")
    _test("ESAP et plaintes IFC tombent dans des chunks DISTINCTS (pas mélangés)",
          not any(c in esap_tags for c in complaints_tags))

    # Vérifie que le filtrage en aval (get_chunks_for_question) exclut
    # bien ces chunks une fois issus d'un vrai chunking, pas seulement
    # sur les petits exemples synthétiques de CC-09/CC-V4-04.
    r_chunks = grid_sections.get_chunks_for_question(classified, "B.1.2")
    _test("Question R : chunks plaintes IFC exclus (chunking réel)",
          all(c["section_tag"] != "ifc_complaints" for c in r_chunks))
    _test("Question R : chunks ESAP conservés (chunking réel)",
          any(c["section_tag"] == "esap" for c in r_chunks))

    a_chunks = grid_sections.get_chunks_for_question(classified, "B.1.2", for_mitigation=True)
    _test("Question A (mitigation) : chunks ESAP exclus (chunking réel)",
          all(c["section_tag"] != "esap" for c in a_chunks))
    _test("Question A (mitigation) : chunks plaintes IFC exclus (chunking réel)",
          all(c["section_tag"] != "ifc_complaints" for c in a_chunks))


# ============================================================================
# 3. TESTS DE COHÉRENCE MÉTIER (bloc 3.2 de la roadmap)
# ============================================================================

def test_business():
    print("\n--- 3. Tests de cohérence métier ---\n")

    try:
        from analyze import analyze

        # --- CAS 1 : Community Opposition (haut risque) ---
        text_community = """
        The project has faced significant community opposition. Local populations
        report involuntary displacement without adequate compensation. Multiple
        grievances filed through the CAO mechanism. Indigenous communities claim
        violation of FPIC. Stakeholder engagement described as inadequate.
        """

        # --- CAS 2 : ESAP Delays (risque moyen) ---
        text_esap = """
        The ESAP action plan shows delays in implementation of corrective measures.
        Several environmental monitoring commitments are overdue. Non-compliance
        with PS1 requirements on assessment and management. Pollution discharge
        thresholds exceeded on two occasions. Remediation plan not yet submitted.
        """

        # --- CAS 3 : Biodiversity Risk (haut risque flag3) ---
        text_biodiversity = """
        The project area overlaps with a critical habitat for endangered species.
        PS6 requirements for biodiversity management have not been fully met.
        No adequate biodiversity offset program established. Environmental impact
        assessment did not properly identify all species at risk. Habitat
        fragmentation concerns raised by independent environmental review.
        """

        # --- CAS 4 : Projet propre (bas risque) ---
        text_clean = """
        The project's environmental and social management system is fully operational.
        Regular monitoring reports demonstrate compliance with all Performance Standards.
        Community feedback mechanisms are active with positive stakeholder sentiment.
        Biodiversity offset program is on track. ESAP actions completed ahead of schedule.
        """

        # Analyser chaque cas
        print("  Analyse des 4 cas de test...")
        r1 = analyze(text_community)
        r2 = analyze(text_esap)
        r3 = analyze(text_biodiversity)
        r4 = analyze(text_clean)

        # Résumé visuel (CHANTIER SIMPLIFICATION PIPELINE, 2026-08-08 : plus de
        # probability_12m/Cox — risk_score = max(flag_scores), 0-100)
        print(f"\n  Cas 1 (Community Opposition) : {r1['prediction']['risk_grade']} "
              f"({r1['prediction']['risk_label']}) — score={r1['prediction']['risk_score']}/100")
        print(f"  Cas 2 (ESAP Delays)          : {r2['prediction']['risk_grade']} "
              f"({r2['prediction']['risk_label']}) — score={r2['prediction']['risk_score']}/100")
        print(f"  Cas 3 (Biodiversity Risk)    : {r3['prediction']['risk_grade']} "
              f"({r3['prediction']['risk_label']}) — score={r3['prediction']['risk_score']}/100")
        print(f"  Cas 4 (Projet propre)        : {r4['prediction']['risk_grade']} "
              f"({r4['prediction']['risk_label']}) — score={r4['prediction']['risk_score']}/100")

        # Vérifications
        _test("Cas 1 (risque) > Cas 4 (propre)",
              r1["prediction"]["risk_score"] > r4["prediction"]["risk_score"],
              f"{r1['prediction']['risk_score']} vs {r4['prediction']['risk_score']}")

        # Convention conservée (2026-08-08) : A = pire (Escalade), D = meilleur
        # (Vigilance) — même sens qu'avec le Cox, cf. model.py.
        _test("Cas 1 = grade A ou B",
              r1["prediction"]["risk_grade"] in ["A", "B"],
              f"Grade = {r1['prediction']['risk_grade']}",
              warning_only=True)

        _test("Cas 4 = grade C ou D",
              r4["prediction"]["risk_grade"] in ["C", "D"],
              f"Grade = {r4['prediction']['risk_grade']}",
              warning_only=True)

        _test("Cas 1 : signaux détectés",
              len(r1["detected_signals"]) > 0,
              "Aucun signal — vérifier les mots-clés dans analyze._extract_signals")

        # Ordonnancement global
        scores = [r1["prediction"]["risk_score"],
                  r2["prediction"]["risk_score"],
                  r3["prediction"]["risk_score"],
                  r4["prediction"]["risk_score"]]
        _test("Cas propre a le score le plus bas",
              scores[3] == min(scores),
              f"Scores : community={scores[0]} esap={scores[1]} "
              f"bio={scores[2]} propre={scores[3]}",
              warning_only=True)

    except Exception as e:
        print(f"  ❌ Erreur tests métier : {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# RÉSUMÉ + MAIN
# ============================================================================

def print_summary():
    total = _passed + _failed + _warnings
    print("\n" + "=" * 60)
    print(f"RÉSULTATS : {_passed}/{total} passés, {_failed} échecs, {_warnings} warnings")
    if _failed == 0:
        print("🎉 Tous les tests critiques passent !")
    else:
        print("🔴 Des tests critiques ont échoué — à corriger avant la démo")
    print("=" * 60)


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--unit" in args:
        test_unit()
    elif "--integ" in args:
        test_integration()
    elif "--business" in args:
        test_business()
    else:
        # Tout lancer
        test_unit()
        test_integration()
        test_business()

    print_summary()