"""Automatic planning: variables and tests per research question and hypothesis, AI choice guarded to the engine's candidates."""
from app.ai.providers import AIProvider
from app.ai.service import AIService
from app.services import ai_runtime

from tests.conftest import auth_headers, make_project, upload_sample


def _post(client, url, headers, json=None, expected=(200, 201, 202)):
    response = client.post(url, json=json or {}, headers=headers)
    assert response.status_code in expected, f"{url}: {response.status_code} {response.text[:400]}"
    return response.json()


class Scripted(AIProvider):
    """Returns a fixed reply, so the test controls what the 'AI' chooses."""
    name = "scripted"

    def __init__(self, reply: str):
        super().__init__(model="scripted-1")
        self.reply = reply

    def complete(self, system, messages, max_tokens=1200):
        return self.reply


def _setup(client, h):
    pid = make_project(client, h)["id"]
    dataset = upload_sample(client, h, pid)
    did = dataset["id"]
    variables = {v["name"]: v["id"] for v in client.get(f"/api/datasets/{did}/dictionary", headers=h).json()["variables"]}
    rq1 = _post(client, f"/api/projects/{pid}/research-questions", h, {
        "text": "Is daily social media use related to GPA?",
        "variables": [{"variable_id": variables["gpa"], "role": "dependent"}, {"variable_id": variables["social_media_hours"], "role": "independent"}]})
    rq2 = _post(client, f"/api/projects/{pid}/research-questions", h, {
        "text": "Does GPA differ by gender?",
        "variables": [{"variable_id": variables["gpa"], "role": "dependent"}, {"variable_id": variables["gender"], "role": "independent"}]})
    h1 = _post(client, f"/api/projects/{pid}/hypotheses", h, {
        "research_question_id": rq1["id"], "null_text": "No relationship.", "alternative_text": "A relationship exists."})
    return pid, did, rq1, rq2, h1


