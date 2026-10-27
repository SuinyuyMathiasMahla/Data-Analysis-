"""Run the whole analysis pipeline on the sample dataset WITHOUT a database or
web server, and write the four report formats.

    python backend/scripts/demo_workflow.py [output_dir]

It drives exactly the same engine code as the API (profiling -> quality ->
audited cleaning -> EDA -> descriptive -> method recommendation -> tests ->
findings -> conclusions -> recommendations -> limitations -> charts -> reports),
so it is a quick way to check an installation and to see what the platform
produces. Every step asserts what it expects, so a failure is loud.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.context import build_context  # noqa: E402
from app.ai.guard import check_grounding  # noqa: E402
from app.ai.service import AIService  # noqa: E402
from app.analysis import cleaning, eda, evidence, profiling, quality, visualization  # noqa: E402
from app.reports import renderers  # noqa: E402
from app.reports.content import assemble_report_content  # noqa: E402
from app.statistics import descriptive, power, recommender  # noqa: E402
from app.statistics.registry import run_method  # noqa: E402
from app.statistics.utils import AnalysisError, MethodNotImplementedError, software_versions  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "sample_data" / "student_performance.csv"

PROJECT = {"id": 1, "title": "Impact of Social Media Use on Academic Performance", "academic_level": "masters", "research_field": "Education",
           "institution": "Example University", "department": "Education", "study_design": "Cross-sectional survey",
           "research_methodology": "Quantitative", "study_population": "Undergraduate students of Example University", "sample_size": 240,
           "sampling_technique": "Convenience sampling", "data_collection_method": "Self-administered questionnaire"}
QUESTIONS = [{"id": 1, "code": "RQ1", "text": "Is there a relationship between daily social media use and GPA?"},
             {"id": 2, "code": "RQ2", "text": "Does GPA differ between students with low, moderate and high social media use?"},
             {"id": 3, "code": "RQ3", "text": "Which factors (study hours, social media use, attendance) predict GPA?"}]
HYPOTHESES = [{"id": 1, "code": "H1", "research_question_id": 1, "direction": "non_directional", "alpha": 0.05, "decision": "pending",
               "null_text": "There is no significant relationship between daily social media use and GPA.",
               "alternative_text": "There is a significant relationship between daily social media use and GPA."},
              {"id": 2, "code": "H2", "research_question_id": 2, "direction": "non_directional", "alpha": 0.05, "decision": "pending",
               "null_text": "Mean GPA does not differ between levels of social media use.",
               "alternative_text": "Mean GPA differs between at least two levels of social media use."}]
CLEANING_STEPS = [
    ("remove_duplicates", {}, "Exact duplicate questionnaire submissions"),
    ("remove_invalid", {"column": "age", "min": 15, "max": 80, "action": "set_missing"}, "Impossible ages are data-entry errors"),
    ("remove_invalid", {"column": "attendance_pct", "min": 0, "max": 100, "action": "set_missing"}, "Attendance cannot exceed 100%"),
    ("convert_type", {"column": "study_hours", "to": "numeric"}, "Text entered in a numeric field"),
    ("standardize_categories", {"column": "gender", "case": "title"}, "Inconsistent capitalisation of gender"),
    ("standardize_categories", {"column": "department", "case": "title", "mapping": {"Bussiness": "Business"}}, "Spelling of department"),
    ("derive", {"new_column": "stress_score", "operation": "mean", "columns": [f"stress_q{i}" for i in range(1, 6)]},
     "Composite stress scale (mean of five items)"),
]


def step(text: str) -> None:
    print(f"\n== {text}")


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    step("4. Upload: the original is kept, a working copy is profiled")
    original_bytes = SAMPLE.read_bytes()
    raw = profiling.read_raw(original_bytes, "csv")
    schema = profiling.infer_schema(raw)
    assert raw.shape == (243, 20), raw.shape
    assert schema["gpa"]["type"] == "numeric" and schema["gender"]["type"] == "categorical" and schema["student_id"]["type"] == "identifier"
    print(f"   {raw.shape[0]} rows x {raw.shape[1]} columns; types: " + ", ".join(f"{k}={v['type']}" for k, v in list(schema.items())[:6]) + ", ...")

    step("5. Data quality")
    first_quality = quality.assess_quality(raw, schema)
    codes = {i["code"] for i in first_quality["issues"]}
    assert {"missing_values", "duplicate_rows", "impossible_value", "invalid_numeric", "inconsistent_category", "outliers"} <= codes
    assert first_quality["summary"]["duplicate_rows"] == 3
    print(f"   Data Quality Score: {first_quality['score']}%  ({len(first_quality['issues'])} issues)")
    for issue in first_quality["issues"][:6]:
        print(f"   - [{issue['severity']}] {issue['message']}")

    step("6. Cleaning with an audit trail (each step = a new version)")
    audit_trail, version = [], 1
    for operation, params, reason in CLEANING_STEPS:
        outcome = cleaning.apply_operation(raw, schema, operation, params, reason)
        version += 1
        audit_trail.append({"operation": operation, "params": params, "reason": reason, "rows_before": outcome.rows_before,
                            "rows_after": outcome.rows_after, "cells_changed": outcome.cells_changed, "details": outcome.details})
        raw, schema = outcome.raw, outcome.schema
        example = (outcome.details.get("changes") or [{}])[0]
        print(f"   v{version}: {cleaning.OPERATIONS[operation]['label']:34s} rows {outcome.rows_before}->{outcome.rows_after}, "
              f"cells changed {outcome.cells_changed}" + (f"   e.g. row {example['row']}: {example['old']!r} -> {example['new']!r}" if example.get("row") else ""))
    assert raw.shape == (240, 21) and version == 8
    assert audit_trail[1]["details"]["changes"][0]["old"] == "-5" and audit_trail[1]["details"]["changes"][0]["new"] is None
    assert profiling.read_raw(original_bytes, "csv").shape == (243, 20)          # the original is unaffected
    final_quality = quality.assess_quality(raw, schema, {"gpa": (0, 4)})
    assert final_quality["score"] > first_quality["score"]
    print(f"   Data Quality Score after cleaning: {final_quality['score']}%")

    df = profiling.typed_frame(raw, schema)
    variables = [{"name": p["name"], "label": None, "data_type": p["type"], "measurement_level": p["measurement_level"], "role": "other",
                  "n_unique": p["n_unique"], "n_missing": p["n_missing"], "stats": p["stats"]} for p in profiling.profile_columns(raw, schema)]
    assert next(v for v in variables if v["name"] == "age")["n_missing"] == 2

    step("8-9. Exploratory and descriptive analysis")
    overview = eda.run_eda(df, schema)
    for line in overview["highlights"]:
        print("   " + line)
    desc = descriptive.run_descriptive(df, schema, ["gpa", "study_hours", "social_media_hours", "gender", "usage_level"], group_by="gender")
    assert desc["numeric"]["gpa"]["n"] == 240 and 2.0 < desc["numeric"]["gpa"]["mean"] < 3.5

    step("10-11. Method recommendation, then the tests (statistical engine)")
    runs, results = [], []

    def run(run_id: int, method: str, variables_: dict, rq: int | None, hypothesis: int | None = None, filters=None, why: str | None = None):
        result = run_method(df, schema, method, variables_, {}, filters)
        results.append(result)
        runs.append({"id": run_id, "name": result["method_name"], "status": "COMPLETED", "research_question_id": rq, "version_number": version,
                     "filters": filters or [], "software": software_versions(), "completed_at": renderers.now_iso(),
                     "results": [{"id": run_id, "result_type": "test", "result": result, "justification": why,
                                  "test": {"hypothesis_id": hypothesis, "params": {}}}]})
        print(f"   {result['method_name']}: {result['apa']}")
        for warning in result["warnings"][:2]:
            print(f"      ! {warning}")
        return result

    rec = recommender.recommend(df, schema, outcome="gpa", predictors=["social_media_hours"], academic_level="masters",
                                study_design=PROJECT["study_design"])
    assert rec["primary"]["method"] in ("pearson", "spearman") and rec["why"] and rec["assumption_checks"]
    print(f"   Recommended for RQ1: {rec['primary']['name']} - {rec['primary']['reason']}")
    pearson = run(1, "pearson", {"x": "social_media_hours", "y": "gpa"}, 1, 1, why=" ".join(rec["why"]))
    assert -0.7 < pearson["statistic"]["value"] < -0.2 and pearson["p_value"] < 0.001 and pearson["decision"] == "reject_null"
    run(2, rec["config"]["method"] if rec["config"]["method"] != "pearson" else "spearman", {"x": "social_media_hours", "y": "gpa"}, 1)
    rec2 = recommender.recommend(df, schema, outcome="gpa", predictors=["usage_level"], academic_level="masters")
    print(f"   Recommended for RQ2: {rec2['primary']['name']} - {rec2['primary']['reason']}")
    anova = run(3, "one_way_anova", {"outcome": "gpa", "group": "usage_level"}, 2, 2, why=" ".join(rec2["why"]))
    assert anova["post_hoc"]
    regression = run(4, "multiple_linear_regression", {"outcome": "gpa", "predictors": ["study_hours", "social_media_hours", "attendance_pct"]},
                     3, filters=[{"column": "age", "op": "not_missing"}])
    assert 0.1 < regression["model_fit"]["r_squared"] < 0.8 and regression["records_after_filters"] == 238

    for method, vars_, expected in [("independent_t_test", {"outcome": "gpa", "group": "department"}, "exactly 2 groups"),
                                    ("survival_analysis", {}, "not implemented")]:
        try:
            run_method(df, schema, method, vars_)
            raise AssertionError(f"{method} should have been refused")
        except (AnalysisError, MethodNotImplementedError) as exc:
            assert expected in str(exc)
            print(f"   Refused as expected ({method}): {str(exc)[:90]}")

    plan = power.run_power_analysis("correlation", "required_n", effect_size=0.3)
    print("   " + plan["summary"])

    step("12. AI-assisted interpretation (no provider configured -> labelled rule engine; numbers are verified)")
    context = build_context(project=PROJECT, research_questions=QUESTIONS, hypotheses=HYPOTHESES, dataset={"rows": 240, "columns": 21},
                            variables=variables, quality=final_quality, results=results)
    reply = AIService(None).explain_result(context, pearson)
    assert reply.source == "rule_engine" and pearson["apa"] in reply.content
    assert check_grounding(reply.content, context)["grounded"]
    print("   " + reply.content.split("\n")[2][:150] + " ...")
    fabricated = check_grounding("The correlation was r = -0.75 (p = 0.0001).", context)
    assert not fabricated["grounded"]
    print(f"   A reply inventing 'r = -0.75, p = 0.0001' is flagged: unverified numbers {fabricated['unverified']}")

    step("13-15. Findings -> conclusions -> recommendations -> limitations")
    findings = []
    for i, (result, rq, hyp) in enumerate([(pearson, QUESTIONS[0], HYPOTHESES[0]), (anova, QUESTIONS[1], HYPOTHESES[1]), (regression, QUESTIONS[2], None)], 1):
        draft = evidence.draft_finding(result, rq, hyp)
        findings.append({**draft, "id": i, "research_question_id": rq["id"], "hypothesis_id": hyp["id"] if hyp else None,
                         "analysis_result_id": {1: 1, 2: 3, 3: 4}[i], "significant": result["significant"], "is_edited": False})
        print(f"   Finding {i} [{draft['confidence_level']} confidence]: {draft['statement'][:120]}...")
    assert "H1" in findings[0]["interpretation"] and "r(" in findings[0]["statistical_evidence"]
    conclusions = evidence.draft_conclusions(findings, QUESTIONS)
    recommendations = evidence.draft_recommendations(findings, PROJECT["study_design"])
    limitations = [{**item, "status": "active", "status_note": None, "source": "auto"}
                   for item in evidence.detect_limitations(PROJECT, final_quality["summary"], results, audit_trail)]
    assert len(conclusions) == 3 and len(recommendations) == 3 and all(c["finding_ids"] for c in conclusions)
    assert {"design", "sampling_bias", "self_report", "generalizability"} <= {item["category"] for item in limitations}
    print(f"   {len(conclusions)} conclusions, {len(recommendations)} recommendations, {len(limitations)} limitations: "
          + ", ".join(sorted({item['category'] for item in limitations})))

    step("16. Charts")
    labels = {"gpa": "Grade point average (GPA)", "social_media_hours": "Social media use (hours/day)", "usage_level": "Social media use level"}
    charts = [
        ("descriptive", {"chart_type": "histogram", "x": "gpa"}),
        ("descriptive", {"chart_type": "box", "x": "usage_level", "y": "gpa", "category_order": ["Low", "Moderate", "High"]}),
        ("inferential", {"chart_type": "regression", "x": "social_media_hours", "y": "gpa"}),
        ("inferential", {"chart_type": "group_comparison", "x": "usage_level", "y": "gpa", "category_order": ["Low", "Moderate", "High"]}),
    ]
    figures, images = [], {}
    for i, (section, config) in enumerate(charts, 1):
        png, meta = visualization.render_chart(df, config, labels)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        images[f"fig{i}"] = png
        figures.append({"image_key": f"fig{i}", "title": meta["title"], "note": " ".join(meta["notes"]) or None, "section": section})
        (out_dir / f"figure_{i}_{config['chart_type']}.png").write_bytes(png)
    images["diag"] = visualization.render_regression_diagnostics(regression["diagnostics"], "gpa")
    figures.append({"image_key": "diag", "title": "Regression diagnostics for gpa", "note": None, "section": "inferential"})
    print(f"   {len(figures)} charts rendered")

    step("17. Reports")
    runs.insert(0, {"id": 0, "name": "Descriptive statistics", "status": "COMPLETED", "research_question_id": None, "version_number": version,
                    "software": software_versions(), "completed_at": renderers.now_iso(),
                    "results": [{"id": 0, "result_type": "descriptive", "result": desc, "test": None}]})
    content = assemble_report_content(
        title=f"{PROJECT['title']} - Research Data Analysis Report", researcher="Demo Researcher", project=PROJECT,
        dataset={"name": "Student survey", "description": "Simulated survey data (see sample_data/README.md).", "source_type": "csv",
                 "original_filename": SAMPLE.name, "version_number": version, "rows": 240, "columns": 21,
                 "original_checksum": __import__("hashlib").sha256(original_bytes).hexdigest()},
        variables=variables, quality={**final_quality, "version_number": version}, cleaning=audit_trail, runs=runs,
        research_questions=QUESTIONS, hypotheses=HYPOTHESES, findings=findings, conclusions=conclusions, recommendations=recommendations,
        limitations=limitations, figures=figures)
    assert len(content["inferential"]) == 4 and content["hypotheses"][0]["decision_text"] == "Reject H0"
    assert len(content["data_quality"]["cleaning"]) == 7
    data_rows = (list(raw.columns), raw.values.tolist())
    outputs = {"pdf": renderers.render_pdf(content, images), "docx": renderers.render_docx(content, images),
               "xlsx": renderers.render_xlsx(content, data_rows), "csv": renderers.render_csv(content)}
    signatures = {"pdf": b"%PDF", "docx": b"PK\x03\x04", "xlsx": b"PK\x03\x04", "csv": b"\xef\xbb\xbf"}
    for fmt, data in outputs.items():
        assert data.startswith(signatures[fmt]) and len(data) > 500, fmt
        path = out_dir / f"research_report.{fmt}"
        path.write_bytes(data)
        print(f"   wrote {path}  ({len(data) / 1024:.0f} KB)")
    (out_dir / "cleaned_dataset.csv").write_bytes(profiling.raw_to_csv_bytes(raw))

    step("18. Reproducibility: the same configuration on the same version gives identical numbers")
    again = run_method(df, schema, "pearson", {"x": "social_media_hours", "y": "gpa"})
    assert again["statistic"]["value"] == pearson["statistic"]["value"] and again["p_value"] == pearson["p_value"]
    print(f"   r = {again['statistic']['value']:.6f} both times; software: " + ", ".join(f"{k} {v}" for k, v in list(software_versions().items())[:4]))
    print("\nWorkflow completed: raw data -> analysis -> statistical evidence -> interpretation -> finding -> conclusion -> report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "reports" / "demo"))
