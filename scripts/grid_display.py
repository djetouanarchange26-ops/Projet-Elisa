"""
GRILLE ESG V4 — affichage Streamlit (audit UI "ESG Risk Intelligence
Workspace", 2026-08-20)
=====================================================================
Rendu de l'onglet Transaction Analysis (pipeline V4) : assemblage pur d'un
résultat déjà produit par grid_analyze.analyze_grid() (cf. grid_result.py
pour le contrat exact) en composants Streamlit. Aucune logique de scoring
ni d'appel LLM ici — uniquement de l'affichage. `result_v4` n'est jamais
modifié — cf. "Ce qu'il ne faut PAS faire" de l'audit UI (ne pas changer
la structure du dict, seulement son affichage).

CHOIX: module séparé plutôt qu'une fonction de plus dans app.py (déjà
~1550 lignes) — import plat (`import grid_display`), cohérent avec le
reste de scripts/ (pas de package).

3 zones empilées (remplace le layout à 5 sections égales du 2026-08-20 —
la synthèse et les facteurs de risque principaux étaient noyés au milieu
d'une liste plate dans l'ordre technique de la grille A.1.1->B.3.2, sans
hiérarchie ; cf. audit UI pour le détail du raisonnement) :

  1. Project Overview (_render_project_overview) — détection du type de
     document (R11), contexte dossier (4 champs BLOC D), documents
     analysés, mode de lecture, date d'analyse.
  2. Executive Risk Summary (_render_executive_summary) — score, synthèse
     LLM IMMÉDIATEMENT sous le score (avant, position 4/5), puis 3
     groupes dérivés des mêmes 12 questions, AUCUNE nouvelle donnée :
       - Principaux facteurs de risque : questions OUI triées par impact
         réel (|penalty+gain| décroissant) au lieu de l'ordre fixe de la
         grille — un -25 pts et un -3 pts avaient la même importance
         visuelle avant.
       - Points nécessitant une vérification humaine : INCONNU (par
         construction : "le rapport ne permet pas de conclure") + OUI
         avec un doute LLM explicite (confidence_note non-silence).
       - Points favorables : NON attesté (preuve explicite d'absence,
         pas juste un silence) + mitigation prouvée (OUI_PROUVEE) —
         section absente avant l'audit UI, l'outil n'affichait que des
         problèmes.
  3. Grille détaillée (_render_grid) — les 12 questions, vue d'analyse
     approfondie explicitement secondaire (plus le premier écran).

Dans les 3 zones, le libellé métier (`sous_theme`, déjà en langage
courant : "Communautaire", "Pollution"...) précède le code technique
(`code`, ex. "A.1.1") — avant, c'était l'inverse partout, obligeant à
connaître les codes de la grille pour lire l'écran.

CHOIX (paramètres `documents`/`analyzed_at` de render_grid_v4_tab) :
optionnels (None par défaut), passés par app.py depuis
session_state["last_analysis"] — PAS dérivés de result_v4, qui ne les
contient pas (cf. audit UI : "documents analysés" n'existait avant que
comme une string déjà formatée pour affichage côté app.py, jamais
structurée ; "date d'analyse" n'existait nulle part dans last_analysis,
l'ancien code affichait datetime.now() AU RENDU — recalculé à chaque
rerun Streamlit, donc une date FAUSSE qui dérivait vers "maintenant" à
chaque interaction, pas seulement absente).

FRAGILE (inchangé depuis les versions précédentes de ce module, toujours
vrai après cette restructuration) :
  - `reading_mode_label` est un champ de NIVEAU RÉSULTAT
    (result_v4["reading_mode_label"]), pas de result_v4["scoring"] (cf.
    grid_result.build_grid_result).
  - Les questions n'ont pas de clé "sub_theme"/"net"/"verbatim" — ce sont
    "sous_theme", penalty+gain calculé ici (_net), et evidence_r["passage"]
    (cf. grid_result.py pour le contrat exact).
  - `mitigation_label`/`evidence_r["page"]`/`evidence_a["page"]` sont des
    clés TOUJOURS PRÉSENTES mais dont la valeur peut être None — un
    `dict.get(clé, défaut)` ne retombe sur `défaut` que si la clé est
    ABSENTE, pas si sa valeur est None. `dict.get(clé) or défaut` partout
    où c'est pertinent.
  - Grille détaillée : masquer une question ne s'applique QUE pour un
    NON par silence standard, non attesté, côté a_condition="r_oui" — un
    NA exige TOUJOURS un evidence_r (cf. grid_questions.SILENCE_VALUES
    ["NA"], "verbatim obligatoire") et reste donc toujours dépliable.
  - Les questions NA n'apparaissent dans AUCUN des 3 groupes de
    l'Executive Summary (ni facteur de risque, ni à vérifier, ni
    favorable) — "non applicable" n'est ni un problème ni un point
    positif à mettre en avant, elles restent visibles dans la grille
    détaillée uniquement (même choix que l'ancienne section "Signaux
    identifiés", qui filtrait déjà sur OUI/INCONNU).
"""

