"""Findings, conclusions, recommendations and limitations (database side).

Drafting rules live in app/analysis/evidence.py; this module stores drafts and
keeps the links  conclusion/recommendation -> finding -> analysis result  intact.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import evidence
from app.core.errors import bad_request, not_found
from app.ai.service import AIService
from app.models import (AnalysisResult, AnalysisRun, Conclusion, Finding, Hypothesis, Limitation, Project, Recommendation,
                        ResearchQuestion, StatisticalTest, User, Variable)
from app.services import analysis_service, audit, auto_analysis, dataset_service, project_service


def list_findings(db: Session, project_id: int) -> list[Finding]:
    return list(db.scalars(select(Finding).where(Finding.project_id == project_id).order_by(Finding.id)))


def _not_analysed_reason(item: dict) -> str:
    """Why one hypothesis (or question) has no finding, in words the researcher can act on."""
    if item["status"] == "skipped":
        return item["reason"]
    if item["status"] == "failed":
        return f"the analysis failed ({(item.get('run') or {}).get('error_message') or 'unknown error'}). Fix the problem, then run it again."
    if item["status"] == "running":
        return "the analysis is still running."
    return "it has not been analysed on the current version of the data. Run the analysis again."


def unanswered_notes(db: Session, project: Project) -> dict[int, list[str]]:
    """For each research question, the hypotheses that have no completed analysis, with the reason."""
    dataset = project_service.primary_dataset(db, project.id)
    if dataset is None or dataset.current_version is None:
        return {q.id: ["No dataset has been analysed yet."] for q in project.research_questions}
    overview = auto_analysis.overview(db, project, dataset, dataset.current_version, AIService(None))
    answered = {f.research_question_id for f in list_findings(db, project.id)}
    notes: dict[int, list[str]] = {}
    for item in overview["items"]:
        if item["research_question"] is None:
            continue
        if item["status"] == "completed":
            if item["research_question"]["id"] not in answered:
                notes.setdefault(item["research_question"]["id"], []).append(
                    "Its analysis is complete, but no finding has been recorded from it yet. Record a finding to answer the question.")
            continue
        label = f"Hypothesis {item['hypothesis']['code']} was not analysed" if item["hypothesis"] else "It was not analysed"
        notes.setdefault(item["research_question"]["id"], []).append(f"{label}: {_not_analysed_reason(item)}")
    return notes


def variable_labels(db: Session, project: Project) -> dict[str, str]:
    """Variable name -> label from the data dictionary of the project's primary dataset (empty when there is no dataset)."""
    dataset = project_service.primary_dataset(db, project.id)
    if dataset is None:
        return {}
    return {v.name: v.label for v in db.scalars(select(Variable).where(Variable.dataset_id == dataset.id)) if v.label}


def analysis_basis(db: Session, project: Project) -> tuple[list[dict], dict[int, list[str]], dict[str, str]]:
    """Everything the written conclusions and recommendations are built from:
    the findings, each with its statistical result, hypothesis, research question code and how its variables were chosen;
    the notes on unanswered items; and the variable labels."""
    codes = {q.id: q.code for q in project.research_questions}
    findings = []
    for finding in list_findings(db, project.id):
        data = finding.to_dict()
        result = db.get(AnalysisResult, finding.analysis_result_id) if finding.analysis_result_id else None
        run = db.get(AnalysisRun, result.analysis_run_id) if result else None
        hypothesis = db.get(Hypothesis, finding.hypothesis_id) if finding.hypothesis_id else None
        automatic = ((run.config_json or {}).get("automatic") or {}) if run else {}
        findings.append({**data, "result": result.result_json if result else None, "hypothesis": hypothesis.to_dict() if hypothesis else None,
                         "research_question_code": codes.get(finding.research_question_id), "variable_source": automatic.get("variables_source"),
                         "variable_basis": automatic.get("variables_basis"), "filter_note": automatic.get("filter_note")})
    return findings, unanswered_notes(db, project), variable_labels(db, project)


def _findings_by_ids(db: Session, project_id: int, ids: list[int]) -> list[Finding]:
    if not ids:
        return []
    found = list(db.scalars(select(Finding).where(Finding.project_id == project_id, Finding.id.in_(ids))))
    if len(found) != len(set(ids)):
        raise bad_request("One or more of the linked findings do not belong to this project.")
    return found


