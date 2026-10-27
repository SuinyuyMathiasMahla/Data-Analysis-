"""Workflow steps 9 and 10: findings, conclusions and recommendations built automatically."""
import json
import time

from app.ai.providers import AIProvider
from app.ai.service import AIService
from app.services import ai_runtime

from tests.conftest import auth_headers
from tests.test_auto_analysis import _post, _setup


class Routed(AIProvider):
    """Answers each kind of request in the shape the service expects, and cites real finding ids from the context."""
    name = "routed"

    def __init__(self):
        super().__init__(model="routed-1")

    def complete(self, system, messages, max_tokens=1200):
        prompt = messages[-1]["content"]
        context = json.loads(prompt.split("TASK:")[0].replace("CONTEXT (JSON):", "").strip())
        if "Rewrite it for a reader" in prompt:
            return json.dumps({"title": "Plain title", "what_was_tested": "We compared two groups.", "what_we_found": "The groups differed.",
                               "what_it_means": "The difference matters in practice.", "how_sure": "The evidence is moderate."})
        if "Write ONE conclusion" in prompt:
            return json.dumps({"text": "The evidence supports a difference between the groups."})
        if "Write practical recommendations" in prompt:
            ids = [f["id"] for f in context["focus"]["findings"]]
            return json.dumps({"items": [{"text": "Follow up the difference with a larger sample.", "finding_ids": ids[:1]}]})
        return "{}"


def _wait(client, headers, run_ids):
    for run_id in run_ids:
        for _ in range(120):
            status = client.get(f"/api/analysis/{run_id}", headers=headers).json()["status"]
            if status in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.25)


