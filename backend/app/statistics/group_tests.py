"""Group comparisons: t-tests, ANOVA family and their rank-based alternatives."""
from __future__ import annotations

import itertools
import math
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from app.statistics import assumptions as A
from app.statistics import effect_sizes as ES
from app.statistics.descriptive import mean_ci
from app.statistics.utils import (AnalysisError, InsufficientDataError, finalize, fmt_num, fmt_p, new_result, numeric,
                                  require_columns, table)

_ALTERNATIVES = ("two-sided", "greater", "less")


# --------------------------------------------------------------------------- #
# data preparation
# --------------------------------------------------------------------------- #
def _label(value) -> str:
    return f"{value:g}" if isinstance(value, (float, np.floating)) else str(value)


def _groups(df: pd.DataFrame, outcome: str, group: str, *, exactly: int | None = None,
            minimum: int = 2) -> tuple[dict[str, np.ndarray], int]:
    require_columns(df, outcome, group)
    if outcome == group:
        raise AnalysisError("The outcome and the grouping variable must be different.")
    frame = pd.DataFrame({"y": numeric(df[outcome]), "g": df[group]}).dropna()
    dropped = len(df) - len(frame)
    frame["g"] = frame["g"].map(_label)
    groups = {name: part["y"].to_numpy() for name, part in frame.groupby("g", sort=True)}
    if exactly is not None and len(groups) != exactly:
        raise AnalysisError(f"'{group}' must have exactly {exactly} groups with data, but it has {len(groups)} "
                            f"({', '.join(list(groups)[:8])}{'...' if len(groups) > 8 else ''}).")
    if len(groups) < minimum:
        raise AnalysisError(f"'{group}' needs at least {minimum} groups with data.")
    if len(groups) > 20:
        raise AnalysisError(f"'{group}' has {len(groups)} groups, which is too many for a group comparison.")
    small = [name for name, values in groups.items() if len(values) < 2]
    if small:
        raise InsufficientDataError(f"Group(s) {', '.join(small)} have fewer than 2 valid observations.")
    return groups, dropped


def _paired(df: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, int]:
    require_columns(df, *columns)
    if len(set(columns)) != len(columns):
        raise AnalysisError("Choose different variables for each measurement.")
    frame = pd.DataFrame({c: numeric(df[c]) for c in columns})
    complete = frame.dropna()
    return complete.to_numpy(dtype=float), int(len(frame) - len(complete))


def _group_table(groups: dict[str, np.ndarray], outcome: str) -> dict:
    rows = []
    for name, values in groups.items():
        lo, hi = mean_ci(values)
        rows.append([name, len(values), float(np.mean(values)), float(np.std(values, ddof=1)), float(np.median(values)), lo, hi])
    return table(f"{outcome} by group", ["Group", "N", "Mean", "SD", "Median", "95% CI low", "95% CI high"], rows)


def _holm(pvalues: list[float]) -> list[float]:
    """Holm step-down adjustment for multiple comparisons."""
    m = len(pvalues)
    order = np.argsort(pvalues)
    adjusted = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * pvalues[idx])
        adjusted[idx] = min(1.0, running)
    return adjusted.tolist()


def _missing_warning(res: dict, dropped: int) -> None:
    if dropped:
        res["warnings"].append(f"{dropped} record(s) with a missing value were excluded (listwise deletion).")


