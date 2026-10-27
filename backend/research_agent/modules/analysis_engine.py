"""
analysis_engine.py
------------------
Runs the statistical test selected by test_selector.py
for each hypothesis. Returns structured results including
test statistic, p-value, effect size, group means/counts,
and an interpretation label.
"""

import pandas as pd
import numpy as np
from scipy import stats
from typing import Any
import warnings
warnings.filterwarnings("ignore")


def run_analysis(df: pd.DataFrame, test_plan: list[dict]) -> list[dict]:
    """
    Execute every test in the plan and return a results list.
    Each result mirrors its test_plan entry but adds
    'result', 'effect_size', 'interpretation', 'group_stats'.
    """
    results = []
    for plan_item in test_plan:
        test = plan_item["test"]
        iv   = plan_item["iv"]
        dv   = plan_item["dv"]

        try:
            if test == "pearson_correlation":
                res = _pearson(df, iv, dv)
            elif test == "spearman_correlation":
                res = _spearman(df, iv, dv)
            elif test == "independent_t_test":
                res = _t_test(df, iv, dv)
            elif test == "mann_whitney_u":
                res = _mann_whitney(df, iv, dv)
            elif test == "one_way_anova":
                res = _anova(df, iv, dv)
            elif test == "kruskal_wallis":
                res = _kruskal(df, iv, dv)
            elif test == "chi_square":
                res = _chi_square(df, iv, dv)
            elif test == "fishers_exact":
                res = _fishers_exact(df, iv, dv)
            elif test == "binary_logistic_regression":
                res = _logistic_regression(df, iv, dv, multi=False)
            elif test == "multinomial_logistic_regression":
                res = _logistic_regression(df, iv, dv, multi=True)
            else:
                res = _descriptive_only(df, iv, dv)

        except Exception as e:
            res = {"error": str(e), "test": test}

        results.append({**plan_item, **res})

    return results


# ── Individual Test Runners ───────────────────────────────────────────────────

def _pearson(df, iv, dv):
    x = df[iv].dropna()
    y = df[dv].dropna()
    idx = x.index.intersection(y.index)
    r, p = stats.pearsonr(x[idx], y[idx])
    r2 = r ** 2
    return {
        "result": {"r": round(r, 4), "r_squared": round(r2, 4), "p_value": round(p, 6), "n": len(idx)},
        "effect_size": {"name": "r", "value": round(abs(r), 4),
                        "magnitude": _effect_label_r(abs(r))},
        "interpretation": _interpret(p, f"Pearson r = {round(r,4)}"),
        "group_stats": None,
        "significant": p < 0.05,
        "p_value": round(p, 6),
    }


def _spearman(df, iv, dv):
    x = df[iv].dropna()
    y = df[dv].dropna()
    idx = x.index.intersection(y.index)
    rho, p = stats.spearmanr(x[idx], y[idx])
    return {
        "result": {"rho": round(rho, 4), "p_value": round(p, 6), "n": len(idx)},
        "effect_size": {"name": "ρ", "value": round(abs(rho), 4),
                        "magnitude": _effect_label_r(abs(rho))},
        "interpretation": _interpret(p, f"Spearman ρ = {round(rho,4)}"),
        "group_stats": None,
        "significant": p < 0.05,
        "p_value": round(p, 6),
    }


def _t_test(df, iv, dv):
    groups = df.groupby(iv)[dv].apply(list)
    if len(groups) < 2:
        raise ValueError("Need exactly 2 groups for t-test.")
    g1, g2 = list(groups.iloc[0]), list(groups.iloc[1])
    t, p = stats.ttest_ind(g1, g2)
    n1, n2 = len(g1), len(g2)
    pooled_sd = np.sqrt(((n1-1)*np.std(g1)**2 + (n2-1)*np.std(g2)**2) / (n1+n2-2))
    d = (np.mean(g1) - np.mean(g2)) / pooled_sd if pooled_sd > 0 else 0
    group_stats = {str(groups.index[0]): _group_desc(g1),
                   str(groups.index[1]): _group_desc(g2)}
    return {
        "result": {"t": round(t, 4), "df": n1+n2-2, "p_value": round(p, 6)},
        "effect_size": {"name": "Cohen's d", "value": round(abs(d), 4),
                        "magnitude": _effect_label_d(abs(d))},
        "interpretation": _interpret(p, f"t({n1+n2-2}) = {round(t,4)}"),
        "group_stats": group_stats,
        "significant": p < 0.05,
        "p_value": round(p, 6),
    }


