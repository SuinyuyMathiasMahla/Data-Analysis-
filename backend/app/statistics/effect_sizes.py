"""Effect sizes and their verbal interpretation.

Benchmarks are Cohen's (1988) conventions. They are rules of thumb: the
practical importance of an effect always depends on the field, which is why
every interpretation string says "by Cohen's conventions".
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats


def _entry(name: str, value: float | None, magnitude: str | None, ci: tuple[float, float] | None = None,
           note: str | None = None) -> dict:
    return {
        "name": name,
        "value": None if value is None or not math.isfinite(value) else float(value),
        "magnitude": magnitude,
        "ci_low": None if ci is None else float(ci[0]),
        "ci_high": None if ci is None else float(ci[1]),
        "ci_level": 0.95 if ci is not None else None,
        "note": note,
    }


def magnitude_d(d: float) -> str:
    a = abs(d)
    return "negligible" if a < 0.2 else "small" if a < 0.5 else "medium" if a < 0.8 else "large"


def magnitude_r(r: float) -> str:
    a = abs(r)
    return "negligible" if a < 0.1 else "weak" if a < 0.3 else "moderate" if a < 0.5 else "strong"


def magnitude_eta2(eta2: float) -> str:
    return "negligible" if eta2 < 0.01 else "small" if eta2 < 0.06 else "medium" if eta2 < 0.14 else "large"


def magnitude_cramers_v(v: float, df_min: int) -> str:
    """Cohen's w benchmarks (.1/.3/.5) rescaled by sqrt(min(r, c) - 1)."""
    scale = math.sqrt(max(df_min, 1))
    return "negligible" if v < 0.1 / scale else "weak" if v < 0.3 / scale else "moderate" if v < 0.5 / scale else "strong"


def cohens_d_independent(x: np.ndarray, y: np.ndarray) -> list[dict]:
    """Cohen's d (pooled SD) with an approximate 95% CI, plus Hedges' g."""
    n1, n2 = len(x), len(y)
    v1, v2 = np.var(x, ddof=1), np.var(y, ddof=1)
    pooled = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    if pooled == 0:
        return [_entry("Cohen's d", None, None, note="Undefined: both groups have zero variance.")]
    d = (np.mean(x) - np.mean(y)) / pooled
    se = math.sqrt((n1 + n2) / (n1 * n2) + d**2 / (2 * (n1 + n2)))
    z = stats.norm.ppf(0.975)
    correction = 1 - 3 / (4 * (n1 + n2) - 9)
    return [
        _entry("Cohen's d", d, magnitude_d(d), (d - z * se, d + z * se)),
        _entry("Hedges' g", d * correction, magnitude_d(d * correction), note="Cohen's d corrected for small-sample bias."),
    ]


def cohens_d_paired(diff: np.ndarray) -> list[dict]:
    """d_z: mean of the paired differences divided by their SD."""
    sd = np.std(diff, ddof=1)
    if sd == 0:
        return [_entry("Cohen's d (paired, dz)", None, None, note="Undefined: all differences are identical.")]
    n = len(diff)
    d = np.mean(diff) / sd
    se = math.sqrt(1 / n + d**2 / (2 * n))
    z = stats.norm.ppf(0.975)
    return [_entry("Cohen's d (paired, dz)", d, magnitude_d(d), (d - z * se, d + z * se))]


def r_entry(name: str, r: float, ci: tuple[float, float] | None = None) -> dict:
    return _entry(name, r, magnitude_r(r), ci)


def r_squared_entry(r: float) -> dict:
    return _entry("r² (shared variance)", r * r, None,
                  note=f"The two variables share about {100 * r * r:.1f}% of their variance.")


