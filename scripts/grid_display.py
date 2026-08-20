"""
GRILLE ESG V4 — affichage Streamlit (directive CC-V4-08, refonte maquette
Elisa 2026-08-20)
=====================================================================
Rendu de l'onglet « ESG Grid V4 (beta) » : assemblage pur d'un résultat
déjà produit par grid_analyze.analyze_grid() (cf. grid_result.py pour le
contrat exact) en composants Streamlit. Aucune logique de scoring ni
d'appel LLM ici — uniquement de l'affichage. `result_v4` n'est jamais
modifié — cf. "Ce qu'il ne faut PAS faire" de la directive refonte
layout (ne pas changer la structure du dict, seulement son affichage).

CHOIX: module séparé plutôt qu'une fonction de plus dans app.py (déjà
~1270 lignes) — cf. directive CC-V4-08, "le fichier séparé est plus
propre". Import plat (`import grid_display`), cohérent avec le reste de
scripts/ (pas de package).

5 sections empilées verticalement (maquette papier Elisa, 2026-08-20 —
remplace l'ancien layout Risk Summary/Grille/Evidence explorer à 3
blocs) :
  1. Description du projet — contexte dossier (4 champs BLOC D), mode de
     lecture, document, date de génération
  2. Score — score/100, couleur, questions actives, plafond atténuation
  3. Signaux identifiés — KPI : toutes les questions OUI/INCONNU avec
     verbatim tronqué (fusion de l'ancien "Risques identifiés" + "Non
     documenté")
  4. Synthèse — texte libre optionnel (result_v4.get("synthesis")),
     section masquée si absent. Aucune clé "synthesis" n'existe encore
     dans le contrat result_v4 (cf. grid_result.py) — deep_analysis
     n'est pas branché sur le pipeline V4 à ce jour (cf. app.py:
     deep_analysis n'est appelé que si pipeline_used=="legacy"). Lu en
     `.get()` défensif exprès : la section reste masquée aujourd'hui et
     s'activera automatiquement le jour où ce champ sera peuplé, sans
     modifier ce module (donc sans toucher grid_analyze.py/grid_result.py,
     hors périmètre de cette directive).
  5. Grille — liste des 12 questions, ligne compacte si rien à montrer,
     expander sinon (fusionne l'ancien tableau + evidence explorer en une
     seule liste, comme demandé par la maquette)

FRAGILE (écarts corrigés par rapport à des brouillons de directive
précédents — même vigilance appliquée à la maquette 2026-08-20) :
  - `reading_mode_label` est un champ de NIVEAU RÉSULTAT
    (result_v4["reading_mode_label"]), pas de result_v4["scoring"] (cf.
    grid_result.build_grid_result, CC-V4-03).
  - Les questions n'ont pas de clé "sub_theme"/"net"/"verbatim" — ce sont
    "sous_theme", penalty+gain calculé ici, et evidence_r["passage"]
    (cf. grid_result.py pour le contrat exact).
  - `mitigation_label`/`evidence_r["page"]`/`evidence_a["page"]` sont des
    clés TOUJOURS PRÉSENTES mais dont la valeur peut être None — un
    `dict.get(clé, défaut)` ne retombe sur `défaut` que si la clé est
    ABSENTE, pas si sa valeur est None. `dict.get(clé) or défaut` partout
    où c'est pertinent.
  - Grille (section 5) : masquer une question ne s'applique QUE pour un
    NON par silence standard, non attesté, côté a_condition="r_oui" — un
    NA exige TOUJOURS un evidence_r (cf. grid_questions.SILENCE_VALUES
    ["NA"], "verbatim obligatoire") et reste donc toujours dépliable.
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

    _render_document_type_detection(result_v4)
    _render_project_description(result_v4, project_name)
    _render_score(result_v4)
    _render_signals(result_v4)
    _render_synthesis(result_v4)
    _render_grid(result_v4)
    _render_export_buttons(result_v4, project_name)


def _render_document_type_detection(result_v4):
    """Affiche la détection R11 (grid_doctype.py) : type détecté, confiance,
    justification. CHOIX: affichée en tête, avant même le score — le type de
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
# SECTION 1 — DESCRIPTION DU PROJET
# ============================================================================

