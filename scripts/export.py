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
    pdf.cell(0, 6, f"Probability of ESG event in 12 months: {display['probability_12m']:.0%}", new_x="LMARGIN", new_y="NEXT")
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
        ("Probability of ESG event (12m)", f"{display['probability_12m']:.0%}"),
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
    for row in ws.iter_rows(min_row=1, max_row=7, min_col=1, max_col=1):
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
