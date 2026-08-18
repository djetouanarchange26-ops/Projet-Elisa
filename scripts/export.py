"""
EXPORT DES RÉSULTATS D'ANALYSE — PDF / Excel
==============================================
Feuille de route, point 4.2 : permettre à l'analyste de joindre le résultat
d'une analyse à un mémo de comité de crédit, sans repasser par un
copier-coller manuel depuis l'app.

CHOIX: fpdf2 (pur Python, pas de dépendance système type wkhtmltopdf/
weasyprint) pour le PDF, openpyxl (déjà utilisé pour lire corpus_cao_ifc.xlsx)
pour l'Excel — pas de nouvelle dépendance lourde.
FRAGILE: fpdf2 core fonts (Helvetica) sont limitées à Latin-1 — les résumés
LLM peuvent contenir des caractères hors Latin-1 (tirets typographiques,
guillemets courbes...). `_safe()` les remplace plutôt que de faire planter
l'export.
"""

import html
import io
from datetime import datetime

from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


# Ponctuation Unicode courante (LLM, texte collé) sans équivalent Latin-1 —
# remplacée par un équivalent ASCII plutôt que par "?" (fallback encode()).
_UNICODE_REPLACEMENTS = {
    "—": "-", "–": "-",           # em/en dash
    "‘": "'", "’": "'",           # guillemets courbes simples
    "“": '"', "”": '"',           # guillemets courbes doubles
    "…": "...",                        # ellipse
}


def _safe(text):
    """Sanitize pour fpdf2 (Latin-1 core fonts) — remplace la ponctuation
    Unicode courante par un équivalent ASCII, puis remplace le reste
    (rare) plutôt que de planter l'export."""
    text = str(text)
    for char, repl in _UNICODE_REPLACEMENTS.items():
        text = text.replace(char, repl)
    return text.encode("latin-1", "replace").decode("latin-1")


def _unescape(text):
    """`display["signals"]`/`display["similar_cases"]` viennent de
    app._map_result_to_display, qui html.escape() certains champs pour le
    rendu Streamlit (unsafe_allow_html) — pas pertinent pour un export
    PDF/Excel, donc on inverse ici plutôt que de dupliquer la logique
    d'agrégation pour repartir des données brutes de `result`."""
    return html.unescape(text)


# ============================================================================
# PDF
# ============================================================================

