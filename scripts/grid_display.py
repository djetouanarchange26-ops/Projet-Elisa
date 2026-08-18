"""
GRILLE ESG V4 — affichage Streamlit (directive CC-V4-08)
=====================================================================
Rendu de l'onglet « ESG Grid V4 (beta) » : assemblage pur d'un résultat
déjà produit par grid_analyze.analyze_grid() (cf. grid_result.py pour le
contrat exact) en composants Streamlit. Aucune logique de scoring ni
d'appel LLM ici — uniquement de l'affichage.

CHOIX: module séparé plutôt qu'une fonction de plus dans app.py (déjà
~1270 lignes) — cf. directive CC-V4-08, "le fichier séparé est plus
propre". Import plat (`import grid_display`), cohérent avec le reste de
scripts/ (pas de package).

3 sections empilées verticalement (vision produit Elisa) :
  1. Risk Summary   — score, couleur, top drivers, points INCONNU/favorables
  2. Grille détaillée — tableau des 12 questions
  3. Evidence explorer — un expander par question, verbatims + doute LLM

FRAGILE (écarts corrigés par rapport au brouillon de la directive) :
  - `reading_mode_label` est un champ de NIVEAU RÉSULTAT
    (result_v4["reading_mode_label"]), pas de result_v4["scoring"]
    (cf. grid_result.build_grid_result, CC-V4-03) — le brouillon lisait
    scoring["reading_mode_label"], qui n'existe pas.
  - `mitigation_label`/`evidence_r["page"]`/`evidence_a["page"]` sont des
    clés TOUJOURS PRÉSENTES mais dont la valeur peut être None — un
    `dict.get(clé, défaut)` ne retombe sur `défaut` que si la clé est
    ABSENTE, pas si sa valeur est None. Corrigé en `dict.get(clé) or
    défaut` partout où c'est pertinent.
  - `shared_cap_applied` : le brouillon réécrivait la cellule "Pénalité"
    en string ("0 (plafonné)") pour la ligne concernée, ce qui aurait
    rendu la colonne à dtype mixte (int + str) et cassé le formatage
    st.column_config.NumberColumn de tout le tableau. Déplacé dans une
    colonne "Notes" dédiée, avec atteste/verrou_applique.
  - Evidence explorer : le brouillon masquait aussi les questions
    status="NA" sans evidence_r pertinent à montrer — or NA exige
    TOUJOURS un evidence_r (cf. grid_questions.SILENCE_VALUES["NA"],
    "verbatim obligatoire") : le masquer priverait l'analyste de la
    justification du N/A. Seul "NON" par silence standard est masqué.
"""

import logging

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

_COLOR_MAP = {
    "VERT": "#2ecc71",
    "JAUNE": "#f1c40f",
    "ORANGE": "#e67e22",
    "ROUGE": "#e74c3c",
}


def render_grid_v4_tab(result_v4, project_name=""):
    """Affiche le résultat de la Grille V4 dans l'onglet Streamlit.

    result_v4 : dict retourné par grid_analyze.analyze_grid(), ou None si
    le pipeline V4 est désactivé ou a échoué (cf. app.py : les exceptions
    sont déjà attrapées en amont, ce module ne reçoit jamais que None ou
    un résultat bien formé).
    project_name : nom du projet/document analysé, transmis tel quel aux
    exports PDF/Excel (cf. export.build_grid_v4_pdf/build_grid_v4_excel) —
    purement cosmétique, absent du calcul.
    """
    if result_v4 is None:
        st.info("La Grille V4 n'a pas pu être calculée. Vérifiez les logs.")
        return

    _render_risk_summary(result_v4)
    _render_grid_table(result_v4)
    _render_evidence_explorer(result_v4)
    _render_export_buttons(result_v4, project_name)


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


# ============================================================================
# SECTION 1 — RISK SUMMARY
# ============================================================================