import logging
from datetime import datetime

import streamlit as st

logger = logging.getLogger(__name__)

_COLOR_MAP = {
    "VERT": "#2ecc71",
    "JAUNE": "#f1c40f",
    "ORANGE": "#e67e22",
    "ROUGE": "#e74c3c",
}

_STATUS_ICON = {"OUI": "🔴", "NON": "🟢", "INCONNU": "🟡", "NA": "⚪"}


def render_grid_v4_tab(result_v4, project_name="", documents=None, analyzed_at=None):
    """Affiche le résultat de la Grille V4 dans l'onglet Streamlit.

    result_v4 : dict retourné par grid_analyze.analyze_grid(), ou None si
    le pipeline V4 est désactivé ou a échoué (cf. app.py : les exceptions
    sont déjà attrapées en amont, ce module ne reçoit jamais que None ou
    un résultat bien formé).
    project_name : nom du projet/document analysé (string déjà formatée),
    transmis tel quel aux exports PDF/Excel — purement cosmétique.
    documents : list[str] | None — noms des fichiers réellement analysés
    (BLOC D audit UI) ; None si non fourni par l'appelant (rétro-
    compatibilité), auquel cas on retombe sur project_name.
    analyzed_at : datetime | None — horodatage réel du clic "Run
    Analysis" ; None si non fourni (affiche "—", jamais une date
    fabriquée).
    """
    if result_v4 is None:
        st.info("La Grille V4 n'a pas pu être calculée. Vérifiez les logs.")
        return

    _render_project_overview(result_v4, project_name, documents, analyzed_at)
    _render_executive_summary(result_v4)
    _render_grid(result_v4)
    _render_export_buttons(result_v4, project_name)


def _net(q):
    return q["penalty"] + q.get("gain", 0)


def _question_line(q, suffix=""):
    """Ligne d'affichage compacte : libellé métier en avant, code
    technique en secondaire (audit UI — avant, le code A.1.1 précédait
    toujours le libellé, partout)."""
    icon = _STATUS_ICON.get(q["status"], "⚪")
    return f"{icon} **{q['sous_theme']}** _{q['code']}_ ({_net(q):+d} pts){suffix}"


def _truncated_verbatim(passage, max_len=200):
    if not passage:
        return None
    return passage[:max_len] + "…" if len(passage) > max_len else passage


# ============================================================================
# GROUPES DE L'EXECUTIVE SUMMARY — fonctions pures (pas de Streamlit),
# testables indépendamment du rendu.
# ============================================================================

def _top_risk_drivers(questions):
    """Questions OUI triées par impact réel (net le plus négatif en
    premier) — remplace l'ordre fixe de la grille (A.1.1->B.3.2), qui ne
    dit rien de l'importance relative des signaux. Aucune nouvelle
    donnée : penalty/gain existent déjà par question (grid_result.py)."""
    drivers = [q for q in questions if q["status"] == "OUI"]
    return sorted(drivers, key=_net)


def _needs_verification(questions):
    """INCONNU (par construction : "le rapport ne permet pas de
    conclure") + OUI avec un doute LLM explicite non issu d'un silence
    pur — silence_applied distingue "aucun élément trouvé" d'un vrai
    doute de lecture sur un passage qui existe (cf. directive "gestion
    INCONNU", 2026-08-20)."""
    result = []
    for q in questions:
        if q["status"] == "INCONNU":
            result.append(q)
        elif q["status"] == "OUI" and q.get("confidence_note") and not q.get("silence_applied"):
            result.append(q)
    return result