def test_findings_conclusions_and_recommendations_are_built_once_and_kept(client):
    ai_runtime.set_ai_service(AIService(Routed()))
    h = auth_headers(client, "evidence@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)
    plans = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    _wait(client, h, [p["run_id"] for p in plans["plans"] if p["run_id"]])

    first = _post(client, f"/api/projects/{pid}/evidence/auto", h, {})
    assert first["findings_created"] >= 1 and first["conclusions"] >= 1 and first["recommendations"] >= 1
    findings = client.get(f"/api/projects/{pid}/findings", headers=h).json()["findings"]
    for finding in findings:
        assert finding["source"] == "ai" and finding["title"] == "Plain title"
        assert set(finding["breakdown"]) == {"title", "what_was_tested", "what_we_found", "what_it_means", "how_sure"}
        assert all(finding["breakdown"][k] for k in finding["breakdown"])
    conclusions = client.get(f"/api/projects/{pid}/conclusions", headers=h).json()["conclusions"]
    answered = [c for c in conclusions if c["finding_ids"]]
    # conclusions are written by the platform in the required layout, whether or not the AI is available
    assert answered and all(c["source"] == "engine" and "DIRECT ANSWER TO THE RESEARCH QUESTION:" in c["text"] for c in answered)
    assert all(c["source"] == "engine" and "could not be answered by the analysis yet" in c["text"]
               for c in conclusions if not c["finding_ids"])
    assert all(isinstance(f["charts"], list) for f in findings)
    assert any(f["charts"] for f in findings)
    assert any(c["chart"] for c in conclusions)
    recommendations = client.get(f"/api/projects/{pid}/recommendations", headers=h).json()["recommendations"]
    assert recommendations and all(r["finding_ids"] for r in recommendations)

    # a second visit adds nothing and does not duplicate anything
    again = _post(client, f"/api/projects/{pid}/evidence/auto", h, {})
    assert again["findings_created"] == 0 and again["conclusions"] == 0 and again["recommendations"] == 0
    assert len(client.get(f"/api/projects/{pid}/conclusions", headers=h).json()["conclusions"]) == len(conclusions)

    # the researcher's edits survive, and regenerating replaces only the automatic conclusions
    edited = findings[0]
    client.put(f"/api/findings/{edited['id']}", headers=h, json={"statement": "My own wording of the result."})
    regenerated = _post(client, f"/api/projects/{pid}/evidence/auto", h, {"regenerate": True})
    assert regenerated["conclusions"] >= 1
    assert len(client.get(f"/api/projects/{pid}/conclusions", headers=h).json()["conclusions"]) == len(conclusions)
    kept = next(f for f in client.get(f"/api/projects/{pid}/findings", headers=h).json()["findings"] if f["id"] == edited["id"])
    assert kept["statement"] == "My own wording of the result." and kept["is_edited"] is True
    ai_runtime.set_ai_service(None)


def test_without_an_ai_provider_the_engine_wording_is_used(client):
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "noai-evidence@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)
    plans = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    _wait(client, h, [p["run_id"] for p in plans["plans"] if p["run_id"]])

    summary = _post(client, f"/api/projects/{pid}/evidence/auto", h, {})
    assert summary["findings_created"] >= 1
    findings = client.get(f"/api/projects/{pid}/findings", headers=h).json()["findings"]
    assert all(f["source"] == "engine" and f["breakdown"]["what_was_tested"] for f in findings)
    conclusions = client.get(f"/api/projects/{pid}/conclusions", headers=h).json()["conclusions"]
    assert all(c["source"] == "engine" for c in conclusions)


def test_an_edited_conclusion_is_kept_when_the_analysis_changes(client):
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "edit-conclusion@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)
    plans = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    _wait(client, h, [p["run_id"] for p in plans["plans"] if p["run_id"]])
    _post(client, f"/api/projects/{pid}/evidence/auto", h, {})
    conclusions = client.get(f"/api/projects/{pid}/conclusions", headers=h).json()["conclusions"]
    mine = conclusions[0]
    edited = client.put(f"/api/conclusions/{mine['id']}", headers=h, json={"text": "My own answer to the question.", "finding_ids": mine["finding_ids"]})
    assert edited.status_code == 200 and edited.json()["source"] == "manual"
    # a new analysis run changes the basis, so automatic conclusions are rewritten, but the researcher's stays
    _post(client, f"/api/projects/{pid}/evidence/auto", h, {"regenerate": True})
    texts = [c["text"] for c in client.get(f"/api/projects/{pid}/conclusions", headers=h).json()["conclusions"]]
    assert "My own answer to the question." in texts


class OutcomeMapper(AIProvider):
    """Identifies the outcome and predictors from the dataset's variable names, as the real provider would."""
    name = "outcome-mapper"

    def __init__(self):
        super().__init__(model="mapper-1")

    def complete(self, system, messages, max_tokens=1200):
        prompt = messages[-1]["content"]
        if "dataset_variables" in prompt:
            return json.dumps({"dependent": "gpa", "independent": ["social_media_hours"]})
        return "{}"


class Unreachable(AIProvider):
    name = "unreachable"

    def __init__(self):
        super().__init__(model="down-1")

    def complete(self, system, messages, max_tokens=1200):
        from app.ai.providers import AIUnavailableError
        raise AIUnavailableError("connection timed out")


def _question_without_outcome(client, h, pid, did):
    """A question with an independent variable only, so the planner has no outcome for it."""
    variables = {v["name"]: v["id"] for v in client.get(f"/api/datasets/{did}/dictionary", headers=h).json()["variables"]}
    return _post(client, f"/api/projects/{pid}/research-questions", h, {
        "text": "Which factors predict GPA?", "variables": [{"variable_id": variables["social_media_hours"], "role": "independent"}]})


def _status_item(client, h, pid, did, question_id):
    overview = client.get(f"/api/projects/{pid}/ai/automatic-analysis", headers=h, params={"dataset_id": did}).json()
    return next(i for i in overview["items"] if i["research_question"] and i["research_question"]["id"] == question_id)


def test_status_page_asks_the_ai_for_the_outcome_and_saves_it(client):
    from tests.test_auto_analysis import _setup as setup_auto
    ai_runtime.set_ai_service(AIService(OutcomeMapper()))
    h = auth_headers(client, "page-map@example.org")
    pid, did, rq1, rq2, h1 = setup_auto(client, h)
    rq3 = _question_without_outcome(client, h, pid, did)

    item = _status_item(client, h, pid, did, rq3["id"])
    assert item["status"] == "not_run" and "no dependent" not in (item["reason"] or "")
    saved = next(q for q in client.get(f"/api/projects/{pid}/research-questions", headers=h).json()["research_questions"] if q["id"] == rq3["id"])
    assert {"name": "gpa", "role": "dependent"} in [{"name": v["name"], "role": v["role"]} for v in saved["variables"]]
    ai_runtime.set_ai_service(None)


def test_every_question_gets_a_conclusion_even_without_a_dataset(client):
    from tests.conftest import make_project
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "no-data-conclusions@example.org")
    pid = make_project(client, h)["id"]
    for text in ("Is social media use related to GPA?", "Does GPA differ by gender?"):
        _post(client, f"/api/projects/{pid}/research-questions", h, {"text": text})

    summary = _post(client, f"/api/projects/{pid}/evidence/auto", h, {})
    assert summary["conclusions"] == 2 and summary["findings_created"] == 0
    conclusions = client.get(f"/api/projects/{pid}/conclusions", headers=h).json()["conclusions"]
    assert len(conclusions) == 2
    assert all("could not be answered by the analysis yet" in c["text"] and "No dataset has been analysed yet." in c["text"] for c in conclusions)


