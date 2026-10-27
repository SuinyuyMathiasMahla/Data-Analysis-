"""Project-level read models: serialised context, progress and dashboard."""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.evidence import STAGES, research_question_status
from app.core.errors import bad_request
from app.models import (AIRecommendation, AnalysisResult, AnalysisRun, CleaningOperation, Conclusion, Dataset, DatasetVersion,
                        Finding, Project, ProjectMember, Report, ReportVersion, StatisticalTest, User, Visualization)
from app.services import client_store, dataset_service

CLIENT_FIELDS = ("client_name", "client_email", "client_whatsapp")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def client_details(project_type: str, values: dict) -> dict:
    """The client's details as stored. A client project must have all three; a personal project keeps none.

    The WhatsApp number is stored as digits with the country code, which is the form wa.me links need."""
    if project_type != "client":
        return {field: None for field in CLIENT_FIELDS}
    name = (values.get("client_name") or "").strip()
    email = (values.get("client_email") or "").strip().lower()
    whatsapp = re.sub(r"[\s()+.-]", "", values.get("client_whatsapp") or "")
    if len(name) < 2:
        raise bad_request("Enter the client's name.")
    if not _EMAIL.match(email):
        raise bad_request("Enter a valid e-mail address for the client.")
    if not (whatsapp.isdigit() and 8 <= len(whatsapp) <= 15):
        raise bad_request("Enter the client's WhatsApp number with the country code, for example 237 677 000 000.")
    if whatsapp.startswith("0"):
        raise bad_request("Enter the number with the country code, without the leading 0 (for example 237 677 000 000).")
    return {"client_name": name, "client_email": email, "client_whatsapp": whatsapp}


def report_party(project: Project, client: dict, fallback_name: str) -> tuple[str, str]:
    """The name printed in a report and its label. For a client project this is the client, not the researcher."""
    if client["project_type"] == "client" and client["client_name"]:
        return client["client_name"], "Client"
    return (project.owner.full_name if project.owner else fallback_name), "Researcher"


def with_client(project_id: int, data: dict) -> dict:
    """A project's serialised data with its client details (type, name, e-mail, WhatsApp) added."""
    return {**data, **client_store.get(project_id)}


def accessible_projects(db: Session, user: User) -> list[Project]:
    """Projects the user owns or is a member of (admins see their own here;
    system-wide listing is under /api/admin)."""
    member_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    query = select(Project).where((Project.owner_id == user.id) | (Project.id.in_(member_ids))).order_by(Project.updated_at.desc())
    return list(db.scalars(query))


def datasets_of(db: Session, project_id: int) -> list[Dataset]:
    return list(db.scalars(select(Dataset).where(Dataset.project_id == project_id).order_by(Dataset.id)))


def primary_dataset(db: Session, project_id: int, dataset_id: int | None = None) -> Dataset | None:
    datasets = datasets_of(db, project_id)
    if dataset_id is not None:
        return next((d for d in datasets if d.id == dataset_id), None)
    return datasets[-1] if datasets else None


def progress(db: Session, project: Project) -> dict:
    """Step-by-step completion of the guided workflow."""
    pid = project.id
    datasets = datasets_of(db, pid)
    current_versions = [d.current_version_id for d in datasets if d.current_version_id]
    quality = [dataset_service.latest_quality_report(db, vid) for vid in current_versions]
    quality = [q for q in quality if q is not None]
    n_cleaning = db.scalar(select(func.count(CleaningOperation.id)).join(Dataset, Dataset.id == CleaningOperation.dataset_id)
                           .where(Dataset.project_id == pid)) or 0
    serious_open = any(i.get("severity") in ("high", "medium") and i.get("affects_score", True) for q in quality for i in (q.issues_json or []))
    def runs(kind: str) -> int:
        return db.scalar(select(func.count(AnalysisRun.id)).where(AnalysisRun.project_id == pid, AnalysisRun.status == "COMPLETED",
                                                                 AnalysisRun.analysis_type == kind)) or 0
    done = {
        "project": True,
        "research_questions": len(project.research_questions) > 0,
        "hypotheses": len(project.hypotheses) > 0,
        "dataset": len(datasets) > 0,
        "quality": len(quality) > 0,
        "cleaning": len(quality) > 0 and (n_cleaning > 0 or not serious_open),
        "exploration": runs("eda") + runs("descriptive") > 0,
        "analysis": runs("inferential") > 0,
        "findings": (db.scalar(select(func.count(Finding.id)).where(Finding.project_id == pid)) or 0) > 0,
        "conclusions": (db.scalar(select(func.count(Conclusion.id)).where(Conclusion.project_id == pid)) or 0) > 0,
        "charts": (db.scalar(select(func.count(Visualization.id)).where(Visualization.project_id == pid)) or 0) > 0,
        "report": (db.scalar(select(func.count(Report.id)).where(Report.project_id == pid)) or 0) > 0,
    }
    steps = [{"key": key, "label": label, "done": bool(done[key])} for key, label in STAGES]
    next_step = next((s for s in steps if not s["done"]), None)
    return {"percent": round(100 * sum(s["done"] for s in steps) / len(steps)), "steps": steps,
            "next_step": next_step["key"] if next_step else None}