def _favorable_points(questions):
    """NON attesté (preuve explicite d'absence, pas un silence) +
    mitigation prouvée (OUI_PROUVEE, gain>0). Un OUI avec mitigation
    prouvée reste AUSSI un facteur de risque (peut apparaître dans les
    deux groupes) — deux angles différents sur la même donnée, pas une
    contradiction : l'un montre le poids réel, l'autre la nuance
    positive."""
    result = []
    for q in questions:
        if q["status"] == "NON" and q.get("atteste"):
            result.append(q)
        elif q["status"] == "OUI" and q.get("mitigation_status") == "OUI_PROUVEE":
            result.append(q)
    return result


# ============================================================================
# ZONE 1 — PROJECT OVERVIEW
# ============================================================================

def _render_project_overview(result_v4, project_name, documents, analyzed_at):
    st.markdown("## Vue d'ensemble du dossier")

    _render_project_metadata(result_v4)
    _render_document_type_detection(result_v4)

    context = result_v4.get("context") or {}
    sentence = _format_context_sentence(context)
    if sentence:
        st.markdown(sentence)

    mode_label = result_v4.get("reading_mode_label") or "—"
    st.markdown(f"**Mode de lecture :** {mode_label}")

    if documents:
        label = "Document" if len(documents) == 1 else f"Documents analysés ({len(documents)})"
        st.markdown(f"**{label} :** " + ", ".join(documents))
    elif project_name:
        st.markdown(f"**Document :** {project_name}")

    date_str = analyzed_at.strftime("%d/%m/%Y %H:%M") if analyzed_at else "—"
    st.markdown(f"**Date d'analyse :** {date_str}")

    st.markdown("---")


_PROJECT_METADATA_LABELS = (
    ("sponsor", "Sponsor"),
    ("country", "Pays"),
    ("sector", "Secteur"),
    ("client", "Client"),
    ("project_type", "Type de projet"),
)


def _render_project_metadata(result_v4):
    """Sponsor/pays/secteur/client/type de projet (audit UI 2026-08-20,
    cf. grid_metadata.py) — extraction LLM fail-open, jamais inventée.
    Affichée en tête du Project Overview : "quel est ce projet ?" précède
    "comment la banque le classe" (contexte BLOC D, juste après). Section
    masquée si aucun champ n'a été trouvé (LLM indisponible ou document
    sans ces informations explicites) — pas de "—" répétés 5 fois."""
    metadata = result_v4.get("project_metadata") or {}
    parts = [f"**{label} :** {metadata[key]}" for key, label in _PROJECT_METADATA_LABELS if metadata.get(key)]
    if not parts:
        return
    st.markdown(" · ".join(parts))


def _render_document_type_detection(result_v4):
    """Affiche la détection R11 (grid_doctype.py) : type détecté, confiance,
    justification. CHOIX: affichée en tête du Project Overview — le type de
    document conditionne toute la lecture des 12 questions (R8/R9/R11), un
    analyste doit pouvoir la contester avant de lire le reste. Un
    "source" != "llm" (repli heuristique) est signalé explicitement, pas
    masqué derrière un type par défaut silencieux (cf. grid_doctype.py)."""
    detection = result_v4.get("document_type_detection")
    if not detection:
        return

    source = detection.get("source")
    confidence = detection.get("confidence", "faible")
    label = result_v4.get("reading_mode_label") or "—"

    if source == "llm":
        st.caption(
            f"**Type de document détecté (R11)** : Type {detection['document_type']} — "
            f"{label} · confiance {confidence}"
        )
    elif source == "manuel":
        st.caption(f"**Type de document (R11)** : Type {detection['document_type']} — {label} · saisie manuelle")
    else:
        st.warning(
            f"⚠️ Détection automatique du type de document indisponible — repli sur "
            f"Type {detection['document_type']} ({label}) par heuristique lexicale, "
            f"confiance {confidence}. **Vérifiez ce type manuellement avant de valider l'analyse.**"
        )

    evidence = detection.get("evidence")
    if evidence:
        with st.expander("Justification de la détection de type"):
            st.caption(evidence)