def test_an_edit_made_before_source_tracking_survives_a_regeneration(client):
    from app.database.session import SessionLocal
    from app.models import Conclusion
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "legacy-edit@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)
    plans = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    _wait(client, h, [p["run_id"] for p in plans["plans"] if p["run_id"]])
    _post(client, f"/api/projects/{pid}/evidence/auto", h, {})

    # an edit made directly, the way it was saved before edits flipped the source to 'manual'
    with SessionLocal() as db:
        first = db.query(Conclusion).filter(Conclusion.project_id == pid).order_by(Conclusion.id).first()
        first.text = "My own answer, written before the source tracking existed."
        db.commit()

    _post(client, f"/api/projects/{pid}/evidence/auto", h, {"regenerate": True})
    texts = [c["text"] for c in client.get(f"/api/projects/{pid}/conclusions", headers=h).json()["conclusions"]]
    assert "My own answer, written before the source tracking existed." in texts


def test_interleaved_state_updates_do_not_overwrite_each_other(client):
    import threading
    from app.services import evidence_state
    from app.services.storage import get_storage
    project_id = 987654
    get_storage().delete(evidence_state.storage_key(project_id))
    keys = [f"writer-{i}" for i in range(40)]
    threads = [threading.Thread(target=evidence_state.merge, args=(project_id, {key: i})) for i, key in enumerate(keys)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    state = evidence_state.get(project_id)
    assert all(state.get(key) == i for i, key in enumerate(keys))          # every update survived
    get_storage().delete(evidence_state.storage_key(project_id))


def test_plain_conclusions_follow_the_required_layout(client):
    from app.analysis import evidence
    supported = {"id": 1, "code": "F1", "research_question_id": 1, "confidence_level": "moderate", "significant": True, "statement": "",
                 "hypothesis": {"code": "H1", "null_text": "There is no relationship between social media use and GPA.",
                                "alternative_text": "Daily social media use is linked to lower GPA.", "direction": "non_directional"},
                 "result": {"method": "pearson", "method_name": "Pearson correlation", "apa": "r(98) = -0.41, p < .001", "n": 100,
                            "p_value": 0.0004, "alpha": 0.05, "decision": "reject_null", "variables": {"x": "social_media_hours", "y": "gpa"},
                            "statistic": {"name": "t", "value": -4.5}, "df": 98, "assumptions": [],
                            "effect_sizes": [{"name": "Pearson correlation coefficient (r)", "value": -0.41, "ci_low": -0.56, "ci_high": -0.23,
                                              "magnitude": "moderate"}]}}
    not_supported = {"id": 2, "code": "F2", "research_question_id": 2, "confidence_level": "low", "significant": False, "statement": "No difference.",
                     "hypothesis": None,
                     "result": {"method": "kruskal_wallis", "method_name": "Kruskal-Wallis H test", "apa": "H(2) = 1.20, p = .549", "n": 90,
                                "p_value": 0.549, "alpha": 0.05, "decision": "fail_to_reject_null", "variables": {"outcome": "gpa", "group": "gender"},
                                "statistic": {"name": "H", "value": 1.2}, "df": 2, "assumptions": [], "effect_sizes": []}}
    questions = [{"id": 1, "code": "RQ1", "text": "Is social media use related to GPA?"},
                 {"id": 2, "code": "RQ2", "text": "Does GPA differ by gender?"},
                 {"id": 3, "code": "RQ3", "text": "Which factors predict GPA?"}]
    labels = {"gpa": "Grade point average (GPA)", "social_media_hours": "Daily social media hours", "gender": "Gender"}
    drafts = evidence.draft_conclusions([supported, not_supported], questions, {3: ["Hypothesis H3 was not analysed: no predictor."]}, labels)
    assert [d["research_question_id"] for d in drafts] == [1, 2, 3]
    rq1, rq2, rq3 = (d["text"] for d in drafts)

    # the standard layout, in order: verdict, summary, direct answer, strength, limitation, recommendation
    order = ["CONCLUSION 1 — Research Question RQ1: Is social media use related to GPA?", "HYPOTHESIS VERDICT:", "SUMMARY OF EVIDENCE:",
             "DIRECT ANSWER TO THE RESEARCH QUESTION:", "STRENGTH OF EVIDENCE:", "LIMITATION FOR THIS CONCLUSION:", "RECOMMENDATION 1:"]
    positions = [rq1.index(part) for part in order]
    assert positions == sorted(positions)
    assert "H1 — H0 (Null Hypothesis): Rejected. H1 (Alternative Hypothesis): Accepted." in rq1
    assert rq1.split("DIRECT ANSWER TO THE RESEARCH QUESTION:\n")[1].startswith("Yes.")
    assert "These results describe a correlation" in rq1 and "does not establish that one causes the other" in rq1
    assert rq2.split("DIRECT ANSWER TO THE RESEARCH QUESTION:\n")[1].startswith("No.")
    assert "H2" not in rq2 and "Accepted" in rq2
    assert rq3.startswith("CONCLUSION 3 — Research Question RQ3: Which factors predict GPA?")
    assert "could not be answered by the analysis yet" in rq3


def test_status_page_explains_when_no_variables_can_be_chosen(client, monkeypatch):
    from tests.test_auto_analysis import _setup as setup_auto
    monkeypatch.setattr("app.ai.service.time.sleep", lambda seconds: None)
    monkeypatch.setattr("app.services.auto_analysis.variable_choice.choose_variables",
                        lambda question, rows, dependent=None: {"dependent": None, "independent": [], "matched": [], "basis": "nothing"})
    ai_runtime.set_ai_service(AIService(Unreachable()))
    h = auth_headers(client, "page-fail@example.org")
    pid, did, rq1, rq2, h1 = setup_auto(client, h)
    rq3 = _question_without_outcome(client, h, pid, did)
    item = _status_item(client, h, pid, did, rq3["id"])
    assert item["status"] == "skipped"
    assert "could not identify the outcome variable" in item["reason"] and "could not answer" in item["reason"]
    ai_runtime.set_ai_service(None)


def test_status_page_chooses_variables_itself_when_the_ai_is_turned_off(client):
    from tests.test_auto_analysis import _setup as setup_auto
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "page-off@example.org")
    pid, did, rq1, rq2, h1 = setup_auto(client, h)
    rq3 = _question_without_outcome(client, h, pid, did)
    item = _status_item(client, h, pid, did, rq3["id"])
    assert item["status"] == "not_run" and item["variables_source"] == "rules"
    saved = next(q for q in client.get(f"/api/projects/{pid}/research-questions", headers=h).json()["research_questions"] if q["id"] == rq3["id"])
    assert any(v["role"] == "dependent" for v in saved["variables"])


