"""Dataset loading, type inference and the data dictionary.

Storage model
-------------
* The uploaded file is stored byte-for-byte and never touched again.
* A *working copy* is stored as a canonical CSV of raw values (strings, with
  empty = missing) plus a ``schema``: ``{column: {"type", "measurement_level"}}``.
* Analyses read the working copy through :func:`typed_frame`, which applies the
  schema. Values that do not fit the declared type (e.g. ``"abc"`` in a numeric
  column) become missing *in memory only*; the data-quality engine reports
  them and a cleaning operation is needed to change the stored data, so nothing
  is ever altered silently.
"""
from __future__ import annotations

import io
import json
import re
import warnings
from typing import Any

import numpy as np
import pandas as pd

from app.statistics.utils import AnalysisError, to_jsonable

MISSING_TOKENS = {"", "na", "n/a", "#n/a", "nan", "null", "none", "nil", "missing", "?", "-", "--", "."}
NUMERIC_TYPES = {"numeric", "integer"}
CATEGORICAL_TYPES = {"categorical", "boolean"}
DATA_TYPES = ["numeric", "integer", "categorical", "boolean", "datetime", "text", "identifier"]
MEASUREMENT_LEVELS = ["nominal", "ordinal", "interval", "ratio"]

_ID_NAME = re.compile(r"(^|[_\s\-.])(id|uuid|code|serial|index|respondent|participant|s/?n)($|[_\s\-.])|(^|[_\s])no\.?$", re.I)
_DATE_HINT = re.compile(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}:\d{2}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}")
_BOOL_TOKENS = {"true", "false"}


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def _cell_to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        if np.isnan(value):
            return None
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    if isinstance(value, (pd.Timestamp,)):
        if pd.isna(value):
            return None
        return value.strftime("%Y-%m-%d") if value == value.normalize() else value.isoformat(sep=" ")
    if isinstance(value, (bool, np.bool_)):
        return "true" if value else "false"
    if isinstance(value, (np.integer,)):
        return str(int(value))
    if isinstance(value, (np.floating,)):
        return _cell_to_str(float(value))
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value)
    return None if text.strip().lower() in MISSING_TOKENS else text


def _canonical(df: pd.DataFrame) -> pd.DataFrame:
    """Raw frame: unique string column names, string cells, None for missing."""
    names: list[str] = []
    seen: dict[str, int] = {}
    for i, col in enumerate(df.columns):
        name = str(col).strip()
        if not name or name.lower().startswith("unnamed:"):
            name = f"column_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        names.append(name)
    out = pd.DataFrame(
        {name: [_cell_to_str(v) for v in df.iloc[:, i].tolist()] for i, name in enumerate(names)},
        dtype=object,
    )
    return out.reset_index(drop=True)


def read_raw(content: bytes, file_format: str) -> pd.DataFrame:
    """Parse an uploaded file into the canonical raw frame."""
    fmt = file_format.lower().lstrip(".")
    try:
        if fmt == "csv":
            text = None
            for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                try:
                    text = content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                raise AnalysisError("The CSV file encoding could not be detected.")
            df = pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str, keep_default_na=False)
        elif fmt == "xlsx":
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl", sheet_name=0)
        elif fmt == "xls":
            try:
                df = pd.read_excel(io.BytesIO(content), engine="xlrd", sheet_name=0)
            except ImportError as exc:
                raise AnalysisError("Reading legacy .xls files requires the 'xlrd' package.") from exc
        elif fmt == "json":
            df = _frame_from_json(json.loads(content.decode("utf-8-sig")))
        else:
            raise AnalysisError(f"Unsupported file format: .{fmt}")
    except AnalysisError:
        raise
    except Exception as exc:
        raise AnalysisError(f"The file could not be read as {fmt.upper()}: {exc}") from exc

    if df.shape[1] == 0:
        raise AnalysisError("The file contains no columns.")
    raw = _canonical(df)
    raw = raw.dropna(axis=0, how="all").reset_index(drop=True)  # trailing blank lines
    if raw.shape[0] == 0:
        raise AnalysisError("The file contains no data rows.")
    return raw