def test_auto_analysis_runs_every_question_and_hypothesis(client):
    ai_runtime.set_ai_service(None)                       # rule engine only
    h = auth_headers(client, "auto@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)

    result = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    plans = {(p["research_question_id"], p["hypothesis_id"]): p for p in result["plans"]}

    # RQ1 has a hypothesis, so it is planned through H1; RQ2 has none, so it is planned on its own
    assert (rq1["id"], h1["id"]) in plans and (rq2["id"], None) in plans
    assert plans[(rq1["id"], h1["id"])]["status"] == "ready"
    assert plans[(rq1["id"], h1["id"])]["variables"]                        # the engine's role assignment is used
    assert plans[(rq1["id"], h1["id"])]["justification"]                    # every run carries a reason for the methods section
    assert result["summary"]["ready"] >= 2

    runs = [p["run_id"] for p in result["plans"] if p["status"] == "ready"]
    for run_id in runs:
        run = client.get(f"/api/analysis/{run_id}", headers=h).json()
        assert run["status"] in ("PENDING", "PROCESSING", "COMPLETED", "FAILED")
        assert run["config"]["hypothesis_id"] in (None, h1["id"])
    assert len(runs) == len(set(runs))


def test_ai_choice_is_used_only_when_it_is_one_of_the_engine_candidates(client):
    h = auth_headers(client, "choice@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)

    # 1. the AI picks a method that the engine did not offer: rejected, the engine's choice is kept
    ai_runtime.set_ai_service(AIService(Scripted('{"method": "not_a_real_method", "reason": "Because."}')))
    rejected = _post(client, f"/api/projects/{pid}/ai/plan", h, {"research_question_id": rq1["id"]})
    assert rejected["source"] == "rule_engine" and rejected["notice"]
    rule_method = rejected["method"]

    # 2. the AI picks the rule engine's own candidate and writes a reason: accepted
    ai_runtime.set_ai_service(AIService(Scripted(f'```json\n{{"method": "{rule_method}", "reason": "It fits a numeric outcome and predictor."}}\n```')))
    accepted = _post(client, f"/api/projects/{pid}/ai/plan", h, {"research_question_id": rq1["id"]})
    assert accepted["source"] == "llm" and accepted["method"] == rule_method
    assert accepted["justification"] == "It fits a numeric outcome and predictor."

    ai_runtime.set_ai_service(None)


def test_plan_requires_a_question_or_hypothesis(client):
    h = auth_headers(client, "noselect@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)
    response = client.post(f"/api/projects/{pid}/ai/plan", json={"dataset_id": did}, headers=h)
    assert response.status_code == 400




def test_second_automatic_run_does_not_duplicate_analyses(client):
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "dupe@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)

    first = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    started = {p["research_question_id"]: p["run_id"] for p in first["plans"] if p["status"] == "ready"}
    assert len(started) == 2

    # every earlier run is respected: completed ones are not repeated, failed ones are not retried silently
    second = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    assert second["summary"]["ready"] == 0
    for plan in second["plans"]:
        assert plan["status"] == "skipped" and plan["run_id"] == started[plan["research_question_id"]]
        assert plan["reason"].startswith("Already")

    third = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did, "rerun": True})
    assert third["summary"]["ready"] == 2


def test_overview_lists_every_item_with_its_run_or_reason(client):
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "overview@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)

    before = client.get(f"/api/projects/{pid}/ai/automatic-analysis", headers=h, params={"dataset_id": did}).json()
    assert len(before["items"]) == 2 and all(i["status"] == "not_run" for i in before["items"])

    _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    overview = client.get(f"/api/projects/{pid}/ai/automatic-analysis", headers=h, params={"dataset_id": did}).json()
    by_rq = {i["research_question"]["id"]: i for i in overview["items"]}
    assert by_rq[rq1["id"]]["hypothesis"]["id"] == h1["id"]
    for item in overview["items"]:
        assert item["status"] in ("running", "completed", "failed")
        assert item["run"] is not None and item["reason"] and item["reason_source"] == "rule_engine"
        assert item["run"]["results"] is not None or item["status"] != "completed"


def test_variables_missing_from_a_question_are_identified_and_saved(client):
    h = auth_headers(client, "mapping@example.org")
    pid = make_project(client, h)["id"]
    did = upload_sample(client, h, pid)["id"]
    rq = _post(client, f"/api/projects/{pid}/research-questions", h, {"text": "Does weekly study time differ by gender?"})

    ai_runtime.set_ai_service(AIService(Scripted('{"dependent": "study_hours", "independent": ["gender", "not_a_column"]}')))
    result = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    plan = next(p for p in result["plans"] if p["research_question_id"] == rq["id"])
    assert plan["status"] == "ready" and plan["outcome"] == "study_hours" and plan["predictors"] == ["gender"]

    saved = client.get(f"/api/projects/{pid}/research-questions", headers=h).json()["research_questions"]
    linked = {v["name"]: v["role"] for q in saved if q["id"] == rq["id"] for v in q["variables"]}
    assert linked == {"study_hours": "dependent", "gender": "independent"}
    overview = client.get(f"/api/projects/{pid}/ai/automatic-analysis", headers=h, params={"dataset_id": did}).json()
    item = next(i for i in overview["items"] if i["research_question"]["id"] == rq["id"])
    assert item["variables_source"] == "ai"
    ai_runtime.set_ai_service(None)


def test_a_new_dataset_version_is_analysed_again_not_skipped(client):
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "newversion@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)
    first = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    old_runs = {p["research_question_id"]: p["run_id"] for p in first["plans"] if p["status"] == "ready"}
    assert len(old_runs) == 2

    # the data changes: a new working version is current
    _post(client, f"/api/datasets/{did}/clean", h, {"operation": "remove_duplicates", "params": {}, "reason": "Exact duplicate rows removed"})

    again = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    assert again["summary"]["ready"] == 2, again["summary"]
    new_runs = {p["research_question_id"]: p["run_id"] for p in again["plans"] if p["status"] == "ready"}
    assert all(new_runs[q] != old_runs[q] for q in old_runs)
    overview = client.get(f"/api/projects/{pid}/ai/automatic-analysis?dataset_id={did}", headers=h).json()
    statuses = {i["research_question"]["id"]: i["status"] for i in overview["items"] if i["research_question"]}
    # the new version was analysed: its runs exist and have a status (the gender test may fail on the still-inconsistent spelling,
    # which the engine reports with a reason)
    assert statuses[rq1["id"]] == "completed" and statuses[rq2["id"]] in ("completed", "failed")


def test_a_question_without_matching_variables_is_still_analysed_and_the_choice_is_explained(client):
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "skip@example.org")
    pid = make_project(client, h)["id"]
    upload_sample(client, h, pid)
    rq = _post(client, f"/api/projects/{pid}/research-questions", h, {"text": "A question with no variables linked yet?"})
    result = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {})
    plan = next(p for p in result["plans"] if p["research_question_id"] == rq["id"])
    # nothing in the wording matches a variable, so the platform picks one itself and says so
    assert plan["status"] == "ready" and plan["variables_source"] == "rules"
    assert "no variable name matches" in plan["variables_basis"]
    saved = client.get(f"/api/projects/{pid}/research-questions", headers=h).json()["research_questions"]
    assert any(v["role"] == "dependent" for v in next(q for q in saved if q["id"] == rq["id"])["variables"])


def test_an_outcome_the_ai_cannot_name_is_chosen_from_the_wording(client):
    h = auth_headers(client, "nomap@example.org")
    pid = make_project(client, h)["id"]
    did = upload_sample(client, h, pid)["id"]
    rq = _post(client, f"/api/projects/{pid}/research-questions", h, {"text": "Is the weather related to happiness?"})

    ai_runtime.set_ai_service(AIService(Scripted('{"dependent": null, "independent": []}')))
    result = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    plan = next(p for p in result["plans"] if p["research_question_id"] == rq["id"])
    assert plan["status"] == "ready" and plan["variables_source"] == "rules"
    saved = client.get(f"/api/projects/{pid}/research-questions", headers=h).json()["research_questions"]
    assert any(v["role"] == "dependent" for v in next(q for q in saved if q["id"] == rq["id"])["variables"])
    ai_runtime.set_ai_service(None)
