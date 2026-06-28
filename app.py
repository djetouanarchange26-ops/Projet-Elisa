"""
NLP ESG Risk Intelligence — Streamlit Interface
CA-CIB · Portfolio Management · Energy & Infrastructure Group
Squelette avec données fictives — sera branché sur analyze() au Bloc 3.1
"""

import streamlit as st
import numpy as np
import pandas as pd

# ── Page config ──────────────────────────────────────────────
st.set_page_config(
    page_title="ESG Risk Intelligence — CA-CIB",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS — Charte CA-CIB (IBM Plex, green/teal/red) ──────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

:root {
    --green: #006F4E;
    --teal: #009B9D;
    --red: #ED1C24;
    --green-light: #e6f7f0;
    --teal-light: #e6f7f9;
    --red-light: #fee;
    --orange: #f59e0b;
    --orange-light: #fff4e6;
    --bg: #f5f5f5;
    --surface: #ffffff;
    --border: #e0e0e0;
    --text: #333;
    --muted: #666;
}

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
}

/* Header bar */
.header-bar {
    background: white;
    border-bottom: 3px solid var(--green);
    padding: 0.8rem 2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: -1rem -1rem 1.5rem -1rem;
    box-shadow: 0 2px 4px rgba(0,0,0,0.08);
}
.header-logo {
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--green);
}
.header-logo span { color: var(--teal); }
.header-badge {
    background: var(--green-light);
    color: var(--green);
    padding: 0.35rem 0.9rem;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
}

/* Cards */
.card {
    background: white;
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.card-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 1rem;
    padding-bottom: 0.75rem;
    border-bottom: 2px solid #f0f0f0;
}

/* Risk grade badge */
.risk-grade {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 2.5rem;
    font-weight: 700;
    width: 65px;
    height: 65px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
}
.grade-A { background: var(--red-light); color: var(--red); }
.grade-B { background: var(--orange-light); color: var(--orange); }
.grade-C { background: #fff8e1; color: #e65100; }
.grade-D { background: var(--green-light); color: var(--green); }

/* Score bars */
.score-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.6rem;
}
.score-lbl {
    font-size: 0.8rem;
    color: var(--muted);
    width: 180px;
    font-weight: 500;
}
.score-bg {
    flex: 1;
    height: 8px;
    background: #f0f0f0;
    border-radius: 4px;
    overflow: hidden;
}
.score-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.9s ease;
}
.score-num {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.8rem;
    font-weight: 600;
    width: 32px;
    text-align: right;
}

/* Flag items */
.flag-item {
    padding: 0.75rem 1rem;
    border-radius: 6px;
    margin-bottom: 0.5rem;
    border-left: 3px solid transparent;
    background: #fafafa;
    font-size: 0.85rem;
}
.flag-high { border-left-color: var(--red); background: rgba(237,28,36,0.04); }
.flag-medium { border-left-color: var(--orange); background: rgba(245,158,11,0.04); }
.flag-low { border-left-color: var(--teal); background: var(--teal-light); }

/* Annotated text */
.annotated-text {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.82rem;
    line-height: 1.9;
    white-space: pre-wrap;
    word-break: break-word;
}
.hl-red {
    background: rgba(237,28,36,0.12);
    border-bottom: 2px solid var(--red);
    border-radius: 2px;
    padding: 0 2px;
}
.hl-orange {
    background: rgba(245,158,11,0.12);
    border-bottom: 2px solid var(--orange);
    border-radius: 2px;
    padding: 0 2px;
}
.hl-teal {
    background: rgba(0,155,157,0.12);
    border-bottom: 2px solid var(--teal);
    border-radius: 2px;
    padding: 0 2px;
}

/* Pattern items */
.pattern-item {
    padding: 0.75rem 1rem;
    border-radius: 6px;
    margin-bottom: 0.6rem;
    font-size: 0.88rem;
}
.severity-high { background: var(--red-light); border-left: 4px solid var(--red); }
.severity-med { background: var(--orange-light); border-left: 4px solid var(--orange); }

