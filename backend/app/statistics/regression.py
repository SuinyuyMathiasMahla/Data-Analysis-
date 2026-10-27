"""Regression models.

Linear, logistic and Poisson regression are fitted here with NumPy/SciPy
(ordinary least squares in closed form; GLMs by iteratively reweighted least
squares), which keeps the core models dependency-light and lets the test suite
check every number against independent implementations (SciPy, scikit-learn
and, when installed, statsmodels - see tests/test_regression.py).

Negative-binomial and mixed-effects models delegate to statsmodels.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
from scipy import special, stats

from app.statistics import assumptions as A
from app.statistics.utils import (AnalysisError, InsufficientDataError, MethodNotImplementedError, finalize, fmt_num,
                                  fmt_p, new_result, numeric, require_columns, table)

MAX_DIAGNOSTIC_POINTS = 2000
NUMERIC_TYPES = {"numeric", "integer"}


# --------------------------------------------------------------------------- #
# design matrix
# --------------------------------------------------------------------------- #
def build_design(df: pd.DataFrame, outcome: str, predictors: list[str], schema: dict | None,
                 extra: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Listwise-complete outcome frame and predictor matrix.

    Numeric predictors enter as they are. Categorical predictors are dummy
    coded against a reference level (the first level in sorted order).
    Returns ``(data, X, info)`` where ``data`` keeps the outcome and ``extra``.
    """
    schema = schema or {}
    predictors = list(dict.fromkeys(predictors or []))
    if not predictors:
        raise AnalysisError("Select at least one predictor variable.")
    if outcome in predictors:
        raise AnalysisError("The outcome variable cannot also be a predictor.")
    require_columns(df, outcome, *predictors, *(extra or []))
    used = df[[outcome, *predictors, *(extra or [])]].dropna()
    columns: dict[str, pd.Series] = {}
    references: dict[str, str] = {}
    term_of: dict[str, str] = {}
    for var in predictors:
        spec = schema.get(var, {})
        is_numeric = pd.api.types.is_numeric_dtype(used[var]) and not pd.api.types.is_bool_dtype(used[var])
        if is_numeric and spec.get("measurement_level", "ratio") != "nominal":
            columns[var] = used[var].astype(float)
            term_of[var] = var
            continue
        labels = used[var].map(lambda v: f"{v:g}" if isinstance(v, (float, np.floating)) else str(v))
        levels = sorted(labels.unique())
        if len(levels) < 2:
            raise AnalysisError(f"Predictor '{var}' has only one category among the complete records.")
        if len(levels) > 15:
            raise AnalysisError(f"Predictor '{var}' has {len(levels)} categories, too many to enter as dummy variables.")
        references[var] = levels[0]
        for level in levels[1:]:
            name = f"{var}[{level}]"
            columns[name] = (labels == level).astype(float)
            term_of[name] = var
    X = pd.DataFrame(columns, index=used.index)
    constant = [c for c in X.columns if X[c].nunique() < 2]
    if constant:
        raise AnalysisError(f"Predictor(s) with no variation among the complete records: {', '.join(constant)}")
    info = {"dropped": int(len(df) - len(used)), "references": references, "term_of": term_of, "predictors": predictors}
    return used, X, info


def _with_intercept(X: pd.DataFrame) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X.to_numpy(dtype=float)])


def _check_rank(design: np.ndarray, names: list[str]) -> None:
    if np.linalg.matrix_rank(design) < design.shape[1]:
        raise AnalysisError("The predictors are perfectly collinear (one is an exact combination of others). "
                            f"Remove a redundant predictor from: {', '.join(names)}.")


def vif(X: pd.DataFrame) -> dict[str, float]:
    """Variance inflation factor for each column of the predictor matrix."""
    if X.shape[1] < 2:
        return {c: 1.0 for c in X.columns}
    values = X.to_numpy(dtype=float)
    out = {}
    for i, name in enumerate(X.columns):
        others = np.column_stack([np.ones(len(values)), np.delete(values, i, axis=1)])
        beta, *_ = np.linalg.lstsq(others, values[:, i], rcond=None)
        resid = values[:, i] - others @ beta
        ss_tot = ((values[:, i] - values[:, i].mean()) ** 2).sum()
        r2 = 1 - (resid**2).sum() / ss_tot if ss_tot > 0 else 0.0
        out[name] = float("inf") if r2 >= 1 - 1e-12 else float(1 / (1 - r2))
    return out


def _vif_check(X: pd.DataFrame) -> tuple[dict, dict]:
    values = vif(X)
    worst = max(values.values()) if values else 1.0
    ok = worst < 5
    note = (f"Largest VIF = {worst:.2f}. " + ("No multicollinearity concern (all VIF < 5)." if ok else
            "VIF of 5-10 is a moderate and above 10 a serious multicollinearity problem: coefficients and their p-values become unstable."))
    return values, A._check("No multicollinearity", "Variance inflation factor", worst, None, ok if X.shape[1] > 1 else None,
                            note if X.shape[1] > 1 else "Only one predictor, so multicollinearity does not apply.")


