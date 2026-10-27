"""Regression engine checked against R, scikit-learn, SciPy and (when it is
installed) statsmodels."""
import math

import numpy as np
import pandas as pd
import pytest
from scipy import optimize, stats

from app.statistics import regression
from app.statistics.utils import AnalysisError, InsufficientDataError
from tests.reference_data import ANSCOMBE_X, ANSCOMBE_Y, MTCARS, MTCARS_SCHEMA


def approx(value, expected, tol=1e-3):
    assert value == pytest.approx(expected, abs=tol), f"{value} != {expected}"


def coef(res, term):
    return next(c for c in res["coefficients"] if c["term"] == term)


# --------------------------------------------------------------------------- #
# linear regression
# --------------------------------------------------------------------------- #
def test_simple_regression_mtcars_matches_r():
    # R: summary(lm(mpg ~ wt, mtcars))
    res = regression.linear_regression(MTCARS, "mpg", ["wt"], MTCARS_SCHEMA)
    assert res["method"] == "simple_linear_regression"
    approx(coef(res, "(Intercept)")["b"], 37.2851, 1e-4)
    approx(coef(res, "wt")["b"], -5.3445, 1e-4)
    approx(coef(res, "wt")["se"], 0.5591, 1e-4)
    approx(coef(res, "wt")["t"], -9.559, 1e-3)
    approx(res["model_fit"]["r_squared"], 0.7528, 1e-4)
    approx(res["model_fit"]["adj_r_squared"], 0.7446, 1e-4)
    approx(res["statistic"]["value"], 91.38, 1e-2)
    approx(res["model_fit"]["rmse"], 3.046, 1e-3)
    # AIC follows the statsmodels convention (k = number of coefficients). R's AIC(lm) also counts
    # the residual variance as a parameter, so R prints 166.0294 = this value + 2.
    approx(res["model_fit"]["aic"], 164.0294, 1e-3)
    assert res["df"] == "1, 30" and res["significant"] is True


def test_simple_regression_agrees_with_scipy_linregress():
    df = pd.DataFrame({"x": ANSCOMBE_X, "y": ANSCOMBE_Y})
    res = regression.linear_regression(df, "y", ["x"], {})
    ref = stats.linregress(ANSCOMBE_X, ANSCOMBE_Y)
    approx(coef(res, "x")["b"], ref.slope, 1e-10)
    approx(coef(res, "(Intercept)")["b"], ref.intercept, 1e-10)
    approx(coef(res, "x")["se"], ref.stderr, 1e-10)
    approx(coef(res, "x")["p_value"], ref.pvalue, 1e-10)
    approx(coef(res, "x")["beta_std"], ref.rvalue, 1e-10)     # standardised slope equals r with one predictor


def test_multiple_regression_mtcars_matches_r():
    # R: summary(lm(mpg ~ wt + hp, mtcars))
    res = regression.linear_regression(MTCARS, "mpg", ["wt", "hp"], MTCARS_SCHEMA)
    assert res["method"] == "multiple_linear_regression"
    approx(coef(res, "(Intercept)")["b"], 37.22727, 1e-4)
    approx(coef(res, "wt")["b"], -3.87783, 1e-4)
    approx(coef(res, "hp")["b"], -0.03177, 1e-4)
    approx(coef(res, "wt")["se"], 0.63273, 1e-4)
    approx(coef(res, "hp")["se"], 0.00903, 1e-4)
    approx(res["model_fit"]["r_squared"], 0.8268, 1e-4)
    approx(res["model_fit"]["adj_r_squared"], 0.8148, 1e-4)
    approx(res["statistic"]["value"], 69.21, 1e-2)
    # VIF with two predictors is 1 / (1 - r^2)
    r = np.corrcoef(MTCARS["wt"], MTCARS["hp"])[0, 1]
    approx(coef(res, "wt")["vif"], 1 / (1 - r * r), 1e-8)
    assert len(res["diagnostics"]["residuals"]) == 32
    assert {a["name"] for a in res["assumptions"]} >= {"Linearity", "Normality of the residuals", "No multicollinearity"}


