"""Shared helpers for the statistical engine.

Everything the engine returns goes through :func:`to_jsonable` so that results
can be stored in a JSON column and sent to the browser without NumPy types,
NaN or infinity leaking out.
"""
from __future__ import annotations

import math
import platform
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


class AnalysisError(ValueError):
    """The analysis cannot be run on the data as given (user-fixable)."""


class InsufficientDataError(AnalysisError):
    """There is not enough valid data to compute the statistic reliably."""

    def __init__(self, detail: str = "") -> None:
        msg = "Insufficient evidence to perform this analysis reliably."
        super().__init__(f"{msg} {detail}".strip())


class MethodNotImplementedError(AnalysisError):
    """The method is registered but not implemented. Never fabricate output."""


def to_jsonable(value: Any) -> Any:
    """Recursively convert NumPy / pandas objects to plain JSON-safe Python."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, pd.Series):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, pd.DataFrame):
        return to_jsonable(value.to_dict(orient="records"))
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def fmt_num(value: Any, digits: int = 3) -> str:
    """Format a number for prose; returns 'n/a' for missing values."""
    if value is None:
        return "n/a"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(f):
        return "n/a"
    if f != 0 and abs(f) < 10 ** (-digits):
        return f"{f:.2g}"          # keep two significant digits for very small values
    return f"{f:.{digits}f}"


def fmt_p(p: Any) -> str:
    """APA-style p-value: exact to three decimals, 'p < .001' below that."""
    if p is None:
        return "p = n/a"
    p = float(p)
    if not math.isfinite(p):
        return "p = n/a"
    if p < 0.001:
        return "p < .001"
    return "p = " + f"{p:.3f}".lstrip("0")


def numeric(series: pd.Series) -> pd.Series:
    """Coerce a series to float; anything unparseable becomes NaN."""
    return pd.to_numeric(series, errors="coerce").astype(float)


def require_columns(df: pd.DataFrame, *columns: str | None) -> None:
    missing = [c for c in columns if c and c not in df.columns]
    if missing:
        raise AnalysisError(f"Variable(s) not found in the dataset: {', '.join(missing)}")


def software_versions() -> dict[str, str]:
    """Library versions recorded with every analysis run for reproducibility."""
    import scipy
    import sklearn

    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit-learn": sklearn.__version__,
    }
    for name in ("statsmodels", "matplotlib", "seaborn"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", "unknown")
        except Exception:  # pragma: no cover - optional at import time
            versions[name] = "not installed"
    return versions


def table(title: str, columns: list[str], rows: list[list[Any]], note: str | None = None) -> dict:
    return {"title": title, "columns": columns, "rows": to_jsonable(rows), "note": note}


def new_result(method: str, method_name: str, *, n: int, variables: dict, alpha: float = 0.05) -> dict:
    """Skeleton shared by every statistical result so the UI, the findings
    generator, the AI context builder and the report all read one shape."""
    return {
        "method": method,
        "method_name": method_name,
        "n": int(n),
        "variables": variables,
        "alpha": alpha,
        "alternative": "two-sided",
        "statistic": None,          # {"name": "t", "value": 2.31}
        "df": None,
        "p_value": None,
        "significant": None,
        "decision": None,           # reject_null | fail_to_reject_null
        "estimates": [],            # [{name, value, ci_low, ci_high, ci_level}]
        "effect_sizes": [],         # [{name, value, magnitude, ci_low, ci_high}]
        "assumptions": [],          # [{name, test, statistic, p_value, satisfied, note}]
        "tables": [],
        "warnings": [],
        "apa": None,
        "summary": None,
        "source": "statistical_engine",
    }


def finalize(result: dict) -> dict:
    """Set the hypothesis decision from p and alpha, then make JSON-safe."""
    p = result.get("p_value")
    if p is not None and math.isfinite(float(p)):
        result["significant"] = bool(float(p) < result["alpha"])
        result["decision"] = "reject_null" if result["significant"] else "fail_to_reject_null"
    return to_jsonable(result)