def _frame_from_json(payload: Any) -> pd.DataFrame:
    if isinstance(payload, dict):
        for key in ("data", "rows", "records", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if isinstance(payload, list) and payload and all(isinstance(r, dict) for r in payload):
        return pd.json_normalize(payload)
    if isinstance(payload, dict) and payload and all(isinstance(v, list) for v in payload.values()):
        return pd.DataFrame(payload)
    raise AnalysisError("JSON must be a list of records or an object of equal-length column arrays.")


def frame_from_manual(columns: list[str], rows: list[list[Any]]) -> pd.DataFrame:
    """Build a raw frame from manually entered data."""
    if not columns:
        raise AnalysisError("At least one column is required.")
    width = len(columns)
    for i, row in enumerate(rows):
        if len(row) != width:
            raise AnalysisError(f"Row {i + 1} has {len(row)} values but there are {width} columns.")
    raw = _canonical(pd.DataFrame(rows, columns=columns, dtype=object))
    raw = raw.dropna(axis=0, how="all").reset_index(drop=True)
    if raw.empty:
        raise AnalysisError("No data rows were entered.")
    return raw


def raw_to_csv_bytes(raw: pd.DataFrame) -> bytes:
    return raw.to_csv(index=False, na_rep="").encode("utf-8")


def raw_from_csv_bytes(content: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False, encoding="utf-8")
    return df.astype(object).where(df != "", None)


# --------------------------------------------------------------------------- #
# Type inference
# --------------------------------------------------------------------------- #
def _parse_numeric(values: pd.Series) -> pd.Series:
    cleaned = values.astype(str).str.strip().str.replace(r"(?<=\d),(?=\d{3}(\D|$))", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def _parse_datetime(values: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return pd.to_datetime(values, errors="coerce", format="mixed")
        except (TypeError, ValueError):
            return pd.to_datetime(values, errors="coerce")


def infer_column(name: str, values: pd.Series) -> dict[str, str]:
    """Infer ``type`` and ``measurement_level`` for one raw column."""
    nonnull = values.dropna()
    n = len(nonnull)
    if n == 0:
        return {"type": "text", "measurement_level": "nominal"}

    n_unique = nonnull.nunique()
    lowered = set(nonnull.astype(str).str.strip().str.lower().unique())
    if lowered <= _BOOL_TOKENS:
        return {"type": "boolean", "measurement_level": "nominal"}

    parsed = _parse_numeric(nonnull)
    numeric_share = parsed.notna().mean()
    if numeric_share >= 0.9:
        valid = parsed.dropna()
        is_int = bool(np.all(np.mod(valid, 1) == 0))
        distinct = valid.nunique()
        if is_int and _ID_NAME.search(name) and distinct >= 0.95 * len(valid) and len(valid) > 2:
            return {"type": "identifier", "measurement_level": "nominal"}
        if is_int and distinct <= 2:
            return {"type": "integer", "measurement_level": "nominal"}
        if is_int and distinct <= 7 and valid.min() >= 0 and valid.max() <= 10:
            return {"type": "integer", "measurement_level": "ordinal"}
        return {"type": "integer" if is_int else "numeric", "measurement_level": "ratio"}

    sample = nonnull.astype(str)
    if sample.str.contains(_DATE_HINT).mean() >= 0.9 and _parse_datetime(sample).notna().mean() >= 0.9:
        return {"type": "datetime", "measurement_level": "interval"}

    if n_unique >= 0.95 * n and n > 2 and _ID_NAME.search(name):
        return {"type": "identifier", "measurement_level": "nominal"}
    mean_len = sample.str.len().mean()
    if n_unique > max(20, 0.5 * n) or mean_len > 60:
        return {"type": "text", "measurement_level": "nominal"}
    return {"type": "categorical", "measurement_level": "nominal"}


def infer_schema(raw: pd.DataFrame) -> dict[str, dict[str, str]]:
    return {col: infer_column(col, raw[col]) for col in raw.columns}


def typed_frame(raw: pd.DataFrame, schema: dict[str, dict[str, str]]) -> pd.DataFrame:
    """Apply the schema: numbers become floats, dates become timestamps, and
    everything else stays as text with NaN for missing."""
    out: dict[str, pd.Series] = {}
    for col in raw.columns:
        kind = schema.get(col, {}).get("type", "text")
        series = raw[col]
        if kind in NUMERIC_TYPES:
            out[col] = _parse_numeric(series.where(series.notna(), "")).astype(float)
        elif kind == "datetime":
            out[col] = _parse_datetime(series)
        else:
            out[col] = series.astype(object).where(series.notna(), np.nan)
    return pd.DataFrame(out, index=raw.index)


# --------------------------------------------------------------------------- #
# Variable classification used by the method recommender and the tests
# --------------------------------------------------------------------------- #
def variable_kind(series: pd.Series, spec: dict[str, str] | None) -> str:
    """Analytic kind: continuous | ordinal | binary | nominal | datetime | other."""
    spec = spec or {}
    kind = spec.get("type", "text")
    level = spec.get("measurement_level", "nominal")
    distinct = series.dropna().nunique()
    if kind == "datetime":
        return "datetime"
    if kind in ("identifier", "text"):
        return "other"
    if distinct == 2:
        return "binary"
    if kind in NUMERIC_TYPES:
        if level == "ordinal":
            return "ordinal"
        if level == "nominal":
            return "nominal"
        return "continuous"
    return "ordinal" if level == "ordinal" else "nominal"


# --------------------------------------------------------------------------- #
# Column profile / data dictionary
# --------------------------------------------------------------------------- #
def profile_columns(raw: pd.DataFrame, schema: dict[str, dict[str, str]]) -> list[dict]:
    """Per-column profile: the machine-generated part of the data dictionary."""
    typed = typed_frame(raw, schema)
    profiles: list[dict] = []
    n_rows = len(raw)
    for position, col in enumerate(raw.columns):
        spec = schema.get(col, {"type": "text", "measurement_level": "nominal"})
        series = typed[col]
        n_missing = int(series.isna().sum())
        valid = series.dropna()
        stats: dict[str, Any] = {
            "n_valid": int(len(valid)),
            "missing_pct": round(100 * n_missing / n_rows, 2) if n_rows else 0.0,
        }
        if spec["type"] in NUMERIC_TYPES and len(valid):
            stats.update(
                min=float(valid.min()),
                max=float(valid.max()),
                mean=float(valid.mean()),
                median=float(valid.median()),
                std=float(valid.std(ddof=1)) if len(valid) > 1 else None,
            )
        elif spec["type"] == "datetime" and len(valid):
            stats.update(min=valid.min().isoformat(), max=valid.max().isoformat())
        elif len(valid):
            counts = valid.astype(str).value_counts()
            stats["top_values"] = [{"value": k, "count": int(v)} for k, v in counts.head(10).items()]
        profiles.append(
            {
                "name": col,
                "position": position,
                "type": spec["type"],
                "measurement_level": spec["measurement_level"],
                "n_unique": int(valid.nunique()),
                "n_missing": n_missing,
                "stats": to_jsonable(stats),
            }
        )
    return profiles


def preview(raw: pd.DataFrame, offset: int = 0, limit: int = 50) -> dict:
    """A page of rows for the UI. The browser never receives the whole file."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    page = raw.iloc[offset : offset + limit]
    return {
        "columns": list(raw.columns),
        "rows": [[None if v is None or (isinstance(v, float) and np.isnan(v)) else v for v in row] for row in page.values.tolist()],
        "offset": offset,
        "limit": limit,
        "total_rows": int(len(raw)),
    }
