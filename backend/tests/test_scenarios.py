"""Scenario tests for the assistant: a dirty dataset is flagged, blocks cleaning until fixed, and blocks the report while any problem
remains. Each dirty value is one the step checks must name."""
import io
import random

from tests.conftest import auth_headers, make_project


def _dirty_csv() -> bytes:
    rng = random.Random(7)
    lines = ["student_id,gender,bmi,gpa,study_hours"]
    for i in range(1, 61):
        gender = ["Male", "male ", "M", "Female", "female", "F"][i % 6]     # inconsistent coding of one category
        bmi = 999 if i in (3, 17, 42) else round(rng.uniform(18, 32), 1)    # 999 is a missing-value code, not a BMI
        gpa = round(rng.uniform(1.5, 4.0), 2)
        hours = round(rng.uniform(0, 30), 1)
        lines.append(f"S{i:03d},{gender},{bmi},{gpa},{hours}")
    lines.append(lines[1])                                                 # one exact duplicate row
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_dirty_dataset_is_flagged_blocks_cleaning_and_blocks_the_report(client):
    h = auth_headers(client, "scenario@example.org", "Scenario Tester")
    pid = make_project(client, h)["id"]
    upload = client.post(f"/api/projects/{pid}/datasets", headers=h,
                         files={"file": ("dirty.csv", io.BytesIO(_dirty_csv()), "text/csv")}, data={"name": "Dirty survey"})
    assert upload.status_code == 201, upload.text
    did = upload.json()["id"]

    # step 5: the quality check names each problem
    quality = client.get(f"/api/datasets/{did}/quality-report", headers=h).json()
    codes = {i["code"] for i in quality["issues"]}
    assert {"duplicate_rows", "inconsistent_category"} <= codes
    assert "suspicious_code" in codes or "impossible_value" in codes      # the 999 BMI codes are flagged
    check = client.get(f"/api/projects/{pid}/steps/quality/check?dataset_id={did}", headers=h).json()
    blocking = {i["code"] for i in check["blocking"]}
    assert "inconsistent_category" in blocking and "duplicate_rows" not in blocking
    assert any(w["code"] == "duplicate_rows" for w in check["warnings"])

    # step 12: the assistant's pass cleans the serious problems itself, then the package builds
    built = client.post(f"/api/projects/{pid}/client-package", json={"dataset_id": did, "references": ["A. (2020). B."]}, headers=h)
    assert built.status_code == 200, built.text[:300]
    history = client.get(f"/api/datasets/{did}/cleaning-history", headers=h).json()["operations"]
    assert any(op["reason"].startswith("Automatic") for op in history)


def test_fixing_each_problem_with_a_reason_clears_the_blocks(client):
    h = auth_headers(client, "fix@example.org", "Fix Tester")
    pid = make_project(client, h)["id"]
    did = client.post(f"/api/projects/{pid}/datasets", headers=h,
                      files={"file": ("dirty.csv", io.BytesIO(_dirty_csv()), "text/csv")}, data={"name": "Dirty survey"}).json()["id"]

    def clean(operation, params, reason):
        response = client.post(f"/api/datasets/{did}/clean", json={"operation": operation, "params": params, "reason": reason}, headers=h)
        assert response.status_code in (200, 201), response.text

    clean("remove_duplicates", {}, "One exact duplicate submission of S001 found in the file.")
    clean("standardize_categories", {"column": "gender", "case": "title", "strip": True},
          "Trailing spaces and lower case variants of the same answer were counted as separate groups.")
    clean("replace_values", {"column": "gender", "mapping": {"M": "Male", "F": "Female"}},
          "Single-letter codes M and F are the same answers as Male and Female.")
    clean("remove_invalid", {"column": "bmi", "min": 10, "max": 60, "action": "set_missing"},
          "999 is a missing-value code; a BMI of 999 is impossible, so it is set to missing.")

    check = client.get(f"/api/projects/{pid}/steps/cleaning/check?dataset_id={did}", headers=h).json()
    assert check["blocking"] == [], check["blocking"]
    refused = client.post(f"/api/projects/{pid}/client-package", json={"dataset_id": did, "references": ["A. (2020). B."]}, headers=h)
    assert refused.status_code == 200, refused.text[:300]


def test_auto_clean_reaches_100_with_a_reason_for_every_decision(client):
    h = auth_headers(client, "auto@example.org", "Auto Tester")
    pid = make_project(client, h)["id"]
    did = client.post(f"/api/projects/{pid}/datasets", headers=h,
                      files={"file": ("dirty.csv", io.BytesIO(_dirty_csv()), "text/csv")}, data={"name": "Dirty survey"}).json()["id"]
    before = client.get(f"/api/datasets/{did}/quality-report", headers=h).json()["score"]

    body = client.post(f"/api/datasets/{did}/auto-clean", headers=h).json()
    assert body["score_before"] == before and body["score_after"] == 100.0, body
    assert all(step["reason"] for step in body["applied"] + body["decisions"])
    assert all(d["source"] in ("rules", "ai_assistant") for d in body["decisions"])
    assert {d["action"] for d in body["decisions"]} <= {"impute_median", "impute_mode", "delete_records", "drop_column"}
    assert body["rows_after"] <= body["rows_before"]

    log = client.get(f"/api/datasets/{did}/auto-decisions", headers=h).json()["decisions"]
    assert len(log) == len(body["decisions"]) and not any(d["undone"] for d in log)


