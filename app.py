"""
NLP ESG Risk Intelligence — Streamlit Interface
CA-CIB · Portfolio Management · Energy & Infrastructure Group
"""

import html
import re
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
import pandas as pd
import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from analyze import analyze
from model import DEFAULT_RISK_THRESHOLDS
from signals import SIGNAL_KEYWORDS, SIGNAL_PATTERNS
import llm_confirm
import export

CHUNKS_PATH = Path(__file__).resolve().parent / "data/processed/chunks.csv"

FLAG_LABELS = {
    "flag1_community":  "Community & Stakeholder Risk",
    "flag2_pollution":  "Pollution & Monitoring Risk",
    "flag3_compliance": "Structural Compliance Risk",
}
SEVERITY_BY_FLAG = {1: "high", 2: "medium", 3: "low"}
HL_CLASS_BY_FLAG = {1: "hl-red", 2: "hl-orange", 3: "hl-teal"}
# FRAGILE: fallback seulement — analyze() génère normalement une recommandation
# contextualisée via llm_confirm.generate_recommendation (basée sur les signaux
# réellement détectés). Ce template fixe par grade ne sert que si Ollama est
# injoignable (result["recommendation"] est None dans ce cas).
RECOMMENDATION_BY_GRADE = {
    "A": "Escalade immédiate au credit committee. Downgrade proposé.",
    "B": "Alerte — downgrade d'un cran proposé.",
    "C": "Attention — revue renforcée à 90 jours.",
    "D": "Vigilance — monitoring standard.",
}


def _build_annotated_html(text, spans, limit=3000):
    """Construit le HTML du document avec surlignage des signaux détectés.

    `spans` est une liste de (start, end, flag_num) — positions dans `text`
    trouvées par analyze(). Le texte hors-span est échappé pour éviter que
    du contenu PDF cassé (ex: caractères "<") ne casse le rendu HTML.
    """
    text = text[:limit]

    merged = []
    for start, end, flag_num in sorted(s for s in spans if s[0] < limit):
        end = min(end, limit)
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end), merged[-1][2])
        else:
            merged.append((start, end, flag_num))

    parts = []
    cursor = 0
    for start, end, flag_num in merged:
        parts.append(html.escape(text[cursor:start]))
        css_class = HL_CLASS_BY_FLAG.get(flag_num, "hl-teal")
        parts.append(f'<span class="{css_class}">{html.escape(text[start:end])}</span>')
        cursor = end
    parts.append(html.escape(text[cursor:]))
    return "".join(parts)


def _extract_uploaded_text(uploaded_file):
    """Extrait le texte d'un fichier uploadé (.pdf ou .txt).
    ALT: brancher ingest.extract_pdf() pour l'OCR (pdf scannés) si besoin.
    """
    if uploaded_file.name.lower().endswith(".txt"):
        return uploaded_file.read().decode("utf-8", errors="ignore")
    with pdfplumber.open(uploaded_file) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _extract_multi_doc_text(uploaded_files):
    """Concatène le texte de plusieurs documents (ESIA + ESAP + Monitoring
    Report, typique d'une due diligence) en un seul texte pour analyze().

    CHOIX: concaténation avec séparateur par nom de fichier, pas une
    analyse séparée par document — garde le pipeline analyze() inchangé
    (une seule liste de chunks, un seul jeu de flag_scores). Limite assumée
    (cohérente avec le chantier "annotation page par page", en pause) :
    les signaux détectés/le surlignage ne distinguent pas de quel document
    ils viennent, seulement leur position dans le texte concaténé.
    """
    parts = []
    for f in uploaded_files:
        parts.append(f"\n\n=== {f.name} ===\n\n" + _extract_uploaded_text(f))
    return "".join(parts)


def _safe_filename(label, max_len=60):
    """`doc_label` peut être un nom de fichier, "Texte collé", ou une liste
    de plusieurs documents ("3 documents (a.pdf, b.pdf, ...)") — normalise
    en un nom de fichier de téléchargement propre plutôt que de propager
    espaces/parenthèses/virgules tels quels."""
    stem = label.rsplit(".", 1)[0] if "." in label.split("(")[0] else label
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    return (safe or "analysis")[:max_len]


def _format_outcome(row):
    """Résume l'issue connue d'un projet historique à partir des colonnes
    event/time_to_event du corpus (pas de texte narratif inventé)."""
    event = row.get("event")
    time_to_event = row.get("time_to_event")
    if event == 1 and time_to_event:
        return f"Événement ESG survenu à {time_to_event:.0f} mois"
    if event == 0:
        return "Aucun événement ESG observé sur la période de suivi"
    return "Issue non documentée"


