"""Client package: one zip with the summary, the full report, charts, data and an analysis log.

Every file is rendered from the same report snapshot, so the one-page summary, the Word and PDF reports, the workbook and the
README cannot disagree with each other. The caller must run ``gate.check`` first; this module assumes the gate passed.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any

import pandas as pd

from app.reports import renderers

DELIVERABLES = ("summary", "report", "charts", "data", "workbook", "log", "dashboard", "deck")
DICTIONARY_COLUMNS = ["Variable", "Label", "Type", "Level", "Unique", "Missing", "Min", "Max", "Mean", "Median", "SD"]


def _effect(content: dict, code: str | None) -> str:
    """The first effect size with a confidence interval for the latest test of a hypothesis."""
    items = [i for i in content.get("inferential") or [] if i.get("hypothesis_code") == code]
    if not items:
        return "No test run"
    effect = next((e for e in items[-1].get("effect_sizes") or [] if e.get("value") is not None and e.get("ci_low") is not None), None)
    if effect is None:
        return "No effect size with CI"
    return f"{effect['name']} = {renderers.fmt(effect['value'], 2)} (95% CI {renderers.fmt(effect['ci_low'], 2)} to {renderers.fmt(effect['ci_high'], 2)})"


def _verdict(content: dict, question_code: str) -> str:
    """Yes when a hypothesis linked to the question is rejected (on the primary or the Holm-adjusted p-value); otherwise
    Inconclusive. 'No' is never assigned automatically: a non-significant result does not show that there is no effect."""
    codes = {t.get("hypothesis_code") for t in content.get("inferential") or [] if t.get("rq_code") == question_code}
    decided = [h for h in content.get("hypotheses") or [] if h["code"] in codes]
    return "Yes" if any(h["decision_text"] == "Reject H0" for h in decided) else "Inconclusive"


def _certainty(content: dict, code: str | None) -> str:
    levels = [f.get("confidence_level") for f in content.get("findings") or [] if f.get("hypothesis_code") == code and f.get("confidence_level")]
    return str(levels[-1]) if levels else "Not rated"


AUDIENCE_LINES = {
    "executive": "Prepared for: decision-makers. Read the answer and the recommended action first.",
    "technical": "Prepared for: analysts. The effect sizes, intervals and adjusted p-values are the key figures.",
    "academic": "Prepared for: examiners and supervisors. Every decision is traceable to a test in the analysis log.",
}


def summary_pdf(content: dict, audience: str = "academic") -> bytes:
    """One page: the answer first, then one row per hypothesis, certainty and the recommended action."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["Normal"], fontSize=9, leading=12)
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=11, spaceBefore=6, spaceAfter=3)
    story: list = [Paragraph(renderers._pdf_text(content.get("title") or "Research summary"), base["Title"])]
    story.append(Paragraph(renderers._pdf_text(AUDIENCE_LINES.get(audience, AUDIENCE_LINES["academic"])),
                           ParagraphStyle("audience", parent=body, fontSize=8, textColor=colors.HexColor("#52514e"))))
    story.append(Paragraph("<b>The answer.</b> " + renderers._pdf_text(" ".join((content.get("executive_summary") or [""])[:2])), body))

    story.append(Paragraph("Verdict by research question", h2))
    rq_rows = [[renderers._pdf_text(r["code"]), renderers._pdf_text(r["text"]), renderers._pdf_text(_verdict(content, r["code"]))]
               for r in content.get("research_questions") or []]
    if rq_rows:
        story.append(Table([[Paragraph(c, head) for c in ("Question", "Research question", "Verdict")]] +
                           [[Paragraph(renderers._pdf_text(c), cell) for c in row] for row in rq_rows],
                           colWidths=[2 * cm, 11 * cm, 4.5 * cm],
                           style=TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14213d")),
                                             ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9c7c0")), ("VALIGN", (0, 0), (-1, -1), "TOP")])))

    story.append(Paragraph("Hypotheses: effect, certainty and decision", h2))
    rows = []
    for h in content.get("hypotheses") or []:
        p_text = renderers.fmt(h.get("p_value"), 3)
        if h.get("p_adjusted") is not None:
            p_text += f" (Holm {renderers.fmt(h['p_adjusted'], 3)})"
        rows.append([h["code"] + (" (primary)" if h.get("primary") else ""), h.get("test") or "Not tested", _effect(content, h["code"]),
                     p_text, h["decision_text"], _certainty(content, h["code"])])
    if rows:
        story.append(Table([[Paragraph(c, head) for c in ("Hypothesis", "Test", "Effect (95% CI)", "p", "Decision", "Certainty")]] +
                           [[Paragraph(renderers._pdf_text(c), cell) for c in row] for row in rows],
                           colWidths=[2.2 * cm, 3.4 * cm, 5.6 * cm, 2.8 * cm, 2.6 * cm, 2.2 * cm],
                           style=TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14213d")),
                                             ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9c7c0")), ("VALIGN", (0, 0), (-1, -1), "TOP")])))
    story.append(Paragraph("Certainty is the researcher's rating of the evidence recorded in the findings. Holm-adjusted p-values apply to "
                           "secondary hypotheses only; the primary hypothesis uses the raw p-value.", ParagraphStyle("note", parent=body, fontSize=7.5)))

    story.append(Paragraph("Recommended action", h2))
    recs = content.get("recommendations") or []
    story.append(Paragraph(renderers._pdf_text(recs[0]["text"]) if recs else "No recommendation has been recorded.", body))
    story.append(Spacer(1, 6))
    story.append(Paragraph(renderers._pdf_text(renderers.INTEGRITY_NOTE), ParagraphStyle("small", parent=body, fontSize=7, textColor=colors.HexColor("#52514e"))))

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                      title=f"{content.get('title') or 'Summary'} - summary").build(story)
    return buffer.getvalue()


def summary_docx(content: dict, audience: str = "academic") -> bytes:
    """The same one-page summary as summary.pdf, as an editable Word document."""
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(10)
    doc.add_heading(content.get("title") or "Research summary", level=1)
    doc.add_paragraph(AUDIENCE_LINES.get(audience, AUDIENCE_LINES["academic"]))
    doc.add_paragraph().add_run("The answer. ").bold = True
    doc.paragraphs[-1].add_run(" ".join((content.get("executive_summary") or [""])[:2]))

    def table(title: str, columns: list[str], rows: list[list[Any]]) -> None:
        doc.add_heading(title, level=2)
        if not rows:
            doc.add_paragraph("None recorded.")
            return
        grid = doc.add_table(rows=1, cols=len(columns))
        grid.style = "Light Grid Accent 1"
        for cell, label in zip(grid.rows[0].cells, columns):
            cell.text = label
        for row in rows:
            for cell, value in zip(grid.add_row().cells, row):
                cell.text = "" if value is None else str(value)

    table("Verdict by research question", ["Question", "Research question", "Verdict"],
          [[r["code"], r["text"], _verdict(content, r["code"])] for r in content.get("research_questions") or []])
    table("Hypotheses: effect, certainty and decision", ["Hypothesis", "Test", "Effect (95% CI)", "p", "Decision", "Certainty"],
          [[h["code"] + (" (primary)" if h.get("primary") else ""), h.get("test") or "Not tested", _effect(content, h["code"]),
            renderers.fmt(h.get("p_value"), 3) + (f" (Holm {renderers.fmt(h['p_adjusted'], 3)})" if h.get("p_adjusted") is not None else ""),
            h["decision_text"], _certainty(content, h["code"])] for h in content.get("hypotheses") or []])
    doc.add_heading("Recommended action", level=2)
    recs = content.get("recommendations") or []
    doc.add_paragraph(recs[0]["text"] if recs else "No recommendation has been recorded.")
    doc.add_paragraph(renderers.INTEGRITY_NOTE).runs[0].font.size = Pt(8)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def bi_export_csv(content: dict) -> bytes:
    """One tidy row per distinct test, with the columns a BI tool needs to filter and chart it (Power BI, Tableau, Looker)."""
    header = ["question", "hypothesis", "test", "variables", "n", "statistic", "statistic_value", "p_value", "decision",
              "effect_measure", "effect_value", "ci_low", "ci_high", "dataset_version", "run_at"]
    rows = []
    for test in content.get("inferential") or []:
        effect = next((e for e in test.get("effect_sizes") or [] if e.get("value") is not None), {})
        stat = test.get("statistic") or {}
        rows.append([test.get("rq_code") or "", test.get("hypothesis_code") or "", test["method_name"], test["variables_text"], test.get("n"),
                     stat.get("name"), stat.get("value"), test.get("p_value"),
                     {"reject_null": "Reject H0", "fail_to_reject_null": "Fail to reject H0"}.get(test.get("decision"), ""),
                     effect.get("name"), effect.get("value"), effect.get("ci_low"), effect.get("ci_high"),
                     test.get("dataset_version"), test.get("run_at")])
    return pd.DataFrame(rows, columns=header).to_csv(index=False).encode("utf-8-sig")


DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
body { font-family: system-ui, sans-serif; margin: 0; padding: 1.5rem; color: #14213d; background: #fbfbf9; }
h1 { font-size: 1.4rem; margin: 0 0 .3rem; } .muted { color: #52514e; font-size: .9rem; }
.filters { display: flex; flex-wrap: wrap; gap: .75rem; margin: 1rem 0; }
table { border-collapse: collapse; width: 100%; background: #fff; font-size: .9rem; }
th, td { border-bottom: 1px solid #c9c7c0; padding: .4rem .5rem; text-align: left; vertical-align: top; }
th { background: #14213d; color: #fff; position: sticky; top: 0; }
.bar { height: .6rem; background: #1c5cab; border-radius: 4px; }
.note { margin-top: 1rem; font-size: .85rem; color: #52514e; }
</style></head>
<body>
<h1 id="title"></h1>
<div class="muted" id="generated"></div>
<div class="filters">
  <label>Decision <select id="decision"><option value="">All</option><option>Reject H0</option><option>Fail to reject H0</option></select></label>
  <label>Question <select id="question"><option value="">All</option></select></label>
  <label>Search <input id="search" type="search" placeholder="test or variable"></label>
</div>
<table><thead><tr><th>Question</th><th>Hypothesis</th><th>Test</th><th>Variables</th><th>n</th><th>p</th><th>Effect (95% CI)</th><th>Decision</th></tr></thead>
<tbody id="rows"></tbody></table>
<p class="note">Figures are the platform's computed results from the dataset version in the README. Filtering only hides rows; nothing is recalculated.
Load <code>bi_export.csv</code> from this package into Power BI, Tableau or Looker for your own charts.</p>
<script id="data" type="application/json">__DATA__</script>
<script>
const data = JSON.parse(document.getElementById("data").textContent);
const cell = (text) => { const td = document.createElement("td"); td.textContent = text == null ? "-" : String(text); return td; };
document.getElementById("title").textContent = data.title;
document.getElementById("generated").textContent = "Generated " + data.generated_at;
const questions = [...new Set(data.tests.map((t) => t.question).filter(Boolean))];
const select = document.getElementById("question");
questions.forEach((q) => { const o = document.createElement("option"); o.value = q; o.textContent = q; select.appendChild(o); });
function draw() {
  const decision = document.getElementById("decision").value;
  const question = select.value;
  const search = document.getElementById("search").value.trim().toLowerCase();
  const body = document.getElementById("rows");
  body.replaceChildren();
  data.tests.filter((t) => (!decision || t.decision === decision) && (!question || t.question === question)
      && (!search || `${t.test} ${t.variables}`.toLowerCase().includes(search)))
    .forEach((t) => {
      const tr = document.createElement("tr");
      const effect = t.effect ? `${t.effect.name} = ${t.effect.value} (${t.effect.ci_low} to ${t.effect.ci_high})` : "-";
      [t.question, t.hypothesis, t.test, t.variables, t.n, t.p_value, effect, t.decision].forEach((v) => tr.appendChild(cell(v)));
      body.appendChild(tr);
    });
}
["decision", "question", "search"].forEach((id) => document.getElementById(id).addEventListener("input", draw));
draw();
</script>
</body></html>
"""


def dashboard_html(content: dict) -> bytes:
    """A self-contained page: filter the tests by decision, question or text. The data is embedded as JSON and drawn with
    textContent, so no value from the dataset can inject markup."""
    tests = []
    for t in content.get("inferential") or []:
        effect = next((e for e in t.get("effect_sizes") or [] if e.get("value") is not None), None)
        tests.append({"question": t.get("rq_code"), "hypothesis": t.get("hypothesis_code"), "test": t["method_name"], "variables": t["variables_text"],
                      "n": t.get("n"), "p_value": None if t.get("p_value") is None else round(float(t["p_value"]), 3),
                      "decision": {"reject_null": "Reject H0", "fail_to_reject_null": "Fail to reject H0"}.get(t.get("decision"), "Not decided"),
                      "effect": None if effect is None else {"name": effect["name"], "value": round(float(effect["value"]), 3),
                                                              "ci_low": None if effect.get("ci_low") is None else round(float(effect["ci_low"]), 3),
                                                              "ci_high": None if effect.get("ci_high") is None else round(float(effect["ci_high"]), 3)}})
    payload = json.dumps({"title": content.get("title") or "Research results", "generated_at": content.get("generated_at"), "tests": tests}, default=str)
    payload = payload.replace("</", "<\\/")          # a value cannot close the data script element
    html = DASHBOARD_TEMPLATE.replace("__TITLE__", renderers._pdf_text(content.get("title") or "Research results").replace('"', "&quot;")).replace("__DATA__", payload)
    return html.encode("utf-8")


def _chart_for(content: dict, images: dict[str, bytes], variables_text: str) -> bytes | None:
    """The first chart whose title names one of the variables a question's test used. Charts are not linked to questions in
    the platform, so this matches on names; a question with no matching chart simply gets no picture."""
    names = {token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", variables_text or "")}
    for fig in content.get("figures") or []:
        title = (fig.get("title") or "").lower()
        if fig.get("image_key") in images and any(name in title for name in names):
            return images[fig["image_key"]]
    return None


def deck_pptx(content: dict, images: dict[str, bytes], audience: str = "academic") -> bytes:
    """A handover deck of 8 to 12 slides. Each slide's speaker notes explain it in plain language."""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    title_layout, content_layout = prs.slide_layouts[0], prs.slide_layouts[1]

    def bullets_slide(title: str, lines: list[str], notes: str):
        slide = prs.slides.add_slide(content_layout)
        slide.shapes.title.text = title
        frame = slide.placeholders[1].text_frame
        frame.clear()
        for index, line in enumerate(lines or ["Nothing to report for this slide."]):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = line
            paragraph.font.size = Pt(18)
        slide.notes_slide.notes_text_frame.text = notes
        return slide

    rqs = content.get("research_questions") or []
    tests = content.get("inferential") or []
    hyps = content.get("hypotheses") or []
    dataset = content.get("dataset") or {}
    cleaning = (content.get("data_quality") or {}).get("cleaning") or []

    title_slide = prs.slides.add_slide(title_layout)
    title_slide.shapes.title.text = content.get("title") or "Research handover"
    title_slide.placeholders[1].text = f"{AUDIENCE_LINES.get(audience, AUDIENCE_LINES['academic'])}\n{(content.get('generated_at') or '')[:10]}"
    title_slide.notes_slide.notes_text_frame.text = ("This deck summarises the study for the person receiving it. Every number comes from the "
                                                     "analysis run on the dataset version named in the README.")

    answer = [f"{q['code']}: {_verdict(content, q['code'])}. " + _effect(content, next((t.get("hypothesis_code") for t in tests
                                                                                     if t.get("rq_code") == q["code"]), None))
              for q in rqs]
    bullets_slide("The answer", (content.get("executive_summary") or [])[:2] + answer,
                  "Start here. 'Yes' means the test rejected the no-effect hypothesis after adjustment where needed. 'Inconclusive' "
                  "means the study did not show an effect; it does not show that there is no effect.")

    bullets_slide("What was asked and the data used",
                  [f"{q['code']}: {q['text']}" for q in rqs] +
                  [f"{h['code']}: H0 {h['null_text']}" for h in hyps[:3]] +
                  [f"Data: {dataset.get('name') or 'not recorded'}, {dataset.get('rows') or '-'} records, {dataset.get('columns') or '-'} variables"],
                  "The questions are what the study set out to answer. The data is the file as it was analysed; the README gives its checksum.")

    cleaning_lines = [f"{step['label']}: {step['rows_before']} to {step['rows_after']} records. Reason: {step['reason']}" for step in cleaning[:6]]
    bullets_slide("Data quality and cleaning", cleaning_lines or ["No cleaning operations were applied; the data were analysed as uploaded."],
                  "Each cleaning step changed the data and is recorded with its reason. Rows before and after show how many records each step kept.")

    for question in rqs[:5]:
        linked = [t for t in tests if t.get("rq_code") == question["code"]]
        first = linked[0] if linked else None
        hypothesis_code = first.get("hypothesis_code") if first else None
        lines = [f"Question: {question['text']}",
                 f"Verdict: {_verdict(content, question['code'])}",
                 f"Test: {first['method_name']} ({first.get('apa') or 'no statistic recorded'})" if first else "Test: none has been run for this question",
                 _effect(content, hypothesis_code) if hypothesis_code else "No effect size: no test linked to this question",
                 f"Takeaway: {(first.get('summary') if first else None) or 'Not yet tested.'}"]
        slide = bullets_slide(f"{question['code']}: {_verdict(content, question['code'])}", lines,
                              "Plain language: the verdict is Yes only when the test rejected the no-effect hypothesis. The effect size and its "
                              "95% interval show how big the effect is and how precisely it was estimated. The takeaway is the test's own reading.")
        picture = _chart_for(content, images, first.get("variables_text") if first else "")
        if picture:
            slide.placeholders[1].width = Inches(6)
            slide.shapes.add_picture(io.BytesIO(picture), Inches(7), Inches(2), width=Inches(5.8))

    limitations = [item["description"] for item in content.get("limitations") or []][:8]
    bullets_slide("Limitations", limitations, "These limit how far the results can be trusted or generalised. Read them before the recommendations.")

    recs = content.get("recommendations") or []
    bullets_slide("Recommendations and owners",
                  [f"{r['text']} Owner: {r.get('audience') or 'not yet assigned; name one before presenting'}" for r in recs[:6]],
                  "Each recommendation names who should act. A recommendation without an owner is not ready to present.")

    follow = [f"{q['code']}: {_verdict(content, q['code'])}. Consider a follow-up study with a larger sample before deciding."
              for q in rqs if _verdict(content, q["code"]) == "Inconclusive"]
    untested = [h["code"] for h in hyps if h.get("test") is None]
    if untested:
        follow.append(f"Run the planned tests for: {', '.join(untested)}")
    bullets_slide("Next steps and follow-up analyses", follow or ["No follow-up is required by these results."],
                  "Next steps follow from the verdicts: inconclusive questions need more evidence, and untested hypotheses need a test run.")

    bullets_slide("How to rerun the analysis",
                  ["1. Open the project and select the dataset version in the README.",
                   "2. Re-run the analyses listed in analysis_log.json.",
                   "3. Generate the client package with the same options.",
                   "4. Compare the verdict slide with the new package."],
                  "To check the results yourself, rerun the same tests on the cleaned_dataset.csv file and compare the numbers with analysis_log.json.")
    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


REPRODUCE_SCRIPT = '''"""Reproduce the tests in this package from cleaned_dataset.csv and compare each p-value with analysis_log.json.

Recomputed with SciPy: Pearson and Spearman correlation, Welch t-test, Mann-Whitney U and the chi-square test.
Other methods are listed as not reproduced here. Rerun them in the platform with the parameters in the log.
Run from the package folder:  python reproduce_analysis.py   (needs pandas and scipy)
Exit code 0 when every reproduced p-value agrees with the log to three decimals, 1 otherwise.
"""
import json
import pathlib
import sys

import pandas as pd
from scipy import stats

HERE = pathlib.Path(__file__).resolve().parent
log = json.loads((HERE / "analysis_log.json").read_text(encoding="utf-8"))
data = pd.read_csv(HERE / "cleaned_dataset.csv")


def roles(text):
    """'x: a; y: b' -> {'x': 'a', 'y': 'b'}"""
    out = {}
    for part in (text or "").split("; "):
        if ": " in part:
            role, value = part.split(": ", 1)
            out[role.strip()] = value.strip()
    return out


def numeric(name):
    return pd.to_numeric(data[name], errors="coerce")


def recompute(test):
    method, v = test.get("method"), roles(test.get("variables_text"))
    if method in ("pearson", "spearman"):
        x, y = numeric(v["x"]), numeric(v["y"])
        keep = x.notna() & y.notna()
        func = stats.pearsonr if method == "pearson" else stats.spearmanr
        return func(x[keep], y[keep])[1]
    if method == "independent_t_test":
        groups = data[v["group"]]
        levels = sorted(groups.dropna().unique())
        if len(levels) != 2:
            return None
        values = numeric(v["outcome"])
        return stats.ttest_ind(values[groups == levels[0]].dropna(), values[groups == levels[1]].dropna(), equal_var=False)[1]
    if method == "mann_whitney":
        groups = data[v["group"]]
        levels = sorted(groups.dropna().unique())
        if len(levels) != 2:
            return None
        values = numeric(v["outcome"])
        return stats.mannwhitneyu(values[groups == levels[0]].dropna(), values[groups == levels[1]].dropna(), alternative="two-sided")[1]
    if method == "chi_square":
        table = pd.crosstab(data[v["x"]], data[v["y"]])
        return stats.chi2_contingency(table, correction=False)[1]
    return "not reproduced here"


failures = 0
print(f"{'hypothesis':<12}{'test':<34}{'logged p':>10}{'recomputed p':>14}  result")
for test in log.get("tests", []):
    logged = test.get("p_value")
    try:
        recomputed = recompute(test)
    except Exception as error:                                   # a column missing from the CSV, for example
        print(f"{test.get('hypothesis_code') or '-':<12}{test['method_name'][:32]:<34}{logged!s:>10}{'-':>14}  could not run: {error}")
        failures += 1
        continue
    if isinstance(recomputed, str) or recomputed is None:
        label = recomputed or "not reproduced here"
        print(f"{test.get('hypothesis_code') or '-':<12}{test['method_name'][:32]:<34}{logged!s:>10}{'-':>14}  {label}")
        continue
    agree = logged is not None and abs(round(float(recomputed), 3) - round(float(logged), 3)) < 0.0011
    failures += 0 if agree else 1
    print(f"{test.get('hypothesis_code') or '-':<12}{test['method_name'][:32]:<34}{logged!s:>10}{recomputed:>14.3f}  {'match' if agree else 'DIFFERS'}")
sys.exit(1 if failures else 0)
'''


def _dictionary_csv(content: dict) -> bytes:
    rows = (content.get("appendix") or {}).get("data_dictionary") or []
    frame = pd.DataFrame(rows, columns=DICTIONARY_COLUMNS)
    return frame.to_csv(index=False).encode("utf-8")


def _log_json(content: dict) -> bytes:
    log = {
        "generated_at": content.get("generated_at"),
        "dataset": {k: (content.get("dataset") or {}).get(k) for k in ("name", "version_number", "rows", "columns", "checksum", "original_checksum")},
        "analysis_runs": (content.get("appendix") or {}).get("analysis_config") or [],
        "tests": [{k: i.get(k) for k in ("hypothesis_code", "rq_code", "method", "method_name", "variables_text", "n", "p_value", "decision", "dataset_version", "run_at")}
                  for i in content.get("inferential") or []],
        "hypotheses": [{k: h.get(k) for k in ("code", "test", "p_value", "p_adjusted", "tests_in_report", "primary", "decision_text")}
                       for h in content.get("hypotheses") or []],
    }
    return json.dumps(log, indent=2, default=str).encode("utf-8")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "figure").lower()).strip("_")[:60] or "figure"


def _readme(content: dict, deliverables: list[str], files: list[str], references: list[str], audience: str) -> str:
    dataset = content.get("dataset") or {}
    software = (content.get("methodology") or {}).get("software") or {}
    lines = [
        f"# {content.get('title') or 'Research package'}",
        "",
        f"Generated: {content.get('generated_at')}",
        "",
        "## Dataset version",
        f"- Dataset: {dataset.get('name') or '-'} (analysed version {dataset.get('version_number') or '-'})",
        f"- Records analysed: {dataset.get('rows') or '-'}; variables: {dataset.get('columns') or '-'}",
        f"- SHA-256 of the analysed file: {dataset.get('checksum') or '-'}",
        f"- SHA-256 of the original upload: {dataset.get('original_checksum') or '-'}",
        "",
        "## Settings",
        f"- Audience: {audience}",
        f"- Deliverables: {', '.join(deliverables)}",
        f"- Hypotheses: {len(content.get('hypotheses') or [])}; distinct secondary tests adjusted with Holm: {(content.get('hypotheses') or [{}])[0].get('tests_in_report', 0)}",
        f"- References supplied: {len(references)}",
        f"- Software: {', '.join(f'{k} {v}' for k, v in software.items()) or '-'}",
        "",
        "## Files",
    ]
    lines += [f"- `{name}`" for name in files]
    lines += [
        "",
        "## What is not checked automatically",
        "- That each number in the narrative matches its table. The narrative and tables are built from the same snapshot, but no text-to-table comparison is run.",
        "- That the charts' one-line takeaways are correct. They are the researcher's notes, not computed text.",
        "",
        "## How to rerun",
        "1. Open the project in the platform and select the same dataset version.",
        "2. Re-run the analyses listed in `analysis_log.json` (Appendix C of the report gives the same list).",
        "3. Generate the client package with the same deliverables and references.",
        "4. Compare the hypothesis table in `summary.pdf` with the one in the new package. Any difference means the data or settings changed.",
        "",
        "Every test's raw p-value, method and variables are in `analysis_log.json`, so a reviewer can recompute each result from the cleaned dataset.",
    ]
    return "\n".join(lines) + "\n"


def build(content: dict, images: dict[str, bytes], deliverables: list[str], *, frame: pd.DataFrame | None,
          references: list[str], audience: str = "academic") -> bytes:
    wanted = [d for d in DELIVERABLES if d in deliverables]
    out: dict[str, bytes] = {}
    if "summary" in wanted:
        out["summary.pdf"] = summary_pdf(content, audience)
        out["summary.docx"] = summary_docx(content, audience)
    if "report" in wanted:
        out["report.pdf"] = renderers.render_pdf(content, images)
        out["report.docx"] = renderers.render_docx(content, images)
    if "deck" in wanted:
        out["handover_deck.pptx"] = deck_pptx(content, images, audience)
    if "dashboard" in wanted:
        out["dashboard.html"] = dashboard_html(content)
        out["bi_export.csv"] = bi_export_csv(content)
    if "charts" in wanted:
        for i, fig in enumerate([f for f in content.get("figures") or [] if f.get("image_key") in images], 1):
            out[f"charts/figure_{i}_{_slug(fig.get('title'))}.png"] = images[fig["image_key"]]
    if "data" in wanted and frame is not None:
        out["cleaned_dataset.csv"] = frame.to_csv(index=False).encode("utf-8")
        out["data_dictionary.csv"] = _dictionary_csv(content)
    if "workbook" in wanted:
        data_rows = None
        if frame is not None:
            data_rows = (list(frame.columns), frame.astype(object).where(frame.notna(), None).values.tolist())
        out["workbook.xlsx"] = renderers.render_xlsx(content, data_rows)
    if "log" in wanted:
        out["analysis_log.json"] = _log_json(content)
        out["reproduce_analysis.py"] = REPRODUCE_SCRIPT.encode("utf-8")
    out["README.md"] = _readme(content, wanted, sorted(out), references, audience).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in out.items():
            archive.writestr(name, data)
    return buffer.getvalue()