def _sample(arrays: dict[str, np.ndarray]) -> dict[str, list[float]]:
    n = len(next(iter(arrays.values())))
    if n > MAX_DIAGNOSTIC_POINTS:
        idx = np.linspace(0, n - 1, MAX_DIAGNOSTIC_POINTS).astype(int)
        arrays = {k: v[idx] for k, v in arrays.items()}
    return {k: [float(x) for x in v] for k, v in arrays.items()}


# --------------------------------------------------------------------------- #
# linear regression (OLS)
# --------------------------------------------------------------------------- #
def ols_fit(design: np.ndarray, y: np.ndarray, robust: bool = False) -> dict:
    """Closed-form OLS. ``robust=True`` returns HC3 standard errors."""
    n, k = design.shape
    xtx_inv = np.linalg.inv(design.T @ design)
    beta = xtx_inv @ design.T @ y
    fitted = design @ beta
    resid = y - fitted
    sse = float(resid @ resid)
    df_resid = n - k
    sigma2 = sse / df_resid
    leverage = np.einsum("ij,jk,ik->i", design, xtx_inv, design)
    if robust:
        omega = (resid / (1 - np.clip(leverage, None, 1 - 1e-10))) ** 2
        cov = xtx_inv @ (design.T * omega) @ design @ xtx_inv
    else:
        cov = sigma2 * xtx_inv
    sst = float(((y - y.mean()) ** 2).sum())
    llf = -n / 2 * (math.log(2 * math.pi) + math.log(sse / n) + 1) if sse > 0 else float("inf")
    return {"beta": beta, "cov": cov, "se": np.sqrt(np.diag(cov)), "fitted": fitted, "resid": resid, "sse": sse, "sst": sst,
            "df_resid": df_resid, "sigma2": sigma2, "leverage": leverage, "llf": llf, "n": n, "k": k}


