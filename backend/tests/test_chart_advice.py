"""Chart suggestions for findings and conclusions."""
from app.analysis.chart_advice import chart_ideas

SCHEMA = {"gpa": {"type": "numeric"}, "study_hours": {"type": "numeric"}, "gender": {"type": "categorical"}, "passed": {"type": "categorical"}}


def test_correlation_gets_a_scatter_and_a_fitted_line():
    ideas = chart_ideas("spearman", {"x": "study_hours", "y": "gpa"}, SCHEMA)
    assert [i["chart_type"] for i in ideas] == ["scatter", "regression"]
    assert ideas[0]["x"] == "study_hours" and ideas[0]["y"] == "gpa" and ideas[0]["reason"]


def test_group_test_gets_group_means_and_box_plot_regardless_of_order():
    ideas = chart_ideas("one_way_anova", {"outcome": "gpa", "group": "gender"}, SCHEMA)
    assert ideas[0]["chart_type"] == "group_comparison" and ideas[0]["x"] == "gender" and ideas[0]["y"] == "gpa"
    assert ideas[1]["chart_type"] == "box"


def test_association_gets_a_heatmap_and_unknown_methods_still_get_a_chart():
    assert chart_ideas("chi_square", {"x": "passed", "y": "gender"}, SCHEMA)[0]["chart_type"] == "heatmap"
    fallback = chart_ideas("something_new", {"variables": ["gpa"]}, SCHEMA)
    assert fallback and fallback[0]["chart_type"] == "histogram"


def test_no_variables_no_charts():
    assert chart_ideas("pearson", {}, SCHEMA) == []


def test_preview_draws_a_chart_without_saving_it(client):
    from tests.conftest import auth_headers, make_project, upload_sample
    h = auth_headers(client, "preview@example.org")
    pid = make_project(client, h)["id"]
    did = upload_sample(client, h, pid)["id"]
    before = len(client.get(f"/api/projects/{pid}/visualizations", headers=h).json()["visualizations"])
    response = client.post(f"/api/projects/{pid}/visualizations/preview", headers=h, json={"chart_type": "histogram", "x": "gpa", "dataset_id": did})
    assert response.status_code == 200 and response.headers["content-type"] == "image/png" and response.content[:4] == b"\x89PNG"
    assert len(client.get(f"/api/projects/{pid}/visualizations", headers=h).json()["visualizations"]) == before


def test_suggested_charts_come_from_the_exploration_and_mark_the_charts_step(client):
    import time
    from tests.conftest import auth_headers, make_project, upload_sample
    h = auth_headers(client, "charts-step@example.org")
    pid = make_project(client, h)["id"]
    did = upload_sample(client, h, pid)["id"]
    assert client.get(f"/api/projects/{pid}/charts/suggested?dataset_id={did}", headers=h).json()["charts"] == []
    run = client.post(f"/api/projects/{pid}/analysis", headers=h, json={"analysis_type": "eda", "dataset_id": did}).json()
    for _ in range(120):
        run = client.get(f"/api/analysis/{run['id']}", headers=h).json()
        if run["status"] in ("COMPLETED", "FAILED"):
            break
        time.sleep(0.25)
    suggested = client.get(f"/api/projects/{pid}/charts/suggested?dataset_id={did}", headers=h).json()
    assert suggested["run_id"] == run["id"] and suggested["charts"] and all(c["run_id"] == run["id"] for c in suggested["charts"])
    steps = {s["key"]: s["done"] for s in client.get(f"/api/projects/{pid}", headers=h).json()["progress"]["steps"]}
    assert steps["charts"] is False
    client.post(f"/api/projects/{pid}/visualizations", headers=h, json={"chart_type": "histogram", "x": "gpa", "dataset_id": did})
    steps = {s["key"]: s["done"] for s in client.get(f"/api/projects/{pid}", headers=h).json()["progress"]["steps"]}
    assert steps["charts"] is True


def test_holm_adjustment_and_null_results_are_rated_low():
    from app.analysis.evidence import evidence_confidence
    from app.reports.content import holm_adjusted
    adjusted = holm_adjusted({1: 0.01, 2: 0.04, 3: 0.03})
    assert round(adjusted[1], 4) == 0.03 and round(adjusted[3], 4) == 0.06 and round(adjusted[2], 4) == 0.06
    null = {"n": 300, "p_value": 0.4, "alpha": 0.05, "effect_sizes": [{"magnitude": "moderate"}], "assumptions": []}
    assert evidence_confidence(null)[0] == "low"
    weak = {"n": 300, "p_value": 0.001, "alpha": 0.05, "effect_sizes": [{"magnitude": "weak"}], "assumptions": []}
    assert evidence_confidence(weak)[0] != "high"
    strong = {"n": 300, "p_value": 0.001, "alpha": 0.05, "effect_sizes": [{"magnitude": "moderate"}], "assumptions": []}
    assert evidence_confidence(strong)[0] == "high"