def _format_context_sentence(context):
    """Phrase narrative du contexte dossier (BLOC D) au lieu d'une ligne de
    champs bruts façon `A | Sensible | 400 | Mandated Lead Arranger` — cf.
    retour Elisa 2026-08-20, "en faire un vrai rapport". Les 4 champs sont
    obligatoires avant analyse (cf. app.py:900-905, manual_fields_ok) donc
    tous présents dans le cas courant ; les clauses restent individuellement
    optionnelles ici en défensif pour d'anciens résultats en cache
    (session_state d'une exécution antérieure au champ)."""
    ep = context.get("ep_classification")
    sensitivity = context.get("sensitivity")
    amount = context.get("financing_amount")
    role = context.get("cacib_role")

    if not any([ep, sensitivity, amount, role]):
        return ""

    lead = f"classé **Catégorie {ep}** (Equator Principles)" if ep else "présente le contexte suivant"
    clauses = []
    if sensitivity:
        clauses.append(f"un statut de portefeuille **{sensitivity}**")
    if amount:
        clauses.append(f"un financement de **{amount}**")
    if role:
        clauses.append(f"la banque intervenant en tant que **{role}**")

    sentence = f"Ce dossier est {lead}"
    if clauses:
        sentence += ", avec " + ", ".join(clauses)
    return sentence + "."


# ============================================================================
# ZONE 2 — EXECUTIVE RISK SUMMARY
# ============================================================================

def _render_executive_summary(result_v4):
    st.markdown("## Executive Risk Summary")

    _render_score(result_v4)
    _render_synthesis(result_v4)

    questions = result_v4["questions"]
    _render_risk_driver_group(questions)
    _render_verification_group(questions)
    _render_favorable_group(questions)