def linear_regression(df, outcome, predictors, schema=None, alpha=0.05, robust=False, **_):
    """Simple or multiple linear regression with full diagnostics."""
    used, X, info = build_design(df, outcome, predictors, schema)
    y = numeric(used[outcome]).to_numpy()
    if np.isnan(y).any():
        raise AnalysisError(f"The outcome '{outcome}' must be numeric for linear regression.")
    n, p = len(y), X.shape[1]
    if n < p + 3:
        raise InsufficientDataError(f"{n} complete record(s) for {p} predictor term(s).")
    if np.ptp(y) == 0:
        raise AnalysisError(f"The outcome '{outcome}' has no variation.")
    design = _with_intercept(X)
    names = ["(Intercept)", *X.columns]
    _check_rank(design, names[1:])
    fit = ols_fit(design, y, robust=bool(robust))
    beta, se = fit["beta"], fit["se"]
    t = beta / se
    pvals = 2 * stats.t.sf(np.abs(t), fit["df_resid"])
    crit = stats.t.ppf(0.975, fit["df_resid"])
    r2 = 1 - fit["sse"] / fit["sst"]
    adj_r2 = 1 - (1 - r2) * (n - 1) / fit["df_resid"]
    f_stat = ((fit["sst"] - fit["sse"]) / p) / fit["sigma2"]
    f_p = float(stats.f.sf(f_stat, p, fit["df_resid"]))
    sd_y = y.std(ddof=1)
    std_beta = [None] + [float(beta[i + 1] * X.iloc[:, i].std(ddof=1) / sd_y) for i in range(p)]

    simple = len(info["predictors"]) == 1 and p == 1
    method = "simple_linear_regression" if simple else "multiple_linear_regression"
    res = new_result(method, "Simple linear regression" if simple else "Multiple linear regression", n=n,
                     variables={"outcome": outcome, "predictors": info["predictors"]}, alpha=alpha)
    res["statistic"] = {"name": "F", "value": float(f_stat)}
    res["df"] = f"{p}, {fit['df_resid']}"
    res["p_value"] = f_p
    res["model_fit"] = {"r_squared": float(r2), "adj_r_squared": float(adj_r2), "rmse": float(math.sqrt(fit["sigma2"])),
                        "aic": float(-2 * fit["llf"] + 2 * (p + 1)), "bic": float(-2 * fit["llf"] + math.log(n) * (p + 1)),
                        "f": float(f_stat), "f_p": f_p, "standard_errors": "HC3 robust" if robust else "classical"}
    res["coefficients"] = [
        {"term": names[i], "variable": info["term_of"].get(names[i]), "b": float(beta[i]), "se": float(se[i]), "t": float(t[i]),
         "p_value": float(pvals[i]), "ci_low": float(beta[i] - crit * se[i]), "ci_high": float(beta[i] + crit * se[i]),
         "beta_std": std_beta[i]} for i in range(p + 1)]
    f2 = r2 / (1 - r2) if r2 < 1 else None
    res["effect_sizes"] = [
        {"name": "R²", "value": float(r2), "magnitude": "small" if r2 < 0.13 else "medium" if r2 < 0.26 else "large",
         "ci_low": None, "ci_high": None, "ci_level": None,
         "note": f"The model accounts for {100 * r2:.1f}% of the variance in {outcome} (adjusted R² = {adj_r2:.3f})."},
        {"name": "Cohen's f²", "value": f2, "magnitude": None if f2 is None else ("small" if f2 < 0.15 else "medium" if f2 < 0.35 else "large"),
         "ci_low": None, "ci_high": None, "ci_level": None, "note": None},
    ]
    res["estimates"] = [{"name": c["term"], "value": c["b"], "ci_low": c["ci_low"], "ci_high": c["ci_high"], "ci_level": 0.95}
                        for c in res["coefficients"][1:]]

    # ---- diagnostics -------------------------------------------------------
    resid, lev = fit["resid"], np.clip(fit["leverage"], 0, 1 - 1e-10)
    student = resid / np.sqrt(fit["sigma2"] * (1 - lev))
    cooks = student**2 / (p + 1) * lev / (1 - lev)
    norm = A.normality(resid, "the residuals", alpha)
    aux = ols_fit(design, resid**2)
    bp = n * (1 - aux["sse"] / aux["sst"]) if aux["sst"] > 0 else 0.0
    bp_p = float(stats.chi2.sf(bp, p))
    homo = A._check("Homoscedasticity (constant residual variance)", "Breusch-Pagan (Koenker)", bp, bp_p, bool(bp_p > alpha),
                    "Residual variance looks constant." if bp_p > alpha else
                    "Residual variance is not constant (heteroscedasticity): classical standard errors and p-values are unreliable.")
    dw = float(np.sum(np.diff(resid) ** 2) / np.sum(resid**2))
    auto = A._check("No autocorrelation of residuals", "Durbin-Watson", dw, None, bool(1.5 <= dw <= 2.5),
                    f"Durbin-Watson = {dw:.2f} (values near 2 indicate no first-order autocorrelation). "
                    "Only meaningful when rows are in a time or collection order.")
    vifs, vif_check = _vif_check(X)
    influential = int((cooks > 4 / n).sum())
    infl = A._check("No unduly influential observations", "Cook's distance", float(cooks.max()), None, bool(cooks.max() < 1),
                    f"Largest Cook's distance = {cooks.max():.3f}; {influential} observation(s) exceed 4/n. "
                    + ("No single observation dominates the model." if cooks.max() < 1 else "At least one observation strongly influences the estimates; check it."))
    linear = A._check("Linearity", None, None, None, None,
                      "Inspect the residuals-vs-fitted plot: a curved pattern means the relationship is not linear.")
    res["assumptions"] = [linear, norm, homo, auto, vif_check, infl, A.independence_note()]
    for c in res["coefficients"][1:]:
        c["vif"] = vifs.get(c["term"])
    res["diagnostics"] = _sample({"fitted": fit["fitted"], "residuals": resid, "standardized_residuals": student, "cooks_distance": cooks})

    res["tables"] = [
        table("Model summary", ["R²", "Adjusted R²", "RMSE", "F", "df1", "df2", "p", "AIC", "BIC"],
              [[r2, adj_r2, math.sqrt(fit["sigma2"]), f_stat, p, fit["df_resid"], f_p, res["model_fit"]["aic"], res["model_fit"]["bic"]]]),
        table("Coefficients", ["Term", "B", "SE", "t", "p", "95% CI low", "95% CI high", "Beta (standardised)", "VIF"],
              [[c["term"], c["b"], c["se"], c["t"], c["p_value"], c["ci_low"], c["ci_high"], c["beta_std"], c.get("vif")] for c in res["coefficients"]],
              note=("Standard errors are heteroscedasticity-robust (HC3). " if robust else "")
              + "".join(f"Reference category for {v}: {r}. " for v, r in info["references"].items())),
    ]
    if homo["satisfied"] is False and not robust:
        res["warnings"].append("The residual variance appears non-constant. Re-run with robust (HC3) standard errors, or consider transforming the outcome.")
    if norm["satisfied"] is False and n < 50:
        res["warnings"].append("Residuals are not normally distributed and the sample is small, so p-values and confidence intervals may be inaccurate.")
    if vif_check["satisfied"] is False:
        res["warnings"].append("Multicollinearity detected: consider removing or combining highly related predictors.")
    if n / max(p, 1) < 10:
        res["warnings"].append(f"Only {n / p:.1f} observations per predictor term (at least 10-15 is recommended); the model may be over-fitted.")
    if info["dropped"]:
        res["warnings"].append(f"{info['dropped']} record(s) with a missing value on any model variable were excluded (listwise deletion).")

    res = finalize(res)
    res["apa"] = f"F({p}, {fit['df_resid']}) = {fmt_num(f_stat, 2)}, {fmt_p(f_p)}, R2 = {fmt_num(r2, 3)}, adjusted R2 = {fmt_num(adj_r2, 3)}"
    sig_terms = [c for c in res["coefficients"][1:] if c["p_value"] < alpha]
    if res["significant"]:
        parts = [f"{c['term']} (B = {fmt_num(c['b'])}, {fmt_p(c['p_value'])})" for c in sig_terms]
        res["summary"] = (f"The model is statistically significant and explains {100 * r2:.1f}% of the variance in {outcome} ({res['apa']}). "
                          + (f"Significant predictors: {'; '.join(parts)}. " if parts else "No individual predictor is significant on its own. ")
                          + (f"Each one-unit increase in {sig_terms[0]['term']} is associated with a change of {fmt_num(sig_terms[0]['b'])} in {outcome}"
                             + (", holding the other predictors constant. " if p > 1 else ". ") if sig_terms else "")
                          + "These are associations: regression on observational data does not establish cause and effect.")
    else:
        res["summary"] = (f"The model is not statistically significant ({res['apa']}). The predictors do not explain a reliable share of the variance in {outcome}.")
    return res