def _mann_whitney(df, iv, dv):
    groups = df.groupby(iv)[dv].apply(list)
    g1, g2 = list(groups.iloc[0]), list(groups.iloc[1])
    u, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
    n1, n2 = len(g1), len(g2)
    r = 1 - (2*u)/(n1*n2) if n1*n2 > 0 else 0
    group_stats = {str(groups.index[0]): _group_desc(g1),
                   str(groups.index[1]): _group_desc(g2)}
    return {
        "result": {"U": round(u, 4), "p_value": round(p, 6), "n": n1+n2},
        "effect_size": {"name": "r", "value": round(abs(r), 4),
                        "magnitude": _effect_label_r(abs(r))},
        "interpretation": _interpret(p, f"U = {round(u,4)}"),
        "group_stats": group_stats,
        "significant": p < 0.05,
        "p_value": round(p, 6),
    }


def _anova(df, iv, dv):
    groups = [g[dv].dropna().values for _, g in df.groupby(iv)]
    f, p = stats.f_oneway(*groups)
    # Eta-squared
    grand_mean = df[dv].mean()
    ss_between = sum(len(g)*(g.mean()-grand_mean)**2 for g in [pd.Series(g) for g in groups])
    ss_total   = ((df[dv] - grand_mean)**2).sum()
    eta2 = ss_between / ss_total if ss_total > 0 else 0
    df_between = len(groups) - 1
    df_within  = len(df[dv].dropna()) - len(groups)
    group_stats = {
        str(name): _group_desc(list(grp[dv].dropna()))
        for name, grp in df.groupby(iv)
    }
    return {
        "result": {"F": round(f, 4), "df_between": df_between,
                   "df_within": df_within, "p_value": round(p, 6)},
        "effect_size": {"name": "η²", "value": round(eta2, 4),
                        "magnitude": _effect_label_eta2(eta2)},
        "interpretation": _interpret(p, f"F({df_between},{df_within}) = {round(f,4)}"),
        "group_stats": group_stats,
        "significant": p < 0.05,
        "p_value": round(p, 6),
    }


def _kruskal(df, iv, dv):
    groups = [g[dv].dropna().values for _, g in df.groupby(iv)]
    h, p = stats.kruskal(*groups)
    n = df[dv].dropna().shape[0]
    k = len(groups)
    eta2_h = (h - k + 1) / (n - k) if n > k else 0
    group_stats = {
        str(name): _group_desc(list(grp[dv].dropna()))
        for name, grp in df.groupby(iv)
    }
    return {
        "result": {"H": round(h, 4), "df": k-1, "p_value": round(p, 6), "n": n},
        "effect_size": {"name": "η²(H)", "value": round(eta2_h, 4),
                        "magnitude": _effect_label_eta2(eta2_h)},
        "interpretation": _interpret(p, f"H({k-1}) = {round(h,4)}"),
        "group_stats": group_stats,
        "significant": p < 0.05,
        "p_value": round(p, 6),
    }


def _chi_square(df, iv, dv):
    ct = pd.crosstab(df[iv], df[dv])
    chi2, p, dof, expected = stats.chi2_contingency(ct)
    n = ct.values.sum()
    cramers_v = np.sqrt(chi2 / (n * (min(ct.shape)-1))) if n > 0 else 0
    return {
        "result": {"chi2": round(chi2, 4), "df": dof, "p_value": round(p, 6), "n": int(n)},
        "effect_size": {"name": "Cramér's V", "value": round(cramers_v, 4),
                        "magnitude": _effect_label_v(cramers_v)},
        "interpretation": _interpret(p, f"χ²({dof}) = {round(chi2,4)}"),
        "group_stats": ct.to_dict(),
        "significant": p < 0.05,
        "p_value": round(p, 6),
    }


