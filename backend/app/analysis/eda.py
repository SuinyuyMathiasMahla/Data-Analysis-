"""Automatic exploratory data analysis."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.profiling import NUMERIC_TYPES, variable_kind
from app.statistics import assumptions as A
from app.statistics.correlation import correlation_matrix
from app.statistics.descriptive import describe_numeric, frequency_table
from app.statistics.effect_sizes import magnitude_r
from app.statistics.utils import table, to_jsonable

MAX_MATRIX_VARS = 25


def suggest_charts(df: pd.DataFrame, schema: dict, limit: int = 12) -> list[dict]:
    """Chart suggestions chosen from the variable types (not from the values)."""
    kinds = {c: variable_kind(df[c], schema.get(c)) for c in df.columns}
    continuous = [c for c, k in kinds.items() if k == "continuous"]
    categorical = [c for c, k in kinds.items() if k in ("binary", "nominal", "ordinal") and df[c].nunique() <= 12]
    dates = [c for c, k in kinds.items() if k == "datetime"]
    out: list[dict] = []
    for c in continuous[:3]:
        out.append({"chart_type": "histogram", "x": c, "title": f"Distribution of {c}",
                    "reason": "A histogram shows the shape, centre and spread of a continuous variable."})
    for c in categorical[:3]:
        out.append({"chart_type": "bar", "x": c, "title": f"Frequency of {c}",
                    "reason": "A bar chart compares how often each category occurs."})
    if len(continuous) >= 2:
        out.append({"chart_type": "scatter", "x": continuous[0], "y": continuous[1], "title": f"{continuous[1]} against {continuous[0]}",
                    "reason": "A scatter plot shows the form and strength of the relationship between two continuous variables."})
    if len(continuous) >= 3:
        out.append({"chart_type": "correlation_matrix", "columns": continuous[:12], "title": "Correlation matrix",
                    "reason": "A correlation heatmap gives an overview of all pairwise linear relationships."})
    if continuous and categorical:
        out.append({"chart_type": "box", "x": categorical[0], "y": continuous[0], "title": f"{continuous[0]} by {categorical[0]}",
                    "reason": "Box plots compare the median, spread and outliers of a numeric variable across groups."})
        out.append({"chart_type": "group_comparison", "x": categorical[0], "y": continuous[0], "title": f"Mean {continuous[0]} by {categorical[0]}",
                    "reason": "Group means with 95% confidence intervals show whether groups plausibly differ."})
    if len(categorical) >= 2:
        out.append({"chart_type": "heatmap", "x": categorical[0], "y": categorical[1], "title": f"{categorical[0]} by {categorical[1]}",
                    "reason": "A heatmap of counts shows how two categorical variables are jointly distributed."})
    if dates and continuous:
        out.append({"chart_type": "time_series", "x": dates[0], "y": continuous[0], "title": f"{continuous[0]} over time",
                    "reason": "A time-series plot shows trends and seasonality."})
    return out[:limit]


def run_eda(df: pd.DataFrame, schema: dict) -> dict:
    """Overview of a typed dataset: dimensions, summaries, missing data,
    distributions, outliers, correlations and suggested charts."""
    n_rows, n_cols = df.shape
    kinds = {c: variable_kind(df[c], schema.get(c)) for c in df.columns}
    numeric_cols = [c for c in df.columns if schema.get(c, {}).get("type") in NUMERIC_TYPES and kinds[c] in ("continuous", "ordinal")]
    categorical_cols = [c for c in df.columns if kinds[c] in ("binary", "nominal") or (kinds[c] == "ordinal" and c not in numeric_cols)]

    # numeric summaries, distribution shape and outliers
    numeric_summary, distributions, outliers = {}, [], []
    for col in numeric_cols:
        d = describe_numeric(df[col])
        numeric_summary[col] = d
        values = df[col].dropna().to_numpy(dtype=float)
        if len(values) >= 3 and kinds[col] == "continuous":
            norm = A.normality(values, col)
            skew = d.get("skewness") or 0.0
            shape = ("approximately symmetric" if abs(skew) < 0.5 else "moderately skewed" if abs(skew) < 1 else "highly skewed")
            if abs(skew) >= 0.5:
                shape += " to the right (long upper tail)" if skew > 0 else " to the left (long lower tail)"
            distributions.append({"variable": col, "skewness": d.get("skewness"), "kurtosis": d.get("kurtosis"), "shape": shape,
                                  "normality_test": norm["test"], "normality_p": norm["p_value"], "normal": norm["satisfied"]})
        if len(values) >= 8 and d.get("iqr"):
            low, high = d["q1"] - 1.5 * d["iqr"], d["q3"] + 1.5 * d["iqr"]
            mask = (values < low) | (values > high)
            if mask.any():
                outliers.append({"variable": col, "count": int(mask.sum()), "percent": float(100 * mask.mean()),
                                 "lower_fence": low, "upper_fence": high, "min": float(values.min()), "max": float(values.max())})

    categorical_summary = {c: frequency_table(df[c].map(lambda v: None if pd.isna(v) else (f"{v:g}" if isinstance(v, float) else str(v))), max_levels=15)
                           for c in categorical_cols}

    # missing data
    missing_by_col = df.isna().sum()
    missing = {
        "total_cells": int(missing_by_col.sum()),
        "percent_cells": float(100 * missing_by_col.sum() / max(n_rows * n_cols, 1)),
        "rows_with_missing": int(df.isna().any(axis=1).sum()),
        "complete_rows": int((~df.isna().any(axis=1)).sum()),
        "by_variable": [{"variable": c, "count": int(v), "percent": float(100 * v / max(n_rows, 1))}
                        for c, v in missing_by_col.sort_values(ascending=False).items() if v > 0],
    }

    # correlations
    correlations, relationships = None, []
    matrix_cols = numeric_cols[:MAX_MATRIX_VARS]
    if len(matrix_cols) >= 2:
        correlations = {"pearson": correlation_matrix(df, matrix_cols, "pearson"),
                        "spearman": correlation_matrix(df, matrix_cols, "spearman"),
                        "truncated": len(numeric_cols) > MAX_MATRIX_VARS}
        r = np.array([[np.nan if v is None else v for v in row] for row in correlations["pearson"]["r"]], dtype=float)
        p = correlations["pearson"]["p"]
        for i in range(len(matrix_cols)):
            for j in range(i + 1, len(matrix_cols)):
                if not np.isnan(r[i, j]):
                    relationships.append({"x": matrix_cols[i], "y": matrix_cols[j], "r": float(r[i, j]), "p": p[i][j],
                                          "strength": magnitude_r(r[i, j]), "direction": "positive" if r[i, j] > 0 else "negative"})
        relationships.sort(key=lambda item: -abs(item["r"]))
        relationships = relationships[:15]

    tables = []
    if numeric_summary:
        tables.append(table("Summary of numeric variables", ["Variable", "N", "Missing", "Mean", "SD", "Min", "Median", "Max", "Skewness"],
                            [[c, d["n"], d["n_missing"], d.get("mean"), d.get("std"), d.get("min"), d.get("median"), d.get("max"), d.get("skewness")]
                             for c, d in numeric_summary.items()]))
    if missing["by_variable"]:
        tables.append(table("Missing data by variable", ["Variable", "Missing", "Percent"],
                            [[m["variable"], m["count"], m["percent"]] for m in missing["by_variable"]]))
    if relationships:
        tables.append(table("Strongest linear relationships (exploratory)", ["Variable 1", "Variable 2", "Pearson r", "p", "Strength"],
                            [[rel["x"], rel["y"], rel["r"], rel["p"], rel["strength"]] for rel in relationships],
                            note="Unadjusted for multiple comparisons. Use these to generate questions, not to draw conclusions."))

    highlights = [f"The dataset has {n_rows} records and {n_cols} variables "
                  f"({len(numeric_cols)} numeric, {len(categorical_cols)} categorical)."]
    if missing["total_cells"]:
        highlights.append(f"{missing['percent_cells']:.1f}% of cells are missing; {missing['complete_rows']} of {n_rows} records are complete.")
    else:
        highlights.append("There are no missing values.")
    non_normal = [d["variable"] for d in distributions if d["normal"] is False]
    if non_normal:
        highlights.append(f"Not normally distributed: {', '.join(non_normal[:8])}. Consider rank-based methods for these variables.")
    if outliers:
        highlights.append("Possible outliers in: " + ", ".join(f"{o['variable']} ({o['count']})" for o in outliers[:8]) + ".")
    if relationships and abs(relationships[0]["r"]) >= 0.3:
        top = relationships[0]
        highlights.append(f"Strongest linear relationship: {top['x']} and {top['y']} (r = {top['r']:.2f}, {top['strength']} {top['direction']}).")

    return to_jsonable({
        "method": "eda", "method_name": "Exploratory data analysis", "n": n_rows,
        "dimensions": {"rows": n_rows, "columns": n_cols, "numeric": len(numeric_cols), "categorical": len(categorical_cols)},
        "variable_kinds": kinds,
        "numeric_summary": numeric_summary,
        "categorical_summary": categorical_summary,
        "missing": missing,
        "distributions": distributions,
        "outliers": outliers,
        "correlations": correlations,
        "relationships": relationships,
        "suggested_charts": suggest_charts(df, schema),
        "tables": tables,
        "highlights": highlights,
        "warnings": [],
        "summary": " ".join(highlights),
        "source": "statistical_engine",
    })
