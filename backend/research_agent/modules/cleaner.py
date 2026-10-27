"""
cleaner.py
----------
Automatically detects and fixes data quality issues.
Returns cleaned DataFrame + a human-readable cleaning log
that the app can display to the user for review.
"""

import pandas as pd
import numpy as np
from typing import Tuple


def auto_clean(df: pd.DataFrame, profile: dict) -> Tuple[pd.DataFrame, list[dict]]:
    """
    Runs all cleaning steps. Returns:
      - cleaned DataFrame
      - cleaning_log: list of actions taken, each with column,
        issue, action, and rows_affected
    """
    df = df.copy()
    log = []

    # 1 — Remove exact duplicate rows
    dupes = df.duplicated().sum()
    if dupes > 0:
        df = df.drop_duplicates()
        log.append({
            "step": "Duplicate Removal",
            "column": "ALL",
            "issue": f"{dupes} fully duplicate rows detected.",
            "action": f"Removed {dupes} duplicate rows.",
            "rows_affected": int(dupes),
        })

    # 2 — Handle missing values per column
    for col, info in profile["columns"].items():
        if col not in df.columns:
            continue
        missing = info["missing"]
        if missing == 0:
            continue

        dtype = info["dtype"]
        missing_pct = info["missing_pct"]

        if missing_pct > 50:
            # Drop column — too much missing
            df.drop(columns=[col], inplace=True)
            log.append({
                "step": "Column Removal",
                "column": col,
                "issue": f"{missing_pct}% of values are missing (>50% threshold).",
                "action": "Column dropped from dataset.",
                "rows_affected": missing,
            })

        elif dtype == "numeric":
            # Fill with median (robust to outliers)
            fill_val = round(df[col].median(), 4)
            df[col].fillna(fill_val, inplace=True)
            log.append({
                "step": "Missing Value Imputation",
                "column": col,
                "issue": f"{missing} missing numeric values ({missing_pct}%).",
                "action": f"Filled with median value ({fill_val}).",
                "rows_affected": missing,
            })

        elif dtype == "categorical":
            # Fill with mode
            fill_val = df[col].mode()[0] if not df[col].mode().empty else "Unknown"
            df[col].fillna(fill_val, inplace=True)
            log.append({
                "step": "Missing Value Imputation",
                "column": col,
                "issue": f"{missing} missing categorical values ({missing_pct}%).",
                "action": f"Filled with mode value ('{fill_val}').",
                "rows_affected": missing,
            })

        elif dtype == "datetime":
            # Forward fill dates
            df[col] = pd.to_datetime(df[col], errors="coerce")
            df[col].fillna(method="ffill", inplace=True)
            log.append({
                "step": "Missing Value Imputation",
                "column": col,
                "issue": f"{missing} missing date values ({missing_pct}%).",
                "action": "Forward-filled from nearest prior date.",
                "rows_affected": missing,
            })

    # 3 — Fix outliers in numeric columns (cap at 3 SD)
    for col, info in profile["columns"].items():
        if col not in df.columns:
            continue
        if info["dtype"] != "numeric":
            continue
        outlier_count = info.get("outlier_count", 0)
        if outlier_count == 0:
            continue

        mean, std = df[col].mean(), df[col].std()
        lower, upper = mean - 3 * std, mean + 3 * std
        capped = ((df[col] < lower) | (df[col] > upper)).sum()
        if capped > 0:
            df[col] = df[col].clip(lower=lower, upper=upper)
            log.append({
                "step": "Outlier Capping",
                "column": col,
                "issue": f"{outlier_count} outliers detected (IQR method).",
                "action": f"Values capped at ±3 standard deviations "
                           f"(range: {round(lower,2)} – {round(upper,2)}).",
                "rows_affected": int(capped),
            })

    # 4 — Strip whitespace from string columns
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip()

    # 5 — Standardise boolean-like columns
    bool_map = {
        "yes": True, "no": False,
        "true": True, "false": False,
        "1": True, "0": False,
    }
    for col in df.select_dtypes(include="object").columns:
        sample = df[col].dropna().str.lower().unique()
        if set(sample).issubset(set(bool_map.keys())):
            df[col] = df[col].str.lower().map(bool_map)
            log.append({
                "step": "Boolean Standardisation",
                "column": col,
                "issue": "Column contains Yes/No text values.",
                "action": "Converted to True/False boolean.",
                "rows_affected": len(df),
            })

    if not log:
        log.append({
            "step": "No Issues Found",
            "column": "ALL",
            "issue": "Dataset passed all quality checks.",
            "action": "No cleaning required.",
            "rows_affected": 0,
        })

    return df, log