def build_pdf_report(document_label, result, display):
    """Construit un rapport PDF à partir du résultat de analyze() (`result`)
    et de sa version mappée pour l'UI (`display`, voir app._map_result_to_display).

    Retourne des bytes, prêts pour st.download_button.
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "ESG Risk Intelligence - Analysis Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, _safe(f"Document: {document_label}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # --- Risk Assessment Summary ---
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Risk Assessment Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _safe(f"Risk Grade: {display['risk_grade']} ({display['risk_label']}) — Score: {display['risk_score']}/100"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    recommendation = result.get("recommendation") or "N/A"
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Recommendation:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, _safe(recommendation), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # --- Flag Scores ---
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Flag Scores", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for label, score in display["flag_scores"].items():
        pdf.cell(0, 6, _safe(f"{label}: {score}/100"), new_x="LMARGIN", new_y="NEXT")
        for e in display.get("evidence_by_flag", {}).get(label, []):
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(120, 120, 120)
            pdf.multi_cell(0, 4, _safe(f"  - {e['name']} ({e['score']}%): {_unescape(e['excerpt'])}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 10)
    pdf.ln(3)

    # --- Detected Signals --- (result["detected_signals"], pas display["signals"]
    # qui est html.escape() par app._map_result_to_display pour le rendu Streamlit)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Detected Signals", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    if result["detected_signals"]:
        for s in result["detected_signals"][:8]:
            pdf.set_font("Helvetica", "B", 9)
            pdf.multi_cell(0, 5, _safe(f"Flag {s['source_flag']} — {s['signal'].upper()} ({s['occurrences']}x)"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(90, 90, 90)
            pdf.multi_cell(0, 5, _safe(s["evidence_excerpt"]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)
    else:
        pdf.cell(0, 6, "No ESG signal detected in this document.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # --- Historical Similar Cases ---
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Historical Similar Cases", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    if display["similar_cases"]:
        for case in display["similar_cases"]:
            pdf.set_font("Helvetica", "B", 9)
            pdf.multi_cell(0, 5, _safe(f"{case['name']} — Similarity: {case['similarity']:.0%} · {case['flag_type']}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(90, 90, 90)
            pdf.multi_cell(0, 5, _safe(case["outcome"]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(130, 130, 130)
            pdf.multi_cell(0, 5, _safe(f'"{_unescape(case["excerpt"])}"'), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)
    else:
        pdf.cell(0, 6, "No similar historical case found.", new_x="LMARGIN", new_y="NEXT")

    # CHOIX: footer "en flux" (pas pdf.set_y(-15) pour l'ancrer en bas de
    # page) — set_y avec une valeur négative juste avant un cell() déclenche
    # un saut de page intempestif dans fpdf2 dès que le contenu au-dessus
    # est court, laissant une page 2 quasi vide avec juste le footer dessus.
    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 10, "CA-CIB ESG Risk Intelligence - NLP Prototype MVP - Public IFC/CAO data")

    return bytes(pdf.output())


# ============================================================================
# EXCEL
# ============================================================================

_HEADER_FILL = PatternFill(start_color="006F4E", end_color="006F4E", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True)


def _write_header_row(ws, row, headers):
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL


def _autofit(ws, widths):
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width


def build_excel_report(document_label, result, display):
    """Construit un classeur Excel (3 feuilles : Summary, Detected Signals,
    Similar Cases) à partir du résultat de analyze(). Retourne des bytes."""
    wb = Workbook()

    # --- Feuille Summary ---
    ws = wb.active
    ws.title = "Summary"
    rows = [
        ("Document", document_label),
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Risk Grade", display["risk_grade"]),
        ("Risk Score (/100)", display["risk_score"]),
        ("Risk Label", display["risk_label"]),
        ("Recommendation", result.get("recommendation") or "N/A"),
        ("", ""),
    ]
    for label, value in rows:
        ws.append([label, value])
    ws.append(["Flag", "Score (/100)"])
    for cell in ws[ws.max_row]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    for label, score in display["flag_scores"].items():
        ws.append([label, score])
    # CHANTIER SIMPLIFICATION PIPELINE (2026-08-08) : max_row=6, pas 7 --
    # une ligne de moins depuis le retrait de "Probability of ESG event".
    for row in ws.iter_rows(min_row=1, max_row=6, min_col=1, max_col=1):
        row[0].font = Font(bold=True)
    _autofit(ws, [38, 60])

    # --- Feuille Detected Signals --- (result["detected_signals"], données
    # brutes non échappées — display["signals"] est html.escape() pour Streamlit)
    ws2 = wb.create_sheet("Detected Signals")
    _write_header_row(ws2, 1, ["Flag", "Signal", "Occurrences", "Confidence", "Evidence excerpt"])
    for s in result["detected_signals"]:
        ws2.append([
            f"Flag {s['source_flag']}", s["signal"], s["occurrences"],
            round(s["confidence"], 2), s["evidence_excerpt"],
        ])
    _autofit(ws2, [10, 22, 12, 12, 80])

    # --- Feuille Similar Cases ---
    ws3 = wb.create_sheet("Similar Cases")
    _write_header_row(ws3, 1, ["Project", "Similarity", "Flag Type", "Outcome", "Summary"])
    for case in display["similar_cases"]:
        ws3.append([case["name"], f"{case['similarity']:.0%}", case["flag_type"], case["outcome"], _unescape(case["excerpt"])])
    _autofit(ws3, [28, 12, 16, 30, 80])

    # --- Feuille Evidence by Flag --- (traçabilité : quels voisins FAISS
    # ont fait monter chaque flag_score, voir app._map_result_to_display)
    ws4 = wb.create_sheet("Evidence by Flag")
    _write_header_row(ws4, 1, ["Flag", "Project", "Score", "Excerpt"])
    for flag_label, evidence in display.get("evidence_by_flag", {}).items():
        for e in evidence:
            ws4.append([flag_label, e["name"], f"{e['score']}%", _unescape(e["excerpt"])])
    _autofit(ws4, [28, 28, 10, 80])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ============================================================================
# GRILLE ESG V4 — PDF / EXCEL (directive CC-V4-10)
# ============================================================================
# Export séparé de build_pdf_report/build_excel_report ci-dessus (pipeline
# ancien, 3 flags) — même conventions (fpdf2/_safe, openpyxl/_write_header_row/
# _autofit), pas de nouvelle dépendance. `result_v4` est le dict retourné par
# grid_analyze.analyze_grid() (cf. grid_result.build_grid_result pour le
# contrat exact).
#
# FRAGILE: plusieurs champs de result_v4 sont des clés TOUJOURS PRÉSENTES
# mais dont la valeur peut être None (mitigation_label, evidence_r["page"],
# evidence_a["page"]...) — un simple `dict.get(clé, défaut)` ne retombe sur
# `défaut` que si la clé est ABSENTE, pas si sa valeur est None. Traité en
# `dict.get(clé) or défaut` partout ici (même correction que grid_display.py,
# CC-V4-08/09). `reading_mode_label` est un champ de NIVEAU RÉSULTAT
# (result_v4["reading_mode_label"]), pas de result_v4["scoring"].

_COLOR_RGB_V4 = {
    "VERT": (46, 204, 113),
    "JAUNE": (241, 196, 15),
    "ORANGE": (230, 126, 34),
    "ROUGE": (231, 76, 60),
}

# SEUIL: largeurs calibrées pour tenir sur une page A4 portrait (~190mm
# utiles avec les marges par défaut de fpdf2) — 7 colonnes, somme = 183mm.
_GRID_V4_TABLE_COLS = [
    ("Code", 18), ("Sous-theme", 62), ("Statut", 20),
    ("Mitigation", 35), ("Penalite", 18), ("Gain", 15), ("Net", 15),
]


def _truncate(text, max_len):
    """Tronque `text` à `max_len` caractères avec une ellipse — évite qu'une
    cellule de tableau fpdf2 (largeur fixe, pas de wrap automatique dans
    cell()) déborde visuellement sur la colonne suivante."""
    text = str(text)
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def _question_has_detail(question):
    """True si `question` a quelque chose à montrer dans la section détail
    (PDF) / feuille Evidence (Excel) : un verbatim de risque, de mitigation,
    de défaillance, une note de doute, ou des champs qualifiants.

    CHOIX: même heuristique que grid_display._render_evidence_explorer —
    un NON par silence en schéma standard (a_condition="r_oui"), non
    attesté, n'a rien de pertinent à montrer. JAMAIS pour NA : un statut
    N/A exige toujours un verbatim de justification (cf.
    grid_questions.SILENCE_VALUES["NA"]), qui doit rester visible.
    """
    if question["status"] == "NON" and not question.get("atteste") and question.get("a_condition", "r_oui") == "r_oui":
        return False
    ev_r = question.get("evidence_r")
    ev_a = question.get("evidence_a")
    return bool(
        (ev_r and ev_r.get("passage"))
        or (ev_a and (ev_a.get("verbatim_mesure") or ev_a.get("verbatim_defaillance")))
        or question.get("confidence_note")
        or question.get("qualifying")
    )


def build_grid_v4_pdf(result_v4, project_name="", filename="esg_grid_v4.pdf"):
    """Génère un rapport PDF de la Grille V4 (12 questions).

    CHOIX: fpdf2 comme l'export existant — pas de nouvelle dépendance.
    `filename` n'est pas utilisé ici (le nom du fichier téléchargé est du
    ressort de st.download_button côté appelant, cf. app.py) — conservé
    dans la signature pour matcher le contrat attendu par CC-V4-10.

    Structure :
    - Page 1 : titre, score, couleur, mode de lecture, risques identifiés,
      questions non documentées (INCONNU)
    - Page 2 : tableau des 12 questions + ligne de total
    - Pages suivantes : détail par question ayant des preuves à montrer
      (cf. _question_has_detail)

    Retourne des bytes, prêts pour st.download_button.
    """
    scoring = result_v4["scoring"]
    score = scoring["score"]
    color = scoring["color"]
    mode_label = result_v4.get("reading_mode_label") or "-"

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- Page 1 : synthèse ---
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    title = f"ESG Risk Assessment - {project_name}" if project_name else "ESG Risk Assessment"
    pdf.cell(0, 10, _safe(title), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, f"Genere le : {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    rgb = _COLOR_RGB_V4.get(color, (100, 100, 100))
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*rgb)
    pdf.cell(0, 12, _safe(f"Score : {score} / 100 - {color}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    if scoring.get("saturation"):
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, "ROUGE - Eliminatoire (score plancher)", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, _safe(f"Mode de lecture : {mode_label}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Questions actives : {scoring['questions_active']} / 12", new_x="LMARGIN", new_y="NEXT")
    if scoring["questions_na"] > 0:
        pdf.cell(0, 7, f"Questions N/A : {scoring['questions_na']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0, 7, f"Plafond d'attenuation applique : {'Oui' if scoring['cap_applied'] else 'Non'}",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(4)

    risk_drivers = [
        q for q in result_v4["questions"]
        if q["status"] == "OUI" or (q.get("a_condition") == "r_non" and q["status"] == "NON")
    ]
    risk_drivers.sort(key=lambda q: q["penalty"])

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Risques identifies", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    if risk_drivers:
        for q in risk_drivers:
            mit_label = q.get("mitigation_label") or "-"
            pdf.multi_cell(
                0, 6,
                _safe(f"- {q['code']} - {q['sous_theme']} (penalite {q['penalty']}, mitigation {mit_label})"),
                new_x="LMARGIN", new_y="NEXT",
            )
    else:
        pdf.cell(0, 6, "Aucun risque identifie.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    inconnu_qs = [q for q in result_v4["questions"] if q["status"] == "INCONNU"]
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Non documente", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    if inconnu_qs:
        for q in inconnu_qs:
            pdf.multi_cell(0, 6, _safe(f"- {q['code']} - {q['sous_theme']}"), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 6, "Aucune question non documentee.", new_x="LMARGIN", new_y="NEXT")

    # --- Page 2 : tableau des 12 questions ---
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Grille d'evaluation - 12 questions", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(0, 111, 78)
    pdf.set_text_color(255, 255, 255)
    for header, width in _GRID_V4_TABLE_COLS:
        pdf.cell(width, 8, header, border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 8)

    for q in result_v4["questions"]:
        gain = q.get("gain", 0)
        row = [
            q["code"],
            _truncate(q["sous_theme"], 38),
            q["status"],
            _truncate(q.get("mitigation_label") or "-", 22),
            str(q["penalty"]),
            f"{gain:+d}" if gain else "0",
            str(q["penalty"] + gain),
        ]
        for (_, width), value in zip(_GRID_V4_TABLE_COLS, row):
            pdf.cell(width, 7, _safe(value), border=1)
        pdf.ln()

    net_total = scoring["total_penalty"] + scoring["total_gain_capped"]
    pdf.set_font("Helvetica", "B", 8)
    total_row = [
        "", "", "", "TOTAL",
        str(scoring["total_penalty"]),
        f"{scoring['total_gain_capped']:+d}",
        str(net_total),
    ]
    for (_, width), value in zip(_GRID_V4_TABLE_COLS, total_row):
        pdf.cell(width, 7, _safe(value), border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(
        0, 6,
        f"Score = max(0, 100 + {scoring['total_penalty']} + {scoring['total_gain_capped']}) = {score}",
        new_x="LMARGIN", new_y="NEXT",
    )

    # --- Pages suivantes : détail par question ---
    detail_questions = [q for q in result_v4["questions"] if _question_has_detail(q)]
    if detail_questions:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "Detail par question", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        for q in detail_questions:
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(0, 7, _safe(f"{q['code']} - {q['sous_theme']}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(0, 5, _safe(f"Statut : {q['status']}"), new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 5, _safe(f"Mitigation : {q.get('mitigation_label') or '-'}"), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

            ev_r = q.get("evidence_r")
            if ev_r and ev_r.get("passage"):
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5, f"Preuve de risque (page {ev_r.get('page') or '?'}) :", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(90, 90, 90)
                pdf.multi_cell(0, 5, _safe(f'"{ev_r["passage"]}"'), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(1)

            ev_a = q.get("evidence_a")
            if ev_a and ev_a.get("verbatim_mesure"):
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(
                    0, 5, f"Preuve de mitigation (page {ev_a.get('page') or '?'}) :",
                    new_x="LMARGIN", new_y="NEXT",
                )
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(60, 130, 70)
                pdf.multi_cell(0, 5, _safe(f'"{ev_a["verbatim_mesure"]}"'), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(1)
            if ev_a and ev_a.get("verbatim_defaillance"):
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5, "Defaillance :", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(180, 130, 30)
                pdf.multi_cell(0, 5, _safe(f'"{ev_a["verbatim_defaillance"]}"'), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(1)

            if q.get("confidence_note"):
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5, "Doute :", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(120, 120, 120)
                pdf.multi_cell(0, 5, _safe(q["confidence_note"]), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(1)

            qualifying = q.get("qualifying")
            if qualifying:
                qual_items = [(k, v) for k, v in qualifying.items() if v and v is not True]
                if qual_items:
                    pdf.set_font("Helvetica", "B", 9)
                    pdf.cell(0, 5, "Champs qualifiants :", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("Helvetica", "", 9)
                    for k, v in qual_items:
                        pdf.multi_cell(0, 5, _safe(f"  {k} : {v}"), new_x="LMARGIN", new_y="NEXT")

            pdf.ln(2)
            pdf.set_draw_color(220, 220, 220)
            pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
            pdf.set_draw_color(0, 0, 0)
            pdf.ln(3)

    return bytes(pdf.output())


# --- Excel : remplissages conditionnels (pénalité < 0 -> rouge clair, gain
# > 0 -> vert clair) sur la feuille "Grille", cf. directive CC-V4-10. ---
_PENALTY_FILL_V4 = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")
_GAIN_FILL_V4 = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")


def build_grid_v4_excel(result_v4, project_name="", filename="esg_grid_v4.xlsx"):
    """Génère un classeur Excel de la Grille V4 (12 questions).

    CHOIX: openpyxl comme l'export existant — pas de nouvelle dépendance.
    `filename` non utilisé (cf. build_grid_v4_pdf ci-dessus).

    4 feuilles :
    - Synthese  : score, couleur, mode, métriques agrégées
    - Grille    : tableau des 12 questions, fond rouge/vert conditionnel
    - Evidence  : une ligne par verbatim (risque/mitigation/défaillance)
    - Qualifiants : champs non scorants (cf. grid_questions.QUALIFYING_FLAGS)

    Retourne des bytes, prêts pour st.download_button.
    """
    scoring = result_v4["scoring"]
    wb = Workbook()

    # --- Feuille Synthese ---
    ws1 = wb.active
    ws1.title = "Synthese"
    summary_rows = [
        ("Projet", project_name or "-"),
        ("Genere le", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Grille", result_v4.get("grid_version") or "-"),
        ("Mode de lecture", result_v4.get("reading_mode_label") or "-"),
        ("Score (/100)", scoring["score"]),
        ("Couleur", scoring["color"]),
        ("Saturation (score plancher)", "Oui" if scoring.get("saturation") else "Non"),
        ("Questions actives", scoring["questions_active"]),
        ("Questions N/A", scoring["questions_na"]),
        ("Penalite totale", scoring["total_penalty"]),
        ("Gain total (brut)", scoring["total_gain"]),
        ("Gain total (plafonne)", scoring["total_gain_capped"]),
        ("Plafond d'attenuation applique", "Oui" if scoring["cap_applied"] else "Non"),
    ]
    for label, value in summary_rows:
        ws1.append([label, value])
    for row in ws1.iter_rows(min_row=1, max_row=len(summary_rows), min_col=1, max_col=1):
        row[0].font = Font(bold=True)
    _autofit(ws1, [32, 40])

    # --- Feuille Grille ---
    ws2 = wb.create_sheet("Grille")
    _write_header_row(ws2, 1, [
        "Code", "Categorie", "Sous-theme", "Statut", "Mitigation Status",
        "Mitigation Label", "Penalite", "Gain", "Net", "Silence Type", "Atteste", "Verrou",
    ])
    for q in result_v4["questions"]:
        gain = q.get("gain", 0)
        ws2.append([
            q["code"], q["category"], q["sous_theme"], q["status"],
            q.get("mitigation_status") or "-", q.get("mitigation_label") or "-",
            q["penalty"], gain, q["penalty"] + gain,
            q.get("silence_type") or "-",
            "Oui" if q.get("atteste") else "Non",
            "Oui" if q.get("verrou_applique") else "Non",
        ])
        row_idx = ws2.max_row
        if q["penalty"] < 0:
            ws2.cell(row=row_idx, column=7).fill = _PENALTY_FILL_V4
        if gain > 0:
            ws2.cell(row=row_idx, column=8).fill = _GAIN_FILL_V4
    _autofit(ws2, [8, 10, 34, 10, 20, 24, 10, 8, 8, 12, 10, 10])

    # --- Feuille Evidence ---
    ws3 = wb.create_sheet("Evidence")
    _write_header_row(ws3, 1, ["Code", "Type", "Page", "Passage", "Sujet"])
    for q in result_v4["questions"]:
        qualifying = q.get("qualifying") or {}
        sujet = "Preteur" if qualifying.get("subject_filter") == "lender" else "SPV"

        ev_r = q.get("evidence_r")
        if ev_r and ev_r.get("passage"):
            ws3.append([q["code"], "risque", ev_r.get("page") or "-", ev_r["passage"], sujet])

        ev_a = q.get("evidence_a")
        if ev_a and ev_a.get("verbatim_mesure"):
            ws3.append([q["code"], "mitigation", ev_a.get("page") or "-", ev_a["verbatim_mesure"], sujet])
        if ev_a and ev_a.get("verbatim_defaillance"):
            ws3.append([q["code"], "defaillance", ev_a.get("page") or "-", ev_a["verbatim_defaillance"], sujet])
    _autofit(ws3, [10, 14, 8, 90, 10])

    # --- Feuille Qualifiants ---
    ws4 = wb.create_sheet("Qualifiants")
    _write_header_row(ws4, 1, ["Code", "Sous-theme", "Champ", "Valeur"])
    for q in result_v4["questions"]:
        qualifying = q.get("qualifying")
        if not qualifying:
            continue
        for k, v in qualifying.items():
            if v and v is not True:
                ws4.append([q["code"], q["sous_theme"], k, v])
    _autofit(ws4, [10, 34, 22, 60])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
