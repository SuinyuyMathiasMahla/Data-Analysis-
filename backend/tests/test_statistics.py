"""Known-answer tests for the statistical engine.

Expected values are published R outputs for standard datasets (see
reference_data.py) or closed-form hand calculations.
"""
import math

import numpy as np
import pandas as pd
import pytest

from app.statistics import correlation, descriptive, effect_sizes, group_tests, multivariate, power
from app.statistics.registry import METHODS, apply_filters, run_method
from app.statistics.utils import AnalysisError, InsufficientDataError, MethodNotImplementedError
from tests.reference_data import ANSCOMBE_X, ANSCOMBE_Y, PLANT, plant_long, sleep_long, sleep_wide


def approx(value, expected, tol=1e-3):
    assert value == pytest.approx(expected, abs=tol), f"{value} != {expected}"


# --------------------------------------------------------------------------- #
# descriptive
# --------------------------------------------------------------------------- #
def test_describe_numeric_hand_values():
    d = descriptive.describe_numeric(pd.Series([2, 4, 4, 4, 5, 5, 7, 9]))
    approx(d["mean"], 5.0)
    approx(d["median"], 4.5)
    approx(d["mode"], 4.0)
    approx(d["variance"], 32 / 7)            # sample variance
    approx(d["std"], math.sqrt(32 / 7))
    approx(d["range"], 7.0)
    approx(d["q1"], 4.0)
    approx(d["q3"], 5.5)
    approx(d["iqr"], 1.5)
    # 95% CI for the mean: 5 +/- t(.975, 7) * s / sqrt(8), t = 2.364624
    half = 2.364624 * math.sqrt(32 / 7) / math.sqrt(8)
    approx(d["mean_ci_low"], 5 - half)
    approx(d["mean_ci_high"], 5 + half)


def test_describe_ignores_missing_and_text():
    d = descriptive.describe_numeric(pd.Series([1.0, None, 3.0, "x"], dtype=object))
    assert d["n"] == 2 and d["n_missing"] == 2
    approx(d["mean"], 2.0)


def test_frequency_table_percentages_use_valid_cases():
    f = descriptive.frequency_table(pd.Series(["a", "a", "b", None], dtype=object))
    assert f["n"] == 3 and f["n_missing"] == 1
    levels = {r["value"]: r for r in f["levels"]}
    approx(levels["a"]["percent"], 66.667, 0.01)
    approx(levels["b"]["percent"], 33.333, 0.01)


def test_wilson_interval():
    lo, hi = descriptive.proportion_ci(10, 20)
    approx(lo, 0.2993, 1e-3)
    approx(hi, 0.7007, 1e-3)


# --------------------------------------------------------------------------- #
# correlation
# --------------------------------------------------------------------------- #
def test_pearson_anscombe():
    df = pd.DataFrame({"x": ANSCOMBE_X, "y": ANSCOMBE_Y})
    res = correlation.pearson(df, "x", "y")
    approx(res["statistic"]["value"], 0.81642, 1e-4)
    approx(res["p_value"], 0.00217, 1e-4)
    assert res["df"] == 9
    assert res["significant"] is True and res["decision"] == "reject_null"
    # Fisher z interval: tanh(atanh(r) +/- 1.96 / sqrt(n - 3))
    z = math.atanh(0.81642)
    approx(res["estimates"][0]["ci_low"], math.tanh(z - 1.959964 / math.sqrt(8)))
    approx(res["estimates"][0]["ci_high"], math.tanh(z + 1.959964 / math.sqrt(8)))
    assert res["effect_sizes"][0]["magnitude"] == "strong"
    assert "does not show that one variable causes" in res["summary"]


def test_perfect_monotonic_spearman_and_kendall():
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5, 6], "y": [1, 4, 9, 16, 25, 36]})
    approx(correlation.spearman(df, "x", "y")["statistic"]["value"], 1.0)
    approx(correlation.kendall(df, "x", "y")["statistic"]["value"], 1.0)


def test_spearman_hand_calculation():
    # rho = 1 - 6 * sum(d^2) / (n (n^2 - 1)) with no ties; d = [0, -1, 1, 0, 0] -> 0.9
    df = pd.DataFrame({"x": [10, 20, 30, 40, 50], "y": [1, 3, 2, 4, 5]})
    approx(correlation.spearman(df, "x", "y")["statistic"]["value"], 0.9)


def test_correlation_needs_variation_and_data():
    with pytest.raises(AnalysisError):
        correlation.pearson(pd.DataFrame({"x": [1, 1, 1, 1], "y": [1, 2, 3, 4]}), "x", "y")
    with pytest.raises(InsufficientDataError):
        correlation.pearson(pd.DataFrame({"x": [1, 2], "y": [1, 2]}), "x", "y")