# --------------------------------------------------------------------------- #
# generalised linear models by IRLS
# --------------------------------------------------------------------------- #
def glm_fit(design: np.ndarray, y: np.ndarray, family: str, max_iter: int = 100, tol: float = 1e-10) -> dict:
    """Binomial (logit) or Poisson (log) GLM by iteratively reweighted least squares."""
    if family == "binomial":
        mu = (y + 0.5) / 2
        eta = np.log(mu / (1 - mu))
    elif family == "poisson":
        mu = (y + y.mean()) / 2 + 1e-8
        eta = np.log(mu)
    else:
        raise AnalysisError(f"Unsupported GLM family: {family}")

    def loglik(m: np.ndarray) -> float:
        if family == "binomial":
            m = np.clip(m, 1e-12, 1 - 1e-12)
            return float(np.sum(y * np.log(m) + (1 - y) * np.log(1 - m)))
        m = np.clip(m, 1e-12, None)
        return float(np.sum(y * np.log(m) - m - special.gammaln(y + 1)))

    beta = np.zeros(design.shape[1])
    previous, converged = -np.inf, False
    iterations = 0
    for iterations in range(1, max_iter + 1):
        weight = np.clip(mu * (1 - mu), 1e-10, None) if family == "binomial" else np.clip(mu, 1e-10, None)
        z = eta + (y - mu) / weight
        xtw = design.T * weight
        try:
            beta = np.linalg.solve(xtw @ design, xtw @ z)
        except np.linalg.LinAlgError as exc:
            raise AnalysisError("The model could not be estimated (singular information matrix). Check for redundant predictors.") from exc
        eta = np.clip(design @ beta, -30, 30)
        mu = special.expit(eta) if family == "binomial" else np.exp(eta)
        current = loglik(mu)
        if abs(current - previous) < tol * (abs(current) + 1):
            converged = True
            break
        previous = current
    weight = np.clip(mu * (1 - mu), 1e-10, None) if family == "binomial" else np.clip(mu, 1e-10, None)
    cov = np.linalg.inv((design.T * weight) @ design)
    return {"beta": beta, "cov": cov, "se": np.sqrt(np.diag(cov)), "mu": mu, "llf": loglik(mu), "converged": converged,
            "iterations": iterations}


def _glm_coefficients(names, fit, term_of, exp_label):
    beta, se = fit["beta"], fit["se"]
    z = beta / se
    pvals = 2 * stats.norm.sf(np.abs(z))
    crit = stats.norm.ppf(0.975)
    rows = []
    for i, name in enumerate(names):
        lo, hi = beta[i] - crit * se[i], beta[i] + crit * se[i]
        rows.append({"term": name, "variable": term_of.get(name), "b": float(beta[i]), "se": float(se[i]), "z": float(z[i]),
                     "p_value": float(pvals[i]), "ci_low": float(lo), "ci_high": float(hi),
                     exp_label: float(math.exp(min(beta[i], 700))), f"{exp_label}_ci_low": float(math.exp(min(lo, 700))),
                     f"{exp_label}_ci_high": float(math.exp(min(hi, 700)))})
    return rows


