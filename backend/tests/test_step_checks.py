"""Step checks: what blocks the user at the quality and analysis steps, and the assistant's decision log."""
from tests.conftest import auth_headers, make_project, upload_sample


def test_quality_step_blocks_on_serious_problems_and_warns_on_duplicates(client):
    h = auth_headers(client, "steps@example.org", "Step Tester")
    pid = make_project(client, h)["id"]
    upload_sample(client, h, pid)

    check = client.get(f"/api/projects/{pid}/steps/quality/check", headers=h).json()
    assert check["passed"] is False
    blocking = {i["code"] for i in check["blocking"]}
    assert {"impossible_value", "inconsistent_category"} <= blocking
    assert "duplicate_rows" not in blocking                       # duplicates are a warning, not a block
    assert any(w["code"] == "duplicate_rows" for w in check["warnings"])
    assert all(i["fix"] for i in check["blocking"] + check["warnings"])


def test_analysis_step_blocks_on_an_untested_primary_hypothesis(client):
    h = auth_headers(client, "analysis@example.org", "Analysis Tester")
    pid = make_project(client, h)["id"]
    rq = client.post(f"/api/projects/{pid}/research-questions", json={"text": "Is study time related to GPA?"}, headers=h).json()
    client.post(f"/api/projects/{pid}/hypotheses", json={"research_question_id": rq["id"], "null_text": "No relationship.",
                                                         "alternative_text": "A relationship."}, headers=h)
    check = client.get(f"/api/projects/{pid}/steps/analysis/check", headers=h).json()
    assert check["passed"] is False
    assert [i["code"] for i in check["blocking"]] == ["hypothesis_untested"]


def test_unknown_step_is_rejected_and_decisions_are_logged(client):
    h = auth_headers(client, "log@example.org", "Log Tester")
    pid = make_project(client, h)["id"]
    assert client.get(f"/api/projects/{pid}/steps/not-a-step/check", headers=h).status_code == 400

    logged = client.post(f"/api/projects/{pid}/assistant/decisions", headers=h,
                         json={"step": "quality", "kind": "suggestion", "text": "Remove the 3 duplicate rows."})
    assert logged.status_code == 201
    decision = client.post(f"/api/projects/{pid}/assistant/decisions", headers=h,
                           json={"step": "quality", "kind": "decision", "text": "Remove the 3 duplicate rows.", "decision": "accepted"})
    assert decision.status_code == 201
    history = client.get(f"/api/projects/{pid}/history?action=assistant", headers=h).json()["history"]
    actions = {(row["action"], (row.get("details") or {}).get("decision")) for row in history}
    assert ("assistant.suggestion", None) in actions and ("assistant.decision", "accepted") in actions


def test_every_wizard_stage_has_a_check_and_items_explain_themselves(client):
    h = auth_headers(client, "stages@example.org", "Stage Tester")
    pid = make_project(client, h)["id"]
    client.post(f"/api/projects/{pid}/research-questions", json={"text": "Is study time related to GPA?"}, headers=h)
    for stage in ("project", "research_questions", "hypotheses", "dataset", "quality", "cleaning", "exploration", "analysis",
                  "findings", "conclusions", "charts", "report"):
        response = client.get(f"/api/projects/{pid}/steps/{stage}/check", headers=h)
        assert response.status_code == 200, stage
        body = response.json()
        assert body["step"] == stage and body["level"] == "analyst" and isinstance(body["passed"], bool)
        assert all(item["why"] for item in body["blocking"] + body["warnings"])

    hypotheses = client.get(f"/api/projects/{pid}/steps/hypotheses/check", headers=h).json()
    assert [i["code"] for i in hypotheses["blocking"]] == ["rq_without_hypothesis"]
    conclusions = client.get(f"/api/projects/{pid}/steps/conclusions/check", headers=h).json()
    assert [i["code"] for i in conclusions["blocking"]] == ["no_conclusions"]


def test_level_selector_changes_the_explanation(client):
    h = auth_headers(client, "level@example.org", "Level Tester")
    pid = make_project(client, h)["id"]
    upload_sample(client, h, pid)
    student = client.get(f"/api/projects/{pid}/steps/quality/check?level=student", headers=h).json()
    expert = client.get(f"/api/projects/{pid}/steps/quality/check?level=expert", headers=h).json()
    assert student["level"] == "student" and expert["level"] == "expert"
    assert student["blocking"][0]["why"] != expert["blocking"][0]["why"]
    assert client.get(f"/api/projects/{pid}/steps/quality/check?level=wizard", headers=h).status_code == 400


def test_steps_summary_reports_locks(client):
    h = auth_headers(client, "summary@example.org", "Summary Tester")
    pid = make_project(client, h)["id"]
    rq = client.post(f"/api/projects/{pid}/research-questions", json={"text": "Is study time related to GPA?"}, headers=h).json()
    client.post(f"/api/projects/{pid}/hypotheses", json={"research_question_id": rq["id"], "null_text": "No.", "alternative_text": "Yes."}, headers=h)
    upload_sample(client, h, pid)
    summary = client.get(f"/api/projects/{pid}/steps/summary", headers=h).json()["stages"]
    assert summary["quality"]["blocking"] > 0 and summary["cleaning"]["blocking"] > 0
    assert "quality" in summary["analysis"]["locked_by"] and "analysis" not in summary["cleaning"]["locked_by"]
    # the lock follows the blocking counts exactly: findings are locked by analysis only while analysis is blocking
    assert summary["findings"]["locked_by"] == []                   # findings stay open while analyses are pending
    assert summary["report"]["locked_by"] == ["analysis"] if summary["analysis"]["blocking"] else True


def test_assistant_drafts_only_what_it_can_support_and_saves_nothing(client):
    h = auth_headers(client, "draft@example.org", "Draft Tester")
    pid = make_project(client, h)["id"]
    rq = client.post(f"/api/projects/{pid}/research-questions", json={"text": "Is study time related to GPA?"}, headers=h).json()
    before = client.get(f"/api/projects/{pid}/hypotheses", headers=h).json()
    asked = client.post(f"/api/projects/{pid}/assistant/draft", json={"kind": "hypothesis", "research_question_id": rq["id"]}, headers=h).json()
    assert asked["draft"] is None and asked["questions"]                  # no variables linked yet: it asks instead of guessing
    gaps = client.post(f"/api/projects/{pid}/assistant/draft", json={"kind": "project_gaps"}, headers=h).json()
    assert any("ethics" in q.lower() for q in gaps["questions"]) and gaps["draft"] is None
    after = client.get(f"/api/projects/{pid}/hypotheses", headers=h).json()
    assert before == after                                                 # a draft is never saved