def test_correlation_pairwise_deletion_is_reported():
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5, None], "y": [2, 1, 4, 3, 6, 9]})
    res = correlation.pearson(df, "x", "y")
    assert res["n"] == 5
    assert any("excluded" in w for w in res["warnings"])


# --------------------------------------------------------------------------- #
# association
# --------------------------------------------------------------------------- #
def _table_frame(a, b, c, d):
    rows = [("r1", "c1")] * a + [("r1", "c2")] * b + [("r2", "c1")] * c + [("r2", "c2")] * d
    return pd.DataFrame(rows, columns=["x", "y"])


def test_chi_square_hand_calculation():
    # 2x2 shortcut: chi2 = N (ad - bc)^2 / (r1 r2 c1 c2)
    a, b, c, d = 30, 10, 15, 25
    res = correlation.chi_square(_table_frame(a, b, c, d), "x", "y")
    n = a + b + c + d
    expected = n * (a * d - b * c) ** 2 / ((a + b) * (c + d) * (a + c) * (b + d))
    approx(res["statistic"]["value"], expected, 1e-6)
    assert res["df"] == 1
    approx(res["effect_sizes"][0]["value"], math.sqrt(expected / n), 1e-6)      # Cramer's V = phi
    approx(res["effect_sizes"][1]["value"], (a * d) / (b * c), 1e-6)            # odds ratio
    assert res["assumptions"][0]["satisfied"] is True


def test_chi_square_flags_small_expected_counts():
    res = correlation.chi_square(_table_frame(3, 1, 1, 3), "x", "y")
    assert res["assumptions"][0]["satisfied"] is False
    assert any("Fisher" in w for w in res["warnings"])


def test_fisher_exact_tea_tasting():
    # Fisher's lady tasting tea: R fisher.test p-value = 0.4857
    res = correlation.fisher_exact(_table_frame(3, 1, 1, 3), "x", "y")
    approx(res["p_value"], 0.4857, 1e-4)
    assert res["significant"] is False


def test_fisher_rejects_larger_tables():
    df = pd.DataFrame({"x": ["a", "b", "c"] * 4, "y": ["u", "v"] * 6})
    with pytest.raises(AnalysisError):
        correlation.fisher_exact(df, "x", "y")


# --------------------------------------------------------------------------- #
# two groups
# --------------------------------------------------------------------------- #
def test_welch_t_test_sleep_data():
    # R: t.test(extra ~ group, data = sleep): t = -1.8608, df = 17.776, p = 0.07939
    res = group_tests.independent_t_test(sleep_long(), "extra", "drug", equal_var=False)
    approx(res["statistic"]["value"], -1.8608, 1e-4)
    approx(res["df"], 17.776, 1e-3)
    approx(res["p_value"], 0.07939, 1e-5)
    approx(res["estimates"][0]["ci_low"], -3.3654832, 1e-4)
    approx(res["estimates"][0]["ci_high"], 0.2054832, 1e-4)
    assert res["significant"] is False and res["decision"] == "fail_to_reject_null"


def test_student_t_test_sleep_data():
    # R: t.test(extra ~ group, data = sleep, var.equal = TRUE): t = -1.8608, df = 18, p = 0.07919
    res = group_tests.independent_t_test(sleep_long(), "extra", "drug", equal_var=True)
    assert res["df"] == 18
    approx(res["p_value"], 0.07919, 1e-5)
    # Cohen's d = mean difference / pooled SD
    a, b = np.array(sleep_wide()["drug1"]), np.array(sleep_wide()["drug2"])
    pooled = math.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    approx(res["effect_sizes"][0]["value"], (a.mean() - b.mean()) / pooled, 1e-6)


def test_t_test_requires_exactly_two_groups():
    with pytest.raises(AnalysisError):
        group_tests.independent_t_test(plant_long(), "weight", "group")


def test_paired_t_test_sleep_data():
    # R: t.test(drug1, drug2, paired = TRUE): t = -4.0621, df = 9, p = 0.002833, CI [-2.4598858, -0.7001142]
    res = group_tests.paired_t_test(sleep_wide(), "drug1", "drug2")
    approx(res["statistic"]["value"], -4.0621, 1e-4)
    assert res["df"] == 9
    approx(res["p_value"], 0.002833, 1e-6)
    approx(res["estimates"][0]["ci_low"], -2.4598858, 1e-5)
    approx(res["estimates"][0]["ci_high"], -0.7001142, 1e-5)
    assert res["significant"] is True


