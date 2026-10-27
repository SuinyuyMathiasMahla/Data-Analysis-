"""Assembles the report ``content`` snapshot from plain dictionaries.

Kept free of database and web code on purpose: the service layer serialises
ORM rows to dicts and calls :func:`assemble_report_content`; tests can call it
directly. The returned dict is stored with the report version, which makes a
generated report auditable and re-renderable later.
"""
from __future__ import annotations

from typing import Any

from app.analysis.cleaning import OPERATIONS
from app.analysis.evidence import research_question_status
from app.reports.renderers import now_iso
from app.statistics.registry import METHODS


def variables_text(variables: dict | None) -> str:
    """'outcome: gpa; predictors: a, b' from a result's variables dict."""
    parts = []
    for role, value in (variables or {}).items():
        if value in (None, "", []):
            continue
        parts.append(f"{role}: {', '.join(str(v) for v in value) if isinstance(value, list) else value}")
    return "; ".join(parts)


def holm_adjusted(p_values: dict) -> dict:
    """Holm step-down adjustment over all tests in the report: keys are result ids, values adjusted p-values."""
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    m, out, running = len(ordered), {}, 0.0
    for rank, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - rank) * p))
        out[key] = running
    return out


def _decision_text(decision: str | None) -> str:
    return {"reject_null": "Reject H0", "fail_to_reject_null": "Fail to reject H0"}.get(decision or "", "Not yet tested")