def _render_score(result_v4):
    scoring = result_v4["scoring"]
    score = scoring["score"]
    color = scoring["color"]

    st.markdown(
        f'<div style="text-align:center;padding:20px;border-radius:12px;'
        f'background:{_COLOR_MAP.get(color, "#ccc")}20;'
        f'border:2px solid {_COLOR_MAP.get(color, "#ccc")}">'
        f'<h1 style="margin:0;color:{_COLOR_MAP.get(color, "#333")}">'
        f'{score}/100</h1>'
        f'<p style="margin:4px 0 0 0;font-weight:600">{color}'
        f'{"  — Éliminatoire" if scoring.get("saturation") else ""}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.metric("Questions actives", f"{scoring['questions_active']} / 12")
    with col_b:
        st.metric("Plafond atténuation", "Oui" if scoring["cap_applied"] else "Non")
    if scoring["cap_applied"]:
        st.caption(
            f"⚠️ Gain d'atténuation plafonné : {scoring['total_gain']} → {scoring['total_gain_capped']}"
        )
    if scoring["questions_na"] > 0:
        st.caption(f"Questions N/A : {scoring['questions_na']}")

    st.markdown("---")


def _render_synthesis(result_v4):
    """Synthèse LLM — remontée juste sous le score (audit UI 2026-08-20 :
    avant, position 4/5 dans la page, après le score ET après la liste
    brute des signaux). Masquée si absente (fail-open, cf.
    grid_analyze._generate_synthesis) — aucune synthèse fabriquée ici."""
    synthesis = result_v4.get("synthesis")
    if not synthesis:
        return

    st.markdown("### Synthèse")
    st.write(synthesis)
    st.markdown("---")


def _render_risk_driver_group(questions):
    st.markdown("### Principaux facteurs de risque")
    drivers = _top_risk_drivers(questions)
    if not drivers:
        st.success("Aucun facteur de risque identifié.")
        st.markdown("---")
        return

    for q in drivers:
        mit_label = q.get("mitigation_label")
        suffix = f" · Mitigation : {mit_label}" if mit_label else ""
        st.markdown(_question_line(q, suffix))
        verbatim = _truncated_verbatim((q.get("evidence_r") or {}).get("passage"))
        if verbatim:
            st.caption(f'"{verbatim}"')

    st.markdown("---")


def _render_verification_group(questions):
    st.markdown("### Points nécessitant une vérification humaine")
    to_check = _needs_verification(questions)
    if not to_check:
        st.caption("Aucun point en attente de vérification.")
        st.markdown("---")
        return

    for q in to_check:
        st.markdown(_question_line(q))
        note = q.get("confidence_note")
        if note:
            st.caption(note)

    st.markdown("---")


def _render_favorable_group(questions):
    st.markdown("### Points favorables")
    favorable = _favorable_points(questions)
    if not favorable:
        st.caption("Aucun élément favorable identifié pour l'instant.")
        st.markdown("---")
        return

    for q in favorable:
        label = f"🟢 **{q['sous_theme']}** _{q['code']}_"
        if q["status"] == "NON":
            st.markdown(f"{label} — risque écarté (preuve explicite)")
            verbatim = _truncated_verbatim((q.get("evidence_r") or {}).get("passage"))
            if verbatim:
                st.caption(f'"{verbatim}"')
        else:
            mit_label = q.get("mitigation_label") or "Mitigation prouvée"
            st.markdown(f"{label} — {mit_label}")

    st.markdown("---")


# ============================================================================
# ZONE 3 — GRILLE DÉTAILLÉE (12 questions, vue d'analyse approfondie)
# ============================================================================

def _render_grid(result_v4):
    st.markdown("## Grille détaillée — analyse approfondie")
    st.caption(
        "Vue complète des 12 critères de la grille — pour vérifier le détail d'un "
        "facteur déjà identifié ci-dessus, ou explorer les critères NON/N/A non "
        "repris dans le résumé."
    )

    for q in result_v4["questions"]:
        icon = _STATUS_ICON.get(q["status"], "⚪")
        header = f"{icon} **{q['sous_theme']}** _{q['code']}_ — {q['status']}"

        # Rien à déplier pour un NON par silence standard (schéma
        # a_condition="r_oui"), non attesté — mais JAMAIS pour NA
        # (verbatim de justification obligatoire, cf. grid_questions.
        # SILENCE_VALUES["NA"]) ni pour un NON attesté (preuve à montrer).
        has_detail = not (
            q["status"] == "NON" and not q.get("atteste") and q.get("a_condition", "r_oui") == "r_oui"
        )

        if not has_detail:
            st.markdown(header)
            continue

        with st.expander(header, expanded=False):
            ev_r = q.get("evidence_r")
            if ev_r and ev_r.get("passage"):
                st.markdown("**Preuve de risque**")
                st.info(f"📄 Page {ev_r.get('page') or '?'} — *\"{ev_r['passage']}\"*")

            ev_a = q.get("evidence_a")
            if ev_a:
                if ev_a.get("verbatim_mesure"):
                    st.markdown("**Preuve de mitigation**")
                    st.success(f"📄 Page {ev_a.get('page') or '?'} — *\"{ev_a['verbatim_mesure']}\"*")
                if ev_a.get("verbatim_defaillance"):
                    st.markdown("**Défaillance constatée**")
                    st.warning(f"*\"{ev_a['verbatim_defaillance']}\"*")

            mit_label = q.get("mitigation_label")
            if mit_label:
                st.markdown(f"**Statut mitigation :** {mit_label}")

            confidence = q.get("confidence_note")
            if confidence:
                if q.get("silence_applied"):
                    # Directive "gestion INCONNU" (2026-08-20) : une
                    # absence totale de passage n'est pas un "doute de
                    # l'IA" — affichage neutre, sans label ni
                    # interprétation, texte canonique tel quel.
                    st.caption(confidence)
                else:
                    st.markdown("**Doute de l'analyste IA**")
                    st.caption(confidence)

            qualifying = q.get("qualifying")
            if qualifying:
                qual_items = [(k, v) for k, v in qualifying.items() if v and v is not True]
                if qual_items:
                    st.markdown("**Champs qualifiants** (non scorants)")
                    for k, v in qual_items:
                        st.caption(f"_{k}_ : {v}")

    scoring = result_v4["scoring"]
    gain_display = f" +{scoring['total_gain_capped']}" if scoring["total_gain_capped"] > 0 else ""
    st.caption(
        f"Score = max(0, 100 {scoring['total_penalty']:+d}{gain_display}) = {scoring['score']}"
    )


# ============================================================================
# EXPORTS
# ============================================================================

def _render_export_buttons(result_v4, project_name):
    # Import différé (CC-V4-10) : même principe que grid_analyze/grid_sections
    # dans app.py — export.py n'est requis que si l'onglet V4 est rendu.
    import export

    st.markdown("---")
    col_pdf, col_excel = st.columns(2)

    with col_pdf:
        pdf_bytes = export.build_grid_v4_pdf(result_v4, project_name=project_name)
        st.download_button(
            label="📥 Télécharger le rapport PDF",
            data=pdf_bytes,
            file_name="esg_grid_v4.pdf",
            mime="application/pdf",
        )

    with col_excel:
        excel_bytes = export.build_grid_v4_excel(result_v4, project_name=project_name)
        st.download_button(
            label="📥 Télécharger le détail Excel",
            data=excel_bytes,
            file_name="esg_grid_v4.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
