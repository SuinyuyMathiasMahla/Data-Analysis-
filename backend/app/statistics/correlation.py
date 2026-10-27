"""Correlation (Pearson, Spearman, Kendall) and tests of association
(chi-square, Fisher's exact)."""
from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from app.statistics import assumptions as A
from app.statistics import effect_sizes as ES
from app.statistics.utils import (AnalysisError, InsufficientDataError, finalize, fmt_num, fmt_p, new_result, numeric,
                                  require_columns, table)

_ALTERNATIVES = ("two-sided", "greater", "less")


def _pair(df: pd.DataFrame, x: str, y: str) -> tuple[np.ndarray, np.ndarray, int]:
    require_columns(df, x, y)
    if x == y:
        raise AnalysisError("Choose two different variables.")
    frame = pd.DataFrame({"x": numeric(df[x]), "y": numeric(df[y])})
    complete = frame.dropna()
    return complete["x"].to_numpy(), complete["y"].to_numpy(), int(len(frame) - len(complete))


def _fisher_ci(r: float, n: int, se_factor: float = 1.0, level: float = 0.95) -> tuple[float, float] | None:
    if n <= 3 or abs(r) >= 1:
        return None
    z = math.atanh(r)
    se = se_factor / math.sqrt(n - 3)
    crit = stats.norm.ppf(0.5 + level / 2)
    return math.tanh(z - crit * se), math.tanh(z + crit * se)


def _direction(r: float) -> str:
    return "positive" if r > 0 else "negative"


def _correlation(df, x, y, kind: str, alpha: float, alternative: str) -> dict:
    if alternative not in _ALTERNATIVES:
        raise AnalysisError("alternative must be two-sided, greater or less.")
    a, b, dropped = _pair(df, x, y)
    n = len(a)
    names = {"pearson": ("pearson", "Pearson correlation", "r"),
             "spearman": ("spearman", "Spearman rank correlation", "rho"),
             "kendall": ("kendall", "Kendall's tau-b", "tau")}
    method, method_name, symbol = names[kind]
    minimum = 3 if kind == "pearson" else 4
    if n < minimum:
        raise InsufficientDataError(f"Only {n} complete pair(s) of '{x}' and '{y}'.")
    if np.ptp(a) == 0 or np.ptp(b) == 0:
        raise AnalysisError("A correlation cannot be computed because one variable has no variation.")

    res = new_result(method, method_name, n=n, variables={"x": x, "y": y}, alpha=alpha)
    res["alternative"] = alternative
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if kind == "pearson":
            out = stats.pearsonr(a, b, alternative=alternative)
            r, p = float(out.statistic), float(out.pvalue)
            ci = _fisher_ci(r, n)
            res["df"] = n - 2
        elif kind == "spearman":
            out = stats.spearmanr(a, b, alternative=alternative)
            r, p = float(out.statistic), float(out.pvalue)
            ci = _fisher_ci(r, n, se_factor=math.sqrt(1 + r * r / 2))   # Bonett & Wright (2000)
            res["df"] = n - 2
        else:
            out = stats.kendalltau(a, b, alternative=alternative)
            r, p = float(out.statistic), float(out.pvalue)
            ci = _fisher_ci(r, n, se_factor=math.sqrt(0.437))            # Fieller et al. (1957)

    res["statistic"] = {"name": symbol, "value": r}
    res["p_value"] = p
    res["estimates"].append({"name": f"{symbol} ({x}, {y})", "value": r, "ci_low": ci[0] if ci else None,
                             "ci_high": ci[1] if ci else None, "ci_level": 0.95})
    res["effect_sizes"].append(ES.r_entry(f"{method_name} coefficient", r, ci))
    if kind == "pearson":
        res["effect_sizes"].append(ES.r_squared_entry(r))

    # assumptions
    if kind == "pearson":
        norm_x, norm_y = A.normality(a, x, alpha), A.normality(b, y, alpha)
        out_x, out_y = A.outlier_influence(a, x), A.outlier_influence(b, y)
        res["assumptions"] += [norm_x, norm_y, out_x, out_y]
        rho = float(stats.spearmanr(a, b).statistic)
        linear_ok = abs(rho) - abs(r) < 0.1
        res["assumptions"].append(A._check(
            "Linearity", "Pearson vs Spearman comparison", abs(rho) - abs(r), None, linear_ok,
            f"Spearman rho = {rho:.3f} vs Pearson r = {r:.3f}. "
            + ("The two agree, which is consistent with a linear relationship." if linear_ok else
               "Spearman is noticeably stronger, suggesting a monotonic but non-linear relationship or influential points. Inspect a scatter plot.")))
        if norm_x["satisfied"] is False or norm_y["satisfied"] is False:
            res["warnings"].append("At least one variable is not normally distributed. Spearman's rank correlation is a safer choice"
                                   + (" (with n >= 30 the Pearson p-value is usually still reasonable)." if n >= 30 else "."))
        if out_x["satisfied"] is False or out_y["satisfied"] is False:
            res["warnings"].append("Extreme values are present and can inflate or mask a Pearson correlation. Compare with Spearman.")
    else:
        res["assumptions"].append(A._check("Monotonic relationship", None, None, None, None,
                                           "Rank correlations assume the relationship is monotonic. Inspect a scatter plot."))
        ties = 1 - len(np.unique(a)) / n, 1 - len(np.unique(b)) / n
        if kind == "spearman" and max(ties) > 0.5:
            res["warnings"].append("More than half of the values are tied. Kendall's tau-b handles heavy ties better.")
    res["assumptions"].append(A.independence_note())
    if n < 30:
        res["warnings"].append(f"The sample is small (n = {n}); the estimate is imprecise, as the wide confidence interval shows.")
    if dropped:
        res["warnings"].append(f"{dropped} record(s) were excluded because one of the two values was missing (pairwise deletion).")

    res = finalize(res)
    strength = ES.magnitude_r(r)
    sig = "statistically significant" if res["significant"] else "not statistically significant"
    df_part = f"({res['df']})" if res["df"] is not None else ""
    res["apa"] = f"{symbol}{df_part} = {fmt_num(r)}, {fmt_p(p)}" + (f", 95% CI [{fmt_num(ci[0])}, {fmt_num(ci[1])}]" if ci else "")
    if res["significant"]:
        res["summary"] = (f"There is a {sig} {strength} {_direction(r)} association between {x} and {y} ({res['apa']}; n = {n}). "
                          f"Higher values of {x} tend to go with {'higher' if r > 0 else 'lower'} values of {y}. "
                          "An association does not show that one variable causes the other.")
    else:
        res["summary"] = (f"The association between {x} and {y} is {sig} at alpha = {alpha:g} ({res['apa']}; n = {n}). "
                          "The data do not provide sufficient evidence of a relationship; this is not proof that none exists.")
    return res


