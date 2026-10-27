"""Descriptive statistics for numeric and categorical variables."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from app.statistics.utils import AnalysisError, require_columns, table, to_jsonable


def mean_ci(values: np.ndarray, level: float = 0.95) -> tuple[float | None, float | None]:
    """t-based confidence interval for a mean."""
    n = len(values)
    if n < 2:
        return None, None
    se = np.std(values, ddof=1) / math.sqrt(n)
    half = stats.t.ppf(0.5 + level / 2, n - 1) * se
    mean = float(np.mean(values))
    return mean - half, mean + half


def proportion_ci(count: int, n: int, level: float = 0.95) -> tuple[float | None, float | None]:
    """Wilson score interval for a proportion (well behaved near 0 and 1)."""
    if n == 0:
        return None, None
    z = stats.norm.ppf(0.5 + level / 2)
    p = count / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def describe_numeric(series: pd.Series, level: float = 0.95) -> dict:
    """Full numeric summary. ``n_missing`` counts values absent or unparseable."""
    x = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    n = len(x)
    out: dict = {"n": n, "n_missing": int(len(series) - n)}
    if n == 0:
        return out
    q1, median, q3 = np.percentile(x, [25, 50, 75])
    modes = pd.Series(x).mode()
    mean = float(np.mean(x))
    sd = float(np.std(x, ddof=1)) if n > 1 else None
    ci_low, ci_high = mean_ci(x, level)
    out.update(
        mean=mean,
        median=float(median),
        mode=float(modes.iloc[0]) if len(modes) and len(modes) < n else None,
        n_modes=int(len(modes)) if len(modes) < n else 0,
        min=float(np.min(x)),
        max=float(np.max(x)),
        range=float(np.ptp(x)),
        variance=float(np.var(x, ddof=1)) if n > 1 else None,
        std=sd,
        sem=sd / math.sqrt(n) if sd is not None else None,
        q1=float(q1),
        q3=float(q3),
        iqr=float(q3 - q1),
        # CV is only meaningful on a ratio scale with a positive mean
        cv=(sd / mean) if sd is not None and mean > 0 and np.min(x) >= 0 else None,
        skewness=float(stats.skew(x, bias=False)) if n > 2 and sd else None,
        kurtosis=float(stats.kurtosis(x, bias=False)) if n > 3 and sd else None,
        ci_level=level,
        mean_ci_low=ci_low,
        mean_ci_high=ci_high,
        sum=float(np.sum(x)),
    )
    return out


def frequency_table(series: pd.Series, level: float = 0.95, max_levels: int = 50) -> dict:
    """Counts, percentages (of valid cases), cumulative % and Wilson CIs."""
    valid = series.dropna()
    n = len(valid)
    counts = valid.astype(str).value_counts()
    numeric_levels = pd.to_numeric(pd.Series(counts.index), errors="coerce")
    if numeric_levels.notna().all():           # keep 1..5 rating scales in order
        counts = counts.iloc[np.argsort(numeric_levels.to_numpy(), kind="stable")]
    rows = []
    cumulative = 0.0
    for value, count in counts.head(max_levels).items():
        pct = 100 * count / n if n else 0.0
        cumulative += pct
        lo, hi = proportion_ci(int(count), n, level)
        rows.append({"value": value, "count": int(count), "percent": pct, "cumulative_percent": cumulative,
                     "ci_low": None if lo is None else 100 * lo, "ci_high": None if hi is None else 100 * hi})
    return {
        "n": int(n),
        "n_missing": int(series.isna().sum()),
        "n_levels": int(len(counts)),
        "mode": counts.idxmax() if n else None,
        "levels": rows,
        "truncated": len(counts) > max_levels,
    }


def run_descriptive(df: pd.DataFrame, schema: dict, variables: list[str] | None = None,
                    group_by: str | None = None, level: float = 0.95) -> dict:
    """Descriptive statistics for the chosen variables (default: all usable ones)."""
    from app.analysis.profiling import NUMERIC_TYPES  # local import: avoid a cycle

    variables = variables or [c for c in df.columns if schema.get(c, {}).get("type") not in ("identifier", "text")]
    require_columns(df, *variables, group_by)
    if not variables:
        raise AnalysisError("Select at least one variable to describe.")

    numeric_rows, numeric, categorical = [], {}, {}
    for col in variables:
        spec = schema.get(col, {})
        if spec.get("type") in NUMERIC_TYPES and spec.get("measurement_level") != "nominal":
            d = describe_numeric(df[col], level)
            numeric[col] = d
            if d["n"]:
                numeric_rows.append([col, d["n"], d["n_missing"], d["mean"], d["std"], d["median"], d["min"], d["max"],
                                     d["q1"], d["q3"], d["skewness"], d["kurtosis"]])
            if spec.get("measurement_level") == "ordinal":
                categorical[col] = frequency_table(df[col].map(lambda v: None if pd.isna(v) else f"{v:g}"), level)
        elif spec.get("type") == "datetime":
            valid = df[col].dropna()
            numeric[col] = {"n": int(len(valid)), "n_missing": int(df[col].isna().sum()),
                            "min": valid.min().isoformat() if len(valid) else None,
                            "max": valid.max().isoformat() if len(valid) else None, "is_datetime": True}
        else:
            source = df[col]
            if spec.get("type") in NUMERIC_TYPES:
                source = source.map(lambda v: None if pd.isna(v) else f"{v:g}")
            categorical[col] = frequency_table(source, level)

    tables = []
    if numeric_rows:
        tables.append(table("Descriptive statistics (numeric variables)",
                            ["Variable", "N", "Missing", "Mean", "SD", "Median", "Min", "Max", "Q1", "Q3", "Skewness", "Kurtosis"],
                            numeric_rows))
    for col, freq in categorical.items():
        tables.append(table(f"Frequency distribution: {col}", ["Value", "Count", "Percent", "Cumulative %"],
                            [[r["value"], r["count"], r["percent"], r["cumulative_percent"]] for r in freq["levels"]],
                            note=f"Valid N = {freq['n']}; missing = {freq['n_missing']}."))

    grouped = None
    if group_by:
        grouped = {}
        rows = []
        for col in numeric:
            if numeric[col].get("is_datetime") or col == group_by:
                continue
            grouped[col] = {}
            for level_name, part in df.groupby(df[group_by].astype(str).where(df[group_by].notna()), sort=True):
                d = describe_numeric(part[col], level)
                grouped[col][str(level_name)] = d
                if d["n"]:
                    rows.append([col, str(level_name), d["n"], d["mean"], d["std"], d["median"], d["mean_ci_low"], d["mean_ci_high"]])
        if rows:
            tables.append(table(f"Descriptive statistics by {group_by}",
                                ["Variable", group_by, "N", "Mean", "SD", "Median", "95% CI low", "95% CI high"], rows))

    return to_jsonable({
        "method": "descriptive",
        "method_name": "Descriptive statistics",
        "n": int(len(df)),
        "variables": {"variables": variables, "group_by": group_by},
        "numeric": numeric,
        "categorical": categorical,
        "grouped": grouped,
        "tables": tables,
        "warnings": [],
        "summary": f"Descriptive statistics were computed for {len(variables)} variable(s) across {len(df)} record(s).",
        "source": "statistical_engine",
    })