# --------------------------------------------------------------------------- #
# two independent groups
# --------------------------------------------------------------------------- #
def independent_t_test(df, outcome, group, alpha=0.05, alternative="two-sided", equal_var="auto", **_):
    """Student's or Welch's t-test. With ``equal_var='auto'`` Welch's test is
    used when Levene's test rejects equal variances."""
    if alternative not in _ALTERNATIVES:
        raise AnalysisError("alternative must be two-sided, greater or less.")
    groups, dropped = _groups(df, outcome, group, exactly=2)
    (name1, x), (name2, y) = groups.items()
    levene = A.homogeneity_of_variance([x, y], alpha)
    if equal_var == "auto":
        use_equal = levene["satisfied"] is not False
    else:
        use_equal = bool(equal_var) if not isinstance(equal_var, str) else equal_var.lower() == "true"
    student = stats.ttest_ind(x, y, equal_var=True, alternative=alternative)
    welch = stats.ttest_ind(x, y, equal_var=False, alternative=alternative)
    chosen = student if use_equal else welch
    name = "Independent-samples t-test" if use_equal else "Welch's t-test (unequal variances)"

    res = new_result("independent_t_test", name, n=len(x) + len(y), variables={"outcome": outcome, "group": group}, alpha=alpha)
    res["alternative"] = alternative
    res["statistic"] = {"name": "t", "value": float(chosen.statistic)}
    res["df"] = float(chosen.df)
    res["p_value"] = float(chosen.pvalue)
    diff = float(np.mean(x) - np.mean(y))
    ci = chosen.confidence_interval(0.95)
    res["estimates"].append({"name": f"Mean difference ({name1} - {name2})", "value": diff,
                             "ci_low": float(ci.low), "ci_high": float(ci.high), "ci_level": 0.95})
    res["effect_sizes"] = ES.cohens_d_independent(x, y)
    norm1, norm2 = A.normality(x, f"{outcome} in {name1}", alpha), A.normality(y, f"{outcome} in {name2}", alpha)
    res["assumptions"] = [norm1, norm2, levene, A.independence_note()]
    res["tables"] = [
        _group_table(groups, outcome),
        table("Both versions of the test", ["Test", "t", "df", "p"],
              [["Student (equal variances)", float(student.statistic), float(student.df), float(student.pvalue)],
               ["Welch (unequal variances)", float(welch.statistic), float(welch.df), float(welch.pvalue)]],
              note=f"Reported as the main result: {'Student' if use_equal else 'Welch'}."),
    ]
    non_normal = [c for c in (norm1, norm2) if c["satisfied"] is False]
    if non_normal:
        if min(len(x), len(y)) < 30:
            res["warnings"].append("The outcome is not normally distributed in at least one group and the groups are small (< 30). "
                                   "The Mann-Whitney U test is a safer choice.")
        else:
            res["warnings"].append("The outcome is not normally distributed in at least one group. With 30 or more per group the t-test "
                                   "is usually robust, but confirm with the Mann-Whitney U test.")
    if levene["satisfied"] is False and use_equal:
        res["warnings"].append("Variances differ between groups but the equal-variance test was requested; prefer Welch's test.")
    _missing_warning(res, dropped)

    res = finalize(res)
    d = res["effect_sizes"][0]
    res["apa"] = (f"t({fmt_num(chosen.df, 2 if not use_equal else 0)}) = {fmt_num(chosen.statistic, 2)}, {fmt_p(chosen.pvalue)}, "
                  f"d = {fmt_num(d['value'], 2)}")
    means = f"{name1}: M = {fmt_num(np.mean(x), 2)}, SD = {fmt_num(np.std(x, ddof=1), 2)}; {name2}: M = {fmt_num(np.mean(y), 2)}, SD = {fmt_num(np.std(y, ddof=1), 2)}"
    if res["significant"]:
        res["summary"] = (f"Mean {outcome} differs significantly between the two groups of {group} ({means}; {res['apa']}). "
                          f"The mean difference is {fmt_num(diff, 2)} (95% CI {fmt_num(ci.low, 2)} to {fmt_num(ci.high, 2)}), "
                          f"a {d['magnitude']} effect. Unless participants were randomly assigned to groups, this difference cannot be attributed to {group} itself.")
    else:
        res["summary"] = (f"The difference in mean {outcome} between the two groups of {group} is not statistically significant "
                          f"({means}; {res['apa']}). The data do not provide sufficient evidence of a difference.")
    return res