def _cross_validated_auc(X: pd.DataFrame, y: np.ndarray, folds: int = 5) -> tuple[float | None, int]:
    """Out-of-sample AUC from stratified k-fold cross-validation. Returns (None, folds) if it cannot be computed."""
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import StratifiedKFold
        k = min(folds, int(min(y.sum(), len(y) - y.sum())))
        if k < 2:
            return None, 0
        scores = np.empty(len(y))
        for train, test in StratifiedKFold(n_splits=k, shuffle=True, random_state=0).split(X, y):
            model = LogisticRegression(max_iter=1000).fit(X.iloc[train], y[train])
            scores[test] = model.predict_proba(X.iloc[test])[:, 1]
        return float(roc_auc_score(y, scores)), k
    except Exception:  # pragma: no cover
        return None, 0


def logistic_regression(df, outcome, predictors, schema=None, alpha=0.05, event=None, **_):
    """Binary logistic regression (maximum likelihood)."""
    used, X, info = build_design(df, outcome, predictors, schema)
    labels = used[outcome].map(lambda v: f"{v:g}" if isinstance(v, (float, np.floating)) else str(v))
    levels = sorted(labels.unique())
    if len(levels) != 2:
        raise AnalysisError(f"Logistic regression needs an outcome with exactly two categories; '{outcome}' has {len(levels)}.")
    event = str(event) if event is not None and str(event) in levels else levels[1]
    y = (labels == event).to_numpy(dtype=float)
    n, p = len(y), X.shape[1]
    events, non_events = int(y.sum()), int(n - y.sum())
    if min(events, non_events) < 5 or n < p + 10:
        raise InsufficientDataError(f"{events} event(s) and {non_events} non-event(s) among {n} complete record(s).")
    design = _with_intercept(X)
    names = ["(Intercept)", *X.columns]
    _check_rank(design, names[1:])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = glm_fit(design, y, "binomial")
        null = glm_fit(np.ones((n, 1)), y, "binomial")
    lr = 2 * (fit["llf"] - null["llf"])
    lr_p = float(stats.chi2.sf(lr, p))
    mcfadden = 1 - fit["llf"] / null["llf"]
    cox_snell = 1 - math.exp(-lr / n)
    nagelkerke = cox_snell / (1 - math.exp(2 * null["llf"] / n))
    predicted = (fit["mu"] >= 0.5).astype(float)
    tp, tn = int(((predicted == 1) & (y == 1)).sum()), int(((predicted == 0) & (y == 0)).sum())
    fp, fn = int(((predicted == 1) & (y == 0)).sum()), int(((predicted == 0) & (y == 1)).sum())
    try:
        from sklearn.metrics import roc_auc_score
        auc = float(roc_auc_score(y, fit["mu"]))
    except Exception:  # pragma: no cover
        auc = None
    cv_auc, cv_folds = _cross_validated_auc(X, y)

    res = new_result("logistic_regression", "Binary logistic regression", n=n,
                     variables={"outcome": outcome, "predictors": info["predictors"], "event": event}, alpha=alpha)
    res["statistic"] = {"name": "LR chi2", "value": float(lr)}
    res["df"] = p
    res["p_value"] = lr_p
    res["coefficients"] = _glm_coefficients(names, fit, info["term_of"], "odds_ratio")
    res["model_fit"] = {"log_likelihood": fit["llf"], "null_log_likelihood": null["llf"], "mcfadden_r2": float(mcfadden),
                        "nagelkerke_r2": float(nagelkerke), "aic": float(-2 * fit["llf"] + 2 * (p + 1)),
                        "accuracy": (tp + tn) / n, "sensitivity": tp / events, "specificity": tn / non_events, "auc": auc,
                        "cv_auc": cv_auc, "cv_folds": cv_folds,
                        "converged": fit["converged"], "events": events, "non_events": non_events}
    res["effect_sizes"] = [{"name": f"Odds ratio: {c['term']}", "value": c["odds_ratio"], "magnitude": None, "ci_low": c["odds_ratio_ci_low"],
                            "ci_high": c["odds_ratio_ci_high"], "ci_level": 0.95, "note": None} for c in res["coefficients"][1:]]
    res["effect_sizes"].append({"name": "Nagelkerke R²", "value": float(nagelkerke), "magnitude": None, "ci_low": None,
                                "ci_high": None, "ci_level": None, "note": "A pseudo-R²; not a proportion of variance explained."})
    epv = min(events, non_events) / p
    vifs, vif_check = _vif_check(X)
    res["assumptions"] = [
        A._check("Binary outcome", None, None, None, True, f"Modelled event: {outcome} = {event} ({events} of {n})."),
        A._check("Adequate events per predictor", "Events per variable", epv, None, bool(epv >= 10),
                 f"{epv:.1f} events per predictor term (at least 10 is recommended)."),
        vif_check,
        A._check("Linearity of the logit", None, None, None, None,
                 "Continuous predictors are assumed to be linearly related to the log-odds; check with a Box-Tidwell term or by categorising the predictor."),
        A.independence_note(),
    ]
    res["tables"] = [
        table("Model summary", ["LR chi2", "df", "p", "McFadden R²", "Nagelkerke R²", "AIC", "Accuracy", "Apparent AUC", "Cross-validated AUC"],
              [[lr, p, lr_p, mcfadden, nagelkerke, res["model_fit"]["aic"], (tp + tn) / n, auc, cv_auc]]),
        table("Coefficients", ["Term", "B", "SE", "z", "p", "Odds ratio", "OR 95% CI low", "OR 95% CI high"],
              [[c["term"], c["b"], c["se"], c["z"], c["p_value"], c["odds_ratio"], c["odds_ratio_ci_low"], c["odds_ratio_ci_high"]] for c in res["coefficients"]],
              note=f"Event modelled: {outcome} = {event}. " + "".join(f"Reference category for {v}: {r}. " for v, r in info["references"].items())),
        table("Classification table (cut-off 0.5)", ["", f"Predicted {event}", "Predicted other"],
              [[f"Observed {event}", tp, fn], ["Observed other", fp, tn]]),
    ]
    separated = (not fit["converged"]) or np.any(np.abs(fit["beta"]) > 15) or np.any(fit["se"] > 1e3)
    if separated:
        res["warnings"].append("The model shows signs of complete or quasi-complete separation (a predictor almost perfectly predicts the outcome). "
                               "Coefficients, odds ratios and p-values are unreliable; do not interpret them.")
    if epv < 10:
        res["warnings"].append("Too few events per predictor: the model is likely over-fitted. Use fewer predictors or collect more data.")
    if vif_check["satisfied"] is False:
        res["warnings"].append("Multicollinearity detected among the predictors.")
    if info["dropped"]:
        res["warnings"].append(f"{info['dropped']} record(s) with a missing value on any model variable were excluded (listwise deletion).")
    res = finalize(res)
    res["apa"] = f"LR chi2({p}) = {fmt_num(lr, 2)}, {fmt_p(lr_p)}, Nagelkerke R2 = {fmt_num(nagelkerke, 3)}"
    sig_terms = [c for c in res["coefficients"][1:] if c["p_value"] < alpha]
    if res["significant"]:
        parts = [f"{c['term']} (OR = {fmt_num(c['odds_ratio'], 2)}, 95% CI {fmt_num(c['odds_ratio_ci_low'], 2)} to {fmt_num(c['odds_ratio_ci_high'], 2)}, {fmt_p(c['p_value'])})" for c in sig_terms]
        res["summary"] = (f"The model predicts {outcome} = {event} significantly better than a model with no predictors ({res['apa']}). "
                          + (f"Significant predictors: {'; '.join(parts)}. An odds ratio above 1 means higher odds of {event}. " if parts else "No individual predictor is significant. ")
                          + "These are associations, not evidence of causation.")
    else:
        res["summary"] = f"The model does not predict {outcome} significantly better than a model with no predictors ({res['apa']})."
    return res