def test_recommendations_follow_the_findings_and_keep_the_researchers_edits(client):
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "recs-refresh@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)
    plans = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    _wait(client, h, [p["run_id"] for p in plans["plans"] if p["run_id"]])
    _post(client, f"/api/projects/{pid}/evidence/auto", h, {})
    recs = client.get(f"/api/projects/{pid}/recommendations", headers=h).json()["recommendations"]
    assert recs and all(r["source"] == "engine" and r["text"].startswith("RECOMMENDATION") for r in recs)

    # the researcher marks a finding's evidence as weak: the recommendation changes to say so, without duplicates
    finding = client.get(f"/api/projects/{pid}/findings", headers=h).json()["findings"][0]
    client.put(f"/api/findings/{finding['id']}", headers=h, json={"confidence_level": "low"})
    _post(client, f"/api/projects/{pid}/evidence/auto", h, {})
    refreshed = client.get(f"/api/projects/{pid}/recommendations", headers=h).json()["recommendations"]
    assert len(refreshed) == len(recs) and all(r["text"].startswith("RECOMMENDATION") for r in refreshed)

    # the researcher edits one; a later change to the findings must not replace it
    mine = refreshed[0]
    client.put(f"/api/recommendations/{mine['id']}", headers=h, json={"text": "My own recommendation.", "finding_ids": mine["finding_ids"]})
    client.put(f"/api/findings/{finding['id']}", headers=h, json={"confidence_level": "moderate"})
    _post(client, f"/api/projects/{pid}/evidence/auto", h, {})
    texts = [r["text"] for r in client.get(f"/api/projects/{pid}/recommendations", headers=h).json()["recommendations"]]
    assert "My own recommendation." in texts