def eta_squared(ss_between: float, ss_total: float, df_between: int, ms_within: float) -> list[dict]:
    if ss_total <= 0:
        return [_entry("Eta squared (η²)", None, None, note="Undefined: no variance in the outcome.")]
    eta2 = ss_between / ss_total
    omega2 = max(0.0, (ss_between - df_between * ms_within) / (ss_total + ms_within))
    return [
        _entry("Eta squared (η²)", eta2, magnitude_eta2(eta2),
               note=f"Group membership accounts for about {100 * eta2:.1f}% of the variance in the outcome."),
        _entry("Omega squared (ω²)", omega2, magnitude_eta2(omega2), note="Less biased estimate of the population effect."),
    ]


def partial_eta_squared(ss_effect: float, ss_error: float) -> dict:
    denom = ss_effect + ss_error
    value = ss_effect / denom if denom > 0 else None
    return _entry("Partial eta squared (ηp²)", value, magnitude_eta2(value) if value is not None else None)


def cramers_v(chi2: float, n: int, n_rows: int, n_cols: int) -> dict:
    k = min(n_rows, n_cols) - 1
    if n <= 0 or k <= 0:
        return _entry("Cramér's V", None, None)
    v = math.sqrt(chi2 / (n * k))
    return _entry("Cramér's V", v, magnitude_cramers_v(v, k))


def odds_ratio(table: np.ndarray) -> dict:
    """Odds ratio for a 2x2 table with a Woolf (log) 95% CI.
    A Haldane-Anscombe 0.5 correction is applied when any cell is zero."""
    a, b, c, d = [float(v) for v in np.asarray(table, dtype=float).ravel()]
    note = None
    if min(a, b, c, d) == 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
        note = "A cell count was zero, so 0.5 was added to every cell (Haldane-Anscombe correction)."
    or_ = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    z = stats.norm.ppf(0.975)
    ci = (math.exp(math.log(or_) - z * se), math.exp(math.log(or_) + z * se))
    size = max(or_, 1 / or_)
    magnitude = "negligible" if size < 1.5 else "small" if size < 2.5 else "medium" if size < 4.3 else "large"
    return _entry("Odds ratio", or_, magnitude, ci, note)


def rank_biserial(u: float, n1: int, n2: int) -> dict:
    """Rank-biserial correlation for Mann-Whitney U (u = U statistic of group 1)."""
    r = 2 * u / (n1 * n2) - 1
    return _entry("Rank-biserial correlation", r, magnitude_r(r))


def matched_rank_biserial(diff: np.ndarray) -> dict:
    """Matched-pairs rank-biserial correlation for the Wilcoxon signed-rank test."""
    d = diff[diff != 0]
    if len(d) == 0:
        return _entry("Matched-pairs rank-biserial correlation", None, None)
    ranks = stats.rankdata(np.abs(d))
    pos, neg = ranks[d > 0].sum(), ranks[d < 0].sum()
    r = (pos - neg) / (pos + neg)
    return _entry("Matched-pairs rank-biserial correlation", r, magnitude_r(r))


def epsilon_squared(h: float, n: int) -> dict:
    """Epsilon squared for Kruskal-Wallis H."""
    value = h * (n + 1) / (n**2 - 1) if n > 1 else None
    value = None if value is None else min(1.0, max(0.0, value))
    return _entry("Epsilon squared (ε²)", value, magnitude_eta2(value) if value is not None else None)


def kendalls_w(chi2: float, n: int, k: int) -> dict:
    """Kendall's W for the Friedman test."""
    value = chi2 / (n * (k - 1)) if n > 0 and k > 1 else None
    magnitude = None if value is None else ("weak" if value < 0.3 else "moderate" if value < 0.5 else "strong")
    return _entry("Kendall's W", value, magnitude)


def describe_effect(entry: dict) -> str:
    """One plain-language sentence about the practical size of an effect."""
    if entry.get("value") is None:
        return f"{entry['name']} could not be computed."
    text = f"{entry['name']} = {entry['value']:.3f}"
    if entry.get("ci_low") is not None:
        text += f" (95% CI {entry['ci_low']:.3f} to {entry['ci_high']:.3f})"
    if entry.get("magnitude"):
        text += f", a {entry['magnitude']} effect by Cohen's conventions"
    return text + "."