def poisson_regression(df, outcome, predictors, schema=None, alpha=0.05, **_):
    """Poisson regression for count outcomes, with an overdispersion check."""
    used, X, info = build_design(df, outcome, predictors, schema)
    y = numeric(used[outcome]).to_numpy()
    if np.isnan(y).any() or (y < 0).any() or (np.mod(y, 1) != 0).any():
        raise AnalysisError(f"Poisson regression needs a count outcome (non-negative whole numbers); '{outcome}' is not.")
    n, p = len(y), X.shape[1]
    if n < p + 10:
        raise InsufficientDataError(f"{n} complete record(s) for {p} predictor term(s).")
    if y.sum() == 0:
        raise AnalysisError("Every count is zero, so the model cannot be estimated.")
    design = _with_intercept(X)
    names = ["(Intercept)", *X.columns]
    _check_rank(design, names[1:])
    fit = glm_fit(design, y, "poisson")
    null = glm_fit(np.ones((n, 1)), y, "poisson")
    lr = 2 * (fit["llf"] - null["llf"])
    lr_p = float(stats.chi2.sf(lr, p))
    pearson = float(np.sum((y - fit["mu"]) ** 2 / fit["mu"]))
    dispersion = pearson / (n - p - 1)

    res = new_result("poisson_regression", "Poisson regression", n=n,
                     variables={"outcome": outcome, "predictors": info["predictors"]}, alpha=alpha)
    res["statistic"] = {"name": "LR chi2", "value": float(lr)}
    res["df"] = p
    res["p_value"] = lr_p
    res["coefficients"] = _glm_coefficients(names, fit, info["term_of"], "rate_ratio")
    res["model_fit"] = {"log_likelihood": fit["llf"], "null_log_likelihood": null["llf"], "aic": float(-2 * fit["llf"] + 2 * (p + 1)),
                        "pearson_chi2": pearson, "dispersion": float(dispersion), "mcfadden_r2": float(1 - fit["llf"] / null["llf"]),
                        "converged": fit["converged"]}
    res["effect_sizes"] = [{"name": f"Incidence rate ratio: {c['term']}", "value": c["rate_ratio"], "magnitude": None,
                            "ci_low": c["rate_ratio_ci_low"], "ci_high": c["rate_ratio_ci_high"], "ci_level": 0.95, "note": None}
                           for c in res["coefficients"][1:]]
    ok = dispersion <= 1.5
    vifs, vif_check = _vif_check(X)
    res["assumptions"] = [
        A._check("Equidispersion (variance equals the mean)", "Pearson chi2 / df", dispersion, None, bool(ok),
                 f"Dispersion = {dispersion:.2f} (about 1 expected). " + ("No overdispersion." if ok else
                 "The counts are overdispersed: Poisson standard errors are too small and p-values too optimistic.")),
        vif_check, A.independence_note(),
    ]
    res["tables"] = [
        table("Model summary", ["LR chi2", "df", "p", "AIC", "Dispersion"], [[lr, p, lr_p, res["model_fit"]["aic"], dispersion]]),
        table("Coefficients", ["Term", "B", "SE", "z", "p", "Rate ratio", "RR 95% CI low", "RR 95% CI high"],
              [[c["term"], c["b"], c["se"], c["z"], c["p_value"], c["rate_ratio"], c["rate_ratio_ci_low"], c["rate_ratio_ci_high"]] for c in res["coefficients"]],
              note="".join(f"Reference category for {v}: {r}. " for v, r in info["references"].items()) or None),
    ]
    if not ok:
        res["warnings"].append("Overdispersion detected. Use negative-binomial regression instead of Poisson for trustworthy p-values.")
    if info["dropped"]:
        res["warnings"].append(f"{info['dropped']} record(s) with a missing value on any model variable were excluded (listwise deletion).")
    res = finalize(res)
    res["apa"] = f"LR chi2({p}) = {fmt_num(lr, 2)}, {fmt_p(lr_p)}"
    sig_terms = [c for c in res["coefficients"][1:] if c["p_value"] < alpha]
    verdict = "fits significantly better than" if res["significant"] else "does not fit significantly better than"
    res["summary"] = (f"The Poisson model {verdict} a model with no predictors ({res['apa']}). "
                      + ("Significant predictors: " + "; ".join(f"{c['term']} (rate ratio = {fmt_num(c['rate_ratio'], 2)}, {fmt_p(c['p_value'])})" for c in sig_terms) + ". " if sig_terms and res["significant"] else "")
                      + ("" if ok else "Because the counts are overdispersed, these p-values are too optimistic."))
    return res


