"""Statistical power and sample-size planning.

Power is computed from noncentral distributions (SciPy), the same approach as
G*Power. Three modes are kept strictly apart:

* ``required_n``  - PROSPECTIVE planning: the sample size needed to detect an
                    assumed effect with the desired power.
* ``power``       - PROSPECTIVE / sensitivity: the power a planned (or
                    available) sample gives for an *assumed* effect size.
* ``post_hoc``    - "observed power" computed from the effect found in the
                    data. It is a one-to-one function of the p-value and adds
                    no information (Hoenig & Heisey, 2001); it is provided only
                    because some departments request it, and always carries a
                    warning.
"""
from __future__ import annotations

import math

from scipy import stats

from app.statistics.utils import AnalysisError, to_jsonable

DESIGNS = {
    "t_test_independent": {"label": "Independent-samples t-test", "effect": "Cohen's d", "benchmarks": {"small": 0.2, "medium": 0.5, "large": 0.8}},
    "t_test_paired": {"label": "Paired-samples / one-sample t-test", "effect": "Cohen's dz", "benchmarks": {"small": 0.2, "medium": 0.5, "large": 0.8}},
    "correlation": {"label": "Pearson correlation", "effect": "r", "benchmarks": {"small": 0.1, "medium": 0.3, "large": 0.5}},
    "anova": {"label": "One-way ANOVA", "effect": "Cohen's f", "benchmarks": {"small": 0.1, "medium": 0.25, "large": 0.4}},
    "chi_square": {"label": "Chi-square test", "effect": "Cohen's w", "benchmarks": {"small": 0.1, "medium": 0.3, "large": 0.5}},
    "regression": {"label": "Multiple regression (overall F test)", "effect": "Cohen's f²", "benchmarks": {"small": 0.02, "medium": 0.15, "large": 0.35}},
}


def _tail_power_t(ncp: float, df: float, alpha: float, two_sided: bool) -> float:
    if two_sided:
        crit = stats.t.ppf(1 - alpha / 2, df)
        return float(stats.nct.sf(crit, df, ncp) + stats.nct.cdf(-crit, df, ncp))
    crit = stats.t.ppf(1 - alpha, df)
    return float(stats.nct.sf(crit, df, ncp))


def compute_power(design: str, effect_size: float, n: int, alpha: float = 0.05, two_sided: bool = True,
                  k_groups: int = 3, df: int = 1, n_predictors: int = 1, ratio: float = 1.0) -> float:
    """Power for a given design. ``n`` is per group for the independent t-test
    (group 2 has ``ratio * n``), the number of pairs for the paired t-test and
    the TOTAL sample size for every other design."""
    es = abs(float(effect_size))
    if es == 0:
        return alpha
    if design == "t_test_independent":
        n1, n2 = n, max(2, round(n * ratio))
        if n1 < 2:
            return float("nan")
        return _tail_power_t(es * math.sqrt(n1 * n2 / (n1 + n2)), n1 + n2 - 2, alpha, two_sided)
    if design == "t_test_paired":
        return float("nan") if n < 2 else _tail_power_t(es * math.sqrt(n), n - 1, alpha, two_sided)
    if design == "correlation":
        if n < 4:
            return float("nan")
        if es >= 1:
            return 1.0
        mean = math.atanh(es) * math.sqrt(n - 3)
        if two_sided:
            crit = stats.norm.ppf(1 - alpha / 2)
            return float(stats.norm.sf(crit - mean) + stats.norm.cdf(-crit - mean))
        return float(stats.norm.sf(stats.norm.ppf(1 - alpha) - mean))
    if design == "anova":
        dfd = n - k_groups
        if dfd < 1:
            return float("nan")
        crit = stats.f.ppf(1 - alpha, k_groups - 1, dfd)
        return float(stats.ncf.sf(crit, k_groups - 1, dfd, es**2 * n))
    if design == "chi_square":
        crit = stats.chi2.ppf(1 - alpha, df)
        return float(stats.ncx2.sf(crit, df, es**2 * n))
    if design == "regression":
        dfd = n - n_predictors - 1
        if dfd < 1:
            return float("nan")
        crit = stats.f.ppf(1 - alpha, n_predictors, dfd)
        return float(stats.ncf.sf(crit, n_predictors, dfd, es * n))   # es is f-squared
    raise AnalysisError(f"Unknown design for power analysis: {design}")


