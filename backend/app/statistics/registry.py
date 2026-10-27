"""Registry of statistical methods.

One place describes every method the platform knows about: what it is called,
which variables it needs, and whether it is implemented. The API, the method
recommender, the UI and the docs all read this table, so a method can never be
offered in one place and missing in another.

Methods that are registered with ``implemented=False`` raise
``MethodNotImplementedError`` when run. They never return made-up output.
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from app.statistics import correlation, group_tests, multivariate, regression
from app.statistics.utils import AnalysisError, MethodNotImplementedError, numeric, software_versions

# role kinds: numeric | categorical | any ; "multiple" roles take a list
def _role(name: str, label: str, kind: str, multiple: bool = False, minimum: int = 1) -> dict:
    return {"name": name, "label": label, "kind": kind, "multiple": multiple, "min": minimum}


_XY_NUM = [_role("x", "First variable", "numeric"), _role("y", "Second variable", "numeric")]
_XY_CAT = [_role("x", "Row variable", "categorical"), _role("y", "Column variable", "categorical")]
_OUT_GROUP = [_role("outcome", "Outcome (numeric)", "numeric"), _role("group", "Grouping variable", "categorical")]
_PAIR = [_role("first", "First measurement", "numeric"), _role("second", "Second measurement", "numeric")]
_MEASURES = [_role("measures", "Repeated measurements (one column each)", "numeric", True, 3)]
_REG = [_role("outcome", "Outcome (dependent variable)", "any"), _role("predictors", "Predictors (independent variables)", "any", True)]
_VARS = [_role("variables", "Variables", "numeric", True, 2)]

METHODS: dict[str, dict[str, Any]] = {}


def _register(key: str, name: str, category: str, roles: list[dict], func: Callable | None, level: str,
              description: str, options: list[str] | None = None, not_implemented_reason: str | None = None) -> None:
    METHODS[key] = {"key": key, "name": name, "category": category, "roles": roles, "func": func,
                    "implemented": func is not None, "typical_level": level, "description": description,
                    "options": options or [], "not_implemented_reason": not_implemented_reason}


# ---- correlation -----------------------------------------------------------
_register("pearson", "Pearson correlation", "Correlation", _XY_NUM, correlation.pearson, "undergraduate",
          "Linear relationship between two continuous variables.", ["alternative"])
_register("spearman", "Spearman rank correlation", "Correlation", _XY_NUM, correlation.spearman, "undergraduate",
          "Monotonic relationship between two ordinal or non-normal variables.", ["alternative"])
_register("kendall", "Kendall's tau-b", "Correlation", _XY_NUM, correlation.kendall, "undergraduate",
          "Rank correlation suited to small samples and many tied values.", ["alternative"])
# ---- association -----------------------------------------------------------
_register("chi_square", "Chi-square test of independence", "Association", _XY_CAT, correlation.chi_square, "undergraduate",
          "Association between two categorical variables.")
_register("fisher_exact", "Fisher's exact test", "Association", _XY_CAT, correlation.fisher_exact, "undergraduate",
          "Association in a 2 x 2 table when expected counts are small.", ["alternative"])
# ---- group comparisons ------------------------------------------------------
_register("independent_t_test", "Independent-samples t-test", "Group comparison", _OUT_GROUP, group_tests.independent_t_test,
          "undergraduate", "Compare the means of two independent groups (Welch's version is used when variances differ).",
          ["alternative", "equal_var"])
_register("paired_t_test", "Paired-samples t-test", "Group comparison", _PAIR, group_tests.paired_t_test, "undergraduate",
          "Compare two measurements taken on the same participants.", ["alternative"])
_register("one_way_anova", "One-way ANOVA", "Group comparison", _OUT_GROUP, group_tests.one_way_anova, "undergraduate",
          "Compare the means of three or more independent groups, with Tukey post hoc tests.")
_register("repeated_measures_anova", "Repeated-measures ANOVA", "Group comparison", _MEASURES, group_tests.repeated_measures_anova,
          "masters", "Compare three or more measurements taken on the same participants.")
_register("mann_whitney", "Mann-Whitney U test", "Group comparison", _OUT_GROUP, group_tests.mann_whitney, "undergraduate",
          "Rank-based alternative to the independent t-test.", ["alternative"])
_register("wilcoxon", "Wilcoxon signed-rank test", "Group comparison", _PAIR, group_tests.wilcoxon_signed_rank, "undergraduate",
          "Rank-based alternative to the paired t-test.", ["alternative"])
_register("kruskal_wallis", "Kruskal-Wallis H test", "Group comparison", _OUT_GROUP, group_tests.kruskal_wallis, "undergraduate",
          "Rank-based alternative to one-way ANOVA.")
_register("friedman", "Friedman test", "Group comparison", _MEASURES, group_tests.friedman, "masters",
          "Rank-based alternative to repeated-measures ANOVA.")
# ---- regression -------------------------------------------------------------
_register("simple_linear_regression", "Simple linear regression", "Regression", _REG, regression.linear_regression, "undergraduate",
          "Predict a continuous outcome from one predictor.", ["robust"])
_register("multiple_linear_regression", "Multiple linear regression", "Regression", _REG, regression.linear_regression, "masters",
          "Predict a continuous outcome from several predictors, with full diagnostics.", ["robust"])
_register("logistic_regression", "Binary logistic regression", "Regression", _REG, regression.logistic_regression, "masters",
          "Predict a two-category outcome; reports odds ratios.", ["event"])
_register("poisson_regression", "Poisson regression", "Regression", _REG, regression.poisson_regression, "masters",
          "Model a count outcome; reports rate ratios and checks overdispersion.")
_register("negative_binomial_regression", "Negative-binomial regression", "Regression", _REG, regression.negative_binomial_regression,
          "phd", "Model an overdispersed count outcome (requires statsmodels).")
_register("mixed_effects", "Linear mixed-effects model", "Advanced", _REG + [_role("group", "Cluster / grouping variable", "categorical")],
          regression.mixed_effects_model, "phd", "Continuous outcome with observations nested in clusters (random intercept; requires statsmodels).")
# ---- multivariate -----------------------------------------------------------
_register("pca", "Principal component analysis", "Multivariate", [_role("variables", "Variables", "numeric", True, 3)], multivariate.pca,
          "masters", "Reduce many correlated variables to a few components.", ["n_components"])
_register("factor_analysis", "Exploratory factor analysis", "Multivariate", [_role("variables", "Items", "numeric", True, 4)],
          multivariate.factor_analysis, "masters", "Identify latent factors behind a set of items.", ["n_factors", "rotation"])
_register("cluster_analysis", "K-means cluster analysis", "Multivariate", _VARS, multivariate.cluster_analysis, "masters",
          "Group similar cases together (exploratory).", ["n_clusters"])
_register("cronbach_alpha", "Reliability analysis (Cronbach's alpha)", "Multivariate", _VARS, multivariate.cronbach_alpha, "masters",
          "Internal consistency of a multi-item scale.")
# ---- registered but NOT implemented (never fabricated) ----------------------
for _key, _name, _why in [
    ("two_way_anova", "Factorial (two-way) ANOVA / ANCOVA", "Factorial and covariate-adjusted designs are planned. Use multiple linear regression with dummy-coded factors as a valid alternative."),
    ("manova", "MANOVA", "Multivariate analysis of variance is not implemented yet."),
    ("ordinal_regression", "Ordinal logistic regression", "Ordinal regression is not implemented yet."),
    ("generalized_linear_model", "Generalised linear model (other families)", "Only the binomial, Poisson and negative-binomial families are implemented."),
    ("time_series", "Time-series analysis (ARIMA and related)", "Time-series modelling is not implemented yet. Time-series plots are available in the Visualization Studio."),
    ("survival_analysis", "Survival analysis (Kaplan-Meier, Cox)", "Survival analysis is not implemented yet."),
    ("sem", "Structural equation modelling", "SEM is not implemented. Factor analysis and regression are available as building blocks; use dedicated SEM software for the full model."),
]:
    _register(_key, _name, "Advanced", [], None, "phd", _why, not_implemented_reason=_why)


def catalogue() -> list[dict]:
    """Method list for the API/UI (without the Python callables)."""
    return [{k: v for k, v in m.items() if k != "func"} for m in METHODS.values()]


# --------------------------------------------------------------------------- #
# filters
# --------------------------------------------------------------------------- #
_OPS = {"eq", "ne", "gt", "ge", "lt", "le", "in", "not_missing"}


def apply_filters(df: pd.DataFrame, filters: list[dict] | None) -> pd.DataFrame:
    """Row filters recorded with the analysis so that it can be reproduced."""
    if not filters:
        return df
    mask = pd.Series(True, index=df.index)
    for f in filters:
        col, op, value = f.get("column"), f.get("op"), f.get("value")
        if col not in df.columns:
            raise AnalysisError(f"Filter refers to an unknown column: {col}")
        if op not in _OPS:
            raise AnalysisError(f"Unknown filter operator: {op}")
        series = df[col]
        if op == "not_missing":
            mask &= series.notna()
        elif op in ("gt", "ge", "lt", "le"):
            nums, target = numeric(series), float(value)
            mask &= {"gt": nums > target, "ge": nums >= target, "lt": nums < target, "le": nums <= target}[op]
        else:
            if pd.api.types.is_numeric_dtype(series):
                def as_num(v):
                    return float(v)
                values = [as_num(v) for v in (value if isinstance(value, list) else [value])]
                hit = series.isin(values)
            else:
                values = [str(v) for v in (value if isinstance(value, list) else [value])]
                hit = series.astype(str).isin(values) & series.notna()
            mask &= ~hit if op == "ne" else hit
    out = df.loc[mask]
    if out.empty:
        raise AnalysisError("The filters exclude every record.")
    return out


# --------------------------------------------------------------------------- #
# running
# --------------------------------------------------------------------------- #
def run_method(df: pd.DataFrame, schema: dict, method: str, variables: dict, params: dict | None = None,
               filters: list[dict] | None = None) -> dict:
    """Run one registered method and return its standard result dict."""
    if method not in METHODS:
        raise AnalysisError(f"Unknown statistical method: {method}")
    spec = METHODS[method]
    if not spec["implemented"]:
        raise MethodNotImplementedError(f"{spec['name']} is not implemented in this version. {spec['not_implemented_reason']} "
                                        "No results were produced.")
    params = dict(params or {})
    variables = dict(variables or {})
    for role in spec["roles"]:
        value = variables.get(role["name"])
        if role["multiple"]:
            if not isinstance(value, list) or len(value) < role["min"]:
                raise AnalysisError(f"'{role['label']}' needs at least {role['min']} variable(s).")
        elif not value or not isinstance(value, str):
            raise AnalysisError(f"Select a variable for '{role['label']}'.")
    allowed = {r["name"] for r in spec["roles"]}
    call_vars = {k: v for k, v in variables.items() if k in allowed}
    call_params = {k: v for k, v in params.items() if k in spec["options"] or k == "alpha"}
    alpha = float(call_params.get("alpha", 0.05))
    if not 0 < alpha < 0.5:
        raise AnalysisError("alpha must be between 0 and 0.5.")
    call_params["alpha"] = alpha
    data = apply_filters(df, filters)
    result = spec["func"](data, schema=schema, **call_vars, **call_params)
    result["records_in_dataset"] = int(len(df))
    result["records_after_filters"] = int(len(data))
    result["filters"] = filters or []
    result["software"] = software_versions()
    return result
