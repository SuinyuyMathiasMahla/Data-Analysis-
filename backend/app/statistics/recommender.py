"""Statistical-method recommendation engine (rule-based, deterministic).

The decision uses, in this order:

    research question / goal -> study design (paired or independent)
    -> variable types -> sample characteristics -> distribution
    -> assumption checks run on the actual data -> academic context

It recommends; it does not run anything. Every recommendation says *why*, lists
the assumption checks it ran, and names an alternative for when they fail.
The academic level changes only the depth of the follow-up advice - it never
makes the engine pick a more advanced method than the question needs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.profiling import variable_kind
from app.statistics import assumptions as A
from app.statistics.registry import METHODS
from app.statistics.utils import AnalysisError, numeric, require_columns, to_jsonable

OUTCOME_KINDS = ("auto", "continuous", "ordinal", "binary", "nominal", "count", "time_to_event")


def _option(method: str, reason: str) -> dict:
    spec = METHODS[method]
    return {"method": method, "name": spec["name"], "implemented": spec["implemented"], "reason": reason}


def _looks_like_count(series: pd.Series) -> bool:
    values = numeric(series).dropna()
    return bool(len(values) and (values >= 0).all() and (np.mod(values, 1) == 0).all() and values.nunique() > 2 and values.max() <= 100)


def _level_notes(level: str, family: str) -> list[str]:
    notes = {
        "undergraduate": ["Report the test statistic, p-value and an effect size, and illustrate the result with one clear chart.",
                          "State the assumptions you checked and what you did if one was not met."],
        "masters": ["Report effect sizes with confidence intervals, not only p-values.",
                    "Include the diagnostics (assumption checks) in an appendix and justify your choice of method in the methodology chapter.",
                    "If the variables form a multi-item scale, report its reliability (Cronbach's alpha) first."],
        "phd": ["Report effect sizes with confidence intervals and discuss practical as well as statistical significance.",
                "Justify the sample size with a prospective power analysis (Power & sample size tool).",
                "Consider a sensitivity analysis: repeat the test with a robust or non-parametric alternative and report whether conclusions change.",
                "If you run several tests on the same data, plan a correction for multiple comparisons."],
    }.get(level, [])
    if family == "regression" and level in ("masters", "phd"):
        notes.append("Add theoretically justified control variables rather than every available variable, and check the model diagnostics.")
    if family == "regression" and level == "phd":
        notes.append("If observations are clustered (students in classes, repeated measures), a mixed-effects model is more appropriate than ordinary regression.")
    return notes


def recommend(df: pd.DataFrame, schema: dict, *, outcome: str | None = None, predictors: list[str] | None = None,
              paired: bool = False, measures: list[str] | None = None, outcome_kind: str = "auto",
              academic_level: str = "undergraduate", study_design: str | None = None, goal: str | None = None) -> dict:
    """Recommend a method for the given variables. ``df`` is the typed frame."""
    predictors = [p for p in (predictors or []) if p]
    measures = [m for m in (measures or []) if m]
    require_columns(df, outcome, *predictors, *measures)
    if outcome_kind not in OUTCOME_KINDS:
        raise AnalysisError(f"outcome_kind must be one of: {', '.join(OUTCOME_KINDS)}.")
    why: list[str] = []
    checks: list[dict] = []
    warnings: list[str] = []
    alternatives: list[dict] = []
    primary: dict | None = None
    config: dict = {}
    family = "other"

    def kind_of(col: str) -> str:
        return variable_kind(df[col], schema.get(col))

    kinds = {c: kind_of(c) for c in [outcome, *predictors, *measures] if c}

    # ------------------------------------------------------------------ #
    # A. repeated / paired measurements in separate columns
    # ------------------------------------------------------------------ #
    if paired or measures:
        cols = measures or [c for c in [outcome, *predictors] if c]
        if len(cols) < 2:
            raise AnalysisError("For a paired or repeated-measures design, choose the two or more measurement columns.")
        bad = [c for c in cols if kinds.get(c, kind_of(c)) not in ("continuous", "ordinal")]
        if bad:
            raise AnalysisError(f"Paired/repeated designs need numeric measurement columns; not suitable: {', '.join(bad)}.")
        data = pd.DataFrame({c: numeric(df[c]) for c in cols}).dropna()
        n = len(data)
        ordinal = any(kinds.get(c, kind_of(c)) == "ordinal" for c in cols)
        family = "paired"
        why.append(f"The same participants were measured {len(cols)} times ({', '.join(cols)}), so the observations are related, not independent.")
        if len(cols) == 2:
            diff = (data[cols[0]] - data[cols[1]]).to_numpy()
            norm = A.normality(diff, "the paired differences")
            checks.append(norm)
            config = {"variables": {"first": cols[0], "second": cols[1]}}
            if ordinal or (norm["satisfied"] is False and n < 30):
                primary = _option("wilcoxon", "The measurements are ordinal." if ordinal else
                                  "The paired differences are not normally distributed and the sample is small.")
                alternatives.append(_option("paired_t_test", "Use if the differences are approximately normal or n is at least 30."))
            else:
                primary = _option("paired_t_test", "Two related numeric measurements with approximately normal differences"
                                  + (" (normality holds)." if norm["satisfied"] else " (n is large enough for the t-test to be robust)."))
                alternatives.append(_option("wilcoxon", "Use if the paired differences are clearly non-normal or contain outliers."))
        else:
            resid = data.to_numpy() - data.to_numpy().mean(axis=1, keepdims=True)
            norm = A.normality(resid.ravel(), "the within-participant deviations")
            checks.append(norm)
            config = {"variables": {"measures": cols}}
            if ordinal or (norm["satisfied"] is False and n < 30):
                primary = _option("friedman", "Three or more related measurements that are ordinal or not normally distributed.")
                alternatives.append(_option("repeated_measures_anova", "Use if the measurements are continuous and approximately normal."))
            else:
                primary = _option("repeated_measures_anova", "Three or more related continuous measurements.")
                alternatives.append(_option("friedman", "Use if normality is doubtful or the scale is ordinal."))
        checks.append(A.minimum_sample(n, 10, "a paired comparison"))

    # ------------------------------------------------------------------ #
    # B. no outcome/predictor pair: description only
    # ------------------------------------------------------------------ #
    elif not outcome or not predictors:
        raise AnalysisError("Choose an outcome (dependent) variable and at least one predictor (independent) variable, "
                            "or mark the design as paired and choose the measurement columns. "
                            "To summarise variables without testing a relationship, use Descriptive Statistics.")

    else:
        y_kind = kinds[outcome] if outcome_kind == "auto" else outcome_kind
        if outcome_kind == "auto" and y_kind == "continuous" and _looks_like_count(df[outcome]) \
                and schema.get(outcome, {}).get("type") == "integer" and numeric(df[outcome]).dropna().skew() > 1:
            warnings.append(f"'{outcome}' looks like a skewed count. If it counts events, set the outcome type to 'count' to get a count model.")
        if y_kind in ("datetime", "other"):
            raise AnalysisError(f"'{outcome}' is an identifier, free text or a date and cannot be used as an outcome.")
        unusable = [p for p in predictors if kinds[p] in ("other", "datetime")]
        if unusable:
            raise AnalysisError(f"Not usable as predictors (identifier, free text or date): {', '.join(unusable)}.")
        complete = df[[outcome, *predictors]].dropna()
        n = len(complete)
        checks.append(A.minimum_sample(n, 30, "inferential statistics"))

        # ---------------- several predictors, or special outcomes -> models
        if len(predictors) > 1 or y_kind in ("count", "time_to_event"):
            family = "regression"
            config = {"variables": {"outcome": outcome, "predictors": predictors}}
            why.append(f"There {'are ' + str(len(predictors)) + ' predictors' if len(predictors) > 1 else 'is one predictor'}, so a model is needed "
                       "that estimates the contribution of each predictor while holding the others constant.")
            if y_kind == "continuous":
                primary = _option("multiple_linear_regression", f"The outcome '{outcome}' is continuous.")
                why.append("If the diagnostics show non-constant residual variance, re-run the same model with robust (HC3) standard errors.")
                checks.append(A.normality(numeric(complete[outcome]), outcome))
                per_term = n / max(len(predictors), 1)
                if per_term < 10:
                    warnings.append(f"Only {per_term:.1f} complete records per predictor; aim for at least 10-15 or use fewer predictors.")
            elif y_kind == "binary":
                primary = _option("logistic_regression", f"The outcome '{outcome}' has two categories.")
                smaller = int(complete[outcome].astype(str).value_counts().min()) if n else 0
                if smaller / max(len(predictors), 1) < 10:
                    warnings.append(f"The smaller outcome category has {smaller} cases; logistic regression needs about 10 per predictor.")
            elif y_kind == "count":
                values = numeric(complete[outcome])
                ratio = float(values.var(ddof=1) / values.mean()) if n > 1 and values.mean() > 0 else float("nan")
                over = ratio > 2
                checks.append(A._check("Equidispersion of the count outcome", "Variance / mean", ratio, None, not over,
                                       f"Variance-to-mean ratio = {ratio:.2f}. " + ("The counts look overdispersed." if over else "No strong overdispersion in the raw counts.")))
                primary = _option("negative_binomial_regression" if over else "poisson_regression",
                                  f"The outcome '{outcome}' is a count" + (" with variance well above its mean." if over else "."))
                alternatives.append(_option("poisson_regression" if over else "negative_binomial_regression",
                                            "Use Poisson only if the dispersion statistic is near 1." if over else "Use if the Poisson model reports overdispersion."))
            elif y_kind == "time_to_event":
                primary = _option("survival_analysis", "The outcome is a time until an event, possibly censored.")
            elif y_kind == "ordinal":
                primary = _option("ordinal_regression", f"The outcome '{outcome}' is ordinal.")
                alternatives.append(_option("multiple_linear_regression", "Sometimes used when the ordinal scale has 5+ ordered levels treated as approximately interval; state this as a limitation."))
            else:
                raise AnalysisError(f"The outcome '{outcome}' is nominal with more than two categories. Multinomial models are not implemented; "
                                    "consider chi-square tests against each predictor or recoding the outcome into two categories.")

        # ---------------- exactly one predictor -> bivariate tests
        else:
            x = predictors[0]
            x_kind = kinds[x]
            pair = {y_kind, x_kind}
            numeric_like = {"continuous", "ordinal"}
            if y_kind in numeric_like and x_kind in numeric_like:
                family = "correlation"
                config = {"variables": {"x": x, "y": outcome}}
                a, b = numeric(complete[x]), numeric(complete[outcome])
                why.append(f"Both '{x}' and '{outcome}' are numeric, and the question is about the relationship between them.")
                if "ordinal" in pair:
                    primary = _option("spearman", "At least one variable is ordinal, so a rank correlation is appropriate.")
                    alternatives.append(_option("kendall", "Prefer with small samples or many tied values."))
                else:
                    nx, ny = A.normality(a, x), A.normality(b, outcome)
                    ox, oy = A.outlier_influence(a, x), A.outlier_influence(b, outcome)
                    checks += [nx, ny, ox, oy]
                    non_normal = nx["satisfied"] is False or ny["satisfied"] is False
                    outliers = ox["satisfied"] is False or oy["satisfied"] is False
                    if outliers or (non_normal and n < 30):
                        primary = _option("spearman", "Extreme values are present." if outliers else
                                          "A variable is not normally distributed and the sample is small.")
                        alternatives.append(_option("pearson", "Use if the relationship is linear and outliers are resolved."))
                    else:
                        primary = _option("pearson", "Both variables are continuous" + (" and approximately normal." if not non_normal else
                                          "; normality is doubtful but n >= 30 makes the test reasonably robust."))
                        alternatives.append(_option("spearman", "Use if assumptions are not satisfied (non-normality, outliers, non-linear but monotonic trend)."))
                    alternatives.append(_option("simple_linear_regression", f"Use if you want to predict '{outcome}' from '{x}' and quantify the slope."))
            elif y_kind in numeric_like and x_kind in ("binary", "nominal"):
                family = "group"
                config = {"variables": {"outcome": outcome, "group": x}}
                labels = complete[x].map(lambda v: f"{v:g}" if isinstance(v, float) else str(v))
                groups = [numeric(part[outcome]).to_numpy() for _, part in complete.groupby(labels)]
                k = len(groups)
                smallest = min(len(g) for g in groups) if groups else 0
                why.append(f"'{outcome}' is numeric and '{x}' splits the sample into {k} independent groups.")
                norms = [A.normality(g, f"{outcome} in group {i + 1}") for i, g in enumerate(groups)]
                levene = A.homogeneity_of_variance(groups)
                non_normal = any(c["satisfied"] is False for c in norms)
                checks += norms[:6] + [levene]
                if smallest < 5:
                    warnings.append(f"The smallest group has only {smallest} observation(s); any comparison will be unreliable.")
                rank_first = y_kind == "ordinal" or (non_normal and smallest < 30)
                reason_rank = "The outcome is ordinal." if y_kind == "ordinal" else "The outcome is not normally distributed in at least one group and groups are small."
                if k == 2:
                    if rank_first:
                        primary = _option("mann_whitney", reason_rank)
                        alternatives.append(_option("independent_t_test", "Use if the outcome is approximately normal within each group."))
                    else:
                        primary = _option("independent_t_test", "Two independent groups and a continuous outcome"
                                          + ("; variances differ, so Welch's version will be used." if levene["satisfied"] is False else "."))
                        alternatives.append(_option("mann_whitney", "Use if the outcome is clearly non-normal or has outliers."))
                elif k >= 3:
                    if rank_first:
                        primary = _option("kruskal_wallis", reason_rank)
                        alternatives.append(_option("one_way_anova", "Use if residuals are approximately normal."))
                    else:
                        primary = _option("one_way_anova", "Three or more independent groups and a continuous outcome"
                                          + ("; variances differ, so report Welch's ANOVA from the output." if levene["satisfied"] is False else "."))
                        alternatives.append(_option("kruskal_wallis", "Use if residuals are clearly non-normal."))
                else:
                    raise AnalysisError(f"'{x}' has fewer than two groups with data.")
            elif y_kind in ("binary", "nominal") and x_kind in ("binary", "nominal"):
                family = "association"
                config = {"variables": {"x": x, "y": outcome}}
                table = pd.crosstab(complete[x].astype(str), complete[outcome].astype(str))
                why.append(f"Both '{x}' and '{outcome}' are categorical, so the question is whether their categories are associated.")
                from scipy.stats import contingency
                expected = contingency.expected_freq(table.to_numpy())
                check = A.expected_counts(expected)
                checks.append(check)
                if table.shape == (2, 2) and check["satisfied"] is False:
                    primary = _option("fisher_exact", "A 2 x 2 table with small expected counts.")
                    alternatives.append(_option("chi_square", "Use when all expected counts are at least 5."))
                else:
                    primary = _option("chi_square", "Two categorical variables" + (" with adequate expected counts." if check["satisfied"] else "."))
                    if table.shape == (2, 2):
                        alternatives.append(_option("fisher_exact", "Use if expected counts are small."))
                    if check["satisfied"] is False:
                        warnings.append("Some expected counts are below 5. Combine sparse categories where it makes sense before testing.")
                if y_kind == "binary":
                    alternatives.append(_option("logistic_regression", "Use to estimate odds ratios or to add further predictors."))
            elif y_kind == "binary" and x_kind in numeric_like:
                family = "regression"
                config = {"variables": {"outcome": outcome, "predictors": [x]}}
                why.append(f"'{outcome}' has two categories and '{x}' is numeric: the question is how '{x}' changes the odds of the outcome.")
                primary = _option("logistic_regression", "Binary outcome with a numeric predictor.")
                alternatives.append(_option("independent_t_test", f"Equivalent simpler view: compare mean '{x}' between the two outcome groups (swap the roles)."))
            elif y_kind == "nominal" and x_kind in numeric_like:
                family = "group"
                config = {"variables": {"outcome": x, "group": outcome}}
                why.append(f"'{outcome}' is categorical with several groups and '{x}' is numeric. Multinomial models are not implemented, "
                           f"so the practical analysis compares '{x}' across the categories of '{outcome}' (roles swapped).")
                primary = _option("one_way_anova", "Compare the numeric variable across the outcome categories.")
                alternatives.append(_option("kruskal_wallis", "Use if the numeric variable is not normally distributed."))
            else:
                raise AnalysisError(f"No method rule matches outcome type '{y_kind}' with predictor type '{x_kind}'.")

    assert primary is not None
    if not primary["implemented"]:
        warnings.append(f"{primary['name']} is the appropriate method but is not implemented in this version: "
                        f"{METHODS[primary['method']]['not_implemented_reason']} No results will be invented for it.")
    why.append(primary["reason"])
    failed = [c["name"] for c in checks if c.get("satisfied") is False]
    if study_design and "cross" in study_design.lower():
        warnings.append("The study design is cross-sectional: results describe associations at one point in time and cannot establish causation.")
    return to_jsonable({
        "source": "rule_engine",
        "goal": goal,
        "primary": primary,
        "alternatives": alternatives,
        "why": why,
        "variable_kinds": kinds,
        "assumption_checks": checks,
        "failed_assumptions": failed,
        "warnings": warnings,
        "config": {"method": primary["method"], **config},
        "level_notes": _level_notes(academic_level, family),
        "academic_level": academic_level,
        "disclaimer": "This is decision support. The researcher remains responsible for choosing and justifying the method.",
    })