def finding_from_result(db: Session, project: Project, user: User, result: AnalysisResult, research_question_id: int | None,
                        hypothesis_id: int | None) -> Finding:
    """Draft a finding from an engine result, keeping the evidence link."""
    if result.result_type != "test":
        raise bad_request("Findings are drafted from statistical test results. Summarise descriptive results in a manual finding.")
    run = db.get(AnalysisRun, result.analysis_run_id)
    test = db.get(StatisticalTest, result.statistical_test_id) if result.statistical_test_id else None
    rq_id = research_question_id if research_question_id is not None else run.research_question_id
    hyp_id = hypothesis_id if hypothesis_id is not None else (test.hypothesis_id if test else None)
    rq = db.get(ResearchQuestion, rq_id) if rq_id else None
    hyp = db.get(Hypothesis, hyp_id) if hyp_id else None
    if (rq and rq.project_id != project.id) or (hyp and hyp.project_id != project.id):
        raise not_found("Research question or hypothesis")
    draft = evidence.draft_finding(result.result_json, rq.to_dict() if rq else None, hyp.to_dict() if hyp else None)
    finding = Finding(project_id=project.id, research_question_id=rq.id if rq else None, hypothesis_id=hyp.id if hyp else None,
                      analysis_result_id=result.id, title=draft["title"], statement=draft["statement"],
                      statistical_evidence=draft["statistical_evidence"], interpretation=draft["interpretation"],
                      confidence_level=draft["confidence_level"], limitations_note=draft["limitations_note"], source="engine",
                      created_by=user.id)
    db.add(finding)
    db.flush()
    audit.record(db, action="finding.drafted", user_id=user.id, project_id=project.id, entity_type="finding", entity_id=finding.id,
                 details={"analysis_result_id": result.id, "title": finding.title})
    db.commit()
    db.refresh(finding)
    return finding


def generate_conclusions(db: Session, project: Project, user: User, replace: bool = True) -> list[Conclusion]:
    findings, unanswered, labels = analysis_basis(db, project)
    if not findings and not project.research_questions:
        raise bad_request("Add a research question and run its analysis first. Conclusions answer the research questions.", "no_findings")
    drafts = evidence.draft_conclusions(findings, project_service.question_dicts(project), unanswered, labels, project.title)
    if replace:
        for old in db.scalars(select(Conclusion).where(Conclusion.project_id == project.id, Conclusion.source == "engine")):
            db.delete(old)
        db.flush()
    start = len(list(db.scalars(select(Conclusion.id).where(Conclusion.project_id == project.id))))
    created = []
    for i, draft in enumerate(drafts):
        item = Conclusion(project_id=project.id, text=draft["text"], source="engine", position=start + i)
        item.findings = _findings_by_ids(db, project.id, draft["finding_ids"])
        db.add(item)
        created.append(item)
    audit.record(db, action="conclusions.generated", user_id=user.id, project_id=project.id, details={"count": len(created)})
    db.commit()
    return created


def generate_recommendations(db: Session, project: Project, user: User, replace: bool = True) -> list[Recommendation]:
    findings = [f.to_dict() for f in list_findings(db, project.id)]
    if not findings:
        raise bad_request("Record at least one finding first. Recommendations must be connected to findings.", "no_findings")
    drafts = evidence.draft_recommendations(findings, project.study_design)
    if not drafts:
        raise bad_request("None of the findings is linked to a statistical result, so no recommendation can be drafted automatically. "
                          "Write recommendations manually and link them to findings.", "no_linked_results")
    if replace:
        for old in db.scalars(select(Recommendation).where(Recommendation.project_id == project.id, Recommendation.source == "engine")):
            db.delete(old)
        db.flush()
    start = len(list(db.scalars(select(Recommendation.id).where(Recommendation.project_id == project.id))))
    created = []
    for i, draft in enumerate(drafts):
        item = Recommendation(project_id=project.id, text=draft["text"], source="engine", position=start + i)
        item.findings = _findings_by_ids(db, project.id, draft["finding_ids"])
        db.add(item)
        created.append(item)
    audit.record(db, action="recommendations.generated", user_id=user.id, project_id=project.id, details={"count": len(created)})
    db.commit()
    return created


def detect_limitations(db: Session, project: Project, user: User) -> list[Limitation]:
    """Add newly detected limitations. Existing ones are never removed or
    reset - not even when the condition that triggered them has gone."""
    dataset = project_service.primary_dataset(db, project.id)
    quality_summary, ops = None, []
    if dataset and dataset.current_version:
        report = dataset_service.latest_quality_report(db, dataset.current_version_id)
        quality_summary = (report.summary_json or {}).get("summary") if report else None
        ops = [op.to_dict(with_details=False) for op in dataset_service.cleaning_for_version(db, dataset.current_version)]
    results = [r.result_json for r in analysis_service.project_results(db, project.id) if r.result_type == "test"]
    detected = evidence.detect_limitations(project.to_dict(), quality_summary, results, ops)
    existing = {(item.category, item.description) for item in db.scalars(select(Limitation).where(Limitation.project_id == project.id))}
    existing_auto_categories = {c for c, _ in existing}
    created = []
    for item in detected:
        if (item["category"], item["description"]) in existing:
            continue
        # one automatic entry per category unless the wording carries new evidence
        if item["category"] in existing_auto_categories and item["category"] in ("generalizability", "design", "self_report", "sampling_bias"):
            continue
        row = Limitation(project_id=project.id, category=item["category"], description=item["description"], source="auto",
                         evidence_json=item["evidence"])
        db.add(row)
        created.append(row)
    audit.record(db, action="limitations.detected", user_id=user.id, project_id=project.id, details={"new": len(created)})
    db.commit()
    return list(db.scalars(select(Limitation).where(Limitation.project_id == project.id).order_by(Limitation.id)))