def mann_whitney(df, outcome, group, alpha=0.05, alternative="two-sided", **_):
    if alternative not in _ALTERNATIVES:
        raise AnalysisError("alternative must be two-sided, greater or less.")
    groups, dropped = _groups(df, outcome, group, exactly=2)
    (name1, x), (name2, y) = groups.items()
    out = stats.mannwhitneyu(x, y, alternative=alternative, method="auto")
    res = new_result("mann_whitney", "Mann-Whitney U test", n=len(x) + len(y), variables={"outcome": outcome, "group": group}, alpha=alpha)
    res["alternative"] = alternative
    res["statistic"] = {"name": "U", "value": float(out.statistic)}
    res["p_value"] = float(out.pvalue)
    rb = ES.rank_biserial(float(out.statistic), len(x), len(y))
    res["effect_sizes"].append(rb)
    res["estimates"].append({"name": f"Median difference ({name1} - {name2})", "value": float(np.median(x) - np.median(y)),
                             "ci_low": None, "ci_high": None, "ci_level": None})
    res["assumptions"] = [
        A.independence_note(),
        A._check("Similar distribution shapes", None, None, None, None,
                 "The test compares whole distributions. It can be read as a comparison of medians only if the two groups have similarly shaped distributions."),
    ]
    res["tables"] = [_group_table(groups, outcome),
                     table("Mean ranks", ["Group", "N", "Mean rank"],
                           [[n_, len(v), float(r)] for (n_, v), r in zip(groups.items(), _mean_ranks([x, y]))])]
    _missing_warning(res, dropped)
    res = finalize(res)
    res["apa"] = f"U = {fmt_num(out.statistic, 1)}, {fmt_p(out.pvalue)}, rank-biserial r = {fmt_num(rb['value'], 2)}"
    medians = f"{name1}: Mdn = {fmt_num(np.median(x), 2)}; {name2}: Mdn = {fmt_num(np.median(y), 2)}"
    verdict = ("differs significantly" if res["significant"] else "does not differ significantly")
    res["summary"] = (f"The distribution of {outcome} {verdict} between the two groups of {group} ({medians}; {res['apa']}). "
                      + (f"The effect is {rb['magnitude']}." if res["significant"] else "The data do not provide sufficient evidence of a difference."))
    return res


def _mean_ranks(arrays: list[np.ndarray]) -> list[float]:
    ranks = stats.rankdata(np.concatenate(arrays))
    out, start = [], 0
    for a in arrays:
        out.append(float(ranks[start:start + len(a)].mean()))
        start += len(a)
    return out