def test_flagged_decisions_can_be_undone_and_the_earlier_version_comes_back(client):
    h = auth_headers(client, "undo@example.org", "Undo Tester")
    pid = make_project(client, h)["id"]
    did = client.post(f"/api/projects/{pid}/datasets", headers=h,
                      files={"file": ("dirty.csv", io.BytesIO(_dirty_csv()), "text/csv")}, data={"name": "Dirty survey"}).json()["id"]
    client.post(f"/api/datasets/{did}/auto-clean", headers=h)
    log = client.get(f"/api/datasets/{did}/auto-decisions", headers=h).json()["decisions"]
    flagged = [d for d in log if d["affects_results"]]
    if not flagged:                                   # every decision in this file touched at most 5% of records
        flagged = log
    target = flagged[-1]
    rows_before_undo = client.get(f"/api/datasets/{did}/preview?limit=1", headers=h).json()["total_rows"]
    response = client.post(f"/api/datasets/{did}/auto-decisions/{target['decision_id']}/undo", headers=h)
    assert response.status_code == 200, response.text
    after = {d["decision_id"]: d for d in response.json()["decisions"]}
    assert after[target["decision_id"]]["undone"] is True
    assert client.post(f"/api/datasets/{did}/auto-decisions/{target['decision_id']}/undo", headers=h).status_code == 400
    assert client.get(f"/api/datasets/{did}/preview?limit=1", headers=h).json()["total_rows"] >= rows_before_undo


def test_ai_answer_is_used_only_when_it_suits_the_column():
    from app.services.dataset_service import _accepted, _rule_decision

    fact = {"column": "bmi", "missing": 3, "missing_pct": 1.7, "type": "numeric", "role": "other", "rows": 180,
            "allowed": ["impute_median", "delete_records", "drop_column"]}
    assert _accepted(fact, {"action": "impute_median", "reason": "Few values missing."})["source"] == "ai_assistant"
    assert _accepted(fact, {"action": "impute_mode", "reason": "x"}) is None          # not an allowed option for a numeric column
    assert _accepted(fact, {"action": "impute_median", "reason": ""}) is None          # no reason given
    assert _accepted(fact, {"action": "impute_median"}) is None
    assert _rule_decision(fact)["action"] == "impute_median"
    assert _rule_decision({**fact, "missing_pct": 35.0})["action"] == "drop_column"


def test_the_ai_assistant_decides_a_column_when_it_is_configured(client):
    import json as _json
    from app.ai import providers
    from app.ai.service import AIService
    from app.services.ai_runtime import set_ai_service

    class _ModelReply(providers.AIProvider):
        name = "fake"

        def __init__(self, text):
            super().__init__(model="fake-model")
            self.text = text

        def complete(self, system, messages, max_tokens=1200):
            return self.text

    reply = {"decisions": [{"column": "bmi", "action": "delete_records", "reason": "Only a few records lack a BMI, so removing them keeps the sample."}]}
    set_ai_service(AIService(_ModelReply(_json.dumps(reply))))
    try:
        h = auth_headers(client, "llm@example.org", "Model Tester")
        pid = make_project(client, h)["id"]
        did = client.post(f"/api/projects/{pid}/datasets", headers=h,
                          files={"file": ("dirty.csv", io.BytesIO(_dirty_csv()), "text/csv")}, data={"name": "Dirty survey"}).json()["id"]
        body = client.post(f"/api/datasets/{did}/auto-clean", headers=h).json()
    finally:
        set_ai_service(None)
    bmi = [d for d in body["decisions"] if d["column"] == "bmi"]
    assert bmi and bmi[0]["source"] == "ai_assistant" and bmi[0]["action"] == "delete_records"
    assert "Only a few records" in bmi[0]["reason"]
    assert body["score_after"] == 100.0


def test_open_issues_come_with_a_diagnosis_and_an_owner(client):
    h = auth_headers(client, "owner@example.org", "Owner Tester")
    pid = make_project(client, h)["id"]
    rq = client.post(f"/api/projects/{pid}/research-questions", json={"text": "Is study time related to GPA?"}, headers=h).json()
    client.post(f"/api/projects/{pid}/hypotheses", json={"research_question_id": rq["id"], "null_text": "No relationship.",
                                                         "alternative_text": "A relationship."}, headers=h)
    response = client.post(f"/api/projects/{pid}/client-package", json={"references": []}, headers=h)
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert isinstance(details["assistant_actions"], list)
    issues = {i["code"]: i for i in details["issues"]}
    assert issues["hypothesis_without_result"]["fixed_by"] == "you"              # no variables linked: only the researcher can decide
    assert issues["hypothesis_without_result"]["diagnosis"]
    assert all(i["diagnosis"] and i["fixed_by"] in ("assistant", "you") for i in details["issues"])