def _map_result_to_display(result):
    """Transforme la sortie de analyze() dans le format attendu par l'UI."""
    pred = result["prediction"]

    flag_scores = {FLAG_LABELS[k]: v for k, v in result["flag_scores"].items()}

    signals = [
        {
            "category": f"FLAG {s['source_flag']} — {s['signal'].upper()}",
            "text":     html.escape(s["evidence_excerpt"]),
            "severity": SEVERITY_BY_FLAG.get(s["source_flag"], "low"),
        }
        for s in result["detected_signals"][:8]
    ]

    # Un "cas similaire" = un projet historique (agrégation des chunks par max score)
    by_project = {}
    for p in result["similar_passages"]:
        name = p["project_name"]
        if name not in by_project or p["score"] > by_project[name]["score"]:
            by_project[name] = p
    # CHOIX: résumé LLM calculé seulement sur les 5 cas retenus (pas sur tous
    # les voisins FAISS bruts, potentiellement des dizaines) — borne le coût
    # à 5 appels max, mis en cache par texte donc quasi instantané dès le
    # 2e rendu Streamlit de la même analyse (voir llm_confirm.summarize_passage).
    similar_cases = [
        {
            "name":       p["project_name"],
            "similarity": p["score"],
            "flag_type":  p["flag_type"],
            "outcome":    _format_outcome(p),
            "excerpt":    html.escape(llm_confirm.summarize_passage(p["text"])),
        }
        for p in sorted(by_project.values(), key=lambda x: x["score"], reverse=True)[:5]
    ]

    # ── Traçabilité : quelles preuves ont influencé chaque flag_score ? ──
    # CHOIX: dérivé de result["similar_passages"] — les mêmes voisins FAISS
    # que search.get_flag_scores a utilisés pour calculer flag_scores (pas
    # un nouvel appel FAISS). Pour chaque flag, les 2 projets (un passage
    # chacun, meilleur score) dont le flag_type correspond, triés par score.
    evidence_by_flag = {}
    for flag_num, flag_key in _FLAG_NUM_TO_KEY.items():
        by_project_for_flag = {}
        for p in result["similar_passages"]:
            if f"Flag {flag_num}" not in str(p["flag_type"]):
                continue
            name = p["project_name"]
            if name not in by_project_for_flag or p["score"] > by_project_for_flag[name]["score"]:
                by_project_for_flag[name] = p
        top = sorted(by_project_for_flag.values(), key=lambda x: x["score"], reverse=True)[:2]
        evidence_by_flag[FLAG_LABELS[flag_key]] = [
            {
                "name":    p["project_name"],
                "score":   round(p["score"] * 100),
                "excerpt": html.escape(llm_confirm.summarize_passage(p["text"])),
            }
            for p in top
        ]

    return {
        "risk_grade":       pred["risk_grade"],
        "risk_label":       pred["risk_label"].upper(),
        "probability_12m":  pred["probability_12m"],
        "flag_scores":      flag_scores,
        "signals":          signals,
        "similar_cases":    similar_cases,
        "evidence_by_flag": evidence_by_flag,
    }


_FLAG_NUM_TO_KEY = {1: "flag1_community", 2: "flag2_pollution", 3: "flag3_compliance"}


