"""The plain-language summary: seven parts in order, under 250 words, no statistical jargon, and the direction kept accurate."""
import re

from app.analysis import plain_summary

from tests.test_conclusion_report import _setup_with_analysis

BANNED = ["p-value", "null hypothesis", "alternative hypothesis", "confidence interval", "degrees of freedom", "test statistic",
          "normality", "spearman", "pearson", "significant", "H0", "H1"]
PARTS = ["The question:", "The answer:", "How strong", "Could it be a fluke?", "What this does NOT mean:", "In one sentence:"]


def _rq(code="RQ1", text="Is daily social media use related to GPA?"):
    return {"id": 1, "code": code, "text": text}


def _result(p, decision, value=-0.37, n=243, magnitude="moderate", assumptions=None):
    return {"method": "pearson", "method_name": "Pearson correlation", "n": n, "p_value": p, "alpha": 0.05, "decision": decision,
            "variables": {"x": "social_media_hours", "y": "gpa"}, "assumptions": assumptions or [],
            "effect_sizes": [{"name": "Pearson correlation coefficient (r)", "value": value, "ci_low": -0.48, "ci_high": -0.25,
                              "magnitude": magnitude}]}


def test_a_supported_link_is_described_in_seven_parts_under_250_words():
    group = [{"result": _result(0.0004, "reject_null")}]
    lines = plain_summary.summarise(_rq(), group, {"gpa": "GPA", "social_media_hours": "daily social media hours"})
    text = "\n".join(lines)
    assert [next(i for i, line in enumerate(lines) if line.startswith(part)) for part in PARTS] == sorted(
        next(i for i, line in enumerate(lines) if line.startswith(part)) for part in PARTS)
    assert len(text.split()) < 250
    assert lines[1] == "The answer: Yes. Among the 243 records, higher daily social media hours goes with lower GPA."
    assert "less than 1 in 1,000 times" in text and "The scale runs from -1" in text
    assert "moderate" in text and "between -0.48 and -0.25" in text
    for term in BANNED:
        assert not re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE), term


def test_an_unsupported_link_says_no_and_gives_the_caution_when_checks_failed():
    group = [{"result": _result(0.446, "fail_to_reject_null", value=-0.05, magnitude="negligible",
                                assumptions=[{"name": "Normality of gpa", "satisfied": False}])}]
    lines = plain_summary.summarise(_rq("RQ3", "Which factors predict GPA?"), group, {"gpa": "GPA", "age": "age"})
    text = "\n".join(lines)
    assert "The answer: No." in text and "about 45 times in 100" in text
    assert any(line.startswith("A note of caution:") for line in lines)
    assert "very weak" in text


def test_a_second_test_that_agreed_is_mentioned_once():
    main = {"result": _result(0.0004, "reject_null")}
    second = {"result": {**_result(0.002, "reject_null"), "method_name": "Spearman"}}
    lines = plain_summary.summarise(_rq(), [main, second], {"gpa": "GPA", "social_media_hours": "daily social media hours"})
    assert sum("A second test gave the same answer." in line for line in lines) == 1


def test_the_report_carries_a_summary_for_each_hypothesis(client):
    content, _ = _setup_with_analysis(client, "plain-summary@example.org")
    summaries = content["plain_summaries"]
    assert summaries and all(len(" ".join(block["lines"]).split()) < 250 for block in summaries)
    assert all(block["lines"][0].startswith("The question:") for block in summaries)