def test_directional_alternative_halves_the_p_value():
    two = group_tests.paired_t_test(sleep_wide(), "drug1", "drug2")
    less = group_tests.paired_t_test(sleep_wide(), "drug1", "drug2", alternative="less")
    approx(less["p_value"], two["p_value"] / 2, 1e-9)


def test_mann_whitney_complete_separation():
    # Exact two-sided p for complete separation of 5 vs 5: 2 / C(10, 5) = 0.007937
    df = pd.DataFrame({"v": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "g": ["a"] * 5 + ["b"] * 5})
    res = group_tests.mann_whitney(df, "v", "g")
    approx(res["statistic"]["value"], 0.0)
    approx(res["p_value"], 0.007937, 1e-6)
    approx(res["effect_sizes"][0]["value"], -1.0)


def test_wilcoxon_signed_rank_exact():
    # differences 1..8 all positive: W = 0, exact two-sided p = 2 / 2^8 = 0.0078125
    df = pd.DataFrame({"a": [11, 12, 13, 14, 15, 16, 17, 18], "b": [10] * 8})
    res = group_tests.wilcoxon_signed_rank(df, "a", "b")
    approx(res["statistic"]["value"], 0.0)
    approx(res["p_value"], 0.0078125, 1e-7)
    approx(res["effect_sizes"][0]["value"], 1.0)


# --------------------------------------------------------------------------- #
# three or more groups
# --------------------------------------------------------------------------- #
def test_one_way_anova_plant_growth():
    # R: summary(aov(weight ~ group, PlantGrowth)): F(2, 27) = 4.846, p = 0.01591; SSB = 3.766, SSW = 10.492
    res = group_tests.one_way_anova(plant_long(), "weight", "group")
    approx(res["statistic"]["value"], 4.846, 1e-3)
    approx(res["p_value"], 0.01591, 1e-5)
    assert res["df"] == "2, 27"
    anova = next(t for t in res["tables"] if t["title"] == "ANOVA table")
    approx(anova["rows"][0][1], 3.76634, 1e-4)
    approx(anova["rows"][1][1], 10.49209, 1e-4)
    approx(res["effect_sizes"][0]["value"], 3.76634 / (3.76634 + 10.49209), 1e-5)   # eta squared


def test_tukey_hsd_plant_growth():
    # R: TukeyHSD: trt1-ctrl p = 0.3909, trt2-ctrl p = 0.1980, trt2-trt1 p = 0.0120
    res = group_tests.one_way_anova(plant_long(), "weight", "group")
    post = {c["comparison"]: c for c in res["post_hoc"]}
    approx(post["ctrl - trt1"]["p_adjusted"], 0.3909, 1e-3)
    approx(post["ctrl - trt2"]["p_adjusted"], 0.1980, 1e-3)
    approx(post["trt1 - trt2"]["p_adjusted"], 0.0120, 1e-3)
    assert post["trt1 - trt2"]["significant"] and not post["ctrl - trt1"]["significant"]


def test_welch_anova_plant_growth():
    # R: oneway.test(weight ~ group, PlantGrowth): F = 5.181, num df = 2, denom df = 17.128, p = 0.01739
    f, df1, df2, p = group_tests.welch_anova([np.array(v) for v in PLANT.values()])
    approx(f, 5.181, 1e-3)
    approx(df2, 17.128, 1e-3)
    approx(p, 0.01739, 1e-5)


def test_kruskal_wallis_plant_growth():
    # R: kruskal.test(weight ~ group, PlantGrowth): chi-squared = 7.9882, df = 2, p = 0.01842
    res = group_tests.kruskal_wallis(plant_long(), "weight", "group")
    approx(res["statistic"]["value"], 7.9882, 1e-4)
    approx(res["p_value"], 0.01842, 1e-5)


def test_repeated_measures_anova_matches_paired_t_for_two_conditions():
    # With two conditions F(1, n-1) must equal the squared paired t
    wide = sleep_wide().assign(drug3=[1.0, 0.2, 0.9, 0.5, 0.3, 3.9, 4.1, 1.9, 2.2, 2.5])
    t = group_tests.paired_t_test(wide, "drug1", "drug2")["statistic"]["value"]
    data = wide[["drug1", "drug2"]].to_numpy()
    n, k = data.shape
    grand = data.mean()
    ss_cond = n * ((data.mean(axis=0) - grand) ** 2).sum()
    ss_subj = k * ((data.mean(axis=1) - grand) ** 2).sum()
    ss_err = ((data - grand) ** 2).sum() - ss_cond - ss_subj
    approx(ss_cond / (ss_err / (n - 1)), t**2, 1e-8)
    res = group_tests.repeated_measures_anova(wide, ["drug1", "drug2", "drug3"])
    assert res["df"] == "2, 18" and res["statistic"]["value"] > 0
    assert 0.5 <= res["assumptions"][0]["statistic"] <= 1.0          # Greenhouse-Geisser epsilon bounds for k = 3


