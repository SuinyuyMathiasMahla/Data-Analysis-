"""Builds the structured, minimal context that is sent to the AI provider.

Privacy rules implemented here:
* no raw data rows are ever included - only summaries computed by the engine;
* no account data (names, e-mail addresses, institution login details);
* free-text and identifier columns are described by name and type only, with
  no example values, because they are the columns most likely to hold
  personal information;
* long result payloads (residuals, per-point diagnostics) are dropped.
"""
from __future__ import annotations

from typing import Any

_DROP_KEYS = {"diagnostics", "software", "filters", "records_in_dataset", "records_after_filters", "power_curve"}
MAX_RESULTS = 12
MAX_VARIABLES = 60


def slim_result(result: dict) -> dict:
    """An engine result reduced to what is needed for interpretation."""
    out = {k: v for k, v in result.items() if k not in _DROP_KEYS and v not in (None, [], {})}
    tables = []
    for t in out.get("tables", [])[:6]:
        tables.append({"title": t.get("title"), "columns": t.get("columns"), "rows": (t.get("rows") or [])[:25], "note": t.get("note")})
    if tables:
        out["tables"] = tables
    for key in ("numeric", "categorical", "numeric_summary", "categorical_summary", "correlations", "loadings"):
        out.pop(key, None)          # already represented by the tables
    return out


def build_context(*, project: dict, research_questions: list[dict], hypotheses: list[dict], dataset: dict | None,
                  variables: list[dict], quality: dict | None, results: list[dict], visualizations: list[dict] | None = None,
                  focus: dict | None = None) -> dict[str, Any]:
    safe_variables = []
    for v in variables[:MAX_VARIABLES]:
        item = {"name": v.get("name"), "label": v.get("label"), "type": v.get("data_type"), "measurement_level": v.get("measurement_level"),
                "role": v.get("role"), "unit": v.get("unit"), "n_missing": v.get("n_missing"), "n_unique": v.get("n_unique")}
        if v.get("data_type") not in ("text", "identifier"):
            stats = v.get("stats") or {}
            item["summary"] = {k: stats[k] for k in ("mean", "median", "std", "min", "max") if stats.get(k) is not None}
            if stats.get("top_values"):
                item["categories"] = [t["value"] for t in stats["top_values"][:8]]
        safe_variables.append({k: val for k, val in item.items() if val not in (None, {}, [])})
    context: dict[str, Any] = {
        "project": {k: project.get(k) for k in ("title", "academic_level", "research_field", "research_problem", "general_objective",
                                                 "study_population", "sample_size", "sampling_technique", "research_methodology",
                                                 "study_design", "data_collection_method") if project.get(k) not in (None, "")},
        "research_questions": [{"code": q["code"], "text": q["text"]} for q in research_questions],
        "hypotheses": [{"code": h["code"], "null": h["null_text"], "alternative": h["alternative_text"], "direction": h.get("direction"),
                        "alpha": float(h.get("alpha", 0.05)), "decision": h.get("decision")} for h in hypotheses],
        "dataset": dataset,
        "variables": safe_variables,
        "data_quality": None if not quality else {"score": quality.get("score"), "summary": quality.get("summary"),
                                                  "issues": [{"severity": i["severity"], "message": i["message"]} for i in (quality.get("issues") or [])[:20]]},
        "statistical_results": [slim_result(r) for r in results[-MAX_RESULTS:]],
        "visualizations": [{"title": v.get("title"), "chart_type": v.get("chart_type"), "x": v.get("x"), "y": v.get("y"),
                            "notes": v.get("notes")} for v in (visualizations or [])[:10]],
    }
    if focus:
        context["focus"] = focus
    return context
