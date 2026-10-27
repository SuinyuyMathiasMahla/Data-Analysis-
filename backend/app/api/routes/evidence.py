"""Findings, conclusions, recommendations and limitations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import READ, WRITE, get_current_user, get_project, get_result, owned
from app.core.config import get_settings
from app.core.errors import bad_request, not_found
from app.core.rate_limit import check_rate
from app.database.session import get_db
from app.models import AnalysisResult, AnalysisRun, Conclusion, Finding, Hypothesis, Limitation, Recommendation, ResearchQuestion, User
from app.schemas.requests import (AutoEvidenceIn, FindingFromResultIn, FindingIn, FindingUpdateIn, GenerateIn, LimitationIn, LimitationStatusIn,
                                  TextItemIn)
from app.services import ai_runtime, audit, automatic_evidence, evidence_service

router = APIRouter(tags=["evidence"])


def _guard(request: Request, user: User) -> None:
    if "ai.use" not in user.permission_codes:
        raise bad_request("Your account is not allowed to use the AI assistant.", "forbidden")
    check_rate(f"ai:{user.id}", get_settings().RATE_LIMIT_AI_PER_MINUTE)


@router.post("/projects/{project_id}/evidence/auto", status_code=201)
def auto_evidence(project_id: int, body: AutoEvidenceIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Workflow steps 9 and 10: findings for every completed analysis, then conclusions and recommendations from them.
    Safe to call repeatedly; it only adds what is missing unless regenerate is set."""
    _guard(request, user)
    project = get_project(db, project_id, user, WRITE)
    summary = automatic_evidence.auto_evidence(db, project, user, ai_runtime.get_ai_service(db), regenerate=body.regenerate)
    return {**summary, "findings": [f.to_dict() for f in evidence_service.list_findings(db, project.id)]}