# --------------------------------------------------------------------------- #
# two related measurements
# --------------------------------------------------------------------------- #
def paired_t_test(df, first, second, alpha=0.05, alternative="two-sided", **_):
    if alternative not in _ALTERNATIVES:
        raise AnalysisError("alternative must be two-sided, greater or less.")
    data, dropped = _paired(df, [first, second])
    n = len(data)
    if n < 3:
        raise InsufficientDataError(f"Only {n} complete pair(s).")
    x, y = data[:, 0], data[:, 1]
    diff = x - y
    if np.ptp(diff) == 0:
        raise AnalysisError("Every pair has the same difference, so the test statistic is undefined.")
    out = stats.ttest_rel(x, y, alternative=alternative)
    ci = out.confidence_interval(0.95)
    res = new_result("paired_t_test", "Paired-samples t-test", n=n, variables={"first": first, "second": second}, alpha=alpha)
    res["alternative"] = alternative
    res["statistic"] = {"name": "t", "value": float(out.statistic)}
    res["df"] = int(out.df)
    res["p_value"] = float(out.pvalue)
    res["estimates"].append({"name": f"Mean difference ({first} - {second})", "value": float(diff.mean()),
                             "ci_low": float(ci.low), "ci_high": float(ci.high), "ci_level": 0.95})
    res["effect_sizes"] = ES.cohens_d_paired(diff)
    norm = A.normality(diff, "the paired differences", alpha)
    res["assumptions"] = [norm, A.outlier_influence(diff, "the paired differences"),
                          A._check("Paired observations", None, None, None, None,
                                   "Each row must hold two measurements of the same participant/unit (or a matched pair).")]
    res["tables"] = [table("Paired measurements", ["Measure", "N", "Mean", "SD"],
                           [[first, n, float(x.mean()), float(x.std(ddof=1))], [second, n, float(y.mean()), float(y.std(ddof=1))],
                            ["Difference", n, float(diff.mean()), float(diff.std(ddof=1))]])]
    if norm["satisfied"] is False and n < 30:
        res["warnings"].append("The paired differences are not normally distributed and n < 30. Use the Wilcoxon signed-rank test.")
    _missing_warning(res, dropped)
    res = finalize(res)
    d = res["effect_sizes"][0]
    res["apa"] = f"t({n - 1}) = {fmt_num(out.statistic, 2)}, {fmt_p(out.pvalue)}, dz = {fmt_num(d['value'], 2)}"
    if res["significant"]:
        res["summary"] = (f"{first} (M = {fmt_num(x.mean(), 2)}) and {second} (M = {fmt_num(y.mean(), 2)}) differ significantly "
                          f"({res['apa']}); the mean difference is {fmt_num(diff.mean(), 2)} (95% CI {fmt_num(ci.low, 2)} to {fmt_num(ci.high, 2)}), a {d['magnitude']} effect.")
    else:
        res["summary"] = (f"The difference between {first} (M = {fmt_num(x.mean(), 2)}) and {second} (M = {fmt_num(y.mean(), 2)}) "
                          f"is not statistically significant ({res['apa']}).")
    return res


