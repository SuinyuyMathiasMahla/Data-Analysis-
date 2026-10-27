"""
test_selector.py
----------------
Decision tree that automatically selects the correct
statistical test for each IV-DV pair based on:
  - Data types (numeric vs categorical)
  - Number of groups
  - Normality (Shapiro-Wilk)
  - Hypothesis being tested

Returns a test plan: list of {iv, dv, test, reason} dicts.
"""

import pandas as pd
import numpy as np
from scipy import stats
from typing import Optional


# ── Public API ────────────────────────────────────────────────────────────────

def select_tests(
    df: pd.DataFrame,
    profile: dict,
    hypotheses: list[dict],   # [{iv, dv, h0, h1}]
) -> list[dict]:
    """
    For each hypothesis, select the best statistical test.
    Returns a test plan list.
    """
    test_plan = []

    for hyp in hypotheses:
        iv_col = hyp.get("iv")
        dv_col = hyp.get("dv")

        if not iv_col or not dv_col:
            continue
        if iv_col not in df.columns or dv_col not in df.columns:
            continue

        iv_type = profile["columns"].get(iv_col, {}).get("dtype", "categorical")
        dv_type = profile["columns"].get(dv_col, {}).get("dtype", "numeric")
        n_groups = df[iv_col].nunique() if iv_type == "categorical" else None

        test, reason, assumptions = _decide_test(
            df, iv_col, dv_col, iv_type, dv_type, n_groups
        )

        test_plan.append({
            "hypothesis_id": hyp.get("id", len(test_plan) + 1),
            "iv":            iv_col,
            "iv_type":       iv_type,
            "dv":            dv_col,
            "dv_type":       dv_type,
            "n_groups":      n_groups,
            "test":          test,
            "reason":        reason,
            "assumptions":   assumptions,
            "h0":            hyp.get("h0", ""),
            "h1":            hyp.get("h1", ""),
        })

    return test_plan


# ── Decision Logic ─────────────────────────────────────────────────────────────

def _decide_test(
    df, iv_col, dv_col, iv_type, dv_type, n_groups
) -> tuple[str, str, dict]:

    assumptions = {}

    # ── BOTH NUMERIC ──────────────────────────────────────────────────────────
    if iv_type == "numeric" and dv_type == "numeric":
        normality_iv = _check_normality(df[iv_col].dropna())
        normality_dv = _check_normality(df[dv_col].dropna())
        assumptions["normality_iv"] = normality_iv
        assumptions["normality_dv"] = normality_dv

        if normality_iv["is_normal"] and normality_dv["is_normal"]:
            return (
                "pearson_correlation",
                "Both IV and DV are numeric and normally distributed. "
                "Pearson correlation measures the linear relationship strength.",
                assumptions,
            )
        else:
            return (
                "spearman_correlation",
                "Both IV and DV are numeric but normality assumption not met. "
                "Spearman correlation is the non-parametric alternative.",
                assumptions,
            )

    # ── CATEGORICAL IV, NUMERIC DV ────────────────────────────────────────────
    if iv_type == "categorical" and dv_type == "numeric":
        normality = _check_normality(df[dv_col].dropna())
        homogeneity = _check_homogeneity(df, iv_col, dv_col)
        assumptions["normality_dv"] = normality
        assumptions["homogeneity"]  = homogeneity

        if n_groups == 2:
            if normality["is_normal"] and homogeneity["is_homogeneous"]:
                return (
                    "independent_t_test",
                    f"IV '{iv_col}' has 2 categories. DV '{dv_col}' is numeric and normally "
                    "distributed with equal variances. Independent samples t-test is appropriate.",
                    assumptions,
                )
            else:
                return (
                    "mann_whitney_u",
                    f"IV '{iv_col}' has 2 categories but normality or equal variance assumption "
                    "not met. Mann-Whitney U is the non-parametric equivalent of the t-test.",
                    assumptions,
                )

        elif n_groups >= 3:
            if normality["is_normal"] and homogeneity["is_homogeneous"]:
                return (
                    "one_way_anova",
                    f"IV '{iv_col}' has {n_groups} categories. DV '{dv_col}' is numeric and "
                    "normally distributed. One-Way ANOVA compares means across all groups.",
                    assumptions,
                )
            else:
                return (
                    "kruskal_wallis",
                    f"IV '{iv_col}' has {n_groups} categories but normality or homogeneity "
                    "not met. Kruskal-Wallis H is the non-parametric alternative to ANOVA.",
                    assumptions,
                )

    # ── BOTH CATEGORICAL ─────────────────────────────────────────────────────
    if iv_type == "categorical" and dv_type == "categorical":
        dv_cats = df[dv_col].nunique()
        contingency = pd.crosstab(df[iv_col], df[dv_col])
        min_expected = _min_expected_frequency(contingency)
        assumptions["min_expected_frequency"] = min_expected

        if min_expected < 5:
            return (
                "fishers_exact",
                f"Both IV '{iv_col}' and DV '{dv_col}' are categorical but expected cell "
                "frequencies are below 5. Fisher's Exact Test is used instead of Chi-Square.",
                assumptions,
            )
        elif dv_cats == 2:
            return (
                "chi_square",
                f"Both IV '{iv_col}' and DV '{dv_col}' are categorical. "
                "Chi-Square test of independence assesses whether the distribution of "
                f"'{dv_col}' differs across '{iv_col}' groups.",
                assumptions,
            )
        else:
            return (
                "chi_square",
                f"Both IV '{iv_col}' and DV '{dv_col}' are categorical with multiple categories. "
                "Chi-Square test assesses statistical independence between them.",
                assumptions,
            )

    # ── NUMERIC IV, CATEGORICAL DV ────────────────────────────────────────────
    if iv_type == "numeric" and dv_type == "categorical":
        n_dv_cats = df[dv_col].nunique()
        if n_dv_cats == 2:
            return (
                "binary_logistic_regression",
                f"DV '{dv_col}' is binary categorical and IV '{iv_col}' is numeric. "
                "Binary Logistic Regression models the probability of each outcome.",
                assumptions,
            )
        else:
            return (
                "multinomial_logistic_regression",
                f"DV '{dv_col}' has {n_dv_cats} categories and IV '{iv_col}' is numeric. "
                "Multinomial Logistic Regression extends logistic regression to multiple classes.",
                assumptions,
            )

    # Fallback
    return (
        "descriptive_only",
        "Variable types could not be matched to a standard test. "
        "Descriptive statistics only.",
        assumptions,
    )