def test_categorical_predictor_is_dummy_coded_and_equals_t_test():
    # Regressing on a two-level factor reproduces the pooled-variance t-test
    res = regression.linear_regression(MTCARS, "mpg", ["am"], MTCARS_SCHEMA)
    term = coef(res, "am[1]")
    t = stats.ttest_ind(MTCARS.loc[MTCARS.am == 1, "mpg"], MTCARS.loc[MTCARS.am == 0, "mpg"], equal_var=True)
    approx(term["t"], t.statistic, 1e-8)
    approx(term["p_value"], t.pvalue, 1e-10)
    approx(term["b"], 7.244939, 1e-5)                         # R: lm(mpg ~ factor(am))
    assert "Reference category for am: 0" in res["tables"][1]["note"]


def test_robust_standard_errors_change_se_not_coefficients():
    plain = regression.linear_regression(MTCARS, "mpg", ["wt", "hp"], MTCARS_SCHEMA)
    robust = regression.linear_regression(MTCARS, "mpg", ["wt", "hp"], MTCARS_SCHEMA, robust=True)
    approx(coef(robust, "wt")["b"], coef(plain, "wt")["b"], 1e-12)
    assert coef(robust, "wt")["se"] != pytest.approx(coef(plain, "wt")["se"], abs=1e-6)
    assert robust["model_fit"]["standard_errors"] == "HC3 robust"


def test_breusch_pagan_detects_heteroscedasticity():
    rng = np.random.default_rng(7)
    x = rng.uniform(1, 10, 400)
    df = pd.DataFrame({"x": x, "y": 2 + 3 * x + rng.normal(0, 0.4 * x**1.5)})
    res = regression.linear_regression(df, "y", ["x"], {})
    homo = next(a for a in res["assumptions"] if a["name"].startswith("Homoscedasticity"))
    assert homo["satisfied"] is False
    assert any("robust" in w for w in res["warnings"])


def test_perfect_collinearity_is_rejected():
    df = MTCARS.assign(wt2=MTCARS["wt"] * 2)
    with pytest.raises(AnalysisError):
        regression.linear_regression(df, "mpg", ["wt", "wt2"], {})


def test_listwise_deletion_is_reported():
    df = MTCARS.copy().astype(float)
    df.loc[0, "hp"] = np.nan
    res = regression.linear_regression(df, "mpg", ["wt", "hp"], {})
    assert res["n"] == 31 and any("listwise" in w for w in res["warnings"])


def test_too_few_observations():
    with pytest.raises(InsufficientDataError):
        regression.linear_regression(MTCARS.head(3), "mpg", ["wt", "hp"], {})


# --------------------------------------------------------------------------- #
# logistic regression
# --------------------------------------------------------------------------- #
def test_logistic_regression_mtcars_matches_r():
    # R: summary(glm(am ~ wt, binomial, mtcars)): intercept 12.040 (SE 4.510), wt -4.024 (SE 1.436),
    # null deviance 43.230, residual deviance 19.176, AIC 23.176
    res = regression.logistic_regression(MTCARS, "am", ["wt"], MTCARS_SCHEMA)
    approx(coef(res, "(Intercept)")["b"], 12.040, 2e-3)
    approx(coef(res, "wt")["b"], -4.024, 2e-3)
    approx(coef(res, "(Intercept)")["se"], 4.510, 2e-3)
    approx(coef(res, "wt")["se"], 1.436, 2e-3)
    approx(-2 * res["model_fit"]["null_log_likelihood"], 43.230, 1e-3)
    approx(-2 * res["model_fit"]["log_likelihood"], 19.176, 1e-3)
    approx(res["model_fit"]["aic"], 23.176, 1e-3)
    approx(coef(res, "wt")["odds_ratio"], math.exp(coef(res, "wt")["b"]), 1e-12)
    assert res["variables"]["event"] == "1" and res["model_fit"]["converged"]