def _render_project_description(result_v4, project_name):
    st.markdown("### Description du projet")

    context = result_v4.get("context") or {}
    ctx_parts = []
    if context.get("ep_classification"):
        ctx_parts.append(f"**EP :** {context['ep_classification']}")
    if context.get("sensitivity"):
        ctx_parts.append(f"**Sensibilité :** {context['sensitivity']}")
    if context.get("financing_amount"):
        ctx_parts.append(f"**Montant :** {context['financing_amount']}")
    if context.get("cacib_role"):
        ctx_parts.append(f"**Rôle :** {context['cacib_role']}")
    if ctx_parts:
        st.markdown(" · ".join(ctx_parts))

    mode_label = result_v4.get("reading_mode_label") or "—"
    st.markdown(f"**Mode de lecture :** {mode_label}")
    if project_name:
        st.markdown(f"**Document :** {project_name}")
    st.markdown(f"**Date :** {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    st.markdown("---")


# ============================================================================
# SECTION 2 — SCORE
# ============================================================================

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


# ============================================================================
# SECTION 3 — SIGNAUX IDENTIFIÉS (KPI)
# ============================================================================

def _render_signals(result_v4):
    st.markdown("### Signaux identifiés")

    risk_questions = [q for q in result_v4["questions"] if q["status"] in ("OUI", "INCONNU")]

    if not risk_questions:
        st.success("Aucun risque identifié.")
        st.markdown("---")
        return

    icon_map = {"OUI": "🔴", "INCONNU": "🟡"}
    for q in risk_questions:
        net = q["penalty"] + q.get("gain", 0)
        mit_label = q.get("mitigation_label")
        mit_suffix = f" · Mitigation : {mit_label}" if mit_label else ""

        st.markdown(
            f"**{icon_map.get(q['status'], '⚪')} {q['code']} — {q['sous_theme']}** "
            f"({net:+d} pts{mit_suffix})"
        )

        ev_r = q.get("evidence_r")
        verbatim = ev_r.get("passage") if ev_r else None
        if verbatim:
            # Tronqué à 200 caractères pour le résumé (maquette Elisa) — le
            # verbatim complet reste visible dans la Grille, section 5.
            display = verbatim[:200] + "…" if len(verbatim) > 200 else verbatim
            st.caption(f'"{display}"')
        elif q["status"] == "INCONNU":
            # Directive "gestion INCONNU" (2026-08-20) : rien inventé quand
            # aucun élément n'a été extrait — même texte canonique que
            # grid_analyze._NO_ELEMENT_FOUND (confidence_note), affiché ici
            # tel quel plutôt que reformulé.
            st.caption(q.get("confidence_note") or "Aucun élément n'a été trouvé.")

    st.markdown("---")


# ============================================================================
# SECTION 4 — SYNTHÈSE (si disponible)
# ============================================================================

def _render_synthesis(result_v4):
    synthesis = result_v4.get("synthesis")
    if not synthesis:
        return

    st.markdown("### Synthèse")
    st.write(synthesis)
    st.markdown("---")


# ============================================================================
# SECTION 5 — GRILLE (12 questions, table + preuves fusionnées)
# ============================================================================

def _render_grid(result_v4):
    st.markdown("### Grille d'évaluation — 12 questions")

    status_icon = {"OUI": "🔴", "NON": "🟢", "INCONNU": "🟡", "NA": "⚪"}

    for q in result_v4["questions"]:
        icon = status_icon.get(q["status"], "⚪")
        header = f"{icon} {q['code']} — {q['sous_theme']} : **{q['status']}**"

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