def test_repeated_measures_anova_textbook_example():
    # 5 participants x 3 conditions, computed by hand:
    # condition means 3, 5, 7 (grand mean 5) -> SS_cond = 5 * (4 + 0 + 4) = 40
    # participant means 10/3, 4, 5, 17/3, 7 -> SS_subj = 3 * 74/9 = 74/3
    # SS_total = 30 + 10 + 26 = 66 -> SS_error = 66 - 40 - 74/3 = 4/3
    # F = (40 / 2) / ((4/3) / 8) = 120
    wide = pd.DataFrame({"t1": [1, 2, 3, 4, 5], "t2": [3, 4, 5, 6, 7], "t3": [6, 6, 7, 7, 9]})
    res = group_tests.repeated_measures_anova(wide, ["t1", "t2", "t3"])
    table = next(t for t in res["tables"] if "ANOVA table" in t["title"])
    approx(table["rows"][0][1], 40.0, 1e-9)
    approx(table["rows"][1][1], 74 / 3, 1e-9)
    approx(table["rows"][2][1], 4 / 3, 1e-9)
    approx(res["statistic"]["value"], 120.0, 1e-7)
    approx(res["effect_sizes"][0]["value"], 40 / (40 + 4 / 3), 1e-9)      # partial eta squared


def test_holm_adjustment():
    assert group_tests._holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


# --------------------------------------------------------------------------- #
# effect sizes
# --------------------------------------------------------------------------- #
def test_effect_size_benchmarks():
    assert effect_sizes.magnitude_d(0.1) == "negligible" and effect_sizes.magnitude_d(0.5) == "medium" and effect_sizes.magnitude_d(-0.9) == "large"
    assert effect_sizes.magnitude_r(-0.42) == "moderate" and effect_sizes.magnitude_r(0.05) == "negligible"
    assert effect_sizes.magnitude_eta2(0.06) == "medium"


def test_odds_ratio_and_woolf_interval():
    entry = effect_sizes.odds_ratio(np.array([[20, 10], [5, 15]]))
    approx(entry["value"], 6.0)
    se = math.sqrt(1 / 20 + 1 / 10 + 1 / 5 + 1 / 15)
    approx(entry["ci_low"], math.exp(math.log(6) - 1.959964 * se), 1e-5)
    approx(entry["ci_high"], math.exp(math.log(6) + 1.959964 * se), 1e-5)


def test_odds_ratio_zero_cell_uses_correction():
    entry = effect_sizes.odds_ratio(np.array([[5, 0], [2, 4]]))
    assert entry["value"] is not None and "0.5" in entry["note"]


# --------------------------------------------------------------------------- #
# power (reference values: G*Power 3.1)
# --------------------------------------------------------------------------- #
def test_required_n_matches_gpower():
    assert power.required_n("t_test_independent", 0.5, 0.8, 0.05) == 64          # per group
    assert power.required_n("t_test_paired", 0.5, 0.8, 0.05) == 34
    assert power.required_n("anova", 0.25, 0.8, 0.05, k_groups=3) == 158        # total; G*Power rounds up to 159 for equal groups
    assert power.required_n("chi_square", 0.3, 0.8, 0.05, df=1) == 88
    assert power.required_n("regression", 0.15, 0.8, 0.05, n_predictors=3) == 77
    assert power.required_n("correlation", 0.3, 0.8, 0.05) in (84, 85)           # 84 exact, 85 by Fisher z approximation


def test_power_value_matches_gpower():
    approx(power.compute_power("t_test_independent", 0.5, 64), 0.8015, 1e-3)
    approx(power.compute_power("t_test_independent", 0.5, 20), 0.3379, 1e-3)
    approx(power.compute_power("t_test_independent", 0.0, 64), 0.05)


def test_power_modes_are_labelled():
    prospective = power.run_power_analysis("t_test_independent", "required_n", effect_size=0.5)
    assert prospective["planning"] == "prospective" and prospective["required_n"] == 64 and prospective["total_n"] == 128
    post = power.run_power_analysis("correlation", "post_hoc", effect_size=0.3, n=50)
    assert post["planning"] == "post_hoc" and any("POST-HOC" in w for w in post["warnings"])
    with pytest.raises(AnalysisError):
        power.run_power_analysis("t_test_independent", "required_n", effect_size=0)


