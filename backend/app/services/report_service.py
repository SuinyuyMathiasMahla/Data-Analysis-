"""Report generation: gather -> snapshot -> render -> store."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis import evidence, finding_review, plain_summary, visualization
from app.core.errors import bad_request
from app.statistics.utils import AnalysisError
from app.models import (AnalysisRun, Conclusion, Dataset, DatasetVersion, Limitation, Project, Recommendation, Report, ReportVersion, User,
                        Visualization)
from app.reports import gate, package, renderers
from app.reports.content import assemble_report_content
from app.services import audit, client_store, dataset_service, evidence_service, project_service, report_details
from app.services.storage import get_storage, make_key


def build_report_content(db: Session, project: Project, user: User, title: str, dataset: Dataset | None,
                         sections: list[str] | None) -> tuple[dict, dict[str, bytes]]:
    """Collect everything the report needs as plain dicts, plus chart images."""
    dataset_info, variables, quality, cleaning = None, [], None, []
    if dataset is not None and dataset.current_version is not None:
        version = dataset.current_version
        original = next((v for v in dataset.versions if v.kind == "original"), None)
        dataset_info = {"name": dataset.name, "description": dataset.description, "source_type": dataset.source_type,
                        "original_filename": dataset.original_filename, "version_number": version.version_number,
                        "rows": version.row_count, "columns": version.column_count, "checksum": version.checksum_sha256,
                        "original_checksum": original.checksum_sha256 if original else None}
        variables = dataset_service.data_dictionary(db, dataset, version)
        report = dataset_service.latest_quality_report(db, version.id)
        quality = report.to_dict() if report else None
        cleaning = [op.to_dict(with_details=False) for op in dataset_service.cleaning_for_version(db, version)]
    runs = [r.to_dict(with_results=True) for r in db.scalars(select(AnalysisRun).where(AnalysisRun.project_id == project.id)
                                                             .order_by(AnalysisRun.id))]
    for run in runs:
        for res in run.get("results", []):
            res["justification"] = ((res.get("test") or {}).get("params") or {}).get("justification")
    figures, images = [], {}
    storage = get_storage()
    for viz in db.scalars(select(Visualization).where(Visualization.project_id == project.id, Visualization.include_in_report.is_(True))
                          .order_by(Visualization.id)):
        if not storage.exists(viz.storage_key):
            continue
        key = f"viz-{viz.id}"
        images[key] = storage.load(viz.storage_key)
        meta = (viz.config_json or {}).get("_meta", {})
        figures.append({"image_key": key, "title": viz.title, "note": " ".join(meta.get("notes") or []) or None,
                        "section": "inferential" if viz.chart_type in ("regression", "qq") or viz.analysis_run_id else "descriptive"})
    conclusion_rows = list(db.scalars(select(Conclusion).where(Conclusion.project_id == project.id).order_by(Conclusion.position, Conclusion.id)))
    party_name, party_label = project_service.report_party(project, client_store.get(project.id), user.full_name)
    content = assemble_report_content(
        title=title, researcher=party_name, researcher_label=party_label, project=project.to_dict(full=True),
        dataset=dataset_info, variables=variables, quality=quality, cleaning=cleaning, runs=runs,
        research_questions=[{**q.to_dict(), "variables": [v["name"] for v in q.to_dict()["variables"] if v["name"]]}
                            for q in project.research_questions],
        hypotheses=project_service.hypothesis_dicts(project),
        findings=[f.to_dict() for f in evidence_service.list_findings(db, project.id)],
        conclusions=[c.to_dict() for c in conclusion_rows],
        recommendations=[r.to_dict() for r in db.scalars(select(Recommendation).where(Recommendation.project_id == project.id).order_by(Recommendation.position, Recommendation.id))],
        limitations=[item.to_dict() for item in db.scalars(select(Limitation).where(Limitation.project_id == project.id).order_by(Limitation.id))],
        figures=figures, sections=sections)
    content["project"]["supervisors"] = [m["full_name"] for m in project.to_dict(full=True)["members"]
                                         if m["member_role"] == "supervisor" and m["full_name"]]
    content["details"] = report_details.get(project.id)
    _attach_finding_reviews(db, project, content, images)
    findings, _, labels = evidence_service.analysis_basis(db, project)
    content["plain_summaries"] = plain_summary.build(project_service.question_dicts(project), findings, labels)
    return content, images


def _finding_chart(db: Session, finding, labels: dict[str, str], images: dict, key: str) -> dict | None:
    """The chart that shows a finding: drawn from the data its test used, with the sample size in its title. None when it cannot be drawn."""
    idea = next(iter(finding.chart_suggestions()), None)
    run = db.get(AnalysisRun, idea["run_id"]) if idea and idea.get("run_id") else None
    if run is None or run.dataset_version_id is None:
        return None
    n = (finding.analysis_result.result_json or {}).get("n") if finding.analysis_result else None
    title = f"{idea['title']} (n = {n})" if n is not None else idea["title"]
    try:
        df, _ = dataset_service.load_typed(db, db.get(DatasetVersion, run.dataset_version_id))
        png, _meta = visualization.render_chart(df, {"chart_type": idea["chart_type"], "x": idea.get("x"), "y": idea.get("y"),
                                                     "title": title}, labels)
    except (AnalysisError, KeyError, ValueError, TypeError):
        return None
    images[key] = png
    return {"image_key": key, "title": title, "note": idea.get("reason")}


def _attach_finding_reviews(db: Session, project: Project, content: dict, images: dict) -> None:
    """The review of every finding (eight parts), with its chart. Charts appear here and nowhere else in the report.
    Also the general conclusion of the study, which is written from the same findings."""
    labels = evidence_service.variable_labels(db, project)
    question_text = {q.id: q.text for q in project.research_questions}
    findings, _, _ = evidence_service.analysis_basis(db, project)
    models = evidence_service.list_findings(db, project.id)
    reviews = []
    for number, (finding, model) in enumerate(zip(findings, models), 1):
        chart = _finding_chart(db, model, labels, images, key=f"finding-{model.id}")
        finding["chart_title"] = chart["title"] if chart else None
        lines = finding_review.review(number, finding, labels, question_text.get(finding.get("research_question_id")))
        reviews.append({"lines": lines, "chart": chart})
    content["review_findings"] = reviews
    content["general_conclusion"] = evidence.general_conclusion(findings, project_service.question_dicts(project), labels)


def _cleaned_frame(db: Session, dataset: Dataset | None):
    """The typed data of the dataset's current version, for the workbook and the data deliverables. None when there is no dataset."""
    if dataset is None or dataset.current_version is None:
        return None
    df, _ = dataset_service.load_typed(db, dataset.current_version)
    return df


