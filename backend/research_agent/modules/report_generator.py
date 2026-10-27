"""
report_generator.py
-------------------
Assembles a full academic PDF report from the project context,
analysis results, and conclusions.
Uses ReportLab for PDF generation.
"""

import os
import io
from typing import Optional
from datetime import date


def generate_pdf_report(
    project_context: dict,
    profile: dict,
    cleaning_log: list,
    analysis_results: list,
    conclusions: list,
    predictions: dict,
    output_path: str,
) -> str:
    """
    Generates a complete PDF report and saves to output_path.
    Returns the output_path on success.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table,
            TableStyle, PageBreak, HRFlowable,
        )
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    except ImportError:
        raise ImportError(
            "ReportLab is required for PDF generation. "
            "Install with: pip install reportlab"
        )

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2.5*cm,
        leftMargin=2.5*cm,
        topMargin=2.5*cm,
        bottomMargin=2.5*cm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle("Title", parent=styles["Title"],
                                  fontSize=18, spaceAfter=12, alignment=TA_CENTER,
                                  textColor=colors.HexColor("#1a1a2e"))
    h1_style    = ParagraphStyle("H1", parent=styles["Heading1"],
                                  fontSize=14, spaceAfter=6,
                                  textColor=colors.HexColor("#16213e"))
    h2_style    = ParagraphStyle("H2", parent=styles["Heading2"],
                                  fontSize=12, spaceAfter=4,
                                  textColor=colors.HexColor("#0f3460"))
    body_style  = ParagraphStyle("Body", parent=styles["Normal"],
                                  fontSize=10, leading=15, alignment=TA_JUSTIFY,
                                  spaceAfter=6)
    label_style = ParagraphStyle("Label", parent=styles["Normal"],
                                  fontSize=9, textColor=colors.HexColor("#666666"))
    verdict_style = ParagraphStyle("Verdict", parent=styles["Normal"],
                                    fontSize=10, leading=14,
                                    backColor=colors.HexColor("#f0f4ff"),
                                    borderPadding=4, spaceAfter=8)

    elements = []

    # ── Cover Page ────────────────────────────────────────────────────────────
    elements.append(Spacer(1, 3*cm))
    elements.append(Paragraph(project_context.get("title", "Research Report"), title_style))
    elements.append(Spacer(1, 0.5*cm))
    elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#0f3460")))
    elements.append(Spacer(1, 0.3*cm))

    meta_data = [
        ["Institution:", project_context.get("institution", "—")],
        ["Department:",  project_context.get("department", "—")],
        ["Methodology:", project_context.get("methodology", "Quantitative")],
        ["Date:",        str(date.today())],
    ]
    meta_table = Table(meta_data, colWidths=[4*cm, 12*cm])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#555555")),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(meta_table)
    elements.append(PageBreak())

    # ── Abstract ──────────────────────────────────────────────────────────────
    elements.append(Paragraph("Abstract", h1_style))
    elements.append(HRFlowable(width="100%", thickness=1,
                                color=colors.HexColor("#cccccc")))
    elements.append(Spacer(1, 0.2*cm))
    elements.append(Paragraph(project_context.get("research_problem", ""), body_style))
    elements.append(Spacer(1, 0.3*cm))
    elements.append(Paragraph(
        f"<b>General Objective:</b> {project_context.get('general_objective', '')}", body_style))
    elements.append(PageBreak())

    # ── Methodology ───────────────────────────────────────────────────────────
    elements.append(Paragraph("Methodology", h1_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
    elements.append(Spacer(1, 0.2*cm))
    meth_items = [
        ("Study Design",       project_context.get("study_design", "")),
        ("Sampling Technique", project_context.get("sampling_technique", "")),
        ("Sample Size",        str(project_context.get("sample_size", ""))),
        ("Study Population",   project_context.get("study_population", "")),
        ("Data Collection",    project_context.get("data_collection_method", "")),
    ]
    for label, value in meth_items:
        if value:
            elements.append(Paragraph(f"<b>{label}:</b> {value}", body_style))
    elements.append(Spacer(1, 0.3*cm))

    # Dataset profile summary
    elements.append(Paragraph("Dataset Overview", h2_style))
    q = profile.get("quality_summary", {})
    profile_data = [
        ["Total Records", str(profile.get("row_count", ""))],
        ["Total Variables", str(profile.get("column_count", ""))],
        ["Completeness", f"{q.get('completeness_pct', '')}%"],
        ["Numeric Variables", str(q.get("numeric_columns", ""))],
        ["Categorical Variables", str(q.get("categorical_columns", ""))],
        ["Duplicate Rows Removed", str(q.get("duplicate_rows", 0))],
    ]
    pt = Table(profile_data, colWidths=[8*cm, 8*cm])
    pt.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f5f5f5")),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#dddddd")),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(pt)
    elements.append(PageBreak())

    # ── Analysis Results ──────────────────────────────────────────────────────
    elements.append(Paragraph("Statistical Analysis Results", h1_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
    elements.append(Spacer(1, 0.2*cm))

    for r in analysis_results:
        hid  = r.get("hypothesis_id", "")
        test = r.get("test", "").replace("_", " ").title()
        res  = r.get("result", {})
        ef   = r.get("effect_size") or {}
        sig  = r.get("significant", False)

        elements.append(Paragraph(
            f"Finding {hid}: {r.get('iv')} → {r.get('dv')}", h2_style))
        elements.append(Paragraph(
            f"Test Used: <b>{test}</b> | p = {r.get('p_value')} | "
            f"Effect Size: {ef.get('name','')} = {ef.get('value','')} "
            f"({ef.get('magnitude','')})", label_style))
        elements.append(Paragraph(
            f"<b>Result:</b> {'H0 Rejected — statistically significant' if sig else 'H0 Retained — not significant'}",
            verdict_style))
        elements.append(Paragraph(
            str(r.get("interpretation", "")), body_style))
        elements.append(Spacer(1, 0.3*cm))

    elements.append(PageBreak())

    # ── Conclusions ───────────────────────────────────────────────────────────
    elements.append(Paragraph("Conclusions and Recommendations", h1_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
    elements.append(Spacer(1, 0.2*cm))

    for c in conclusions:
        if c.get("type") == "overall_summary":
            elements.append(PageBreak())
            elements.append(Paragraph("Overall Conclusions Summary", h1_style))
            elements.append(HRFlowable(width="100%", thickness=1,
                                        color=colors.HexColor("#cccccc")))
            elements.append(Spacer(1, 0.2*cm))

        text = c.get("conclusion_text", "")
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                elements.append(Spacer(1, 0.15*cm))
            elif line.isupper() or line.startswith("CONCLUSION") or \
                    line.startswith("RECOMMENDATION") or \
                    line.startswith("HYPOTHESIS") or \
                    line.startswith("GENERAL") or \
                    line.startswith("FUTURE") or \
                    line.startswith("STUDY"):
                elements.append(Paragraph(line, h2_style))
            else:
                elements.append(Paragraph(line, body_style))

    # ── Predictions Summary ───────────────────────────────────────────────────
    if predictions.get("model_scores"):
        elements.append(PageBreak())
        elements.append(Paragraph("Predictive Model Results", h1_style))
        elements.append(HRFlowable(width="100%", thickness=1,
                                    color=colors.HexColor("#cccccc")))
        elements.append(Spacer(1, 0.2*cm))

        for dv, score in predictions["model_scores"].items():
            elements.append(Paragraph(f"<b>Target Variable:</b> {dv}", body_style))
            elements.append(Paragraph(score.get("label", ""), label_style))
            fi = predictions.get("feature_importance", {}).get(dv, [])[:5]
            if fi:
                elements.append(Paragraph("<b>Top 5 Predictors:</b>", body_style))
                fi_data = [["Feature", "Importance"]] + \
                          [[row["feature"], str(row["importance"])] for row in fi]
                fi_table = Table(fi_data, colWidths=[10*cm, 6*cm])
                fi_table.setStyle(TableStyle([
                    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0f3460")),
                    ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                    ("FONTSIZE", (0,0), (-1,-1), 9),
                    ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#dddddd")),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                    ("TOPPADDING", (0,0), (-1,-1), 4),
                ]))
                elements.append(fi_table)
            elements.append(Spacer(1, 0.3*cm))

    doc.build(elements)
    return output_path
