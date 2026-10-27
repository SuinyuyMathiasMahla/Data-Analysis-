"""Reports, project history, supervision and notifications."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.evidence import STAGES
from app.api.deps import READ, REVIEW, WRITE, get_current_user, get_project, get_report, project_rights
from app.core.errors import ApiError, bad_request, not_found
from app.database.session import get_db
from app.models import AuditLog, Notification, Report, ReviewComment, StageReview, User
from app.models.base import utcnow
from app.reports.renderers import RENDERERS, SECTION_TITLES
from app.schemas.requests import ClientPackageIn, CommentIn, ReportIn, StageReviewIn
from app.services import ai_runtime, audit, dataset_service, package_assistant, project_service, report_service
from app.services.storage import get_storage, safe_name

router = APIRouter(tags=["reports"])
_STAGE_KEYS = {key for key, _ in STAGES}


@router.get("/report-sections")
def report_sections(_: User = Depends(get_current_user)):
    return {"sections": [{"key": k, "title": t} for k, t in SECTION_TITLES], "formats": list(RENDERERS)}


@router.post("/projects/{project_id}/reports", status_code=201)
def create_report(project_id: int, body: ReportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    report = None
    if body.report_id is not None:
        report = db.get(Report, body.report_id)
        if report is None or report.project_id != project.id:
            raise not_found("Report")
    known = {k for k, _ in SECTION_TITLES}
    if body.sections and not set(body.sections) <= known:
        raise bad_request(f"Unknown section(s): {', '.join(sorted(set(body.sections) - known))}")
    dataset = project_service.primary_dataset(db, project.id, body.dataset_id)
    if body.dataset_id is not None and dataset is None:
        raise not_found("Dataset")
    version = report_service.generate_report(db, project, user, fmt=body.format, title=body.title, report=report, sections=body.sections,
                                             dataset=dataset, include_data=body.include_data)
    report = db.get(Report, version.report_id)
    db.refresh(report)
    return {**report.to_dict(), "latest_version": version.to_dict()}


@router.post("/projects/{project_id}/client-package")
def create_client_package(project_id: int, body: ClientPackageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One zip for a client. Refuses (422, with the blocking issues) until the readiness gate passes."""
    project = get_project(db, project_id, user, WRITE)
    dataset = project_service.primary_dataset(db, project.id, body.dataset_id)
    if body.dataset_id is not None and dataset is None:
        raise not_found("Dataset")
    ai = ai_runtime.get_ai_service(db)

    def decide(facts):
        # the same per-column decision the Clean data button uses
        if not ai.available:
            return None
        return ai.decide_missing(ai_runtime.project_context(db, project, dataset, focus={"missing_columns": facts}), facts)

    def explain(issues):
        if not ai.available:
            return None
        return ai.diagnose_issues(ai_runtime.project_context(db, project, dataset, focus={"blocking_issues": issues}), issues)

    # the assistant's pass: start what can run, clean what can be cleaned, then diagnose and assign each remaining issue
    result = package_assistant.resolve(db, project, user, dataset, ai, body.references,
                                       clean=(lambda: dataset_service.auto_clean(db, dataset, user, decide)) if dataset is not None else None,
                                       explain=explain)
    db.commit()
    if result["issues"]:
        raise ApiError(422, "readiness_failed",
                       f"{len(result['issues'])} item(s) must be resolved before the client package can be generated.",
                       details={"issues": result["issues"], "assistant_actions": result["actions"]})
    data, issues = report_service.generate_client_package(db, project, user, title=body.title, dataset=dataset,
                                                          references=body.references, deliverables=body.deliverables,
                                                          audience=body.audience, length=body.length)
    if issues:
        raise ApiError(422, "readiness_failed", f"{len(issues)} item(s) must be resolved before the client package can be generated.",
                       details={"issues": issues, "assistant_actions": result["actions"]})
    filename = f"{safe_name(body.title or project.title, 'client_package')}.zip"
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/projects/{project_id}/reports")
def list_reports(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    rows = db.scalars(select(Report).where(Report.project_id == project.id).order_by(Report.id.desc()))
    return {"reports": [r.to_dict() for r in rows]}


@router.get("/reports/{report_id}")
def read_report(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report, _ = get_report(db, report_id, user, READ)
    return report.to_dict()


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, version: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report, project = get_report(db, report_id, user, READ)
    if not report.versions:
        raise not_found("Report file")
    chosen = report.versions[-1] if version is None else next((v for v in report.versions if v.version_number == version), None)
    if chosen is None:
        raise not_found("Report version")
    media, ext = RENDERERS[chosen.format]
    audit.record(db, action="report.downloaded", user_id=user.id, project_id=project.id, entity_type="report", entity_id=report.id,
                 details={"version": chosen.version_number, "format": chosen.format})
    db.commit()
    filename = f"{safe_name(report.title, 'report')}_v{chosen.version_number}.{ext}"
    return Response(get_storage().load(chosen.storage_key), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/{report_id}/versions/{version}/content")
def report_content(report_id: int, version: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The frozen snapshot a report version was rendered from (for audit)."""
    report, _ = get_report(db, report_id, user, READ)
    chosen = next((v for v in report.versions if v.version_number == version), None)
    if chosen is None:
        raise not_found("Report version")
    return chosen.content_json


@router.delete("/reports/{report_id}")
def delete_report(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report, project = get_report(db, report_id, user, WRITE)
    keys = [v.storage_key for v in report.versions]
    audit.record(db, action="report.deleted", user_id=user.id, project_id=project.id, entity_type="report", entity_id=report.id,
                 details={"title": report.title})
    db.delete(report)
    db.commit()
    for key in keys:
        get_storage().delete(key)
    return {"message": "Report deleted."}


# ---- history ------------------------------------------------------------------
@router.get("/projects/{project_id}/history")
def project_history(project_id: int, limit: int = 100, offset: int = 0, action: str | None = None,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Chronological record of everything done in the project: uploads, cleaning,
    analysis runs, charts, AI interactions and report versions."""
    project = get_project(db, project_id, user, READ)
    query = select(AuditLog).where(AuditLog.project_id == project.id)
    if action:
        query = query.where(AuditLog.action.like(f"{action}%"))
    rows = db.scalars(query.order_by(AuditLog.id.desc()).offset(max(offset, 0)).limit(min(max(limit, 1), 500)))
    return {"history": [r.to_dict() for r in rows]}


# ---- supervision ---------------------------------------------------------------
@router.get("/projects/{project_id}/reviews")
def list_reviews(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    comments = db.scalars(select(ReviewComment).where(ReviewComment.project_id == project.id).order_by(ReviewComment.id.desc()))
    reviews = {r.stage: r.to_dict() for r in db.scalars(select(StageReview).where(StageReview.project_id == project.id))}
    return {"comments": [c.to_dict() for c in comments],
            "stages": [{"key": key, "label": label, **reviews.get(key, {"status": "pending", "note": None, "reviewer_name": None, "reviewed_at": None})}
                       for key, label in STAGES]}


@router.post("/projects/{project_id}/comments", status_code=201)
def add_comment(project_id: int, body: CommentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Owners, collaborators and supervisors can comment; viewers cannot."""
    project = get_project(db, project_id, user, READ)
    if not ({WRITE, REVIEW} & project_rights(db, project, user)):
        raise bad_request("Your role on this project does not allow commenting.", "forbidden")
    if body.stage not in _STAGE_KEYS:
        raise bad_request(f"Unknown stage. Use one of: {', '.join(sorted(_STAGE_KEYS))}")
    comment = ReviewComment(project_id=project.id, author_id=user.id, stage=body.stage, entity_type=body.entity_type,
                            entity_id=body.entity_id, body=body.body)
    db.add(comment)
    db.flush()
    audit.record(db, action="review.commented", user_id=user.id, project_id=project.id, entity_type="review_comment", entity_id=comment.id,
                 details={"stage": body.stage})
    if user.id != project.owner_id:
        audit.notify(db, user_id=project.owner_id, project_id=project.id, type="review",
                     title=f"{user.full_name} commented on '{project.title}' ({body.stage})", body=body.body[:500])
    db.commit()
    db.refresh(comment)
    return comment.to_dict()


@router.put("/projects/{project_id}/stage-review")
def review_stage(project_id: int, body: StageReviewIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Supervisor approves or rejects an analysis stage."""
    project = get_project(db, project_id, user, REVIEW)
    if body.stage not in _STAGE_KEYS:
        raise bad_request(f"Unknown stage. Use one of: {', '.join(sorted(_STAGE_KEYS))}")
    if body.status == "rejected" and not body.note:
        raise bad_request("Explain what needs to change when rejecting a stage.")
    review = db.scalar(select(StageReview).where(StageReview.project_id == project.id, StageReview.stage == body.stage))
    if review is None:
        review = StageReview(project_id=project.id, stage=body.stage)
        db.add(review)
    review.status, review.note, review.reviewer_id, review.reviewed_at = body.status, body.note, user.id, utcnow()
    audit.record(db, action=f"review.stage_{body.status}", user_id=user.id, project_id=project.id, details={"stage": body.stage, "note": body.note})
    if user.id != project.owner_id:
        audit.notify(db, user_id=project.owner_id, project_id=project.id, type="review",
                     title=f"Stage '{body.stage}' was {body.status} by {user.full_name}", body=body.note)
    db.commit()
    db.refresh(review)
    return review.to_dict()


# ---- notifications ---------------------------------------------------------------
@router.get("/notifications")
def notifications(unread_only: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    rows = list(db.scalars(query.order_by(Notification.id.desc()).limit(50)))
    unread = sum(1 for r in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))))
    return {"notifications": [r.to_dict() for r in rows], "unread": unread}


@router.post("/notifications/read")
def mark_notifications_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for row in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))):
        row.is_read = True
    db.commit()
    return {"message": "Notifications marked as read."}