def _render_risk_summary(result_v4):
    scoring = result_v4["scoring"]
    score = scoring["score"]
    color = scoring["color"]
    mode_label = result_v4.get("reading_mode_label") or "—"

    st.header("ESG Risk Summary")

    col_score, col_meta = st.columns([1, 2])
    with col_score:
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

    with col_meta:
        st.markdown(f"**Mode de lecture** : {mode_label}")
        st.markdown(f"**Questions actives** : {scoring['questions_active']} / 12")
        if scoring["questions_na"] > 0:
            st.markdown(f"**Questions N/A** : {scoring['questions_na']}")
        if scoring["cap_applied"]:
            st.markdown(
                f"⚠️ Plafond d'atténuation appliqué "
                f"({scoring['total_gain']} → {scoring['total_gain_capped']})"
            )

    # Top Risk Drivers (questions côté "risque" de leur schéma, cf.
    # a_condition — OUI pour le schéma standard, NON pour B.3.1).
    risk_drivers = [
        q for q in result_v4["questions"]
        if q["status"] == "OUI" or (q.get("a_condition") == "r_non" and q["status"] == "NON")
    ]
    risk_drivers.sort(key=lambda q: q["penalty"])

    if risk_drivers:
        st.subheader("Risques identifiés")
        for q in risk_drivers:
            penalty = q["penalty"]
            mit_label = q.get("mitigation_label") or "—"
            gain = q.get("gain", 0)
            net = penalty + gain
            st.markdown(
                f"- **{q['code']}** {q['sous_theme']} — "
                f"pénalité {penalty}, mitigation {mit_label} "
                f"({'+' if gain > 0 else ''}{gain}), net = {net}"
            )

    # Points INCONNU (silence sur une question d'état/système, cf. R5)
    inconnu_qs = [q for q in result_v4["questions"] if q["status"] == "INCONNU"]
    if inconnu_qs:
        st.subheader("Non documenté")
        for q in inconnu_qs:
            st.markdown(f"- **{q['code']}** {q['sous_theme']} — information absente du document")

    # Mitigations prouvées
    proven_mits = [q for q in result_v4["questions"] if q.get("mitigation_status") == "OUI_PROUVEE"]
    if proven_mits:
        st.subheader("Points favorables")
        for q in proven_mits:
            st.markdown(f"- **{q['code']}** {q['sous_theme']} — mitigation prouvée (+{q.get('gain', 0)})")


# ============================================================================
# SECTION 2 — GRILLE DÉTAILLÉE
# ============================================================================

def _render_grid_table(result_v4):
    scoring = result_v4["scoring"]
    score = scoring["score"]

    st.header("Grille d'évaluation — 12 questions")

    rows = []
    for q in result_v4["questions"]:
        notes = []
        if q.get("atteste"):
            notes.append("attesté")
        if q.get("verrou_applique"):
            notes.append("verrou B.2.1→B.2.2")
        if q.get("shared_cap_applied"):
            notes.append("plafond partagé A.1")

        rows.append({
            "Code": q["code"],
            "Sous-thème": q["sous_theme"],
            "Statut": q["status"],
            "Mitigation": q.get("mitigation_label") or "—",
            "Pénalité": q["penalty"],
            "Gain": q.get("gain", 0),
            "Net": q["penalty"] + q.get("gain", 0),
            "Notes": ", ".join(notes),
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Pénalité": st.column_config.NumberColumn(format="%d"),
            "Gain": st.column_config.NumberColumn(format="%+d"),
            "Net": st.column_config.NumberColumn(format="%d"),
        },
    )

    gain_display = f" +{scoring['total_gain_capped']}" if scoring["total_gain_capped"] > 0 else ""
    st.caption(
        f"Score = max(0, 100 {scoring['total_penalty']:+d}{gain_display}) = {score}"
    )


# ============================================================================
# SECTION 3 — EVIDENCE EXPLORER
# ============================================================================

def _render_evidence_explorer(result_v4):
    st.header("Preuves")

    for q in result_v4["questions"]:
        # Rien à montrer pour un NON par silence en schéma standard, non
        # attesté — mais JAMAIS pour NA (verbatim de justification
        # obligatoire, cf. grid_questions.SILENCE_VALUES["NA"]).
        if q["status"] == "NON" and not q.get("atteste") and q.get("a_condition", "r_oui") == "r_oui":
            continue

        with st.expander(f"**{q['code']}** — {q['sous_theme']} ({q['status']})", expanded=False):
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

            confidence = q.get("confidence_note")
            if confidence:
                st.markdown("**Doute de l'analyste IA**")
                st.caption(confidence)

            qualifying = q.get("qualifying")
            if qualifying:
                qual_items = [(k, v) for k, v in qualifying.items() if v and v is not True]
                if qual_items:
                    st.markdown("**Champs qualifiants** (non scorants)")
                    for k, v in qual_items:
                        st.caption(f"_{k}_ : {v}")
