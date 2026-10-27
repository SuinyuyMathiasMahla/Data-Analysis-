"""Controlled data cleaning with a complete audit trail.

Every operation is a pure function:

    apply_operation(raw, schema, operation, params) -> CleaningOutcome

It never mutates its input. The caller stores the returned frame as a NEW
dataset version and writes the returned ``details`` to ``cleaning_operations``,
so the researcher can always see what changed, in which rows, and why.

There is deliberately no "run arbitrary code" operation: derived variables are
built from a fixed list of arithmetic operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from app.analysis.profiling import (DATA_TYPES, MEASUREMENT_LEVELS, NUMERIC_TYPES, _parse_datetime,
                                    _parse_numeric, infer_column)
from app.statistics.utils import AnalysisError, to_jsonable

MAX_LOGGED_CHANGES = 200


@dataclass
class CleaningOutcome:
    raw: pd.DataFrame
    schema: dict[str, dict[str, str]]
    rows_before: int
    rows_after: int
    cells_changed: int
    details: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _na(value: Any) -> bool:
    """True for None/NaN. Raw frames use None, but pandas may hand back NaN."""
    return value is None or (isinstance(value, float) and value != value)


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Canonical raw frame: object cells, None for missing."""
    return frame.astype(object).where(frame.notna(), None)


def _col(raw: pd.DataFrame, params: dict, key: str = "column") -> str:
    name = params.get(key)
    if not name or name not in raw.columns:
        raise AnalysisError(f"Unknown column: {name!r}")
    return name


def _fmt(value: Any) -> str | None:
    """Store a number as text without spurious float noise."""
    if _na(value) or (isinstance(value, float) and not np.isfinite(value)):
        return None
    f = float(value)
    return str(int(f)) if f.is_integer() and abs(f) < 1e15 else f"{f:.10g}"


def _num(raw: pd.DataFrame, col: str) -> pd.Series:
    series = raw[col]
    return _parse_numeric(series.where(series.notna(), "")).astype(float)


def _changes(before: pd.Series, after: pd.Series, column: str) -> tuple[int, list[dict]]:
    b = before.astype(object).where(before.notna(), None)
    a = after.astype(object).where(after.notna(), None)
    mask = ~((b == a) | (b.isna() & a.isna()))
    idx = b.index[mask]
    log = [{"row": int(i) + 1, "column": column, "old": b[i], "new": a[i]} for i in idx[:MAX_LOGGED_CHANGES]]
    return int(mask.sum()), log


def _target(raw: pd.DataFrame, params: dict, source: str, suffix: str) -> str:
    target = (params.get("new_column") or "").strip() or source
    if target != source and target in raw.columns:
        raise AnalysisError(f"A column named '{target}' already exists.")
    return target


def _column_update(raw, schema, source, target, new_values, spec=None, extra=None) -> CleaningOutcome:
    out = raw.copy()
    new_values = new_values.astype(object).where(new_values.notna(), None)
    if target == source:
        n, log = _changes(raw[source], new_values, source)
        out[source] = new_values
    else:
        n, log = int(new_values.notna().sum()), []
        out[target] = new_values
    new_schema = {**schema}
    if spec:
        new_schema[target] = spec
    elif target not in new_schema:
        new_schema[target] = dict(schema.get(source, infer_column(target, new_values)))
    details = {"changes": log, "changes_truncated": n > len(log), "new_column": target if target != source else None}
    details.update(extra or {})
    return CleaningOutcome(out, new_schema, len(raw), len(out), n, details)


def _row_removal(raw, schema, mask, extra=None) -> CleaningOutcome:
    removed = raw.index[mask]
    out = raw.loc[~mask].reset_index(drop=True)
    details = {
        "rows_removed": [int(i) + 1 for i in removed[:MAX_LOGGED_CHANGES]],
        "rows_removed_truncated": len(removed) > MAX_LOGGED_CHANGES,
        "removed_sample": to_jsonable(raw.loc[removed[:10]].to_dict(orient="records")),
    }
    details.update(extra or {})
    return CleaningOutcome(out, dict(schema), len(raw), len(out), 0, details)