def pearson(df, x, y, alpha=0.05, alternative="two-sided", **_):
    return _correlation(df, x, y, "pearson", alpha, alternative)


def spearman(df, x, y, alpha=0.05, alternative="two-sided", **_):
    return _correlation(df, x, y, "spearman", alpha, alternative)


def kendall(df, x, y, alpha=0.05, alternative="two-sided", **_):
    return _correlation(df, x, y, "kendall", alpha, alternative)


def correlation_matrix(df: pd.DataFrame, columns: list[str], method: str = "pearson") -> dict:
    """Pairwise correlation matrix with p-values and pairwise n."""
    if method not in ("pearson", "spearman", "kendall"):
        raise AnalysisError("method must be pearson, spearman or kendall.")
    require_columns(df, *columns)
    if len(columns) < 2:
        raise AnalysisError("Select at least two numeric variables.")
    data = pd.DataFrame({c: numeric(df[c]) for c in columns})
    func = {"pearson": stats.pearsonr, "spearman": stats.spearmanr, "kendall": stats.kendalltau}[method]
    k = len(columns)
    r = np.full((k, k), np.nan)
    p = np.full((k, k), np.nan)
    n = np.zeros((k, k), dtype=int)
    for i in range(k):
        for j in range(i, k):
            pair = data.iloc[:, [i, j]].dropna()
            n[i, j] = n[j, i] = len(pair)
            if i == j:
                r[i, j] = 1.0
                continue
            a, b = pair.iloc[:, 0].to_numpy(), pair.iloc[:, 1].to_numpy()
            if len(pair) >= 4 and np.ptp(a) > 0 and np.ptp(b) > 0:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    out = func(a, b)
                r[i, j] = r[j, i] = float(out.statistic)
                p[i, j] = p[j, i] = float(out.pvalue)
    return {"method": method, "columns": columns,
            "r": [[None if np.isnan(v) else float(v) for v in row] for row in r],
            "p": [[None if np.isnan(v) else float(v) for v in row] for row in p],
            "n": n.tolist(),
            "note": "p-values are not adjusted for multiple comparisons; treat a matrix as exploratory."}


# --------------------------------------------------------------------------- #
# Association between categorical variables
# --------------------------------------------------------------------------- #
def _crosstab(df, x, y) -> tuple[pd.DataFrame, int]:
    require_columns(df, x, y)
    if x == y:
        raise AnalysisError("Choose two different variables.")
    frame = df[[x, y]].dropna()
    dropped = len(df) - len(frame)
    labels = frame.apply(lambda col: col.map(lambda v: f"{v:g}" if isinstance(v, float) else str(v)))
    ct = pd.crosstab(labels[x], labels[y])
    if ct.shape[0] < 2 or ct.shape[1] < 2:
        raise AnalysisError("Each variable needs at least two categories with data.")
    if ct.shape[0] > 30 or ct.shape[1] > 30:
        raise AnalysisError("One of the variables has more than 30 categories; a contingency-table test is not appropriate.")
    return ct, dropped