@st.cache_data(show_spinner="Chargement des patterns...")
def _compute_pattern_library():
    """Calcule les vraies statistiques de patterns depuis chunks.csv : pour
    chaque catégorie de signal (signals.SIGNAL_KEYWORDS), parmi les projets
    à événement ESG connu (event=1), combien le mentionnent et quel est le
    temps moyen avant l'événement pour ces projets-là.

    Remplace le mockup à données fictives — mis en cache car ça scanne
    l'intégralité du corpus (4203+ chunks) contre 11 catégories de signaux.
    """
    if not CHUNKS_PATH.exists():
        return []

    chunks_df = pd.read_csv(CHUNKS_PATH)
    events_df = chunks_df.dropna(subset=["event", "time_to_event"])
    events_df = events_df[events_df["event"] == 1]
    if events_df.empty:
        return []

    patterns = []
    for (flag_num, signal_name), pattern in SIGNAL_PATTERNS.items():
        is_match = events_df["text"].apply(lambda t: pattern.search(str(t)) is not None)
        matched_chunks = events_df[is_match]
        if matched_chunks.empty:
            continue

        matched_projects = matched_chunks.drop_duplicates("project_name")
        occurrences = matched_chunks["text"].apply(lambda t: len(pattern.findall(str(t)))).sum()
        avg_tte = float(matched_projects["time_to_event"].mean())

        patterns.append({
            "signal":            signal_name,
            "flag_label":        FLAG_LABELS[_FLAG_NUM_TO_KEY[flag_num]],
            "n_projects":        len(matched_projects),
            "occurrences":       int(occurrences),
            "avg_time_to_event": avg_tte,
        })

    # Sévérité relative (tertiles sur les avg_time_to_event RÉELLEMENT
    # observés) plutôt que des seuils absolus en mois : le corpus IFC/CAO a
    # des délais qui se comptent en années (T0 = approbation IFC, pas date
    # de début d'exploitation), pas en mois comme le laissait supposer
    # l'ancien mockup — un seuil fixe type "<10 mois = high" ne différencie
    # plus rien sur les vraies données (tout tombe dans "low").
    if patterns:
        times = sorted(p["avg_time_to_event"] for p in patterns)
        q1 = times[len(times) // 3]
        q2 = times[(2 * len(times)) // 3]
        for p in patterns:
            if p["avg_time_to_event"] <= q1:
                p["severity"] = "high"
            elif p["avg_time_to_event"] <= q2:
                p["severity"] = "med"
            else:
                p["severity"] = "low"

    patterns.sort(key=lambda p: p["n_projects"], reverse=True)
    return patterns


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
.severity-low { background: var(--teal-light); border-left: 4px solid var(--teal); }

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
    _history = st.session_state.get("analysis_history", [])
    if _history:
        _rows = "".join(
            f"{h['document']} (Grade {h['risk_grade']})<br>"
            for h in reversed(_history[-3:])
        )
        st.markdown(f'<div style="font-size:0.85rem; color:#666;">{_rows}</div>', unsafe_allow_html=True)
    else:
        st.caption("Aucune analyse cette session.")
    st.markdown("---")
    st.caption("v0.1 MVP · Données publiques IFC/CAO")


# ══════════════════════════════════════════════════════════════
# PAGE 1 — TRANSACTION ANALYSIS
# ══════════════════════════════════════════════════════════════
if page == "🔍 Transaction Analysis":
    st.markdown("## 🔍 Transaction Analysis")
    st.markdown("*Upload a project document or paste text to detect ESG risk signals*")

    # ── Input zone — fichier ou texte collé ───────────────────
    input_mode = st.radio(
        "Comment fournir le document ?",
        ["📄 Upload a file", "✍️ Paste text"],
        horizontal=True,
        label_visibility="collapsed",
    )

    uploaded_files = []
    pasted_text = ""
    if input_mode == "📄 Upload a file":
        uploaded_files = st.file_uploader(
            "Upload PDF(s) — ESRS, ESIA, Monitoring Report, INSP Review",
            type=["pdf", "txt"],
            accept_multiple_files=True,
            help="Une due diligence croise souvent plusieurs documents (ESIA + ESAP + "
                 "Monitoring Report) — sélectionnez-en plusieurs, ils seront analysés "
                 "ensemble. Traitement local, aucune donnée ne quitte votre machine.",
        ) or []
    else:
        pasted_text = st.text_area(
            "Coller le texte du document",
            height=220,
            placeholder="Coller ici le texte du rapport ESG à analyser...",
            label_visibility="collapsed",
        )

    # ── Analyze button ───────────────────────────────────────
    has_input = bool(uploaded_files) or bool(pasted_text.strip())
    col_btn, col_status = st.columns([1, 3])
    with col_btn:
        analyze_clicked = st.button(
            "▶ Run Analysis", type="primary", use_container_width=True, disabled=not has_input
        )

    analyze_error = None
    if has_input and analyze_clicked:
        with col_status:
            with st.spinner("⏳ Analyse en cours... extraction → embeddings → scoring"):
                try:
                    if pasted_text.strip():
                        extracted_text = pasted_text.strip()
                        doc_label = "Texte collé"
                    elif len(uploaded_files) == 1:
                        extracted_text = _extract_uploaded_text(uploaded_files[0])
                        doc_label = uploaded_files[0].name
                    else:
                        extracted_text = _extract_multi_doc_text(uploaded_files)
                        doc_label = f"{len(uploaded_files)} documents ({', '.join(f.name for f in uploaded_files)})"

                    result = analyze(
                        extracted_text,
                        risk_thresholds=st.session_state.get("risk_thresholds"),
                        # FRAGILE: k (nombre de voisins FAISS interrogés) n'est plus réglable
                        # depuis Settings (paramètre technique, pas pertinent pour l'analyste
                        # métier) — valeur validée par défaut, voir checklist.md.
                        k=15,
                    )
                    display_result = _map_result_to_display(result)

                    # Résultat "actif" affiché ci-dessous — persiste tant que
                    # l'analyste ne relance pas une analyse ou ne change pas
                    # d'onglet et ne revient pas (sinon les résultats
                    # disparaissaient au moindre autre clic sur la page).
                    st.session_state["last_analysis"] = {
                        "result":         result,
                        "display":        display_result,
                        "extracted_text": extracted_text,
                        "document":       doc_label,
                    }
                    # Historique de session pour Portfolio Dashboard.
                    st.session_state.setdefault("analysis_history", []).append({
                        "document":        doc_label,
                        "timestamp":       datetime.now(),
                        "risk_grade":      display_result["risk_grade"],
                        "risk_label":      display_result["risk_label"],
                        "probability_12m": display_result["probability_12m"],
                        # FRAGILE: max() sur result["flag_scores"] (clés brutes "flag1_community"...),
                        # pas display_result["flag_scores"] (clés déjà traduites en libellé humain "Community
                        # & Stakeholder Risk...") — sinon FLAG_LABELS[...] plante plus loin (Portfolio Dashboard).
                        "dominant_flag":   max(result["flag_scores"], key=result["flag_scores"].get),
                    })
                except Exception as e:
                    analyze_error = str(e)

    st.markdown("---")

    if analyze_error:
        st.error(
            f"❌ L'analyse a échoué : {analyze_error}\n\n"
            "Le modèle Cox n'est probablement pas encore entraîné "
            "(`models/cox_model.pkl` manquant — voir checklist.md, point "
            "`time_to_event`)."
        )
        st.stop()
    elif "last_analysis" not in st.session_state:
        st.info("👆 Upload a document or paste text, then click **Run Analysis** to see the results.")
        st.stop()

    active = st.session_state["last_analysis"]
    real_result = active["result"]
    extracted_text = active["extracted_text"]
    display = active["display"]
    doc_label = active["document"]

    # ── Export — joindre le résultat à un mémo de comité de crédit ──
    # CHOIX: généré à chaque rerun (pas de bouton "Generate" séparé) — la
    # construction PDF/Excel ne fait que mettre en forme des données déjà
    # calculées par analyze() (pas de nouvel appel FAISS/LLM), donc c'est
    # quasi instantané, contrairement à l'analyse elle-même.
    col_exp1, col_exp2, _ = st.columns([1, 1, 3])
    with col_exp1:
        st.download_button(
            "⬇ Export PDF",
            data=export.build_pdf_report(doc_label, real_result, display),
            file_name=f"esg_analysis_{_safe_filename(doc_label)}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    with col_exp2:
        st.download_button(
            "⬇ Export Excel",
            data=export.build_excel_report(doc_label, real_result, display),
            file_name=f"esg_analysis_{_safe_filename(doc_label)}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    # ── Risk Grade Summary ───────────────────────────────
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">📊 Risk Assessment Summary</div>', unsafe_allow_html=True)

    col_grade, col_info = st.columns([1, 4])
    with col_grade:
        grade = display["risk_grade"]
        st.markdown(f'<div class="risk-grade grade-{grade}">{grade}</div>', unsafe_allow_html=True)
    with col_info:
        st.markdown(f"**Risk Label:** {display['risk_label']}")
        st.markdown(f"**Probability of ESG event in 12 months:** {display['probability_12m']:.0%}")
        recommendation = real_result.get("recommendation") or RECOMMENDATION_BY_GRADE.get(grade, "Grade non reconnu.")
        st.markdown(f"**Recommendation:** {recommendation}")

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Flag Scores ──────────────────────────────────────
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">🎯 Flag Scores</div>', unsafe_allow_html=True)

    colors = {"Community & Stakeholder Risk": "#ED1C24", "Pollution & Monitoring Risk": "#f59e0b", "Structural Compliance Risk": "#009B9D"}
    for label, score in display["flag_scores"].items():
        color = colors[label]
        st.markdown(f"""
        <div class="score-row">
            <div class="score-lbl">{label}</div>
            <div class="score-bg"><div class="score-fill" style="width:{score}%;background:{color};"></div></div>
            <div class="score-num" style="color:{color};">{score}</div>
        </div>
        """, unsafe_allow_html=True)
        # ── Traçabilité : les passages historiques derrière ce score ────
        # Point 4.4 de la feuille de route — quels voisins FAISS ont fait
        # monter ce flag_score, pas juste le chiffre final. Dérivé de
        # result["similar_passages"] (voir _map_result_to_display), pas
        # d'appel FAISS supplémentaire.
        evidence = display["evidence_by_flag"].get(label, [])
        if evidence:
            items = "".join(
                f'<div style="margin:0.15rem 0 0.15rem 1rem;font-size:0.78rem;color:#666;">'
                f'&#8226; <strong>{e["name"]}</strong> ({e["score"]}%) — <em>{e["excerpt"]}</em></div>'
                for e in evidence
            )
            st.markdown(
                f'<details style="margin:-0.3rem 0 0.8rem 0;"><summary style="font-size:0.78rem;'
                f'color:{color};cursor:pointer;">Evidence behind this score ({len(evidence)})</summary>'
                f'{items}</details>',
                unsafe_allow_html=True,
            )

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Detected Signals + Annotated Document ────────────
    col_signals, col_doc = st.columns(2)

    with col_signals:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">🚨 Detected Signals</div>', unsafe_allow_html=True)
        if display["signals"]:
            for sig in display["signals"]:
                css_class = f"flag-{sig['severity']}"
                icon = "🔴" if sig["severity"] == "high" else ("🟡" if sig["severity"] == "medium" else "🔵")
                st.markdown(f"""
                <div class="flag-item {css_class}">
                    {icon} <strong style="font-size:0.7rem;color:#999;">{sig['category']}</strong><br>
                    {sig['text']}
                </div>
                """, unsafe_allow_html=True)
        else:
            st.caption("Aucun signal ESG détecté dans ce document.")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_doc:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">📄 Annotated Document</div>', unsafe_allow_html=True)
        st.markdown("**Legend:** "
                     '<span class="hl-red">Community risk</span> · '
                     '<span class="hl-orange">Pollution risk</span> · '
                     '<span class="hl-teal">Compliance risk</span>',
                     unsafe_allow_html=True)
        annotated_html = _build_annotated_html(extracted_text, real_result["signal_spans"])
        st.markdown(
            f'<div class="annotated-text">{annotated_html}</div>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Historical Similar Cases ─────────────────────────
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">📚 Historical Similar Cases</div>', unsafe_allow_html=True)

    if display["similar_cases"]:
        for case in display["similar_cases"]:
            sim_pct = f"{case['similarity']:.0%}"
            st.markdown(f"""
            <div class="pattern-item severity-high">
                <strong>{case['name']}</strong> — Similarity: {sim_pct} · {case['flag_type']}<br>
                <span style="font-size:0.82rem;color:#666;">{case['outcome']}</span><br>
                <span style="font-size:0.78rem;color:#999;font-style:italic;">"{case['excerpt']}"</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.caption("Aucun cas historique similaire trouvé.")

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# PAGE 2 — PORTFOLIO DASHBOARD
# ══════════════════════════════════════════════════════════════
elif page == "📊 Portfolio Dashboard":
    st.markdown("## 📊 Portfolio Dashboard")
    st.markdown("*Historique des analyses de cette session*")

    history = st.session_state.get("analysis_history", [])

    if not history:
        st.info(
            "👆 Aucune analyse effectuée cette session. Lance une analyse depuis "
            "**Transaction Analysis** pour la voir apparaître ici."
        )
    else:
        portfolio_df = pd.DataFrame([
            {
                "Document":      h["document"],
                "Risk Grade":    h["risk_grade"],
                "Risk Label":    h["risk_label"],
                "P(event 12m)":  f"{h['probability_12m']:.0%}",
                "Dominant Flag": FLAG_LABELS[h["dominant_flag"]].replace(" Risk", ""),
                "Analyzed At":   h["timestamp"].strftime("%Y-%m-%d %H:%M"),
            }
            for h in reversed(history)
        ])

        grade_filter = st.multiselect("Filter by Risk Grade", ["A", "B", "C", "D"], default=["A", "B", "C", "D"])
        filtered = portfolio_df[portfolio_df["Risk Grade"].isin(grade_filter)]
        st.dataframe(filtered, use_container_width=True, hide_index=True)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Analyses", len(filtered))
        col2.metric("Grade A (Escalade)", len(filtered[filtered["Risk Grade"] == "A"]))
        col3.metric("Grade B (Alerte)", len(filtered[filtered["Risk Grade"] == "B"]))
        col4.metric("Grade C-D (Watch)", len(filtered[filtered["Risk Grade"].isin(["C", "D"])]))

    st.caption("Historique de session uniquement — perdu à la fermeture du navigateur (pas de persistance base de données pour l'instant).")


# ══════════════════════════════════════════════════════════════
# PAGE 3 — PATTERN LIBRARY
# ══════════════════════════════════════════════════════════════
elif page == "📚 Pattern Library":
    st.markdown("## 📚 Pattern Library")
    st.markdown("*Fréquence réelle des signaux ESG dans le corpus IFC/CAO, et temps moyen avant événement*")

    patterns = _compute_pattern_library()

    if not patterns:
        st.info("Corpus indisponible ou aucun projet à événement connu — impossible de calculer les patterns.")
    else:
        flag_options = ["All"] + sorted({p["flag_label"] for p in patterns})
        flag_filter = st.selectbox("Filter by Flag", flag_options)

        for p in patterns:
            if flag_filter != "All" and p["flag_label"] != flag_filter:
                continue
            css = f"severity-{p['severity']}"
            st.markdown(f"""
            <div class="pattern-item {css}">
                <strong>{p['signal'].capitalize()}</strong><br>
                <span style="font-size:0.8rem;color:#666;">
                    {p['flag_label']} · {p['n_projects']} projet(s) · {p['occurrences']} occurrence(s) · Temps moyen avant événement : {p['avg_time_to_event']:.0f} mois
                </span>
            </div>
            """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# PAGE 4 — SETTINGS
# ══════════════════════════════════════════════════════════════
elif page == "⚙️ Settings":
    st.markdown("## ⚙️ Settings")
    st.markdown("*Seuils de risque et informations sur le corpus*")

    st.markdown("### Risk Grade Thresholds")
    st.caption("Ces seuils sont appliqués immédiatement à la prochaine analyse lancée dans Transaction Analysis.")

    current_thresholds = st.session_state.get("risk_thresholds", DEFAULT_RISK_THRESHOLDS)
    t1_default = current_thresholds[0][0]
    t2_default = current_thresholds[1][0]
    t3_default = current_thresholds[2][0]

    col1, col2 = st.columns(2)
    with col1:
        t1 = st.slider("Vigilance → Attention", 0.0, 1.0, t1_default, 0.05)
        t2 = st.slider("Attention → Alerte", 0.0, 1.0, t2_default, 0.05)
    with col2:
        t3 = st.slider("Alerte → Escalade", 0.0, 1.0, t3_default, 0.05)

    if not (t1 < t2 < t3):
        st.warning("Les seuils doivent être strictement croissants (Vigilance < Attention < Alerte) pour un classement cohérent.")

    st.session_state["risk_thresholds"] = [
        (t1, "Vigilance", "D"),
        (t2, "Attention", "C"),
        (t3, "Alerte", "B"),
        (1.01, "Escalade", "A"),
    ]

    st.markdown(f"""
    | Grade | Label | Probability Range | Action |
    |-------|-------|-------------------|--------|
    | D | Vigilance | < {t1:.0%} | Monitoring standard |
    | C | Attention | {t1:.0%} – {t2:.0%} | Revue renforcée à 90 jours |
    | B | Alerte | {t2:.0%} – {t3:.0%} | Downgrade d'un cran proposé |
    | A | Escalade | > {t3:.0%} | Escalade immédiate au credit committee |
    """)

    st.markdown("### Corpus Info")
    if CHUNKS_PATH.exists():
        _chunks = pd.read_csv(CHUNKS_PATH)
        _projects = _chunks.dropna(subset=["event"]).drop_duplicates("project_name")
        n_events = int((_projects["event"] == 1).sum())
        n_controls = int((_projects["event"] == 0).sum())
        st.markdown(f"""
        - **Projects with events:** {n_events}
        - **Control projects:** {n_controls}
        - **Historical passages indexed:** {len(_chunks)}
        """)
    else:
        st.caption("chunks.csv introuvable — impossible d'afficher les statistiques du corpus.")