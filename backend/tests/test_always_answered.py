"""Every research question gets its variables chosen and a written answer, with or without the AI assistant."""
from app.analysis.variable_choice import choose_variables, needs_predictor
from app.services import ai_runtime

from tests.conftest import auth_headers, make_project, upload_sample
from tests.test_auto_analysis import _post

SAMPLE = [
    {"name": "student_id", "label": None, "data_type": "identifier", "role": "identifier"},
    {"name": "gender", "label": "Gender", "data_type": "categorical", "role": "other"},
    {"name": "social_media_hours", "label": "Daily social media hours", "data_type": "numeric", "role": "other"},
    {"name": "gpa", "label": "Grade point average", "data_type": "numeric", "role": "other"},
    {"name": "pre_test", "label": None, "data_type": "numeric", "role": "other"},
    {"name": "post_test", "label": None, "data_type": "numeric", "role": "other"},
]


def test_the_outcome_is_the_variable_named_after_relating_words():
    choice = choose_variables("Is social media use related to GPA?", SAMPLE)
    assert choice["dependent"] == "gpa" and choice["independent"] == ["social_media_hours"]
    assert "named after" in choice["basis"] or "names it after" in choice["basis"]


def test_a_comparison_takes_the_measured_variable_and_the_grouping_variable():
    choice = choose_variables("Does GPA differ by gender?", SAMPLE)
    assert choice["dependent"] == "gpa" and choice["independent"] == ["gender"]


def test_a_question_that_names_nothing_still_gets_an_outcome_and_the_choice_is_explained():
    choice = choose_variables("Is the weather related to happiness?", SAMPLE)
    assert choice["dependent"] is not None
    assert "no variable name matches" in choice["basis"] or "is the outcome" in choice["basis"]


def test_a_dataset_with_only_identifiers_is_reported_plainly():
    choice = choose_variables("Is anything related to anything?", [SAMPLE[0]])
    assert choice["dependent"] is None and "no variables that can be analysed" in choice["basis"]


def test_only_comparing_or_relating_questions_need_a_predictor():
    assert needs_predictor("Does GPA differ by gender?") and needs_predictor("Which factors predict GPA?")
    assert not needs_predictor("What is the average GPA?")


def test_every_question_is_analysed_and_answered_when_the_ai_is_turned_off(client):
    ai_runtime.set_ai_service(None)
    h = auth_headers(client, "always-answered@example.org")
    pid = make_project(client, h, title="Every question answered")["id"]
    did = upload_sample(client, h, pid)["id"]
    for text in ("Is daily social media use related to GPA?", "Does GPA differ by gender?", "Which factors predict GPA?"):
        _post(client, f"/api/projects/{pid}/research-questions", h, {"text": text})

    _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    overview = client.get(f"/api/projects/{pid}/ai/automatic-analysis", headers=h, params={"dataset_id": did}).json()
    assert all(item["variables_source"] == "rules" for item in overview["items"] if item["research_question"])
    _wait_for_runs(client, h, overview)
    _post(client, f"/api/projects/{pid}/evidence/auto", h, {})

    conclusions = client.get(f"/api/projects/{pid}/conclusions", headers=h).json()["conclusions"]
    assert len(conclusions) == 3
    for conclusion in conclusions:
        text = conclusion["text"]
        assert "HYPOTHESIS VERDICT:" in text and "SUMMARY OF EVIDENCE:" in text and "DIRECT ANSWER TO THE RESEARCH QUESTION:" in text
        assert "STRENGTH OF EVIDENCE:" in text and "LIMITATION FOR THIS CONCLUSION:" in text and "RECOMMENDATION" in text
        assert "could not be answered by the analysis yet" not in text


def _wait_for_runs(client, headers, overview):
    import time
    run_ids = [item["run"]["id"] for item in overview["items"] if item.get("run")]
    for _ in range(120):
        statuses = [client.get(f"/api/analysis/{rid}", headers=headers).json()["status"] for rid in run_ids]
        if all(s in ("COMPLETED", "FAILED") for s in statuses):
            return
        time.sleep(0.25)