def _crosstab_tables(ct: pd.DataFrame, expected: np.ndarray | None, x: str, y: str) -> list[dict]:
    cols = [f"{x} \\ {y}"] + [str(c) for c in ct.columns] + ["Total"]
    rows = [[str(idx)] + [int(v) for v in row] + [int(row.sum())] for idx, row in zip(ct.index, ct.to_numpy())]
    rows.append(["Total"] + [int(v) for v in ct.sum(axis=0)] + [int(ct.to_numpy().sum())])
    tables = [table("Observed counts", cols, rows)]
    pct = ct.div(ct.sum(axis=1), axis=0) * 100
    tables.append(table(f"Row percentages (within {x})", cols[:-1],
                        [[str(idx)] + [float(v) for v in row] for idx, row in zip(pct.index, pct.to_numpy())]))
    if expected is not None:
        tables.append(table("Expected counts under independence", cols[:-1],
                            [[str(idx)] + [float(v) for v in row] for idx, row in zip(ct.index, expected)]))
    return tables


def chi_square(df, x, y, alpha=0.05, **_):
    """Pearson chi-square test of independence (no continuity correction)."""
    ct, dropped = _crosstab(df, x, y)
    n = int(ct.to_numpy().sum())
    if n < 5:
        raise InsufficientDataError(f"Only {n} complete record(s).")
    chi2, p, dof, expected = stats.chi2_contingency(ct.to_numpy(), correction=False)
    res = new_result("chi_square", "Chi-square test of independence", n=n, variables={"x": x, "y": y}, alpha=alpha)
    res["statistic"] = {"name": "chi2", "value": float(chi2)}
    res["df"] = int(dof)
    res["p_value"] = float(p)
    v = ES.cramers_v(float(chi2), n, *ct.shape)
    res["effect_sizes"].append(v)
    check = A.expected_counts(expected)
    res["assumptions"] += [check, A.independence_note()]
    res["tables"] = _crosstab_tables(ct, expected, x, y)
    if ct.shape == (2, 2):
        res["effect_sizes"].append(ES.odds_ratio(ct.to_numpy()))
        corrected = stats.chi2_contingency(ct.to_numpy(), correction=True)
        res["tables"].append(table("Yates continuity-corrected result (2 x 2 table)", ["chi2", "df", "p"],
                                   [[float(corrected[0]), int(corrected[2]), float(corrected[1])]]))
    if check["satisfied"] is False:
        res["warnings"].append("Expected counts are too small for the chi-square approximation. "
                               + ("Use Fisher's exact test instead." if ct.shape == (2, 2)
                                  else "Combine sparse categories where that makes sense, or collect more data."))
    if dropped:
        res["warnings"].append(f"{dropped} record(s) with a missing value were excluded.")
    res = finalize(res)
    res["apa"] = f"chi2({dof}, N = {n}) = {fmt_num(chi2, 2)}, {fmt_p(p)}, Cramer's V = {fmt_num(v['value'], 2)}"
    if res["significant"]:
        res["summary"] = (f"There is a statistically significant association between {x} and {y} ({res['apa']}). "
                          f"The strength of the association is {v['magnitude']}. The distribution of {y} differs across categories of {x}; "
                          "this does not establish a causal relationship.")
    else:
        res["summary"] = (f"The association between {x} and {y} is not statistically significant ({res['apa']}). "
                          "The data do not provide sufficient evidence that the two variables are related.")
    return res


def fisher_exact(df, x, y, alpha=0.05, alternative="two-sided", **_):
    """Fisher's exact test for a 2 x 2 table."""
    ct, dropped = _crosstab(df, x, y)
    if ct.shape != (2, 2):
        raise AnalysisError(f"Fisher's exact test is implemented for 2 x 2 tables only; this table is {ct.shape[0]} x {ct.shape[1]}. "
                            "Use the chi-square test, combining sparse categories if needed.")
    if alternative not in _ALTERNATIVES:
        raise AnalysisError("alternative must be two-sided, greater or less.")
    n = int(ct.to_numpy().sum())
    sample_or, p = stats.fisher_exact(ct.to_numpy(), alternative=alternative)
    res = new_result("fisher_exact", "Fisher's exact test", n=n, variables={"x": x, "y": y}, alpha=alpha)
    res["alternative"] = alternative
    res["statistic"] = {"name": "odds ratio", "value": float(sample_or) if np.isfinite(sample_or) else None}
    res["p_value"] = float(p)
    oratio = ES.odds_ratio(ct.to_numpy())
    res["effect_sizes"].append(oratio)
    res["assumptions"] += [A.independence_note(),
                           A._check("Exact test", None, None, None, True, "Fisher's test is exact, so it is valid for small expected counts.")]
    res["tables"] = _crosstab_tables(ct, None, x, y)
    if dropped:
        res["warnings"].append(f"{dropped} record(s) with a missing value were excluded.")
    res = finalize(res)
    res["apa"] = (f"Fisher's exact test, {fmt_p(p)}, OR = {fmt_num(oratio['value'], 2)}, "
                  f"95% CI [{fmt_num(oratio['ci_low'], 2)}, {fmt_num(oratio['ci_high'], 2)}]")
    verdict = "a statistically significant" if res["significant"] else "no statistically significant"
    res["summary"] = (f"Fisher's exact test shows {verdict} association between {x} and {y} ({res['apa']}; N = {n}). "
                      "An association does not show that one variable causes the other.")
    return res