def research_question_evaluation(db: Session, project: Project) -> list[dict]:
    """Traceability per research question: variables -> analyses -> results -> findings."""
    out = []
    for rq in project.research_questions:
        runs = list(db.scalars(select(AnalysisRun).where(AnalysisRun.research_question_id == rq.id).order_by(AnalysisRun.id)))
        analyses, completed = [], 0
        for run in runs:
            tests = {t.id: t for t in run.tests}
            for result in run.results:
                if result.result_type != "test":
                    continue
                completed += 1
                test = tests.get(result.statistical_test_id)
                analyses.append({"analysis_run_id": run.id, "analysis_result_id": result.id, "method": test.method if test else None,
                                 "method_name": test.method_name if test else run.name, "variables": test.variables_json if test else {},
                                 "apa": (result.result_json or {}).get("apa"), "p_value": result.p_value,
                                 "significant": result.is_significant, "summary": result.engine_summary,
                                 "dataset_version": run.version.version_number if run.version else None})
        findings = list(db.scalars(select(Finding).where(Finding.research_question_id == rq.id).order_by(Finding.id)))
        hypotheses = [h.to_dict() for h in project.hypotheses if h.research_question_id == rq.id]
        status, status_text = research_question_status(completed, len(findings))
        out.append({**rq.to_dict(), "status": status, "status_text": status_text, "analyses": analyses, "hypotheses": hypotheses,
                    "findings": [f.to_dict() for f in findings]})
    return out


def dashboard(db: Session, user: User) -> dict:
    projects = accessible_projects(db, user)
    ids = [p.id for p in projects] or [0]
    def count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0
    recent_datasets = list(db.scalars(select(Dataset).where(Dataset.project_id.in_(ids)).order_by(Dataset.id.desc()).limit(5)))
    recent_runs = list(db.scalars(select(AnalysisRun).where(AnalysisRun.project_id.in_(ids)).order_by(AnalysisRun.id.desc()).limit(6)))
    recommendations = list(db.scalars(select(AIRecommendation).where(AIRecommendation.project_id.in_(ids), AIRecommendation.status == "open")
                                      .order_by(AIRecommendation.id.desc()).limit(5)))
    titles = {p.id: p.title for p in projects}
    warnings = []
    for dataset in db.scalars(select(Dataset).where(Dataset.project_id.in_(ids))):
        report = dataset_service.latest_quality_report(db, dataset.current_version_id) if dataset.current_version_id else None
        if report is None:
            continue
        serious = [i for i in (report.issues_json or []) if i.get("severity") == "high"]
        if serious or float(report.score) < 90:
            warnings.append({"project_id": dataset.project_id, "project_title": titles.get(dataset.project_id), "dataset_id": dataset.id,
                             "dataset_name": dataset.name, "score": float(report.score), "high_severity_issues": len(serious),
                             "top_issue": serious[0]["message"] if serious else None})
    active = next((p for p in projects if p.status == "active"), projects[0] if projects else None)
    return {
        "counts": {"projects": len(projects), "active_projects": sum(p.status == "active" for p in projects),
                   "completed_projects": sum(p.status == "completed" for p in projects),
                   "datasets": count(Dataset, Dataset.project_id.in_(ids)),
                   "analyses": count(AnalysisRun, AnalysisRun.project_id.in_(ids), AnalysisRun.status == "COMPLETED"),
                   "statistical_tests": count(StatisticalTest, StatisticalTest.status == "COMPLETED",
                                              StatisticalTest.analysis_run_id.in_(select(AnalysisRun.id).where(AnalysisRun.project_id.in_(ids)))),
                   "reports": count(Report, Report.project_id.in_(ids))},
        "projects": [{**p.to_dict(), "progress": progress(db, p)} for p in projects[:12]],
        "active_project": None if active is None else {**active.to_dict(), "progress": progress(db, active)},
        "recent_datasets": [{**d.to_dict(), "project_title": titles.get(d.project_id)} for d in recent_datasets],
        "recent_analyses": [{"id": r.id, "name": r.name, "status": r.status, "analysis_type": r.analysis_type, "project_id": r.project_id,
                             "project_title": titles.get(r.project_id), "created_at": r.to_dict()["created_at"]} for r in recent_runs],
        "data_quality_warnings": warnings[:8],
        "ai_recommendations": [{**r.to_dict(), "project_title": titles.get(r.project_id)} for r in recommendations],
    }


def results_as_dicts(results: list[AnalysisResult]) -> list[dict]:
    return [r.result_json for r in results if r.result_json]


def hypothesis_dicts(project: Project) -> list[dict]:
    return [h.to_dict() for h in project.hypotheses]


def question_dicts(project: Project) -> list[dict]:
    return [q.to_dict() for q in project.research_questions]


def next_code(prefix: str, existing: list[str]) -> str:
    """RQ1, RQ2, ... / H1, H2, ... skipping codes already in use."""
    n = len(existing) + 1
    while f"{prefix}{n}" in existing:
        n += 1
    return f"{prefix}{n}"


def storage_keys(db: Session, project_id: int) -> list[str]:
    """Every stored file that belongs to a project (dataset versions, charts, reports)."""
    keys = list(db.scalars(select(DatasetVersion.storage_key).join(Dataset, Dataset.id == DatasetVersion.dataset_id)
                           .where(Dataset.project_id == project_id)))
    keys += list(db.scalars(select(Visualization.storage_key).where(Visualization.project_id == project_id)))
    keys += list(db.scalars(select(ReportVersion.storage_key).join(Report, Report.id == ReportVersion.report_id)
                            .where(Report.project_id == project_id)))
    return keys