def test_logistic_regression_agrees_with_direct_likelihood_maximisation():
    rng = np.random.default_rng(11)
    n = 500
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    y = (rng.uniform(size=n) < 1 / (1 + np.exp(-(-0.4 + 0.9 * x1 - 0.6 * x2)))).astype(int)
    df = pd.DataFrame({"y": y, "x1": x1, "x2": x2})
    res = regression.logistic_regression(df, "y", ["x1", "x2"], {"y": {"type": "integer", "measurement_level": "nominal"}})
    design = np.column_stack([np.ones(n), x1, x2])

    def negative_loglik(beta):
        eta = design @ beta
        return float(np.sum(np.logaddexp(0, eta) - y * eta))

    best = optimize.minimize(negative_loglik, np.zeros(3), method="BFGS", options={"gtol": 1e-10})
    for i, term in enumerate(["(Intercept)", "x1", "x2"]):
        approx(coef(res, term)["b"], best.x[i], 1e-5)
    # standard errors from the analytic information matrix at the optimum
    mu = 1 / (1 + np.exp(-(design @ best.x)))
    cov = np.linalg.inv((design.T * (mu * (1 - mu))) @ design)
    for i, term in enumerate(["(Intercept)", "x1", "x2"]):
        approx(coef(res, term)["se"], math.sqrt(cov[i, i]), 1e-5)
    approx(res["model_fit"]["log_likelihood"], -best.fun, 1e-6)


def test_logistic_regression_agrees_with_sklearn():
    from sklearn.linear_model import LogisticRegression

    rng = np.random.default_rng(5)
    n = 400
    x = rng.normal(size=(n, 2))
    y = (rng.uniform(size=n) < 1 / (1 + np.exp(-(0.3 + 1.2 * x[:, 0] - 0.5 * x[:, 1])))).astype(int)
    df = pd.DataFrame({"y": y, "a": x[:, 0], "b": x[:, 1]})
    res = regression.logistic_regression(df, "y", ["a", "b"], {})
    ref = LogisticRegression(C=1e10, tol=1e-10, max_iter=1000).fit(x, y)   # C this large is effectively unpenalised
    approx(coef(res, "a")["b"], ref.coef_[0][0], 1e-4)
    approx(coef(res, "b")["b"], ref.coef_[0][1], 1e-4)
    approx(coef(res, "(Intercept)")["b"], ref.intercept_[0], 1e-4)


def test_logistic_regression_warns_on_separation():
    df = pd.DataFrame({"y": [0] * 20 + [1] * 20, "x": list(range(20)) + list(range(30, 50))})
    res = regression.logistic_regression(df, "y", ["x"], {})
    assert any("separation" in w for w in res["warnings"])


def test_logistic_regression_requires_binary_outcome():
    with pytest.raises(AnalysisError):
        regression.logistic_regression(MTCARS, "hp", ["wt"], MTCARS_SCHEMA)


# --------------------------------------------------------------------------- #
# Poisson regression
# --------------------------------------------------------------------------- #
def _count_data(n=600, seed=2):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    return pd.DataFrame({"x": x, "y": rng.poisson(np.exp(0.5 + 0.4 * x))})


def test_poisson_regression_agrees_with_sklearn():
    from sklearn.linear_model import PoissonRegressor

    df = _count_data()
    res = regression.poisson_regression(df, "y", ["x"], {})
    ref = PoissonRegressor(alpha=0, tol=1e-10, max_iter=1000).fit(df[["x"]], df["y"])
    approx(coef(res, "x")["b"], ref.coef_[0], 1e-5)
    approx(coef(res, "(Intercept)")["b"], ref.intercept_, 1e-5)
    approx(coef(res, "x")["b"], 0.4, 0.08)                   # recovers the simulated effect
    assert next(a for a in res["assumptions"] if a["name"].startswith("Equidispersion"))["satisfied"] is True


def test_poisson_regression_flags_overdispersion():
    rng = np.random.default_rng(4)
    x = rng.normal(size=500)
    y = rng.negative_binomial(1.0, 1 / (1 + np.exp(0.8 + 0.3 * x)))
    res = regression.poisson_regression(pd.DataFrame({"x": x, "y": y}), "y", ["x"], {})
    assert res["model_fit"]["dispersion"] > 1.5
    assert any("negative-binomial" in w for w in res["warnings"])