def generate_report(db: Session, project: Project, user: User, *, fmt: str, title: str | None, report: Report | None,
                    sections: list[str] | None, dataset: Dataset | None, include_data: bool) -> ReportVersion:
    """Build the report content, render it in the chosen format, store the file and record it as a new version of the report."""
    title = title or f"{project.title}: research report"
    content, images = build_report_content(db, project, user, title, dataset, sections)
    if fmt == "pdf":
        data = renderers.render_pdf(content, images)
    elif fmt == "docx":
        data = renderers.render_docx(content, images)
    elif fmt == "xlsx":
        frame = _cleaned_frame(db, dataset) if include_data else None
        data_rows = None
        if frame is not None:
            data_rows = (list(frame.columns), frame.astype(object).where(frame.notna(), None).values.tolist())
        data = renderers.render_xlsx(content, data_rows)
    else:
        data = renderers.render_csv(content)
    if report is None:
        report = Report(project_id=project.id, title=title[:300], created_by=user.id)
        db.add(report)
        db.flush()
    number = max((v.version_number for v in report.versions), default=0) + 1
    key = make_key("projects", project.id, "reports", report.id, filename=f"report_v{number}.{fmt}")
    get_storage().save(key, data)
    version = ReportVersion(report_id=report.id, version_number=number, format=fmt, storage_key=key, size_bytes=len(data),
                            content_json=content, created_by=user.id)
    db.add(version)
    db.flush()
    audit.record(db, action="report.generated", user_id=user.id, project_id=project.id, entity_type="report", entity_id=report.id,
                 details={"version": number, "format": fmt})
    db.commit()
    db.refresh(version)
    return version


def generate_client_package(db: Session, project: Project, user: User, *, title: str | None, dataset: Dataset | None,
                            references: list[str], deliverables: list[str], audience: str, length: str) -> tuple[bytes, list[dict]]:
    """The client package as a zip. Returns the readiness issues instead of a package when the gate refuses it."""
    content, images = build_report_content(db, project, user, title or f"{project.title}: research report", dataset, None)
    issues = gate.check(content, references=references)
    if issues:
        return b"", issues
    frame = _cleaned_frame(db, dataset)
    data = package.build(content, images, deliverables, frame=frame, references=references, audience=audience)
    audit.record(db, action="client_package.generated", user_id=user.id, project_id=project.id, entity_type="project", entity_id=project.id,
                 details={"deliverables": deliverables, "audience": audience})
    db.commit()
    return data, []