def required_n(design: str, effect_size: float, power: float = 0.8, alpha: float = 0.05, **kwargs) -> int | None:
    """Smallest n reaching the target power (bisection); None if above 1e6."""
    minimum = {"t_test_independent": 2, "t_test_paired": 2, "correlation": 4, "chi_square": 2,
               "anova": kwargs.get("k_groups", 3) + 1, "regression": kwargs.get("n_predictors", 1) + 2}[design]

    def enough(n: int) -> bool:
        value = compute_power(design, effect_size, n, alpha, **kwargs)
        return not math.isnan(value) and value >= power

    high = minimum
    while not enough(high):
        high *= 2
        if high > 1_000_000:
            return None
    low = max(minimum, high // 2)
    while low < high:
        mid = (low + high) // 2
        if enough(mid):
            high = mid
        else:
            low = mid + 1
    return int(high)


def run_power_analysis(design: str, mode: str = "required_n", effect_size: float | None = None, n: int | None = None,
                       power: float = 0.8, alpha: float = 0.05, two_sided: bool = True, k_groups: int = 3, df: int = 1,
                       n_predictors: int = 1, ratio: float = 1.0, **_) -> dict:
    if design not in DESIGNS:
        raise AnalysisError(f"design must be one of: {', '.join(DESIGNS)}.")
    if mode not in ("required_n", "power", "post_hoc"):
        raise AnalysisError("mode must be required_n, power or post_hoc.")
    if effect_size is None or float(effect_size) == 0:
        raise AnalysisError("An effect size is required (and must not be zero). Base it on previous studies or the smallest effect that would matter in practice.")
    if not 0 < alpha < 1:
        raise AnalysisError("alpha must be between 0 and 1.")
    if design == "correlation" and abs(effect_size) >= 1:
        raise AnalysisError("A correlation effect size must be between -1 and 1.")
    meta = DESIGNS[design]
    extra: dict = {}
    if design in ("t_test_independent", "t_test_paired", "correlation"):
        extra["two_sided"] = two_sided
    if design == "t_test_independent":
        extra["ratio"] = ratio
    if design == "anova":
        if k_groups < 2:
            raise AnalysisError("ANOVA needs at least 2 groups.")
        extra["k_groups"] = int(k_groups)
    if design == "chi_square":
        extra["df"] = int(df)
    if design == "regression":
        extra["n_predictors"] = int(n_predictors)

    unit = {"t_test_independent": "per group", "t_test_paired": "pairs"}.get(design, "in total")
    out: dict = {"method": "power_analysis", "method_name": "Power and sample-size analysis", "design": design,
                 "design_label": meta["label"], "mode": mode, "effect_size_name": meta["effect"], "effect_size": float(effect_size),
                 "alpha": alpha, "two_sided": two_sided if "two_sided" in extra else None, "benchmarks": meta["benchmarks"],
                 "parameters": extra, "warnings": [], "source": "statistical_engine"}

    if mode == "required_n":
        if not 0 < power < 1:
            raise AnalysisError("Target power must be between 0 and 1 (0.80 is conventional).")
        needed = required_n(design, effect_size, power, alpha, **extra)
        if needed is None:
            raise AnalysisError("The effect size is so small that more than 1,000,000 participants would be needed.")
        achieved = compute_power(design, effect_size, needed, alpha, **extra)
        total = needed + max(2, round(needed * ratio)) if design == "t_test_independent" else needed
        out.update(planning="prospective", target_power=power, required_n=needed, n_unit=unit, total_n=int(total), achieved_power=achieved)
        out["summary"] = (f"PROSPECTIVE sample-size planning: to detect {meta['effect']} = {abs(effect_size):g} with {power:.0%} power at alpha = {alpha:g} "
                          f"using a {meta['label'].lower()}, you need {needed} participants {unit}"
                          + (f" ({total} in total)" if design == "t_test_independent" else "") + f". Achieved power: {achieved:.3f}. "
                          "Increase this number to allow for drop-out and unusable responses.")
        curve_n = sorted({max(4, int(needed * f)) for f in (0.25, 0.5, 0.75, 1, 1.25, 1.5, 2)})
    else:
        if not n or n < 2:
            raise AnalysisError("A sample size is required.")
        value = compute_power(design, effect_size, int(n), alpha, **extra)
        if math.isnan(value):
            raise AnalysisError("The sample is too small for this design.")
        out.update(planning="post_hoc" if mode == "post_hoc" else "prospective", n=int(n), n_unit=unit, power=value)
        if mode == "post_hoc":
            out["warnings"].append("This is POST-HOC (observed) power, computed from the effect size found in your own data. It is a direct "
                                   "function of the p-value and does not show whether the study was adequately powered. Do not use it to explain "
                                   "a non-significant result; report the confidence interval of the effect instead.")
            out["summary"] = f"POST-HOC observed power = {value:.3f} for {meta['effect']} = {abs(effect_size):g} with n = {n} {unit} (interpret with caution; see warning)."
        else:
            out["summary"] = (f"PROSPECTIVE power: with n = {n} {unit}, a {meta['label'].lower()} has {value:.1%} power to detect an assumed "
                              f"{meta['effect']} = {abs(effect_size):g} at alpha = {alpha:g}." + (" This is below the conventional 80%." if value < 0.8 else ""))
        curve_n = sorted({max(4, int(n * f)) for f in (0.25, 0.5, 0.75, 1, 1.5, 2, 3)})
    out["power_curve"] = [{"n": m, "power": compute_power(design, effect_size, m, alpha, **extra)} for m in curve_n]
    return to_jsonable(out)