def test_poisson_regression_rejects_non_counts():
    with pytest.raises(AnalysisError):
        regression.poisson_regression(MTCARS, "mpg", ["wt"], MTCARS_SCHEMA)


# --------------------------------------------------------------------------- #
# cross-validation against statsmodels (runs wherever statsmodels is installed)
# --------------------------------------------------------------------------- #
def test_ols_matches_statsmodels():
    sm = pytest.importorskip("statsmodels.api")
    from statsmodels.stats.diagnostic import het_breuschpagan
    from statsmodels.stats.stattools import durbin_watson

    ref = sm.OLS(MTCARS["mpg"], sm.add_constant(MTCARS[["wt", "hp"]])).fit()
    res = regression.linear_regression(MTCARS, "mpg", ["wt", "hp"], MTCARS_SCHEMA)
    for term, name in [("(Intercept)", "const"), ("wt", "wt"), ("hp", "hp")]:
        approx(coef(res, term)["b"], ref.params[name], 1e-8)
        approx(coef(res, term)["se"], ref.bse[name], 1e-8)
        approx(coef(res, term)["p_value"], ref.pvalues[name], 1e-8)
    approx(res["model_fit"]["aic"], ref.aic, 1e-6)
    approx(res["model_fit"]["bic"], ref.bic, 1e-6)
    bp = next(a for a in res["assumptions"] if a["test"] == "Breusch-Pagan (Koenker)")
    lm, lm_p, _, _ = het_breuschpagan(ref.resid, ref.model.exog)
    approx(bp["statistic"], lm, 1e-8)
    approx(bp["p_value"], lm_p, 1e-8)
    dw = next(a for a in res["assumptions"] if a["test"] == "Durbin-Watson")
    approx(dw["statistic"], durbin_watson(ref.resid), 1e-8)
    robust = regression.linear_regression(MTCARS, "mpg", ["wt", "hp"], MTCARS_SCHEMA, robust=True)
    approx(coef(robust, "wt")["se"], ref.get_robustcov_results("HC3").bse[1], 1e-8)


def test_glms_match_statsmodels():
    sm = pytest.importorskip("statsmodels.api")
    ref = sm.Logit(MTCARS["am"], sm.add_constant(MTCARS[["wt"]])).fit(disp=0)
    res = regression.logistic_regression(MTCARS, "am", ["wt"], MTCARS_SCHEMA)
    approx(coef(res, "wt")["b"], ref.params["wt"], 1e-6)
    approx(coef(res, "wt")["se"], ref.bse["wt"], 1e-6)
    approx(res["model_fit"]["mcfadden_r2"], ref.prsquared, 1e-8)
    df = _count_data()
    ref = sm.GLM(df["y"], sm.add_constant(df[["x"]]), family=sm.families.Poisson()).fit()
    res = regression.poisson_regression(df, "y", ["x"], {})
    approx(coef(res, "x")["b"], ref.params["x"], 1e-7)
    approx(coef(res, "x")["se"], ref.bse["x"], 1e-7)


def test_statsmodels_backed_models_run():
    pytest.importorskip("statsmodels.api")
    rng = np.random.default_rng(9)
    n_groups, per = 30, 12
    group = np.repeat(np.arange(n_groups), per)
    x = rng.normal(size=n_groups * per)
    y = 1 + 0.5 * x + rng.normal(0, 1.0, n_groups)[group] + rng.normal(0, 1.0, n_groups * per)
    res = regression.mixed_effects_model(pd.DataFrame({"y": y, "x": x, "school": group.astype(str)}), "y", ["x"], "school", {})
    approx(coef(res, "x")["b"], 0.5, 0.15)
    assert 0.2 < res["model_fit"]["icc"] < 0.8
    counts = rng.negative_binomial(2.0, 1 / (1 + np.exp(0.5 + 0.4 * x) / 2.0))
    nb = regression.negative_binomial_regression(pd.DataFrame({"y": counts, "x": x}), "y", ["x"], {})
    approx(coef(nb, "x")["b"], 0.4, 0.15)