# --------------------------------------------------------------------------- #
# operations
# --------------------------------------------------------------------------- #
def op_remove_duplicates(raw, schema, params):
    subset = params.get("subset") or None
    if subset:
        unknown = [c for c in subset if c not in raw.columns]
        if unknown:
            raise AnalysisError(f"Unknown column(s): {', '.join(unknown)}")
    mask = raw.duplicated(subset=subset, keep="first")
    return _row_removal(raw, schema, mask, {"subset": subset})


def op_drop_missing(raw, schema, params):
    columns = params.get("columns") or list(raw.columns)
    unknown = [c for c in columns if c not in raw.columns]
    if unknown:
        raise AnalysisError(f"Unknown column(s): {', '.join(unknown)}")
    how = params.get("how", "any")
    if how not in ("any", "all"):
        raise AnalysisError("'how' must be 'any' or 'all'.")
    missing = raw[columns].isna()
    mask = missing.any(axis=1) if how == "any" else missing.all(axis=1)
    return _row_removal(raw, schema, mask, {"columns": columns, "how": how})


def op_impute(raw, schema, params):
    col = _col(raw, params)
    strategy = params.get("strategy", "median")
    series = raw[col]
    is_numeric = schema.get(col, {}).get("type") in NUMERIC_TYPES
    if strategy in ("mean", "median"):
        if not is_numeric:
            raise AnalysisError(f"'{strategy}' imputation needs a numeric column; use 'mode' or 'constant' for '{col}'.")
        values = _num(raw, col)
        if values.notna().sum() == 0:
            raise AnalysisError(f"'{col}' has no valid values to compute the {strategy} from.")
        fill = values.mean() if strategy == "mean" else values.median()
        fill_text = _fmt(fill)
    elif strategy == "mode":
        modes = series.dropna().mode()
        if modes.empty:
            raise AnalysisError(f"'{col}' has no valid values to compute the mode from.")
        fill_text = str(modes.iloc[0])
    elif strategy == "constant":
        if params.get("value") is None or str(params["value"]).strip() == "":
            raise AnalysisError("A replacement value is required for constant imputation.")
        fill_text = str(params["value"])
    else:
        raise AnalysisError("Imputation strategy must be mean, median, mode or constant.")
    new = series.where(series.notna(), fill_text)
    n_missing = int(series.isna().sum())
    share = n_missing / max(len(series), 1)
    note = None
    if share > 0.2:
        note = (f"{share:.0%} of '{col}' was imputed with a single value. This shrinks its variance and can bias "
                "correlations and tests; report this in your limitations or consider multiple imputation.")
    return _column_update(raw, schema, col, col, new, extra={"strategy": strategy, "fill_value": fill_text, "note": note})


def op_replace_values(raw, schema, params):
    col = _col(raw, params)
    mapping = params.get("mapping") or {}
    if not isinstance(mapping, dict) or not mapping:
        raise AnalysisError("Provide at least one value to replace.")
    lookup = {str(k): (None if v is None or str(v) == "" else str(v)) for k, v in mapping.items()}
    series = raw[col]
    # numeric columns: match on the number so that '99' also matches '99.0'
    if schema.get(col, {}).get("type") in NUMERIC_TYPES:
        nums = _num(raw, col)
        new = series.copy()
        for old, replacement in lookup.items():
            try:
                target = float(old)
            except ValueError:
                new = new.where(series != old, replacement)
                continue
            new = new.where(~(nums == target), replacement)
    else:
        new = series.map(lambda v: lookup.get(v, v) if not _na(v) else None)
    return _column_update(raw, schema, col, col, new, extra={"mapping": lookup})


def op_recode(raw, schema, params):
    col = _col(raw, params)
    mapping = params.get("mapping") or {}
    if not mapping:
        raise AnalysisError("Provide a recoding map, e.g. {'Strongly agree': 5}.")
    lookup = {str(k): (None if v is None or str(v) == "" else str(v)) for k, v in mapping.items()}
    target = _target(raw, params, col, "_recoded")
    series = raw[col]
    unmapped = sorted(set(series.dropna().astype(str)) - set(lookup))
    else_value = params.get("else_value", "__keep__")
    def recode(v):
        if _na(v):
            return None
        if str(v) in lookup:
            return lookup[str(v)]
        return v if else_value == "__keep__" else (None if else_value in (None, "") else str(else_value))
    new = series.map(recode)
    spec = infer_column(target, new)
    if params.get("measurement_level") in MEASUREMENT_LEVELS:
        spec["measurement_level"] = params["measurement_level"]
    return _column_update(raw, schema, col, target, new, spec=spec, extra={"mapping": lookup, "unmapped_values": unmapped[:50]})


