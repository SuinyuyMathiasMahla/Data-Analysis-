"""The conclusion layout: one block per hypothesis, a chart under each conclusion, and earlier automatic text replaced."""
from app.analysis import evidence
from app.database.session import SessionLocal
from app.models import Conclusion
from app.services import ai_runtime

from tests.conftest import auth_headers
from tests.test_always_answered import _wait_for_runs
from tests.test_auto_analysis import _post, _setup


def _result(method_name: str, p: float, decision: str) -> dict:
    return {"method": "pearson", "method_name": method_name, "apa": f"r(98) = -0.41, p = {p}", "n": 100, "p_value": p, "alpha": 0.05,
            "decision": decision, "variables": {"x": "social_media_hours", "y": "gpa"}, "statistic": {"name": "t", "value": -4.5},
            "df": 98, "assumptions": [], "effect_sizes": [{"name": "Pearson correlation coefficient (r)", "value": -0.41,
                                                          "ci_low": -0.56, "ci_high": -0.23, "magnitude": "moderate"}]}


def test_several_tests_on_one_hypothesis_are_described_once(client):
    hypothesis = {"code": "H1", "null_text": "There is no relationship between social media use and GPA.",
                  "alternative_text": "Daily social media use is linked to lower GPA.", "direction": "non_directional"}
    findings = [
        {"id": 1, "research_question_id": 1, "hypothesis_id": 5, "hypothesis": hypothesis, "confidence_level": "moderate", "significant": True,
         "statement": "", "title": "Pearson", "result": _result("Pearson correlation", 0.0004, "reject_null")},
        {"id": 2, "research_question_id": 1, "hypothesis_id": 5, "hypothesis": hypothesis, "confidence_level": "moderate", "significant": True,
         "statement": "", "title": "Spearman", "result": _result("Spearman correlation", 0.002, "reject_null")},
    ]
    rqs = [{"id": 1, "code": "RQ1", "text": "Is social media use related to GPA?"}]
    text = evidence.draft_conclusions(findings, rqs, {}, {"gpa": "GPA"})[0]["text"]
    assert text.count("HYPOTHESIS VERDICT:") == 1 and text.count("RECOMMENDATION 1:") == 1
    assert text.count("DIRECT ANSWER TO THE RESEARCH QUESTION:") == 1
    assert "A further test on this hypothesis was run" in text


def test_earlier_automatic_conclusions_are_replaced_and_the_researchers_own_text_is_kept(client):
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "earlier-text@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)
    plans = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    _wait_for_runs(client, h, {"items": [{"run": {"id": p["run_id"]}} for p in plans["plans"] if p["run_id"]]})
    with SessionLocal() as db:
        # rows as an earlier version wrote them, and as they were marked when they had no record
        db.query(Conclusion).filter(Conclusion.project_id == pid).delete()
        db.add(Conclusion(project_id=pid, text="RQ1: Is there a link? Answer: Yes. The analysis used a correlation test.", source="manual", position=0))
        db.add(Conclusion(project_id=pid, text="My own words about the study.", source="manual", position=1))
        db.commit()
    _post(client, f"/api/projects/{pid}/evidence/auto", h, {"regenerate": True})
    texts = [c["text"] for c in client.get(f"/api/projects/{pid}/conclusions", headers=h).json()["conclusions"]]
    assert not any("Answer: Yes. The analysis used" in t for t in texts)      # the earlier draft is gone
    assert "My own words about the study." in texts                          # the researcher's own text is kept


def test_the_charts_belong_to_the_findings_not_the_conclusions(client):
    from tests.test_conclusion_report import _setup_with_analysis as _report_content_with_analysis
    content, images = _report_content_with_analysis(client, "finding-charts@example.org")
    review_charts = [r["chart"] for r in content["review_findings"] if r.get("chart")]
    assert review_charts, "no finding received a chart"
    assert all(chart["image_key"] in images and images[chart["image_key"]][:4] == b"\x89PNG" for chart in review_charts)
    assert all(c.get("chart") is None for c in content["conclusions"])