# --------------------------------------------------------------------------- #
# multivariate
# --------------------------------------------------------------------------- #
def _two_factor_data(n=300, seed=1):
    rng = np.random.default_rng(seed)
    f1, f2 = rng.normal(size=n), rng.normal(size=n)
    cols = {f"a{i}": 0.8 * f1 + rng.normal(scale=0.5, size=n) for i in range(1, 4)}
    cols.update({f"b{i}": 0.8 * f2 + rng.normal(scale=0.5, size=n) for i in range(1, 4)})
    return pd.DataFrame(cols)


def test_pca_eigenvalues_sum_to_number_of_variables():
    df = _two_factor_data()
    res = multivariate.pca(df, list(df.columns))
    approx(sum(res["eigenvalues"]), 6.0, 1e-8)
    approx(sum(res["explained_variance_ratio"]), 1.0, 1e-9)
    assert res["components_retained"] == 2


def test_factor_analysis_recovers_two_factors():
    df = _two_factor_data()
    res = multivariate.factor_analysis(df, list(df.columns))
    assert res["factors_retained"] == 2
    a_factor = int(np.argmax(np.abs(res["loadings"]["a1"])))
    b_factor = int(np.argmax(np.abs(res["loadings"]["b1"])))
    assert a_factor != b_factor
    for item in ("a1", "a2", "a3"):
        assert abs(res["loadings"][item][a_factor]) > 0.7 and abs(res["loadings"][item][b_factor]) < 0.3


def test_cluster_analysis_finds_separated_groups():
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"x": np.r_[rng.normal(0, 0.5, 60), rng.normal(6, 0.5, 60)], "y": np.r_[rng.normal(0, 0.5, 60), rng.normal(6, 0.5, 60)]})
    res = multivariate.cluster_analysis(df, ["x", "y"])
    assert res["n_clusters"] == 2 and sorted(res["cluster_sizes"]) == [60, 60] and res["silhouette"] > 0.8


def test_cronbach_alpha_hand_calculation():
    # item variances 2.5, 2.5, 2.5; total-score variance 22.5 -> alpha = 3/2 * (1 - 7.5/22.5) = 1.0 for identical items
    df = pd.DataFrame({"i1": list(range(1, 11)), "i2": list(range(1, 11)), "i3": list(range(1, 11))})
    approx(multivariate.cronbach_alpha(df, ["i1", "i2", "i3"])["statistic"]["value"], 1.0)
    # Known example: alpha = k/(k-1) * (1 - sum(var_i)/var_total)
    df2 = pd.DataFrame({"i1": [3, 4, 2, 5, 4, 3, 5, 2, 4, 3], "i2": [4, 4, 3, 5, 3, 3, 4, 2, 5, 3], "i3": [2, 5, 2, 4, 4, 2, 5, 3, 4, 4]})
    items = df2.to_numpy(dtype=float)
    expected = 3 / 2 * (1 - items.var(axis=0, ddof=1).sum() / items.sum(axis=1).var(ddof=1))
    approx(multivariate.cronbach_alpha(df2, ["i1", "i2", "i3"])["statistic"]["value"], expected, 1e-9)


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #
def test_unimplemented_methods_refuse_instead_of_fabricating():
    for key in ("survival_analysis", "time_series", "sem", "manova"):
        assert METHODS[key]["implemented"] is False
        with pytest.raises(MethodNotImplementedError):
            run_method(sleep_long(), {}, key, {})


def test_run_method_validates_roles_and_records_provenance():
    with pytest.raises(AnalysisError):
        run_method(sleep_long(), {}, "independent_t_test", {"outcome": "extra"})
    res = run_method(sleep_long(), {}, "independent_t_test", {"outcome": "extra", "group": "drug"}, {"equal_var": False})
    assert res["software"]["scipy"] and res["records_in_dataset"] == 20 and res["source"] == "statistical_engine"


def test_filters_are_applied_and_recorded():
    df = plant_long()
    res = run_method(df, {}, "independent_t_test", {"outcome": "weight", "group": "group"},
                     filters=[{"column": "group", "op": "ne", "value": "ctrl"}])
    assert res["n"] == 20 and res["records_after_filters"] == 20 and res["filters"][0]["op"] == "ne"
    assert len(apply_filters(df, [{"column": "weight", "op": "gt", "value": 5}])) == int((df["weight"] > 5).sum())
    with pytest.raises(AnalysisError):
        apply_filters(df, [{"column": "weight", "op": "gt", "value": 100}])