# --------------------------------------------------------------------------- #
# models delegated to statsmodels
# --------------------------------------------------------------------------- #
def _statsmodels():
    try:
        import statsmodels.api as sm
        return sm
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise MethodNotImplementedError("This model requires the 'statsmodels' package, which is not installed on the server.") from exc


def negative_binomial_regression(df, outcome, predictors, schema=None, alpha=0.05, **_):
    """Negative-binomial (NB2) regression for overdispersed counts."""
    sm = _statsmodels()
    used, X, info = build_design(df, outcome, predictors, schema)
    y = numeric(used[outcome]).to_numpy()
    if np.isnan(y).any() or (y < 0).any() or (np.mod(y, 1) != 0).any():
        raise AnalysisError(f"Negative-binomial regression needs a count outcome; '{outcome}' is not.")
    n, p = len(y), X.shape[1]
    if n < p + 20:
        raise InsufficientDataError(f"{n} complete record(s) for {p} predictor term(s).")
    design = sm.add_constant(X.astype(float), has_constant="add")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = sm.NegativeBinomial(y, design).fit(disp=0, maxiter=200)
    conf = model.conf_int()
    res = new_result("negative_binomial_regression", "Negative-binomial regression", n=n,
                     variables={"outcome": outcome, "predictors": info["predictors"]}, alpha=alpha)
    res["statistic"] = {"name": "LR chi2", "value": float(model.llr)}
    res["df"] = p
    res["p_value"] = float(model.llr_pvalue)
    names = ["(Intercept)", *X.columns]
    coefs = []
    for i, name in enumerate(names):
        b = float(model.params.iloc[i])
        lo, hi = float(conf.iloc[i, 0]), float(conf.iloc[i, 1])
        coefs.append({"term": name, "variable": info["term_of"].get(name), "b": b, "se": float(model.bse.iloc[i]), "z": float(model.tvalues.iloc[i]),
                      "p_value": float(model.pvalues.iloc[i]), "ci_low": lo, "ci_high": hi, "rate_ratio": math.exp(b),
                      "rate_ratio_ci_low": math.exp(lo), "rate_ratio_ci_high": math.exp(hi)})
    res["coefficients"] = coefs
    res["model_fit"] = {"log_likelihood": float(model.llf), "aic": float(model.aic), "alpha_dispersion": float(model.params.iloc[-1]),
                        "converged": bool(model.mle_retvals.get("converged", True))}
    res["assumptions"] = [A.independence_note()]
    res["tables"] = [table("Coefficients", ["Term", "B", "SE", "z", "p", "Rate ratio", "RR 95% CI low", "RR 95% CI high"],
                           [[c["term"], c["b"], c["se"], c["z"], c["p_value"], c["rate_ratio"], c["rate_ratio_ci_low"], c["rate_ratio_ci_high"]] for c in coefs])]
    if info["dropped"]:
        res["warnings"].append(f"{info['dropped']} record(s) with a missing value were excluded (listwise deletion).")
    res = finalize(res)
    res["apa"] = f"LR chi2({p}) = {fmt_num(model.llr, 2)}, {fmt_p(model.llr_pvalue)}"
    verdict = "fits significantly better than" if res["significant"] else "does not fit significantly better than"
    res["summary"] = f"The negative-binomial model {verdict} a model with no predictors ({res['apa']})."
    return res


