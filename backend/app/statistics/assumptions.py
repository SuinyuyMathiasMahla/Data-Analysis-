"""Assumption checks that are run *before* a test is trusted.

Each check returns one dict:
    {name, test, statistic, p_value, satisfied (True/False/None), note}
``satisfied = None`` means "could not be assessed", never "fine".
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy import stats

from app.statistics.utils import fmt_p


def _check(name: str, test: str | None, statistic, p_value, satisfied, note: str) -> dict:
    return {
        "name": name,
        "test": test,
        "statistic": None if statistic is None else float(statistic),
        "p_value": None if p_value is None else float(p_value),
        "satisfied": satisfied,
        "note": note,
    }


def normality(values, label: str = "values", alpha: float = 0.05) -> dict:
    """Shapiro-Wilk (n <= 5000) or D'Agostino-Pearson (larger samples).

    With large samples these tests flag trivial departures, so for n > 300 the
    decision uses skewness and kurtosis (|skew| < 2 and |excess kurtosis| < 7;
    Kim, 2013) and the test p-value is reported for information only.
    """
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    name = f"Normality of {label}"
    if n < 3:
        return _check(name, None, None, None, None, f"Only {n} value(s): normality cannot be assessed.")
    if np.ptp(x) == 0:
        return _check(name, None, None, None, False, "All values are identical, so the distribution is not normal.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if n <= 5000:
            stat, p = stats.shapiro(x)
            test = "Shapiro-Wilk"
        else:
            stat, p = stats.normaltest(x)
            test = "D'Agostino-Pearson"
        skew = float(stats.skew(x, bias=False)) if n > 2 else 0.0
        kurt = float(stats.kurtosis(x, bias=False)) if n > 3 else 0.0
    shape = f"skewness = {skew:.2f}, excess kurtosis = {kurt:.2f}"
    if n > 300:
        ok = abs(skew) < 2 and abs(kurt) < 7
        note = (f"n = {n} is large, so the decision uses shape ({shape}) rather than the {test} p-value, "
                "which becomes over-sensitive in large samples.")
    else:
        ok = bool(p > alpha)
        note = (f"{test} W = {stat:.3f}, {fmt_p(p)}; {shape}. " if test == "Shapiro-Wilk" else f"{shape}. ")
        note += "No evidence against normality." if ok else "The distribution departs from normality."
        if n < 20:
            note += " With fewer than 20 values the test has little power, so inspect a Q-Q plot as well."
    return _check(name, test, stat, p, ok, note)


def homogeneity_of_variance(groups: list, alpha: float = 0.05) -> dict:
    """Brown-Forsythe / Levene test centred on the median (robust to non-normality)."""
    arrays = [np.asarray(g, dtype=float) for g in groups]
    arrays = [a[np.isfinite(a)] for a in arrays]
    name = "Homogeneity of variance"
    if len(arrays) < 2 or any(len(a) < 2 for a in arrays):
        return _check(name, "Levene (median)", None, None, None, "Each group needs at least 2 values.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stat, p = stats.levene(*arrays, center="median")
    if not np.isfinite(stat):
        return _check(name, "Levene (median)", None, None, None, "Could not be computed (no variation within groups).")
    ok = bool(p > alpha)
    note = "Group variances are similar." if ok else "Group variances differ; use a test that does not assume equal variances."
    return _check(name, "Levene (median)", stat, p, ok, note)


def minimum_sample(n: int, minimum: int, what: str) -> dict:
    ok = n >= minimum
    note = f"n = {n}." if ok else f"n = {n} is below the recommended minimum of {minimum} for {what}; treat results with caution."
    return _check("Sample size", None, None, None, ok, note)


def independence_note(design: str | None = None) -> dict:
    """Independence cannot be tested from the data; it is a design property."""
    note = ("Independence of observations is a property of the study design and cannot be verified from the data. "
            "Confirm that each row is a separate participant/unit and that units did not influence one another.")
    if design:
        note += f" Recorded study design: {design}."
    return _check("Independence of observations", None, None, None, None, note)


def expected_counts(expected: np.ndarray) -> dict:
    """Cochran's rule for chi-square: no expected count < 1 and at most 20% < 5."""
    exp = np.asarray(expected, dtype=float)
    below5 = float((exp < 5).mean())
    ok = bool(exp.min() >= 1 and below5 <= 0.2)
    note = (f"Smallest expected count = {exp.min():.2f}; {below5:.0%} of cells have an expected count below 5. "
            + ("Cochran's rule is met." if ok else "Cochran's rule is violated, so the chi-square approximation is unreliable."))
    return _check("Expected cell counts", "Cochran's rule", float(exp.min()), None, ok, note)


def outlier_influence(x, label: str) -> dict:
    """Flags extreme values (beyond 3 x IQR) that can dominate means and r."""
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 8:
        return _check(f"Extreme values in {label}", "3 x IQR rule", None, None, None, "Too few values to assess.")
    q1, q3 = np.percentile(a, [25, 75])
    iqr = q3 - q1
    n_extreme = int(((a < q1 - 3 * iqr) | (a > q3 + 3 * iqr)).sum()) if iqr > 0 else 0
    ok = n_extreme == 0
    note = "No extreme values." if ok else f"{n_extreme} extreme value(s) may unduly influence the result."
    return _check(f"Extreme values in {label}", "3 x IQR rule", n_extreme, None, ok, note)