def op_standardize_categories(raw, schema, params):
    col = _col(raw, params)
    series = raw[col]
    new = series.copy()
    if params.get("strip", True):
        new = new.map(lambda v: " ".join(str(v).split()) if not _na(v) else None)
    case = params.get("case", "none")
    funcs: dict[str, Callable[[str], str]] = {"lower": str.lower, "upper": str.upper, "title": str.title, "none": lambda s: s}
    if case not in funcs:
        raise AnalysisError("case must be one of: none, lower, upper, title.")
    new = new.map(lambda v: funcs[case](v) if not _na(v) else None)
    mapping = {str(k): str(v) for k, v in (params.get("mapping") or {}).items()}
    if mapping:
        stripped_map = {" ".join(k.split()): v for k, v in mapping.items()}
        new = new.map(lambda v: mapping.get(v, stripped_map.get(v, v)) if not _na(v) else None)
    return _column_update(raw, schema, col, col, new, extra={"case": case, "mapping": mapping})


def op_convert_type(raw, schema, params):
    col = _col(raw, params)
    to = params.get("to")
    if to not in DATA_TYPES:
        raise AnalysisError(f"Target type must be one of: {', '.join(DATA_TYPES)}.")
    series = raw[col]
    present = series.notna()
    if to in NUMERIC_TYPES:
        nums = _num(raw, col)
        if to == "integer" and (nums.dropna() % 1 != 0).any():
            raise AnalysisError(f"'{col}' contains non-integer numbers; convert to 'numeric' instead.")
        new = series.where(nums.notna(), None)     # keep the original text of valid numbers
        default_level = "ratio"
    elif to == "datetime":
        dates = _parse_datetime(series.where(present, None))
        new = dates.map(lambda d: None if pd.isna(d) else (d.strftime("%Y-%m-%d") if d == d.normalize() else d.isoformat(sep=" ")))
        default_level = "interval"
    else:
        new = series.copy()
        default_level = "nominal"
    level = params.get("measurement_level") or (schema.get(col, {}).get("measurement_level") if to in NUMERIC_TYPES else None) or default_level
    if level not in MEASUREMENT_LEVELS:
        raise AnalysisError(f"Measurement level must be one of: {', '.join(MEASUREMENT_LEVELS)}.")
    if to not in NUMERIC_TYPES and to != "datetime" and level in ("interval", "ratio"):
        level = "nominal"
    coerced = int((present & new.isna()).sum())
    return _column_update(raw, schema, col, col, new, spec={"type": to, "measurement_level": level},
                          extra={"to": to, "measurement_level": level, "values_set_to_missing": coerced})


def op_remove_invalid(raw, schema, params):
    col = _col(raw, params)
    action = params.get("action", "set_missing")
    if action not in ("set_missing", "drop_rows"):
        raise AnalysisError("action must be 'set_missing' or 'drop_rows'.")
    series = raw[col]
    mask = pd.Series(False, index=raw.index)
    lo, hi = params.get("min"), params.get("max")
    if lo is not None or hi is not None:
        nums = _num(raw, col)
        if lo is not None:
            mask |= nums < float(lo)
        if hi is not None:
            mask |= nums > float(hi)
    explicit = params.get("invalid_values") or []
    if explicit:
        mask |= series.astype(str).isin([str(v) for v in explicit]) & series.notna()
    if params.get("non_numeric") and schema.get(col, {}).get("type") in NUMERIC_TYPES:
        mask |= series.notna() & _num(raw, col).isna()
    if lo is None and hi is None and not explicit and not params.get("non_numeric"):
        raise AnalysisError("Specify what counts as invalid: a min/max range, a list of values, or non_numeric.")
    rule = {"min": lo, "max": hi, "invalid_values": explicit, "action": action}
    if action == "drop_rows":
        return _row_removal(raw, schema, mask, {"rule": rule, "column": col})
    return _column_update(raw, schema, col, col, series.where(~mask, None), extra={"rule": rule})