# ---- findings -----------------------------------------------------------------
@router.get("/projects/{project_id}/findings")
def list_findings(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    return {"findings": [f.to_dict() for f in evidence_service.list_findings(db, project.id)]}


@router.post("/projects/{project_id}/findings/from-result", status_code=201)
def finding_from_result(project_id: int, body: FindingFromResultIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Draft a finding from a statistical result (engine text, editable afterwards)."""
    project = get_project(db, project_id, user, WRITE)
    result, _run, result_project = get_result(db, body.analysis_result_id, user, READ)
    if result_project.id != project.id:
        raise not_found("Analysis result")
    return evidence_service.finding_from_result(db, project, user, result, body.research_question_id, body.hypothesis_id).to_dict()


def _check_links(db: Session, project_id: int, body: FindingIn) -> None:
    owned(db, ResearchQuestion, body.research_question_id, project_id, "Research question")
    owned(db, Hypothesis, body.hypothesis_id, project_id, "Hypothesis")
    if body.analysis_result_id is not None:
        result = db.get(AnalysisResult, body.analysis_result_id)
        run = db.get(AnalysisRun, result.analysis_run_id) if result else None
        if run is None or run.project_id != project_id:
            raise not_found("Analysis result")


@router.post("/projects/{project_id}/findings", status_code=201)
def create_finding(project_id: int, body: FindingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    _check_links(db, project.id, body)
    finding = Finding(project_id=project.id, source="manual", created_by=user.id, **body.model_dump())
    db.add(finding)
    db.flush()
    audit.record(db, action="finding.created", user_id=user.id, project_id=project.id, entity_type="finding", entity_id=finding.id)
    db.commit()
    db.refresh(finding)
    return finding.to_dict()


@router.put("/findings/{finding_id}")
def update_finding(finding_id: int, body: FindingUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise not_found("Finding")
    project = get_project(db, finding.project_id, user, WRITE)
    _check_links(db, project.id, body)
    changes = body.model_dump(exclude_unset=True)
    for field in ("title", "statement", "confidence_level"):
        if field in changes and changes[field] is None:
            changes.pop(field)
    text_changed = any(changes.get(f) is not None and changes[f] != getattr(finding, f) for f in ("title", "statement", "interpretation", "statistical_evidence"))
    for field, value in changes.items():
        setattr(finding, field, value)
    if text_changed and finding.source != "manual":
        finding.is_edited = True               # the report states which drafts the researcher edited
    audit.record(db, action="finding.updated", user_id=user.id, project_id=project.id, entity_type="finding", entity_id=finding.id,
                 details={"fields": sorted(changes)})
    db.commit()
    db.refresh(finding)
    return finding.to_dict()


@router.delete("/findings/{finding_id}")
def delete_finding(finding_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise not_found("Finding")
    project = get_project(db, finding.project_id, user, WRITE)
    audit.record(db, action="finding.deleted", user_id=user.id, project_id=project.id, entity_type="finding", entity_id=finding.id,
                 details={"title": finding.title, "statement": finding.statement})
    db.delete(finding)
    db.commit()
    return {"message": "Finding deleted."}


# ---- conclusions and recommendations (same shape) -------------------------------
def _ai_rewrite(db: Session, project, kind: str, items: list, user: User) -> dict | None:
    """Optionally let the configured LLM rewrite engine drafts as prose. The
    reply is returned for the researcher to review; it is not saved automatically."""
    service = ai_runtime.get_ai_service(db)
    findings = [f.to_dict() for f in evidence_service.list_findings(db, project.id)]
    draft = "\n".join(f"{i + 1}. {item.text}" for i, item in enumerate(items))
    context = ai_runtime.project_context(db, project, focus={"findings": findings, f"engine_draft_{kind}": draft})
    reply = service.draft_section(context, kind, draft)
    audit.record(db, action=f"ai.draft_{kind}", user_id=user.id, project_id=project.id, details={"source": reply.source})
    db.commit()
    return reply.as_dict()


def _register(model, plural: str, label: str, generator) -> None:
    @router.get(f"/projects/{{project_id}}/{plural}", name=f"list_{plural}")
    def list_items(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        project = get_project(db, project_id, user, READ)
        rows = db.scalars(select(model).where(model.project_id == project.id).order_by(model.position, model.id))
        return {plural: [r.to_dict() for r in rows]}

    @router.post(f"/projects/{{project_id}}/{plural}/generate", status_code=201, name=f"generate_{plural}")
    def generate(project_id: int, body: GenerateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        project = get_project(db, project_id, user, WRITE)
        items = generator(db, project, user, body.replace_engine_drafts)
        out = {plural: [i.to_dict() for i in items], "ai_draft": None}
        if body.use_ai:
            out["ai_draft"] = _ai_rewrite(db, project, plural, items, user)
        return out

    @router.post(f"/projects/{{project_id}}/{plural}", status_code=201, name=f"create_{plural}")
    def create(project_id: int, body: TextItemIn, source: str = "manual", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        project = get_project(db, project_id, user, WRITE)
        if source not in ("manual", "ai"):
            raise bad_request("source must be manual or ai.")
        count = len(list(db.scalars(select(model.id).where(model.project_id == project.id))))
        item = model(project_id=project.id, text=body.text, source=source, position=count)
        if hasattr(item, "audience"):
            item.audience = body.audience
        item.findings = evidence_service._findings_by_ids(db, project.id, body.finding_ids)
        db.add(item)
        db.flush()
        audit.record(db, action=f"{label}.created", user_id=user.id, project_id=project.id, entity_type=label, entity_id=item.id)
        db.commit()
        db.refresh(item)
        return item.to_dict()

    @router.put(f"/{plural}/{{item_id}}", name=f"update_{plural}")
    def update(item_id: int, body: TextItemIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        item = db.get(model, item_id)
        if item is None:
            raise not_found(label.capitalize())
        project = get_project(db, item.project_id, user, WRITE)
        if body.text != item.text and item.source in ("engine", "ai"):
            item.source = "manual"          # the researcher's own wording is kept when automatic drafts are rewritten
        item.text = body.text
        if hasattr(item, "audience"):
            item.audience = body.audience
        item.findings = evidence_service._findings_by_ids(db, project.id, body.finding_ids)
        audit.record(db, action=f"{label}.updated", user_id=user.id, project_id=project.id, entity_type=label, entity_id=item.id)
        db.commit()
        db.refresh(item)
        return item.to_dict()

    @router.delete(f"/{plural}/{{item_id}}", name=f"delete_{plural}")
    def delete(item_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        item = db.get(model, item_id)
        if item is None:
            raise not_found(label.capitalize())
        project = get_project(db, item.project_id, user, WRITE)
        audit.record(db, action=f"{label}.deleted", user_id=user.id, project_id=project.id, entity_type=label, entity_id=item.id,
                     details={"text": item.text})
        db.delete(item)
        db.commit()
        return {"message": f"{label.capitalize()} deleted."}


_register(Conclusion, "conclusions", "conclusion", evidence_service.generate_conclusions)
_register(Recommendation, "recommendations", "recommendation", evidence_service.generate_recommendations)


# ---- limitations ------------------------------------------------------------------
@router.get("/projects/{project_id}/limitations")
def list_limitations(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    rows = db.scalars(select(Limitation).where(Limitation.project_id == project.id).order_by(Limitation.id))
    return {"limitations": [r.to_dict() for r in rows]}


@router.post("/projects/{project_id}/limitations/detect", status_code=201)
def detect_limitations(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    return {"limitations": [r.to_dict() for r in evidence_service.detect_limitations(db, project, user)]}


@router.post("/projects/{project_id}/limitations", status_code=201)
def create_limitation(project_id: int, body: LimitationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    item = Limitation(project_id=project.id, category=body.category, description=body.description, source="manual")
    db.add(item)
    db.commit()
    db.refresh(item)
    return item.to_dict()


@router.put("/limitations/{limitation_id}/status")
def set_limitation_status(limitation_id: int, body: LimitationStatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A limitation is never silently dropped: changing its status away from
    'active' requires a written justification, and the report shows both."""
    item = db.get(Limitation, limitation_id)
    if item is None:
        raise not_found("Limitation")
    project = get_project(db, item.project_id, user, WRITE)
    if body.status != "active" and not body.status_note:
        raise bad_request("Explain why this limitation is acknowledged or does not apply.")
    item.status, item.status_note = body.status, body.status_note
    audit.record(db, action="limitation.status_changed", user_id=user.id, project_id=project.id, entity_type="limitation", entity_id=item.id,
                 details={"status": body.status, "note": body.status_note})
    db.commit()
    return item.to_dict()


@router.delete("/limitations/{limitation_id}")
def delete_limitation(limitation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(Limitation, limitation_id)
    if item is None:
        raise not_found("Limitation")
    project = get_project(db, item.project_id, user, WRITE)
    if item.source != "manual":
        raise bad_request("Automatically detected limitations cannot be deleted. Mark it 'not applicable' with a justification instead.")
    audit.record(db, action="limitation.deleted", user_id=user.id, project_id=project.id, entity_type="limitation", entity_id=item.id,
                 details={"description": item.description})
    db.delete(item)
    db.commit()
    return {"message": "Limitation deleted."}