def _fishers_exact(df, iv, dv):
    ct = pd.crosstab(df[iv], df[dv])
    if ct.shape == (2, 2):
        oddsratio, p = stats.fisher_exact(ct.values)
    else:
        chi2, p, _, _ = stats.chi2_contingency(ct)
        oddsratio = None
    return {
        "result": {"odds_ratio": round(oddsratio, 4) if oddsratio else None,
                   "p_value": round(p, 6)},
        "effect_size": None,
        "interpretation": _interpret(p, f"Fisher's p = {round(p,6)}"),
        "group_stats": ct.to_dict(),
        "significant": p < 0.05,
        "p_value": round(p, 6),
    }


def _logistic_regression(df, iv, dv, multi=False):
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import LabelEncoder
        from sklearn.metrics import accuracy_score, classification_report

        X = df[[iv]].dropna()
        y = df[dv].loc[X.index].dropna()
        X = X.loc[y.index]

        if X.dtypes[iv] == object:
            from sklearn.preprocessing import OrdinalEncoder
            X = OrdinalEncoder().fit_transform(X)
        else:
            X = X.values

        le = LabelEncoder()
        y_enc = le.fit_transform(y)

        model = LogisticRegression(max_iter=1000,
                                   multi_class="multinomial" if multi else "ovr")
        model.fit(X, y_enc)
        preds = model.predict(X)
        acc   = accuracy_score(y_enc, preds)

        return {
            "result": {"accuracy": round(acc, 4), "n": len(y_enc),
                       "classes": list(le.classes_)},
            "effect_size": {"name": "Accuracy", "value": round(acc, 4),
                            "magnitude": "Strong" if acc > 0.75 else
                                         "Moderate" if acc > 0.60 else "Weak"},
            "interpretation": f"Model correctly classifies {round(acc*100,1)}% of cases.",
            "group_stats": None,
            "significant": acc > 0.60,
            "p_value": None,
        }
    except ImportError:
        return {"error": "scikit-learn not installed", "test": "logistic_regression"}


def _descriptive_only(df, iv, dv):
    desc = df[[iv, dv]].describe().to_dict()
    return {
        "result": desc,
        "effect_size": None,
        "interpretation": "Descriptive statistics only — no inferential test run.",
        "group_stats": None,
        "significant": False,
        "p_value": None,
    }


# ── Helper Functions ──────────────────────────────────────────────────────────

def _group_desc(values: list) -> dict:
    arr = np.array(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    return {
        "n":      len(arr),
        "mean":   round(float(np.mean(arr)), 4),
        "median": round(float(np.median(arr)), 4),
        "std":    round(float(np.std(arr)), 4),
        "min":    round(float(np.min(arr)), 4),
        "max":    round(float(np.max(arr)), 4),
    }


def _interpret(p: float, stat_str: str) -> str:
    sig = "statistically significant" if p < 0.05 else "not statistically significant"
    threshold = "p < 0.001" if p < 0.001 else f"p = {round(p,4)}"
    return f"{stat_str}, {threshold} — result is {sig}."


def _effect_label_r(r):
    if r >= 0.5: return "Large"
    if r >= 0.3: return "Moderate"
    if r >= 0.1: return "Small"
    return "Negligible"

def _effect_label_d(d):
    if d >= 0.8: return "Large"
    if d >= 0.5: return "Moderate"
    if d >= 0.2: return "Small"
    return "Negligible"

def _effect_label_eta2(e):
    if e >= 0.14: return "Large"
    if e >= 0.06: return "Moderate"
    if e >= 0.01: return "Small"
    return "Negligible"

def _effect_label_v(v):
    if v >= 0.5: return "Large"
    if v >= 0.3: return "Moderate"
    if v >= 0.1: return "Small"
    return "Negligible"
