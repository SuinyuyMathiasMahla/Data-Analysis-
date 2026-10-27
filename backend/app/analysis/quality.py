"""Data-quality engine.

Runs on the raw working copy plus its schema and returns a list of issues and
a 0-100 Data Quality Score.

Scoring (documented in docs/statistical-methods.md)
---------------------------------------------------
The score is 100 minus weighted penalties. Each penalty is driven by the
*share* of the data affected, so the score does not depend on dataset size.
Shares are multiplied by 5 and capped at 1 (20% of cells missing already costs
the full 40 points), because even a few percent of bad cells matters in
research data:

    completeness  40 x min(1, 5 x share of cells that are missing)
    validity      25 x min(1, 5 x share of cells that are invalid/impossible)
    uniqueness    20 x min(1, 5 x share of rows that are exact duplicates)
    consistency   10 x min(1, 5 x share of categorical cells spelled inconsistently)
    structure      5 x min(1, 5 x share of columns that are empty or constant)

Outliers, correlated predictors and other *analytic* warnings are reported but
do not lower the score: an outlier is not an error, and removing observations
to raise a score would be bad science.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

import numpy as np
import pandas as pd

from app.analysis.profiling import NUMERIC_TYPES, _parse_datetime, _parse_numeric, typed_frame
from app.statistics.utils import to_jsonable

MAX_EXAMPLES = 8
SENTINELS = {-999.0, -99.0, -9.0, 99.0, 999.0, 9999.0, 99999.0}

# Name-based plausibility rules: (pattern, min, max, description)
_RANGE_RULES: list[tuple[re.Pattern, float | None, float | None, str]] = [
    (re.compile(r"(^|_)age($|_)", re.I), 0, 120, "age must be between 0 and 120"),
    (re.compile(r"percent|pct|percentage", re.I), 0, 100, "a percentage must be between 0 and 100"),
    (re.compile(r"(^|_)(gpa|cgpa)($|_)", re.I), 0, 5, "GPA is normally between 0 and 5"),
    (
        re.compile(r"hours?|minutes?|count|number|num_|income|salary|price|cost|height|weight|duration|years?", re.I),
        0,
        None,
        "this quantity cannot be negative",
    ),
]


def _issue(code: str, severity: str, message: str, *, column: str | None = None, count: int = 0,
           examples: list | None = None, suggestion: dict | None = None, affects_score: bool = True) -> dict:
    return {
        "code": code,
        "severity": severity,          # high | medium | low | info
        "column": column,
        "count": int(count),
        "message": message,
        "examples": to_jsonable(examples or []),
        "suggestion": suggestion,      # a cleaning operation the user may choose to apply
        "affects_score": affects_score,
    }


def _rows(index: pd.Index) -> list[int]:
    """1-based row numbers for display."""
    return [int(i) + 1 for i in list(index[:MAX_EXAMPLES])]


def _vif(frame: pd.DataFrame) -> dict[str, float]:
    """Variance inflation factors from the inverse correlation matrix."""
    clean = frame.dropna()
    if clean.shape[1] < 2 or clean.shape[0] <= clean.shape[1] + 1:
        return {}
    clean = clean.loc[:, clean.std(ddof=1) > 0]
    if clean.shape[1] < 2:
        return {}
    corr = np.corrcoef(clean.to_numpy(dtype=float), rowvar=False)
    try:
        inv = np.linalg.inv(corr)
    except np.linalg.LinAlgError:
        return {c: float("inf") for c in clean.columns}
    return {c: float(v) for c, v in zip(clean.columns, np.diag(inv))}


def assess_quality(raw: pd.DataFrame, schema: dict[str, dict[str, str]],
                   valid_ranges: dict[str, tuple[float | None, float | None]] | None = None) -> dict:
    """Return ``{"score", "summary", "dimensions", "issues"}`` for a dataset version."""
    valid_ranges = valid_ranges or {}
    issues: list[dict] = []
    n_rows, n_cols = raw.shape
    total_cells = max(n_rows * n_cols, 1)
    typed = typed_frame(raw, schema)

    # ---- structure: empty columns / rows ---------------------------------
    empty_cols = [c for c in raw.columns if raw[c].isna().all()]
    for col in empty_cols:
        issues.append(_issue("empty_column", "medium", f"Column '{col}' is completely empty.", column=col,
                             count=n_rows, suggestion={"operation": "drop_columns", "params": {"columns": [col]}}))
    empty_rows = raw.index[raw.isna().all(axis=1)]
    if len(empty_rows):
        issues.append(_issue("empty_rows", "medium", f"{len(empty_rows)} row(s) contain no data.",
                             count=len(empty_rows), examples=_rows(empty_rows),
                             suggestion={"operation": "drop_missing", "params": {"how": "all"}}))

    # ---- completeness ----------------------------------------------------
    missing_cells = int(raw.isna().sum().sum())
    for col in raw.columns:
        if col in empty_cols:
            continue
        n_missing = int(raw[col].isna().sum())
        if n_missing:
            pct = 100 * n_missing / n_rows
            severity = "high" if pct > 20 else "medium" if pct > 5 else "low"
            issues.append(_issue("missing_values", severity,
                                 f"'{col}' has {n_missing} missing value(s) ({pct:.1f}%).", column=col,
                                 count=n_missing, examples=_rows(raw.index[raw[col].isna()]),
                                 suggestion={"operation": "impute", "params": {"column": col}}))

    # ---- uniqueness ------------------------------------------------------
    dup_mask = raw.duplicated(keep="first")
    n_dups = int(dup_mask.sum())
    if n_dups:
        issues.append(_issue("duplicate_rows", "high" if n_dups / n_rows > 0.05 else "medium",
                             f"{n_dups} row(s) are exact duplicates of an earlier row.", count=n_dups,
                             examples=_rows(raw.index[dup_mask]),
                             suggestion={"operation": "remove_duplicates", "params": {}}))
    for col, spec in schema.items():
        if spec["type"] == "identifier" and col in raw.columns:
            ids = raw[col].dropna()
            dup_ids = ids[ids.duplicated(keep=False)]
            if len(dup_ids):
                issues.append(_issue("duplicate_identifier", "high",
                                     f"Identifier '{col}' has {dup_ids.nunique()} value(s) that occur more than once.",
                                     column=col, count=int(dup_ids.duplicated().sum()),
                                     examples=list(dup_ids.unique()[:MAX_EXAMPLES]), affects_score=False))

    # ---- validity --------------------------------------------------------
    invalid_cells = 0
    for col in raw.columns:
        spec = schema.get(col, {})
        kind = spec.get("type", "text")
        present = raw[col].dropna()
        if present.empty:
            continue

        if kind in NUMERIC_TYPES:
            bad = present[_parse_numeric(present).isna()]
            if len(bad):
                invalid_cells += len(bad)
                issues.append(_issue("invalid_numeric", "high",
                                     f"'{col}' is numeric but {len(bad)} value(s) are not numbers. "
                                     "They are treated as missing in analyses until cleaned.",
                                     column=col, count=len(bad),
                                     examples=[{"row": int(i) + 1, "value": v} for i, v in bad.head(MAX_EXAMPLES).items()],
                                     suggestion={"operation": "convert_type", "params": {"column": col, "to": kind}}))
            values = typed[col].dropna()
            lo, hi = valid_ranges.get(col, (None, None))
            reason = "the valid range set in the data dictionary"
            if lo is None and hi is None:
                for pattern, rule_lo, rule_hi, why in _RANGE_RULES:
                    if pattern.search(col):
                        lo, hi, reason = rule_lo, rule_hi, why
                        break
            if lo is not None or hi is not None:
                mask = pd.Series(False, index=values.index)
                if lo is not None:
                    mask |= values < lo
                if hi is not None:
                    mask |= values > hi
                impossible = values[mask]
                if len(impossible):
                    invalid_cells += len(impossible)
                    issues.append(_issue("impossible_value", "high",
                                         f"'{col}' has {len(impossible)} value(s) outside the plausible range ({reason}).",
                                         column=col, count=len(impossible),
                                         examples=[{"row": int(i) + 1, "value": float(v)} for i, v in impossible.head(MAX_EXAMPLES).items()],
                                         suggestion={"operation": "remove_invalid",
                                                     "params": {"column": col, "min": lo, "max": hi, "action": "set_missing"}}))
            sentinel_hits = values[values.isin(SENTINELS)]
            if len(values) >= 10 and len(sentinel_hits):
                q1, q3 = values.quantile([0.25, 0.75])
                spread = (q3 - q1) or values.std(ddof=1) or 1.0
                far = sentinel_hits[(sentinel_hits > q3 + 3 * spread) | (sentinel_hits < q1 - 3 * spread)]
                if len(far):
                    issues.append(_issue("suspicious_code", "medium",
                                         f"'{col}' contains {len(far)} value(s) such as {sorted(set(far))[:3]} that look like "
                                         "missing-data codes rather than real measurements.",
                                         column=col, count=len(far), examples=_rows(far.index), affects_score=False,
                                         suggestion={"operation": "replace_values",
                                                     "params": {"column": col, "mapping": {str(int(v)): None for v in sorted(set(far))}}}))

        elif kind == "datetime":
            bad = present[_parse_datetime(present).isna()]
            if len(bad):
                invalid_cells += len(bad)
                issues.append(_issue("invalid_date", "high", f"'{col}' has {len(bad)} value(s) that are not valid dates.",
                                     column=col, count=len(bad),
                                     examples=[{"row": int(i) + 1, "value": v} for i, v in bad.head(MAX_EXAMPLES).items()],
                                     suggestion={"operation": "convert_type", "params": {"column": col, "to": "datetime"}}))
        else:
            share = _parse_numeric(present).notna().mean()
            if 0.5 <= share < 0.9:
                issues.append(_issue("mixed_types", "medium",
                                     f"'{col}' mixes numbers ({share:.0%}) and text. Check whether it should be numeric.",
                                     column=col, count=int(round((1 - share) * len(present))), affects_score=False,
                                     suggestion={"operation": "convert_type", "params": {"column": col, "to": "numeric"}}))

    # ---- consistency of categorical values --------------------------------
    inconsistent_cells = 0
    categorical_cells = 0
    for col in raw.columns:
        if schema.get(col, {}).get("type") not in ("categorical", "boolean"):
            continue
        present = raw[col].dropna().astype(str)
        categorical_cells += len(present)
        if present.empty:
            continue
        normalised = present.str.strip().str.casefold().str.replace(r"\s+", " ", regex=True)
        groups = present.groupby(normalised).agg(lambda s: sorted(set(s)))
        variants = {key: forms for key, forms in groups.items() if len(forms) > 1}
        if variants:
            counts = present.value_counts()
            affected = 0
            mapping: dict[str, str] = {}
            for forms in variants.values():
                canonical = max(forms, key=lambda f: (counts[f], f == f.strip()))
                canonical_clean = canonical.strip()
                for form in forms:
                    if form != canonical_clean:
                        mapping[form] = canonical_clean
                        affected += int(counts[form]) if form != canonical else 0
            inconsistent_cells += affected
            issues.append(_issue("inconsistent_category", "medium",
                                 f"'{col}' has {len(variants)} value(s) written in more than one way "
                                 "(different capitalisation or spacing).",
                                 column=col, count=affected, examples=[forms for forms in variants.values()][:MAX_EXAMPLES],
                                 suggestion={"operation": "standardize_categories",
                                             "params": {"column": col, "strip": True, "case": "none", "mapping": mapping}}))
        levels = sorted(set(normalised))
        if 2 < len(levels) <= 40:
            near = []
            for i, a in enumerate(levels):
                for b in levels[i + 1:]:
                    if min(len(a), len(b)) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.88:
                        near.append([a, b])
            if near:
                issues.append(_issue("similar_categories", "low",
                                     f"'{col}' has categories that look like possible misspellings of each other. Please review.",
                                     column=col, count=len(near), examples=near[:MAX_EXAMPLES], affects_score=False))

    # ---- variance / constants ---------------------------------------------
    constant_cols = []
    for col in raw.columns:
        if col in empty_cols:
            continue
        present = raw[col].dropna()
        distinct = present.nunique()
        if distinct == 1 and n_rows > 1:
            constant_cols.append(col)
            issues.append(_issue("constant_column", "medium",
                                 f"'{col}' has the same value in every row, so it cannot explain any variation.",
                                 column=col, count=n_rows))
        elif distinct > 1 and len(present) >= 20 and schema.get(col, {}).get("type") not in ("identifier", "text"):
            top_share = present.value_counts(normalize=True).iloc[0]
            if top_share >= 0.95:
                issues.append(_issue("near_zero_variance", "low",
                                     f"'{col}' has almost no variation: one value accounts for {top_share:.0%} of rows.",
                                     column=col, count=int(round(top_share * len(present))), affects_score=False))

    # ---- outliers (reported, never auto-removed, no score penalty) ---------
    numeric_cols = [c for c in raw.columns if schema.get(c, {}).get("type") in NUMERIC_TYPES
                    and schema[c].get("measurement_level") in ("interval", "ratio") and typed[c].notna().sum() >= 8]
    outlier_total = 0
    for col in numeric_cols:
        values = typed[col].dropna()
        q1, q3 = values.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr <= 0:
            continue
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        out = values[(values < low) | (values > high)]
        if len(out):
            outlier_total += len(out)
            extreme = values[(values < q1 - 3 * iqr) | (values > q3 + 3 * iqr)]
            issues.append(_issue("outliers", "low" if len(extreme) == 0 else "medium",
                                 f"'{col}' has {len(out)} possible outlier(s) by the 1.5 x IQR rule"
                                 + (f", {len(extreme)} of them extreme (3 x IQR)" if len(extreme) else "")
                                 + ". Check whether they are errors or genuine observations before deciding what to do.",
                                 column=col, count=len(out), affects_score=False,
                                 examples=[{"row": int(i) + 1, "value": float(v)} for i, v in out.head(MAX_EXAMPLES).items()]))

    # ---- relationships between predictors ----------------------------------
    if len(numeric_cols) >= 2:
        corr = typed[numeric_cols].corr(method="pearson", min_periods=8)
        pairs = []
        for i, a in enumerate(numeric_cols):
            for b in numeric_cols[i + 1:]:
                r = corr.loc[a, b]
                if pd.notna(r) and abs(r) >= 0.9:
                    pairs.append({"variables": [a, b], "r": round(float(r), 3)})
        if pairs:
            issues.append(_issue("high_correlation", "low",
                                 f"{len(pairs)} pair(s) of numeric variables are very highly correlated (|r| >= 0.90). "
                                 "Using both as predictors in one model can cause multicollinearity.",
                                 count=len(pairs), examples=pairs[:MAX_EXAMPLES], affects_score=False))
        if len(numeric_cols) >= 3:
            high_vif = {c: round(v, 2) for c, v in _vif(typed[numeric_cols]).items() if v > 10}
            if high_vif:
                issues.append(_issue("multicollinearity", "low",
                                     "Some numeric variables are almost a linear combination of the others (VIF > 10).",
                                     count=len(high_vif), examples=[high_vif], affects_score=False))

    # ---- suspicious response patterns --------------------------------------
    ordinal_cols = [c for c in raw.columns if schema.get(c, {}).get("measurement_level") == "ordinal"
                    and schema[c].get("type") in NUMERIC_TYPES]
    if len(ordinal_cols) >= 5 and n_rows >= 10:
        block = typed[ordinal_cols].dropna()
        straight = block.index[block.nunique(axis=1) == 1]
        if len(straight) and len(straight) / n_rows >= 0.02:
            issues.append(_issue("straight_lining", "low",
                                 f"{len(straight)} respondent(s) gave the identical answer to all {len(ordinal_cols)} "
                                 "rating items, which can indicate inattentive responding.",
                                 count=len(straight), examples=_rows(straight), affects_score=False))
    for col in raw.columns:
        present = raw[col].dropna().astype(str)
        padded = present[present != present.str.strip()]
        if len(padded) and schema.get(col, {}).get("type") not in ("categorical", "boolean"):
            issues.append(_issue("whitespace", "info", f"'{col}' has {len(padded)} value(s) with leading or trailing spaces.",
                                 column=col, count=len(padded), affects_score=False))

    # ---- score --------------------------------------------------------------
    structural_cols = len(set(empty_cols) | set(constant_cols))
    shares = {
        "completeness": missing_cells / total_cells,
        "validity": invalid_cells / total_cells,
        "uniqueness": n_dups / max(n_rows, 1),
        "consistency": inconsistent_cells / max(categorical_cells, 1),
        "structure": structural_cols / max(n_cols, 1),
    }
    weights = {"completeness": 40, "validity": 25, "uniqueness": 20, "consistency": 10, "structure": 5}
    # Small shares still matter in research data, so each share is amplified
    # (x5, capped at 1): 20% missing cells already costs the full 40 points.
    penalties = {k: weights[k] * min(1.0, 5 * shares[k]) for k in weights}
    score = round(max(0.0, 100.0 - sum(penalties.values())), 1)

    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    issues.sort(key=lambda i: (order[i["severity"]], -i["count"]))
    summary: dict[str, Any] = {
        "rows": n_rows,
        "columns": n_cols,
        "missing_cells": missing_cells,
        "missing_pct": round(100 * missing_cells / total_cells, 2),
        "duplicate_rows": n_dups,
        "invalid_cells": invalid_cells,
        "inconsistent_category_cells": inconsistent_cells,
        "possible_outliers": outlier_total,
        "empty_columns": len(empty_cols),
        "constant_columns": len(constant_cols),
        "issue_count": len(issues),
        "rows_with_missing": int(raw.isna().any(axis=1).sum()),
    }
    dimensions = {
        k: {"weight": weights[k], "affected_share": round(shares[k], 4), "points_lost": round(penalties[k], 2)}
        for k in weights
    }
    return to_jsonable({"score": score, "summary": summary, "dimensions": dimensions, "issues": issues})