def op_winsorize(raw, schema, params):
    col = _col(raw, params)
    lower = float(params.get("lower_pct", 5))
    upper = float(params.get("upper_pct", 95))
    if not (0 <= lower < upper <= 100):
        raise AnalysisError("Percentiles must satisfy 0 <= lower < upper <= 100.")
    nums = _num(raw, col)
    valid = nums.dropna()
    if len(valid) < 10:
        raise AnalysisError("Winsorization needs at least 10 valid values.")
    lo, hi = np.percentile(valid, [lower, upper])
    clipped = nums.clip(lo, hi)
    changed = nums.notna() & (clipped != nums)
    new = raw[col].where(~changed, clipped.map(_fmt))          # untouched values keep their original text
    return _column_update(raw, schema, col, col, new,
                          extra={"lower_pct": lower, "upper_pct": upper, "lower_limit": float(lo), "upper_limit": float(hi),
                                 "note": "Winsorization changes real observations. Report it in the methodology and, "
                                         "where possible, show that conclusions hold with and without it."})


_TRANSFORMS: dict[str, tuple[Callable[[pd.Series], pd.Series], Callable[[pd.Series], pd.Series], str]] = {
    "log": (np.log, lambda s: s > 0, "natural log requires values > 0"),
    "log10": (np.log10, lambda s: s > 0, "log10 requires values > 0"),
    "log1p": (np.log1p, lambda s: s > -1, "log(1 + x) requires values > -1"),
    "sqrt": (np.sqrt, lambda s: s >= 0, "square root requires values >= 0"),
    "square": (np.square, lambda s: s == s, ""),
    "reciprocal": (lambda s: 1.0 / s, lambda s: s != 0, "reciprocal requires non-zero values"),
}


def op_transform(raw, schema, params):
    col = _col(raw, params)
    name = params.get("function")
    if name not in _TRANSFORMS:
        raise AnalysisError(f"function must be one of: {', '.join(_TRANSFORMS)}.")
    func, domain, message = _TRANSFORMS[name]
    nums = _num(raw, col)
    valid = nums.dropna()
    bad = valid[~domain(valid)]
    if len(bad):
        raise AnalysisError(f"Cannot apply {name} to '{col}': {message} ({len(bad)} value(s) violate this).")
    target = _target(raw, params, col, f"_{name}")
    new = func(nums).map(_fmt)
    return _column_update(raw, schema, col, target, new, spec={"type": "numeric", "measurement_level": "ratio"},
                          extra={"function": name})


def op_normalize(raw, schema, params):
    col = _col(raw, params)
    nums = _num(raw, col)
    lo, hi = nums.min(), nums.max()
    if not np.isfinite(lo) or hi == lo:
        raise AnalysisError(f"'{col}' has no variation, so it cannot be normalised.")
    target = _target(raw, params, col, "_norm")
    return _column_update(raw, schema, col, target, ((nums - lo) / (hi - lo)).map(_fmt),
                          spec={"type": "numeric", "measurement_level": "ratio"}, extra={"min": float(lo), "max": float(hi)})


def op_standardize(raw, schema, params):
    col = _col(raw, params)
    nums = _num(raw, col)
    mean, sd = nums.mean(), nums.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        raise AnalysisError(f"'{col}' has no variation, so it cannot be standardised.")
    target = _target(raw, params, col, "_z")
    return _column_update(raw, schema, col, target, ((nums - mean) / sd).map(_fmt),
                          spec={"type": "numeric", "measurement_level": "interval"}, extra={"mean": float(mean), "sd": float(sd)})


def op_derive(raw, schema, params):
    target = (params.get("new_column") or "").strip()
    if not target:
        raise AnalysisError("A name is required for the new variable.")
    if target in raw.columns:
        raise AnalysisError(f"A column named '{target}' already exists.")
    columns = params.get("columns") or []
    operation = params.get("operation")
    unknown = [c for c in columns if c not in raw.columns]
    if unknown:
        raise AnalysisError(f"Unknown column(s): {', '.join(unknown)}")
    frame = pd.DataFrame({c: _num(raw, c) for c in columns})
    if operation in ("sum", "mean"):
        if len(columns) < 2:
            raise AnalysisError(f"'{operation}' needs at least two columns.")
        min_valid = int(params.get("min_valid") or len(columns))
        enough = frame.notna().sum(axis=1) >= min_valid
        values = (frame.sum(axis=1, skipna=True) if operation == "sum" else frame.mean(axis=1, skipna=True)).where(enough)
    elif operation in ("difference", "product", "ratio"):
        if len(columns) != 2:
            raise AnalysisError(f"'{operation}' needs exactly two columns.")
        a, b = frame[columns[0]], frame[columns[1]]
        if operation == "difference":
            values = a - b
        elif operation == "product":
            values = a * b
        else:
            values = (a / b).where(b != 0)
    else:
        raise AnalysisError("operation must be one of: sum, mean, difference, product, ratio.")
    out = raw.copy()
    new = values.map(_fmt)
    out[target] = new.astype(object).where(new.notna(), None)
    new_schema = {**schema, target: {"type": "numeric", "measurement_level": "ratio"}}
    return CleaningOutcome(out, new_schema, len(raw), len(out), int(new.notna().sum()),
                           {"new_column": target, "operation": operation, "columns": columns})


