"""
profiler.py
-----------
Scans any uploaded dataset and returns a full column profile,
data quality report, and suggested IV/DV mappings based on
the project's research questions.
"""

import pandas as pd
import numpy as np
from typing import Any


def profile_dataset(df: pd.DataFrame, research_questions: list[str] = None) -> dict:
    """
    Full dataset profile. Returns column-level metadata,
    quality flags, and suggested variable roles.
    """
    profile = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": {},
        "quality_summary": {},
        "suggested_roles": {},
        "warnings": [],
    }

    for col in df.columns:
        series = df[col]
        dtype  = _infer_type(series)
        missing = int(series.isna().sum())
        missing_pct = round(missing / len(series) * 100, 2)

        col_info = {
            "dtype":        dtype,
            "missing":      missing,
            "missing_pct":  missing_pct,
            "unique_values": int(series.nunique()),
            "sample_values": series.dropna().head(5).tolist(),
        }

        if dtype == "numeric":
            col_info.update({
                "mean":   round(series.mean(), 4),
                "median": round(series.median(), 4),
                "std":    round(series.std(), 4),
                "min":    round(series.min(), 4),
                "max":    round(series.max(), 4),
                "skewness": round(series.skew(), 4),
                "outlier_count": _count_outliers(series),
            })
        elif dtype == "categorical":
            vc = series.value_counts()
            col_info["top_categories"] = vc.head(10).to_dict()
            col_info["category_count"] = int(series.nunique())

        elif dtype == "datetime":
            parsed = pd.to_datetime(series, errors="coerce")
            col_info["date_min"] = str(parsed.min())
            col_info["date_max"] = str(parsed.max())

        profile["columns"][col] = col_info

        # Quality warnings
        if missing_pct > 20:
            profile["warnings"].append(
                f"'{col}' has {missing_pct}% missing values — consider imputation or exclusion."
            )
        if dtype == "numeric" and col_info.get("outlier_count", 0) > len(series) * 0.05:
            profile["warnings"].append(
                f"'{col}' has {col_info['outlier_count']} outliers (>{5}% of rows) — review before analysis."
            )
        if dtype == "categorical" and col_info["unique_values"] > 50:
            profile["warnings"].append(
                f"'{col}' has {col_info['unique_values']} unique categories — may need grouping."
            )

    # Quality summary
    total_cells = len(df) * len(df.columns)
    total_missing = df.isna().sum().sum()
    profile["quality_summary"] = {
        "total_cells":      total_cells,
        "total_missing":    int(total_missing),
        "completeness_pct": round((1 - total_missing / total_cells) * 100, 2),
        "duplicate_rows":   int(df.duplicated().sum()),
        "numeric_columns":  sum(1 for c in profile["columns"].values() if c["dtype"] == "numeric"),
        "categorical_columns": sum(1 for c in profile["columns"].values() if c["dtype"] == "categorical"),
        "datetime_columns": sum(1 for c in profile["columns"].values() if c["dtype"] == "datetime"),
    }

    # Suggest IV / DV roles
    profile["suggested_roles"] = _suggest_roles(df, profile["columns"], research_questions)

    return profile


def _infer_type(series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    # Try parsing as datetime
    try:
        pd.to_datetime(series.dropna().head(10), infer_datetime_format=True)
        if series.dtype == object:
            sample = series.dropna().head(20).astype(str)
            if sample.str.match(r"\d{4}-\d{2}-\d{2}").mean() > 0.8:
                return "datetime"
    except Exception:
        pass
    return "categorical"


def _count_outliers(series: pd.Series) -> int:
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    return int(((series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)).sum())


def _suggest_roles(df: pd.DataFrame, col_profiles: dict, rqs: list[str]) -> dict:
    """
    Heuristically suggest which columns are likely IVs, DVs,
    ID columns, or date columns.
    """
    roles: dict[str, str] = {}
    rq_text = " ".join(rqs or []).lower()

    for col, info in col_profiles.items():
        col_lower = col.lower()

        # Obvious IDs
        if any(k in col_lower for k in ["id", "order", "customer", "index", "key", "code", "ref"]):
            roles[col] = "identifier"
            continue

        # Date columns
        if info["dtype"] == "datetime" or any(k in col_lower for k in ["date", "time", "year", "month", "season"]):
            roles[col] = "date"
            continue

        # Likely DVs — outcome/target words
        dv_keywords = ["revenue", "profit", "margin", "rating", "score", "return",
                        "result", "outcome", "target", "goal", "performance",
                        "intent", "status", "predict", "grade", "mark", "salary"]
        if any(k in col_lower for k in dv_keywords):
            roles[col] = "dependent_variable"
            continue

        # Remaining numeric → likely IV
        if info["dtype"] == "numeric":
            roles[col] = "independent_variable"
        elif info["dtype"] == "categorical":
            roles[col] = "independent_variable"

    return roles