def mixed_effects_model(df, outcome, predictors, group, schema=None, alpha=0.05, **_):
    """Linear mixed-effects model with a random intercept for ``group``."""
    sm = _statsmodels()
    if not group:
        raise AnalysisError("Choose the grouping (cluster) variable for the random intercept.")
    used, X, info = build_design(df, outcome, predictors, schema, extra=[group])
    y = numeric(used[outcome]).to_numpy()
    if np.isnan(y).any():
        raise AnalysisError(f"The outcome '{outcome}' must be numeric.")
    groups = used[group].astype(str)
    n, n_groups = len(y), groups.nunique()
    if n_groups < 5:
        raise InsufficientDataError(f"Only {n_groups} cluster(s) in '{group}'; a random effect cannot be estimated reliably with fewer than 5.")
    design = sm.add_constant(X.astype(float), has_constant="add")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = sm.MixedLM(y, design, groups=groups.to_numpy()).fit(reml=True)
    conf = model.conf_int()
    names = ["(Intercept)", *X.columns]
    coefs = []
    for i, name in enumerate(names):
        coefs.append({"term": name, "variable": info["term_of"].get(name), "b": float(model.fe_params.iloc[i]), "se": float(model.bse_fe.iloc[i]),
                      "z": float(model.tvalues.iloc[i]), "p_value": float(model.pvalues.iloc[i]),
                      "ci_low": float(conf.iloc[i, 0]), "ci_high": float(conf.iloc[i, 1])})
    var_group = float(np.asarray(model.cov_re)[0, 0])
    var_resid = float(model.scale)
    icc = var_group / (var_group + var_resid) if (var_group + var_resid) > 0 else None
    res = new_result("mixed_effects", "Linear mixed-effects model (random intercept)", n=n,
                     variables={"outcome": outcome, "predictors": info["predictors"], "group": group}, alpha=alpha)
    res["coefficients"] = coefs
    res["model_fit"] = {"log_likelihood": float(model.llf), "n_groups": int(n_groups), "group_variance": var_group,
                        "residual_variance": var_resid, "icc": icc, "converged": bool(model.converged)}
    res["effect_sizes"] = [{"name": "Intraclass correlation (ICC)", "value": icc, "magnitude": None, "ci_low": None, "ci_high": None, "ci_level": None,
                            "note": None if icc is None else f"{100 * icc:.1f}% of the outcome variance lies between {group} clusters."}]
    res["assumptions"] = [A.normality(np.asarray(model.resid), "the residuals", alpha),
                          A._check("Clusters are independent", None, None, None, None, f"Observations may be correlated within {group} but clusters must be independent of one another.")]
    res["tables"] = [table("Fixed effects", ["Term", "B", "SE", "z", "p", "95% CI low", "95% CI high"],
                           [[c["term"], c["b"], c["se"], c["z"], c["p_value"], c["ci_low"], c["ci_high"]] for c in coefs]),
                     table("Random effects", ["Component", "Variance"], [[f"{group} (intercept)", var_group], ["Residual", var_resid]])]
    if not model.converged:
        res["warnings"].append("The model did not converge; estimates are unreliable.")
    if info["dropped"]:
        res["warnings"].append(f"{info['dropped']} record(s) with a missing value were excluded (listwise deletion).")
    res = finalize(res)
    sig_terms = [c for c in coefs[1:] if c["p_value"] < alpha]
    res["summary"] = (f"A mixed-effects model with a random intercept for {group} ({n_groups} clusters, n = {n}) was fitted. "
                      + ("Significant fixed effects: " + "; ".join(f"{c['term']} (B = {fmt_num(c['b'])}, {fmt_p(c['p_value'])})" for c in sig_terms) + "."
                         if sig_terms else "No fixed effect is statistically significant."))
    return res