def op_drop_columns(raw, schema, params):
    columns = params.get("columns") or []
    unknown = [c for c in columns if c not in raw.columns]
    if unknown or not columns:
        raise AnalysisError(f"Unknown column(s): {', '.join(unknown) or '(none given)'}")
    if len(columns) >= raw.shape[1]:
        raise AnalysisError("You cannot remove every column.")
    out = raw.drop(columns=columns)
    return CleaningOutcome(out, {k: v for k, v in schema.items() if k not in columns}, len(raw), len(out), 0,
                           {"columns_removed": columns})


def op_rename_column(raw, schema, params):
    col = _col(raw, params)
    new_name = (params.get("new_name") or "").strip()
    if not new_name:
        raise AnalysisError("A new name is required.")
    if new_name in raw.columns:
        raise AnalysisError(f"A column named '{new_name}' already exists.")
    out = raw.rename(columns={col: new_name})
    new_schema = {(new_name if k == col else k): v for k, v in schema.items()}
    return CleaningOutcome(out, new_schema, len(raw), len(out), 0, {"renamed": {col: new_name}})


OPERATIONS: dict[str, dict[str, Any]] = {
    "remove_duplicates": {"func": op_remove_duplicates, "label": "Remove duplicate rows", "removes_rows": True},
    "drop_missing": {"func": op_drop_missing, "label": "Remove rows with missing values", "removes_rows": True},
    "impute": {"func": op_impute, "label": "Fill in missing values", "removes_rows": False},
    "replace_values": {"func": op_replace_values, "label": "Replace values", "removes_rows": False},
    "recode": {"func": op_recode, "label": "Recode a variable", "removes_rows": False},
    "standardize_categories": {"func": op_standardize_categories, "label": "Standardise category spelling", "removes_rows": False},
    "convert_type": {"func": op_convert_type, "label": "Change data type", "removes_rows": False},
    "remove_invalid": {"func": op_remove_invalid, "label": "Remove invalid values", "removes_rows": True},
    "winsorize": {"func": op_winsorize, "label": "Winsorize extreme values", "removes_rows": False},
    "transform": {"func": op_transform, "label": "Transform a variable", "removes_rows": False},
    "normalize": {"func": op_normalize, "label": "Normalise to 0-1", "removes_rows": False},
    "standardize": {"func": op_standardize, "label": "Standardise (z-scores)", "removes_rows": False},
    "derive": {"func": op_derive, "label": "Create a derived variable", "removes_rows": False},
    "drop_columns": {"func": op_drop_columns, "label": "Remove columns", "removes_rows": False},
    "rename_column": {"func": op_rename_column, "label": "Rename a column", "removes_rows": False},
}


def apply_operation(raw: pd.DataFrame, schema: dict, operation: str, params: dict | None, reason: str) -> CleaningOutcome:
    """Apply one cleaning operation. ``reason`` is mandatory: an undocumented
    change to research data is not allowed."""
    if operation not in OPERATIONS:
        raise AnalysisError(f"Unknown cleaning operation: {operation}")
    if not reason or len(reason.strip()) < 5:
        raise AnalysisError("Please record the reason for this change (at least a few words). "
                            "It becomes part of the project's audit trail.")
    outcome = OPERATIONS[operation]["func"](raw, schema, dict(params or {}))
    if outcome.raw.shape[0] == 0:
        raise AnalysisError("This operation would remove every row, so it was not applied.")
    outcome.raw = _clean_frame(outcome.raw)
    outcome.details = to_jsonable(outcome.details)
    return outcome