# ── Assumption Checkers ───────────────────────────────────────────────────────

def _check_normality(series: pd.Series, max_n: int = 5000) -> dict:
    """Shapiro-Wilk (n≤5000) or D'Agostino-Pearson (n>5000)."""
    series = series.dropna()
    n = len(series)
    if n < 3:
        return {"is_normal": True, "test": "skipped", "p_value": None, "note": "n < 3"}

    sample = series.sample(min(n, max_n), random_state=42)
    try:
        if n <= 5000:
            stat, p = stats.shapiro(sample)
            test_name = "Shapiro-Wilk"
        else:
            stat, p = stats.normaltest(sample)
            test_name = "D'Agostino-Pearson"
        return {
            "is_normal":  p > 0.05,
            "test":       test_name,
            "statistic":  round(float(stat), 4),
            "p_value":    round(float(p), 4),
            "note":       "Normal distribution assumed (p > 0.05)" if p > 0.05
                          else "Normality violated (p ≤ 0.05) — non-parametric test selected",
        }
    except Exception as e:
        return {"is_normal": False, "test": "error", "p_value": None, "note": str(e)}


def _check_homogeneity(df: pd.DataFrame, iv_col: str, dv_col: str) -> dict:
    """Levene's test for equality of variances."""
    groups = [grp[dv_col].dropna().values for _, grp in df.groupby(iv_col)
              if len(grp[dv_col].dropna()) >= 2]
    if len(groups) < 2:
        return {"is_homogeneous": True, "test": "skipped", "p_value": None}
    try:
        stat, p = stats.levene(*groups)
        return {
            "is_homogeneous": p > 0.05,
            "test":           "Levene's",
            "statistic":      round(float(stat), 4),
            "p_value":        round(float(p), 4),
            "note": "Equal variances assumed (p > 0.05)" if p > 0.05
                    else "Unequal variances (p ≤ 0.05)",
        }
    except Exception as e:
        return {"is_homogeneous": True, "test": "error", "p_value": None, "note": str(e)}


def _min_expected_frequency(contingency: pd.DataFrame) -> float:
    from scipy.stats import chi2_contingency
    try:
        _, _, _, expected = chi2_contingency(contingency)
        return float(expected.min())
    except Exception:
        return 5.0