def assemble_report_content(*, title: str, researcher: str | None, researcher_label: str = "Researcher", project: dict,
                            dataset: dict | None, variables: list[dict],
                            quality: dict | None, cleaning: list[dict], runs: list[dict], research_questions: list[dict],
                            hypotheses: list[dict], findings: list[dict], conclusions: list[dict], recommendations: list[dict],
                            limitations: list[dict], figures: list[dict], sections: list[str] | None = None) -> dict[str, Any]:
    """Build the snapshot. Input shapes are documented in docs/architecture.md."""
    rq_by_id = {q["id"]: q for q in research_questions}
    hyp_by_id = {h["id"]: h for h in hypotheses}
    finding_number = {f["id"]: i for i, f in enumerate(findings, 1)}

    descriptive, inferential, config_rows, methods_used = [], [], [], {}
    software: dict = {}
    for run in runs:
        if run.get("status") != "COMPLETED":
            continue
        software = run.get("software") or software
        rq = rq_by_id.get(run.get("research_question_id"))
        for res in run.get("results", []):
            payload = res["result"]
            test = res.get("test") or {}
            hyp = hyp_by_id.get(test.get("hypothesis_id"))
            vtext = variables_text(payload.get("variables"))
            params = {**(test.get("params") or {})}
            if run.get("filters"):
                params["filters"] = run["filters"]
            config_rows.append([run["id"], (run.get("completed_at") or run.get("created_at") or "")[:19].replace("T", " "),
                                payload.get("method_name") or run.get("name"), f"v{run.get('version_number')}", vtext,
                                ", ".join(f"{k}={v}" for k, v in params.items()) or "defaults"])
            if res.get("result_type") in ("descriptive", "eda"):
                descriptive.append({"title": run.get("name"), "tables": payload.get("tables", [])})
                continue
            if res.get("result_type") == "power":
                descriptive.append({"title": run.get("name"), "tables": [{"title": "Power / sample-size analysis", "columns": ["Summary"],
                                                                          "rows": [[payload.get("summary")]] + [[w] for w in payload.get("warnings", [])]}]})
                continue
            method = payload.get("method")
            meta = METHODS.get(method, {})
            methods_used.setdefault((method, vtext), {"name": payload.get("method_name"), "variables": vtext,
                                                      "justification": res.get("justification") or meta.get("description") or ""})
            inferential.append({
                "result_id": res["id"], "method": method, "category": meta.get("category"), "method_name": payload.get("method_name"), "variables_text": vtext,
                "n": payload.get("n"), "apa": payload.get("apa"), "summary": payload.get("summary"), "statistic": payload.get("statistic"),
                "df": payload.get("df"), "p_value": payload.get("p_value"), "significant": payload.get("significant"),
                "decision": payload.get("decision"), "effect_sizes": payload.get("effect_sizes") or [],
                "estimates": payload.get("estimates") or [], "assumptions": payload.get("assumptions") or [],
                "tables": payload.get("tables") or [], "warnings": payload.get("warnings") or [],
                "rq_code": rq["code"] if rq else None, "rq_id": rq["id"] if rq else None,
                "hypothesis_code": hyp["code"] if hyp else None, "hypothesis_id": hyp["id"] if hyp else None,
                "dataset_version": f"v{run.get('version_number')}", "run_at": (run.get("completed_at") or "")[:19].replace("T", " "),
            })

    # Count each distinct test once: a re-run of the same method on the same variables for the same hypothesis replaces the earlier row.
    distinct: dict = {}
    for item in inferential:
        distinct[(item["hypothesis_id"], item["method"], item["variables_text"])] = item
    inferential = list(distinct.values())

    out_findings = []
    for f in findings:
        rq, hyp = rq_by_id.get(f.get("research_question_id")), hyp_by_id.get(f.get("hypothesis_id"))
        out_findings.append({**{k: f.get(k) for k in ("id", "title", "statement", "statistical_evidence", "interpretation", "confidence_level",
                                                       "limitations_note", "source", "is_edited", "analysis_result_id")},
                             "rq_code": rq["code"] if rq else None, "hypothesis_code": hyp["code"] if hyp else None})

    out_rqs = []
    for rq in research_questions:
        analyses = [i for i in inferential if i["rq_id"] == rq["id"]]
        linked = [f for f in findings if f.get("research_question_id") == rq["id"]]
        status, status_text = research_question_status(len(analyses), len(linked))
        out_rqs.append({"code": rq["code"], "text": rq["text"], "status": status, "status_text": status_text,
                        "variables": rq.get("variables") or [],
                        "analyses": [{"method_name": a["method_name"], "variables_text": a["variables_text"], "apa": a["apa"]} for a in analyses],
                        "findings": [{"statement": f["statement"], "interpretation": f.get("interpretation")} for f in linked]})

    # The first hypothesis is the primary (H1): its decision uses the raw p-value. Secondary hypotheses are Holm-adjusted
    # across only their own latest tests, and their decision uses the adjusted p-value so the text agrees with the table.
    latest_by_hyp = {}
    for h in hypotheses:
        tests = [i for i in inferential if i["hypothesis_id"] == h["id"]]
        if tests:
            latest_by_hyp[h["id"]] = tests[-1]
    secondary = [latest_by_hyp[h["id"]] for h in hypotheses[1:] if h["id"] in latest_by_hyp and latest_by_hyp[h["id"]].get("p_value") is not None]
    adjusted = holm_adjusted({i["result_id"]: float(i["p_value"]) for i in secondary})
    out_hyps = []
    for index, h in enumerate(hypotheses):
        latest = latest_by_hyp.get(h["id"])
        stat = (latest or {}).get("statistic") or {}
        alpha = float(h.get("alpha", 0.05))
        primary = index == 0
        p_used = None
        if latest and latest.get("p_value") is not None:
            p_used = float(latest["p_value"]) if primary else adjusted.get(latest["result_id"])
        if p_used is not None:
            decision_text = "Reject H0" if p_used < alpha else "Fail to reject H0"
        else:
            decision_text = _decision_text(latest["decision"] if latest else None)
        interpretation = latest["summary"] if latest else None
        if latest and not primary and p_used is not None:
            interpretation = (f"{interpretation or ''} Holm-adjusted p = {p_used:.3f} across {len(secondary)} secondary test(s); "
                              f"decision on the adjusted value: {decision_text}.").strip()
        out_hyps.append({
            "code": h["code"], "null_text": h["null_text"], "alternative_text": h["alternative_text"], "alpha": alpha,
            "test": latest["method_name"] if latest else None,
            "statistic_text": (f"{stat.get('name')} = {stat.get('value'):.3f}" if latest and stat.get("value") is not None else None),
            "p_value": latest["p_value"] if latest else None,
            "p_adjusted": round(adjusted[latest["result_id"]], 4) if (latest and not primary and latest["result_id"] in adjusted) else None,
            "tests_in_report": len(secondary),
            "primary": primary,
            "not_tested_reason": h.get("not_tested_reason"),
            "decision_text": decision_text,
            "interpretation": interpretation,
        })

    dictionary_rows = []
    for v in variables:
        stats = v.get("stats") or {}
        dictionary_rows.append([v["name"], v.get("label") or "", v["data_type"], v["measurement_level"], v.get("n_unique"), v.get("n_missing"),
                                stats.get("min"), stats.get("max"), stats.get("mean"), stats.get("median"), stats.get("std")])

    def linked_numbers(item: dict) -> list[int]:
        return sorted(finding_number[i] for i in item.get("finding_ids", []) if i in finding_number)

    completed = len(inferential)
    summary = [f"This report describes the analysis of {(dataset or {}).get('name') or 'the dataset'} for the project '{title}'. "
               f"{completed} statistical test{'s' if completed != 1 else ''} {'were' if completed != 1 else 'was'} completed, "
               f"{len(out_findings)} finding{'s' if len(out_findings) != 1 else ''} recorded, and {len(conclusions)} conclusion"
               f"{'s' if len(conclusions) != 1 else ''} and {len(recommendations)} recommendation{'s' if len(recommendations) != 1 else ''} drawn from them."]
    summary += [f"Key finding: {f.get('statement') or f.get('title')}" for f in out_findings[:3]]
    if conclusions:
        summary.append(f"Overall conclusion: {conclusions[0]['text']}")
    if recommendations:
        summary.append(f"Main recommendation: {recommendations[0]['text']}")

    return {
        "title": title,
        "generated_at": now_iso(),
        "executive_summary": summary,
        "sections": sections,
        "project": {**{k: project.get(k) for k in ("title", "academic_level", "research_field", "institution", "department",
                                                   "research_problem", "general_objective", "study_population", "sample_size",
                                                   "sampling_technique", "study_design", "data_collection_method", "research_methodology")},
                    "researcher": researcher, "researcher_label": researcher_label,
                    "objectives": [o.get("text") for o in project.get("objectives") or [] if o.get("text")]},
        "dataset": None if not dataset else {**dataset, "variables": variables},
        "data_quality": {**(quality or {}),
                         "cleaning": [{"label": OPERATIONS.get(op["operation"], {}).get("label", op["operation"]), **op} for op in cleaning]},
        "methodology": {**{k: project.get(k) for k in ("study_design", "research_methodology", "study_population", "sampling_technique",
                                                       "sample_size", "data_collection_method")},
                        "methods": list(methods_used.values()), "software": software},
        "descriptive": descriptive,
        "inferential": inferential,
        "research_questions": out_rqs,
        "hypotheses": out_hyps,
        "findings": out_findings,
        "conclusions": [{"text": c["text"], "source": c.get("source"), "finding_numbers": linked_numbers(c)} for c in conclusions],
        "recommendations": [{"text": r["text"], "source": r.get("source"), "audience": r.get("audience"), "finding_numbers": linked_numbers(r)}
                            for r in recommendations],
        "limitations": [{k: item.get(k) for k in ("category", "description", "status", "status_note", "source")} for item in limitations],
        "figures": figures,
        "appendix": {"data_dictionary": dictionary_rows, "analysis_config": config_rows},
    }