/* Sidebar styling */
section[data-testid="stSidebar"] {
    background: white;
    border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] .stRadio label {
    font-size: 0.9rem;
}
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────
st.markdown("""
<div class="header-bar">
    <div class="header-logo">CA-CIB <span>ESG Risk Intelligence</span></div>
    <div class="header-badge">NLP Prototype — MVP</div>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🧭 Navigation")
    page = st.radio(
        "Section",
        ["🔍 Transaction Analysis", "📊 Portfolio Dashboard", "📚 Pattern Library", "⚙️ Settings"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.markdown("##### 📁 Recent Analyses")
    st.markdown("""
    <div style="font-size:0.85rem; color:#666;">
    🇺🇬 Bujagali Energy (Grade B)<br>
    🇮🇳 Tata Ultra Mega (Grade A)<br>
    🇨🇱 Alto Maipo (Grade A)<br>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    st.caption("v0.1 MVP · Données publiques IFC/CAO")


# ══════════════════════════════════════════════════════════════
# PAGE 1 — TRANSACTION ANALYSIS
# ══════════════════════════════════════════════════════════════
if page == "🔍 Transaction Analysis":
    st.markdown("## 🔍 Transaction Analysis")
    st.markdown("*Upload a project document to detect ESG risk signals*")

    # ── Upload zone ──────────────────────────────────────────
    uploaded_file = st.file_uploader(
        "Upload PDF — ESRS, ESIA, Monitoring Report, INSP Review",
        type=["pdf", "txt"],
        help="Le fichier est traité localement. Aucune donnée ne quitte votre machine."
    )

    # ── Analyze button ───────────────────────────────────────
    col_btn, col_status = st.columns([1, 3])
    with col_btn:
        analyze_clicked = st.button("▶ Run Analysis", type="primary", use_container_width=True)
    with col_status:
        if uploaded_file and analyze_clicked:
            st.info("⏳ Analyse en cours... extraction → embeddings → scoring → SHAP")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════
    # RÉSULTATS (données fictives — sera remplacé par analyze())
    # ══════════════════════════════════════════════════════════

    # --- Données fictives ---
    DUMMY = {
        "risk_grade": "A",
        "risk_label": "ESCALADE",
        "probability_12m": 0.82,
        "flag_scores": {
            "Community & Stakeholder Risk": 87,
            "Pollution & Monitoring Risk": 45,
            "Structural Compliance Risk": 32,
        },
        "signals": [
            {"category": "FLAG 1 — COMMUNITY", "text": "NGOs issuing formal statements opposing project continuation", "severity": "high"},
            {"category": "FLAG 1 — COMMUNITY", "text": "Grievance mechanism independence contested by local leaders", "severity": "high"},
            {"category": "FLAG 2 — POLLUTION", "text": "Monitoring data gaps identified in quarterly discharge reports", "severity": "medium"},
            {"category": "FLAG 2 — POLLUTION", "text": "ESAP item on water quality monitoring overdue by 6 months", "severity": "medium"},
            {"category": "FLAG 3 — COMPLIANCE", "text": "Biodiversity offset plan not submitted within agreed timeline", "severity": "low"},
        ],
        "similar_cases": [
            {"name": "Bujagali Energy (Uganda)", "similarity": 0.89, "outcome": "Worker compensation dispute, 7-year monitoring"},
            {"name": "Nachtigal Hydro (Cameroon)", "similarity": 0.84, "outcome": "Resettlement complaints, GBVH concerns"},
            {"name": "Alto Maipo (Chile)", "similarity": 0.78, "outcome": "Water contamination, community conflict, loss of life"},
        ],
        "shap_values": {"Community & Stakeholder": 0.42, "Pollution & Monitoring": 0.18, "Structural Compliance": 0.08},
        "annotated_text": (
            'The project has faced <span class="hl-red">significant opposition from local fishing communities</span> '
            'who report declining catches since construction began. '
            '<span class="hl-red">Three NGOs have issued formal statements</span> calling for project suspension. '
            'The <span class="hl-orange">quarterly discharge monitoring report for Q2 was not submitted</span> '
            'within the required timeframe. Water quality parameters at the downstream sampling point '
            '<span class="hl-orange">exceeded IFC EHS guideline thresholds for total suspended solids</span>. '
            'The <span class="hl-teal">biodiversity offset equivalence assessment remains pending</span> '
            'per the ESAP timeline agreed at financial close.'
        ),
    }

    # Affichage conditionnel : si on a cliqué analyze ou pas
    show_results = analyze_clicked and uploaded_file

    if not show_results:
        # Affiche les résultats fictifs pour la démo
        st.info("👆 Upload a document and click **Run Analysis** to see real results. Below is a demo with sample data.")

    # ── Risk Grade Summary ───────────────────────────────
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">📊 Risk Assessment Summary</div>', unsafe_allow_html=True)

    col_grade, col_info = st.columns([1, 4])
    with col_grade:
        grade = DUMMY["risk_grade"]
        st.markdown(f'<div class="risk-grade grade-{grade}">{grade}</div>', unsafe_allow_html=True)
    with col_info:
        st.markdown(f"**Risk Label:** {DUMMY['risk_label']}")
        st.markdown(f"**Probability of ESG event in 12 months:** {DUMMY['probability_12m']:.0%}")
        st.markdown("**Recommendation:** Escalade immédiate au credit committee. Downgrade proposé.")

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Flag Scores ──────────────────────────────────────
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">🎯 Flag Scores</div>', unsafe_allow_html=True)

    colors = {"Community & Stakeholder Risk": "#ED1C24", "Pollution & Monitoring Risk": "#f59e0b", "Structural Compliance Risk": "#009B9D"}
    for label, score in DUMMY["flag_scores"].items():
        color = colors[label]
        st.markdown(f"""
        <div class="score-row">
            <div class="score-lbl">{label}</div>
            <div class="score-bg"><div class="score-fill" style="width:{score}%;background:{color};"></div></div>
            <div class="score-num" style="color:{color};">{score}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Detected Signals + Annotated Document ────────────
    col_signals, col_doc = st.columns(2)

    with col_signals:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">🚨 Detected Signals</div>', unsafe_allow_html=True)
        for sig in DUMMY["signals"]:
            css_class = f"flag-{sig['severity']}"
            icon = "🔴" if sig["severity"] == "high" else ("🟡" if sig["severity"] == "medium" else "🔵")
            st.markdown(f"""
            <div class="flag-item {css_class}">
                {icon} <strong style="font-size:0.7rem;color:#999;">{sig['category']}</strong><br>
                {sig['text']}
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with col_doc:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">📄 Annotated Document</div>', unsafe_allow_html=True)
        st.markdown("**Legend:** "
                     '<span class="hl-red">Community risk</span> · '
                     '<span class="hl-orange">Pollution risk</span> · '
                     '<span class="hl-teal">Compliance risk</span>',
                     unsafe_allow_html=True)
        st.markdown(f'<div class="annotated-text">{DUMMY["annotated_text"]}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Survival Curve + SHAP ────────────────────────────
    col_surv, col_shap = st.columns(2)

    with col_surv:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">📈 Survival Curve — Probability of No ESG Event</div>', unsafe_allow_html=True)

        # Courbe de survie fictive
        months = np.arange(0, 61)
        survival = np.exp(-0.028 * months)  # décroissance exponentielle fictive
        chart_df = pd.DataFrame({"Months": months, "Survival Probability": survival})
        st.line_chart(chart_df, x="Months", y="Survival Probability", color="#006F4E")

        # Marqueur 12 mois
        prob_12 = 1 - np.exp(-0.028 * 12)
        st.markdown(f"**→ P(event within 12 months) = {prob_12:.0%}**")

        st.markdown('</div>', unsafe_allow_html=True)

    with col_shap:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">🔬 SHAP — Feature Contributions</div>', unsafe_allow_html=True)

        # Graphique SHAP fictif (barres horizontales)
        shap_df = pd.DataFrame({
            "Feature": list(DUMMY["shap_values"].keys()),
            "SHAP Value": list(DUMMY["shap_values"].values()),
        }).sort_values("SHAP Value", ascending=True)

        st.bar_chart(shap_df, x="Feature", y="SHAP Value", color="#006F4E", horizontal=True)

        st.markdown("""
        <div style="font-size:0.8rem;color:#666;margin-top:0.5rem;">
        ↑ Higher SHAP value = stronger contribution to the risk score.<br>
        Community & Stakeholder risk is the dominant driver for this project.
        </div>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Historical Similar Cases ─────────────────────────
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">📚 Historical Similar Cases</div>', unsafe_allow_html=True)

    for case in DUMMY["similar_cases"]:
        sim_pct = f"{case['similarity']:.0%}"
        st.markdown(f"""
        <div class="pattern-item severity-high">
            <strong>{case['name']}</strong> — Similarity: {sim_pct}<br>
            <span style="font-size:0.82rem;color:#666;">{case['outcome']}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# PAGE 2 — PORTFOLIO DASHBOARD
# ══════════════════════════════════════════════════════════════
elif page == "📊 Portfolio Dashboard":
    st.markdown("## 📊 Portfolio Dashboard")
    st.markdown("*Vue agrégée du portefeuille — sera activée en V2*")

    # Tableau fictif du portefeuille
    portfolio_df = pd.DataFrame({
        "Project": ["Bujagali Energy", "Tata Ultra Mega", "Alto Maipo", "Daehan Wind", "Zarafshan Wind",
                     "Nachtigal Hydro", "Karot Hydro", "Reventazón HPP"],
        "Country": ["Uganda", "India", "Chile", "Jordan", "Uzbekistan", "Cameroon", "Pakistan", "Costa Rica"],
        "Sector": ["Hydropower", "Coal Power", "Hydropower", "Wind", "Wind", "Hydropower", "Hydropower", "Hydropower"],
        "Risk Grade": ["B", "A", "A", "C", "D", "B", "B", "C"],
        "P(event 12m)": ["45%", "82%", "76%", "22%", "12%", "51%", "48%", "28%"],
        "Dominant Flag": ["Community", "Community", "Community + Pollution", "Biodiversity", "Pollution", "Community", "Labor", "Biodiversity"],
        "Last Updated": ["2026-06-15", "2026-06-10", "2026-06-20", "2026-06-18", "2026-06-22", "2026-06-14", "2026-06-19", "2026-06-21"],
    })

    # Filtres
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        grade_filter = st.multiselect("Filter by Risk Grade", ["A", "B", "C", "D"], default=["A", "B", "C", "D"])
    with col_f2:
        sector_filter = st.multiselect("Filter by Sector", portfolio_df["Sector"].unique(), default=portfolio_df["Sector"].unique())

    filtered = portfolio_df[portfolio_df["Risk Grade"].isin(grade_filter) & portfolio_df["Sector"].isin(sector_filter)]
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    # Métriques résumé
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Projects", len(filtered))
    col2.metric("Grade A (Escalade)", len(filtered[filtered["Risk Grade"] == "A"]))
    col3.metric("Grade B (Alerte)", len(filtered[filtered["Risk Grade"] == "B"]))
    col4.metric("Grade C-D (Watch)", len(filtered[filtered["Risk Grade"].isin(["C", "D"])]))


# ══════════════════════════════════════════════════════════════
# PAGE 3 — PATTERN LIBRARY
# ══════════════════════════════════════════════════════════════
elif page == "📚 Pattern Library":
    st.markdown("## 📚 Pattern Library")
    st.markdown("*Bibliothèque des signaux ESG historiques détectés dans le corpus IFC/CAO*")

    patterns = [
        {"signal": "NGOs issuing formal statements opposing project", "flag": "Flag 1 — Community", "frequency": "23 occurrences", "avg_time_to_event": "8 months", "severity": "high"},
        {"signal": "Grievance mechanism declared non-independent", "flag": "Flag 1 — Community", "frequency": "18 occurrences", "avg_time_to_event": "6 months", "severity": "high"},
        {"signal": "Local leaders withdraw from consultation process", "flag": "Flag 1 — Community", "frequency": "15 occurrences", "avg_time_to_event": "10 months", "severity": "high"},
        {"signal": "ESAP items outstanding beyond agreed deadline", "flag": "Flag 2 — Pollution", "frequency": "31 occurrences", "avg_time_to_event": "14 months", "severity": "med"},
        {"signal": "Water quality parameters exceed EHS thresholds", "flag": "Flag 2 — Pollution", "frequency": "12 occurrences", "avg_time_to_event": "9 months", "severity": "med"},
        {"signal": "Biodiversity offset not demonstrated", "flag": "Flag 3 — Compliance", "frequency": "8 occurrences", "avg_time_to_event": "18 months", "severity": "low"},
        {"signal": "PS6 Critical Habitat assessment not updated", "flag": "Flag 3 — Compliance", "frequency": "6 occurrences", "avg_time_to_event": "24 months", "severity": "low"},
    ]

    flag_filter = st.selectbox("Filter by Flag", ["All", "Flag 1 — Community", "Flag 2 — Pollution", "Flag 3 — Compliance"])

    for p in patterns:
        if flag_filter != "All" and p["flag"] != flag_filter:
            continue
        css = "severity-high" if p["severity"] == "high" else "severity-med"
        st.markdown(f"""
        <div class="pattern-item {css}">
            <strong>{p['signal']}</strong><br>
            <span style="font-size:0.8rem;color:#666;">
                {p['flag']} · {p['frequency']} · Avg time to event: {p['avg_time_to_event']}
            </span>
        </div>
        """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# PAGE 4 — SETTINGS
# ══════════════════════════════════════════════════════════════
elif page == "⚙️ Settings":
    st.markdown("## ⚙️ Settings")
    st.markdown("*Configuration du modèle et des seuils*")

    st.markdown("### Risk Grade Thresholds")
    col1, col2 = st.columns(2)
    with col1:
        t1 = st.slider("Vigilance → Attention", 0.0, 1.0, 0.25, 0.05)
        t2 = st.slider("Attention → Alerte", 0.0, 1.0, 0.55, 0.05)
    with col2:
        t3 = st.slider("Alerte → Escalade", 0.0, 1.0, 0.80, 0.05)

    st.markdown(f"""
    | Grade | Label | Probability Range | Action |
    |-------|-------|-------------------|--------|
    | D | Vigilance | < {t1:.0%} | Monitoring standard |
    | C | Attention | {t1:.0%} – {t2:.0%} | Revue renforcée à 90 jours |
    | B | Alerte | {t2:.0%} – {t3:.0%} | Downgrade d'un cran proposé |
    | A | Escalade | > {t3:.0%} | Escalade immédiate au credit committee |
    """)

    st.markdown("### Model Configuration")
    st.selectbox("Embedding Model", ["all-MiniLM-L6-v2", "FinBERT (production)", "LegalBERT (production)"], index=0)
    st.number_input("Cox Penalizer", value=0.1, step=0.01)
    st.number_input("SHAP Background Samples", value=30, step=5)
    st.number_input("FAISS Top-K", value=10, step=1)

    st.markdown("### Corpus Info")
    st.markdown("""
    - **Projects with events:** 21
    - **Control projects:** 15
    - **Total chunks:** 939
    - **Embedding dimension:** 384
    """)