def wilcoxon_signed_rank(df, first, second, alpha=0.05, alternative="two-sided", **_):
    if alternative not in _ALTERNATIVES:
        raise AnalysisError("alternative must be two-sided, greater or less.")
    data, dropped = _paired(df, [first, second])
    x, y = data[:, 0], data[:, 1]
    diff = x - y
    nonzero = diff[diff != 0]
    if len(nonzero) < 5:
        raise InsufficientDataError(f"Only {len(nonzero)} pair(s) have a non-zero difference.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = stats.wilcoxon(x, y, alternative=alternative, zero_method="wilcox")
    res = new_result("wilcoxon", "Wilcoxon signed-rank test", n=len(diff), variables={"first": first, "second": second}, alpha=alpha)
    res["alternative"] = alternative
    res["statistic"] = {"name": "W", "value": float(out.statistic)}
    res["p_value"] = float(out.pvalue)
    rb = ES.matched_rank_biserial(diff)
    res["effect_sizes"].append(rb)
    res["estimates"].append({"name": f"Median difference ({first} - {second})", "value": float(np.median(diff)),
                             "ci_low": None, "ci_high": None, "ci_level": None})
    res["assumptions"] = [A._check("Paired observations", None, None, None, None, "Each row must hold two measurements of the same unit."),
                          A._check("Symmetric differences", None, float(stats.skew(nonzero)), None, bool(abs(stats.skew(nonzero)) < 1),
                                   "The test assumes the distribution of differences is roughly symmetric.")]
    res["tables"] = [table("Paired measurements", ["Measure", "N", "Median", "Q1", "Q3"],
                           [[first, len(x), float(np.median(x)), *[float(v) for v in np.percentile(x, [25, 75])]],
                            [second, len(y), float(np.median(y)), *[float(v) for v in np.percentile(y, [25, 75])]]])]
    zeros = len(diff) - len(nonzero)
    if zeros:
        res["warnings"].append(f"{zeros} pair(s) with no difference were dropped from the ranking (Wilcoxon's method).")
    _missing_warning(res, dropped)
    res = finalize(res)
    res["apa"] = f"W = {fmt_num(out.statistic, 1)}, {fmt_p(out.pvalue)}, rank-biserial r = {fmt_num(rb['value'], 2)}"
    verdict = "differ significantly" if res["significant"] else "do not differ significantly"
    res["summary"] = (f"{first} (Mdn = {fmt_num(np.median(x), 2)}) and {second} (Mdn = {fmt_num(np.median(y), 2)}) {verdict} ({res['apa']}).")
    return res


# --------------------------------------------------------------------------- #
# three or more independent groups
# --------------------------------------------------------------------------- #
def welch_anova(arrays: list[np.ndarray]) -> tuple[float, float, float, float]:
    """Welch's heteroscedastic one-way ANOVA: returns F, df1, df2, p."""
    k = len(arrays)
    n = np.array([len(a) for a in arrays], dtype=float)
    means = np.array([np.mean(a) for a in arrays])
    variances = np.array([np.var(a, ddof=1) for a in arrays])
    if np.any(variances == 0):
        return float("nan"), k - 1, float("nan"), float("nan")
    w = n / variances
    grand = np.sum(w * means) / np.sum(w)
    lam = np.sum((1 - w / np.sum(w)) ** 2 / (n - 1))
    f = (np.sum(w * (means - grand) ** 2) / (k - 1)) / (1 + 2 * (k - 2) * lam / (k**2 - 1))
    df2 = (k**2 - 1) / (3 * lam)
    return float(f), float(k - 1), float(df2), float(stats.f.sf(f, k - 1, df2))


def one_way_anova(df, outcome, group, alpha=0.05, **_):
    groups, dropped = _groups(df, outcome, group, minimum=3)
    arrays = list(groups.values())
    names = list(groups)
    n_total = sum(len(a) for a in arrays)
    k = len(arrays)
    grand = np.concatenate(arrays).mean()
    ss_between = float(sum(len(a) * (a.mean() - grand) ** 2 for a in arrays))
    ss_within = float(sum(((a - a.mean()) ** 2).sum() for a in arrays))
    df_b, df_w = k - 1, n_total - k
    if ss_within == 0:
        raise AnalysisError("There is no variation within groups, so the F statistic is undefined.")
    ms_b, ms_w = ss_between / df_b, ss_within / df_w
    f = ms_b / ms_w
    p = float(stats.f.sf(f, df_b, df_w))

    res = new_result("one_way_anova", "One-way ANOVA", n=n_total, variables={"outcome": outcome, "group": group}, alpha=alpha)
    res["statistic"] = {"name": "F", "value": float(f)}
    res["df"] = f"{df_b}, {df_w}"
    res["p_value"] = p
    res["effect_sizes"] = ES.eta_squared(ss_between, ss_between + ss_within, df_b, ms_w)
    residuals = np.concatenate([a - a.mean() for a in arrays])
    norm = A.normality(residuals, "the residuals", alpha)
    levene = A.homogeneity_of_variance(arrays, alpha)
    res["assumptions"] = [norm, levene, A.independence_note()]
    res["tables"] = [
        _group_table(groups, outcome),
        table("ANOVA table", ["Source", "Sum of squares", "df", "Mean square", "F", "p"],
              [["Between groups", ss_between, df_b, ms_b, float(f), p], ["Within groups", ss_within, df_w, ms_w, None, None],
               ["Total", ss_between + ss_within, n_total - 1, None, None, None]]),
    ]
    wf, wdf1, wdf2, wp = welch_anova(arrays)
    if math.isfinite(wf):
        res["tables"].append(table("Welch's ANOVA (does not assume equal variances)", ["F", "df1", "df2", "p"], [[wf, wdf1, wdf2, wp]]))
    if levene["satisfied"] is False:
        res["warnings"].append("Group variances are unequal. Report Welch's ANOVA (shown in the tables) instead of the classic F test"
                               + (f": F({wdf1:.0f}, {wdf2:.2f}) = {wf:.2f}, {fmt_p(wp)}." if math.isfinite(wf) else "."))
    if norm["satisfied"] is False and min(len(a) for a in arrays) < 30:
        res["warnings"].append("Residuals are not normally distributed and some groups are small. The Kruskal-Wallis test is a safer choice.")

    # post hoc: Tukey HSD is reported whenever the omnibus test is significant
    if p < alpha:
        tukey = stats.tukey_hsd(*arrays)
        ci = tukey.confidence_interval(0.95)
        rows = []
        for i, j in itertools.combinations(range(k), 2):
            rows.append([f"{names[i]} - {names[j]}", float(arrays[i].mean() - arrays[j].mean()), float(ci.low[i, j]),
                         float(ci.high[i, j]), float(tukey.pvalue[i, j]), bool(tukey.pvalue[i, j] < alpha)])
        res["tables"].append(table("Tukey HSD post hoc comparisons", ["Comparison", "Mean difference", "95% CI low", "95% CI high", "Adjusted p", "Significant"],
                                   rows, note="p-values are adjusted for all pairwise comparisons."))
        res["post_hoc"] = [{"comparison": r[0], "mean_difference": r[1], "p_adjusted": r[4], "significant": r[5]} for r in rows]
    _missing_warning(res, dropped)

    res = finalize(res)
    eta = res["effect_sizes"][0]
    res["apa"] = f"F({df_b}, {df_w}) = {fmt_num(f, 2)}, {fmt_p(p)}, eta2 = {fmt_num(eta['value'], 3)}"
    if res["significant"]:
        pairs = [c["comparison"] for c in res.get("post_hoc", []) if c["significant"]]
        res["summary"] = (f"Mean {outcome} differs significantly across the {k} groups of {group} ({res['apa']}), a {eta['magnitude']} effect. "
                          + (f"Tukey post hoc tests show significant differences for: {'; '.join(pairs)}." if pairs else
                             "However, no individual pair of groups differs significantly after Tukey adjustment."))
    else:
        res["summary"] = (f"Mean {outcome} does not differ significantly across the {k} groups of {group} ({res['apa']}). "
                          "The data do not provide sufficient evidence of a difference between groups.")
    return res


def kruskal_wallis(df, outcome, group, alpha=0.05, **_):
    groups, dropped = _groups(df, outcome, group, minimum=3)
    arrays, names = list(groups.values()), list(groups)
    n_total = sum(len(a) for a in arrays)
    if len(np.unique(np.concatenate(arrays))) == 1:
        raise AnalysisError("All values are identical, so the test statistic is undefined.")
    out = stats.kruskal(*arrays)
    res = new_result("kruskal_wallis", "Kruskal-Wallis H test", n=n_total, variables={"outcome": outcome, "group": group}, alpha=alpha)
    res["statistic"] = {"name": "H", "value": float(out.statistic)}
    res["df"] = len(arrays) - 1
    res["p_value"] = float(out.pvalue)
    eps = ES.epsilon_squared(float(out.statistic), n_total)
    res["effect_sizes"].append(eps)
    res["assumptions"] = [A.independence_note(),
                          A._check("Similar distribution shapes", None, None, None, None,
                                   "Interpretable as a comparison of medians only if the groups have similarly shaped distributions.")]
    res["tables"] = [_group_table(groups, outcome),
                     table("Mean ranks", ["Group", "N", "Mean rank"], [[n_, len(a), r] for n_, a, r in zip(names, arrays, _mean_ranks(arrays))])]
    if out.pvalue < alpha:
        raw_p, rows = [], []
        for i, j in itertools.combinations(range(len(arrays)), 2):
            u = stats.mannwhitneyu(arrays[i], arrays[j], alternative="two-sided")
            raw_p.append(float(u.pvalue))
            rows.append([f"{names[i]} - {names[j]}", float(u.statistic), float(u.pvalue)])
        for row, adj in zip(rows, _holm(raw_p)):
            row += [adj, bool(adj < alpha)]
        res["tables"].append(table("Pairwise Mann-Whitney comparisons (Holm-adjusted)", ["Comparison", "U", "p", "Adjusted p", "Significant"], rows))
        res["post_hoc"] = [{"comparison": r[0], "p_adjusted": r[3], "significant": r[4]} for r in rows]
    _missing_warning(res, dropped)
    res = finalize(res)
    res["apa"] = f"H({len(arrays) - 1}) = {fmt_num(out.statistic, 2)}, {fmt_p(out.pvalue)}, epsilon2 = {fmt_num(eps['value'], 3)}"
    if res["significant"]:
        pairs = [c["comparison"] for c in res.get("post_hoc", []) if c["significant"]]
        res["summary"] = (f"The distribution of {outcome} differs significantly across the groups of {group} ({res['apa']}). "
                          + (f"Holm-adjusted pairwise tests show differences for: {'; '.join(pairs)}." if pairs else
                             "No individual pair differs significantly after Holm adjustment."))
    else:
        res["summary"] = f"The distribution of {outcome} does not differ significantly across the groups of {group} ({res['apa']})."
    return res


# --------------------------------------------------------------------------- #
# three or more related measurements
# --------------------------------------------------------------------------- #
def repeated_measures_anova(df, measures: list[str], alpha=0.05, **_):
    """One-way repeated-measures ANOVA on wide data (one column per condition),
    with the Greenhouse-Geisser correction for violations of sphericity."""
    if not measures or len(measures) < 3:
        raise AnalysisError("Repeated-measures ANOVA needs at least three measurement columns (use the paired t-test for two).")
    data, dropped = _paired(df, measures)
    n, k = data.shape
    if n < 3:
        raise InsufficientDataError(f"Only {n} participant(s) have all {k} measurements.")
    grand = data.mean()
    ss_cond = n * ((data.mean(axis=0) - grand) ** 2).sum()
    ss_subj = k * ((data.mean(axis=1) - grand) ** 2).sum()
    ss_total = ((data - grand) ** 2).sum()
    ss_error = ss_total - ss_cond - ss_subj
    df_c, df_e = k - 1, (k - 1) * (n - 1)
    if ss_error <= 1e-12:
        raise AnalysisError("There is no residual variation, so the F statistic is undefined.")
    f = (ss_cond / df_c) / (ss_error / df_e)
    p = float(stats.f.sf(f, df_c, df_e))

    # Greenhouse-Geisser epsilon from the double-centred covariance matrix
    cov = np.cov(data, rowvar=False)
    centring = np.eye(k) - np.ones((k, k)) / k
    dc = centring @ cov @ centring
    eps = float(np.trace(dc) ** 2 / (df_c * np.sum(dc**2))) if np.sum(dc**2) > 0 else 1.0
    eps = min(1.0, max(1.0 / df_c, eps))
    p_gg = float(stats.f.sf(f, df_c * eps, df_e * eps))

    res = new_result("repeated_measures_anova", "Repeated-measures ANOVA", n=n, variables={"measures": measures}, alpha=alpha)
    res["statistic"] = {"name": "F", "value": float(f)}
    res["df"] = f"{df_c}, {df_e}"
    res["p_value"] = p_gg if eps < 0.75 else p
    res["effect_sizes"].append(ES.partial_eta_squared(float(ss_cond), float(ss_error)))
    sphericity_ok = eps >= 0.75
    res["assumptions"] = [
        A._check("Sphericity", "Greenhouse-Geisser epsilon", eps, None, sphericity_ok,
                 f"epsilon = {eps:.3f} (1 = perfect sphericity). "
                 + ("No serious violation." if sphericity_ok else "Sphericity is violated, so the Greenhouse-Geisser corrected p-value is reported as the main result.")),
        A.normality(data - data.mean(axis=1, keepdims=True) - data.mean(axis=0) + grand, "the residuals", alpha),
    ]
    res["tables"] = [
        table("Condition means", ["Measure", "N", "Mean", "SD"], [[m, n, float(data[:, i].mean()), float(data[:, i].std(ddof=1))] for i, m in enumerate(measures)]),
        table("Repeated-measures ANOVA table", ["Source", "Sum of squares", "df", "Mean square", "F", "p", "p (Greenhouse-Geisser)"],
              [["Conditions", float(ss_cond), df_c, float(ss_cond / df_c), float(f), p, p_gg],
               ["Participants", float(ss_subj), n - 1, float(ss_subj / (n - 1)), None, None, None],
               ["Error", float(ss_error), df_e, float(ss_error / df_e), None, None, None]]),
    ]
    main_p = res["p_value"]
    if main_p < alpha:
        raw_p, rows = [], []
        for i, j in itertools.combinations(range(k), 2):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")       # a constant difference gives an infinite t, handled below
                t = stats.ttest_rel(data[:, i], data[:, j])
            p_pair = float(t.pvalue) if np.isfinite(t.pvalue) else 1.0
            raw_p.append(p_pair)
            rows.append([f"{measures[i]} - {measures[j]}", float((data[:, i] - data[:, j]).mean()), float(t.statistic), p_pair])
        for row, adj in zip(rows, _holm(raw_p)):
            row += [adj, bool(adj < alpha)]
        res["tables"].append(table("Pairwise paired t-tests (Holm-adjusted)", ["Comparison", "Mean difference", "t", "p", "Adjusted p", "Significant"], rows))
        res["post_hoc"] = [{"comparison": r[0], "mean_difference": r[1], "p_adjusted": r[4], "significant": r[5]} for r in rows]
    _missing_warning(res, dropped)
    res = finalize(res)
    pes = res["effect_sizes"][0]
    res["apa"] = (f"F({df_c}, {df_e}) = {fmt_num(f, 2)}, {fmt_p(main_p)}" + (" (Greenhouse-Geisser corrected)" if not sphericity_ok else "")
                  + f", partial eta2 = {fmt_num(pes['value'], 3)}")
    verdict = "differ significantly" if res["significant"] else "do not differ significantly"
    res["summary"] = f"Mean scores {verdict} across the {k} repeated measurements ({res['apa']}; n = {n})."
    return res


def friedman(df, measures: list[str], alpha=0.05, **_):
    if not measures or len(measures) < 3:
        raise AnalysisError("The Friedman test needs at least three measurement columns.")
    data, dropped = _paired(df, measures)
    n, k = data.shape
    if n < 5:
        raise InsufficientDataError(f"Only {n} participant(s) have all {k} measurements.")
    out = stats.friedmanchisquare(*[data[:, i] for i in range(k)])
    if not np.isfinite(out.statistic):
        raise AnalysisError("All measurements are identical, so the test statistic is undefined.")
    res = new_result("friedman", "Friedman test", n=n, variables={"measures": measures}, alpha=alpha)
    res["statistic"] = {"name": "chi2", "value": float(out.statistic)}
    res["df"] = k - 1
    res["p_value"] = float(out.pvalue)
    w = ES.kendalls_w(float(out.statistic), n, k)
    res["effect_sizes"].append(w)
    res["assumptions"] = [A._check("Related measurements", None, None, None, None, "Each row must hold all measurements of the same unit.")]
    ranks = np.apply_along_axis(stats.rankdata, 1, data)
    res["tables"] = [table("Condition medians and mean ranks", ["Measure", "N", "Median", "Mean rank"],
                           [[m, n, float(np.median(data[:, i])), float(ranks[:, i].mean())] for i, m in enumerate(measures)])]
    _missing_warning(res, dropped)
    res = finalize(res)
    res["apa"] = f"chi2({k - 1}) = {fmt_num(out.statistic, 2)}, {fmt_p(out.pvalue)}, Kendall's W = {fmt_num(w['value'], 2)}"
    verdict = "differ significantly" if res["significant"] else "do not differ significantly"
    res["summary"] = f"Scores {verdict} across the {k} repeated measurements ({res['apa']}; n = {n})."
    return res
