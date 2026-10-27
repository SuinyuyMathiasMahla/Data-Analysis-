"""The logic of the written conclusions: odds ratios are read against 1, every predictor is described, mismatched variables are flagged,
regression is never described as a simple correlation, and recommendations name the project and its own figures."""
from app.analysis import evidence, plain_english


def _logistic(predictors, effects, question_variables=None):
    return {"id": 1, "research_question_id": 1, "hypothesis_id": None, "confidence_level": "moderate", "significant": True, "statement": "",
            "title": "Binary logistic regression", "hypothesis": None,
            "result": {"method": "logistic_regression", "method_name": "Binary logistic regression", "n": 300, "p_value": 0.002, "alpha": 0.05,
                       "decision": "reject_null", "variables": {"outcome": "turnover", "predictors": predictors},
                       "statistic": {"name": "chi2", "value": 18.4}, "df": 3, "assumptions": [], "effect_sizes": effects}}


LABELS = {"turnover": "Employee turnover", "salary_satisfaction": "Salary satisfaction", "years_experience": "Years of experience",
          "job_satisfaction": "Job satisfaction"}
QUESTION = [{"id": 1, "code": "RQ1", "text": "Which factors predict employee turnover?"}]


def test_an_odds_ratio_below_one_is_read_as_lower_odds_not_a_positive_direction():
    effect = {"name": "Odds ratio: salary_satisfaction", "value": 0.54, "ci_low": 0.40, "ci_high": 0.73, "magnitude": None}
    clause = plain_english.direction_clause(effect, "salary satisfaction", "turnover")
    assert "lower odds" in clause and "positive" not in clause and "higher" not in clause.split("lower")[0]
    assert "odds ratio 0.54" in clause
    text = evidence.draft_conclusions([_logistic(["salary_satisfaction"], [effect])], QUESTION, {}, LABELS, "Cameroon turnover study")[0]["text"]
    assert "a positive direction" not in text and "lower odds" in text


def test_every_predictor_of_a_model_is_described_and_none_is_reported_as_not_recorded():
    effects = [{"name": "Odds ratio: salary_satisfaction", "value": 0.54, "ci_low": 0.4, "ci_high": 0.73, "magnitude": None},
               {"name": "Odds ratio: years_experience", "value": 0.93, "ci_low": 0.88, "ci_high": 0.98, "magnitude": None}]
    text = evidence.draft_conclusions([_logistic(["salary_satisfaction", "years_experience"], effects)], QUESTION, {}, LABELS)[0]["text"]
    assert "Together, the predictors were Salary satisfaction, Years of experience." in text
    assert "odds ratio 0.54" in text and "odds ratio 0.93" in text
    assert "not recorded" not in text.split("STRENGTH OF EVIDENCE:")[1].split("LIMITATION")[0]


def test_a_regression_is_never_described_as_a_simple_correlation():
    text = evidence.draft_conclusions([_logistic(["salary_satisfaction"], [])], QUESTION, {}, LABELS)[0]["text"]
    assert "predictive model" in text and "correlation" not in text.split("DIRECT ANSWER")[1].split("STRENGTH")[0]


def test_variables_that_do_not_match_the_question_are_flagged():
    question = [{"id": 1, "code": "RQ1", "text": "Does employee turnover differ across private companies in Cameroon?"}]
    finding = _logistic(["job_satisfaction"], [])
    finding["result"]["variables"] = {"outcome": "job_satisfaction", "group": "years_experience"}
    text = evidence.draft_conclusions([finding], question, {}, LABELS)[0]["text"]
    assert "Check the variables" in text and "confirm that they measure what the question asks" in text


def test_the_recommendation_names_the_project_and_its_own_figures():
    text = evidence.draft_conclusions([_logistic(["salary_satisfaction"], [{"name": "Odds ratio: salary_satisfaction", "value": 0.54,
                                                                         "ci_low": 0.4, "ci_high": 0.73, "magnitude": None}])],
                                      QUESTION, {}, LABELS, "Employee turnover in Cameroonian private companies")[0]["text"]
    recommendation = text.split("RECOMMENDATION 1:")[1]
    assert "those responsible for Employee turnover in Cameroonian private companies" in recommendation
    assert "p 0.002" in recommendation and "odds ratio 0.54" in recommendation
