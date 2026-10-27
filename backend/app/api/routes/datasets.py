"""Datasets: upload, preview, data dictionary, quality, cleaning, versions."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.orm import Session

from app.analysis import cleaning, profiling
from app.api.deps import READ, WRITE, get_current_user, get_dataset, get_project
from app.core.config import get_settings
from app.core.errors import ApiError, bad_request, not_found
from app.database.session import get_db
from app.models import DatasetVersion, Project, User, Variable
from app.schemas.requests import CleanIn, ManualDatasetIn, VariableIn
from app.services import ai_runtime, audit, dataset_service, project_service
from app.services.storage import get_storage, safe_name

router = APIRouter(tags=["datasets"])


@router.post("/projects/{project_id}/datasets", status_code=201)
async def upload_dataset(project_id: int, file: UploadFile = File(...), name: str | None = Form(None), description: str | None = Form(None),
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    limit = get_settings().MAX_UPLOAD_MB * 1024 * 1024
    content = await file.read(limit + 1)                    # never read more than the limit into memory
    if len(content) > limit:
        raise ApiError(413, "payload_too_large", f"The file is larger than the {get_settings().MAX_UPLOAD_MB} MB limit.")
    fmt = dataset_service.detect_format(file.filename, content)
    raw = profiling.read_raw(content, fmt)
    filename = safe_name(file.filename, f"dataset.{fmt}")
    dataset = dataset_service.create_dataset(db, project, user, name=(name or filename.rsplit(".", 1)[0])[:200], description=description,
                                             source_type=fmt, original_bytes=content, original_filename=filename, raw=raw)
    return _detail(db, dataset)


@router.post("/projects/{project_id}/datasets/manual", status_code=201)
def create_manual_dataset(project_id: int, body: ManualDatasetIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    raw = profiling.frame_from_manual(body.columns, body.rows)
    original = json.dumps({"columns": body.columns, "rows": body.rows}, default=str).encode("utf-8")
    dataset = dataset_service.create_dataset(db, project, user, name=body.name, description=body.description, source_type="manual",
                                             original_bytes=original, original_filename=None, raw=raw)
    return _detail(db, dataset)


@router.get("/projects/{project_id}/datasets")
def list_datasets(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    out = []
    for dataset in project_service.datasets_of(db, project.id):
        report = dataset_service.latest_quality_report(db, dataset.current_version_id) if dataset.current_version_id else None
        out.append({**dataset.to_dict(), "quality_score": float(report.score) if report else None})
    return {"datasets": out}


def _detail(db: Session, dataset) -> dict:
    report = dataset_service.latest_quality_report(db, dataset.current_version_id) if dataset.current_version_id else None
    return {**dataset.to_dict(with_versions=True), "quality_score": float(report.score) if report else None,
            "variables": dataset_service.data_dictionary(db, dataset)}


@router.get("/datasets/{dataset_id}")
def read_dataset(dataset_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dataset, _ = get_dataset(db, dataset_id, user, READ)
    return _detail(db, dataset)


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dataset, project = get_dataset(db, dataset_id, user, WRITE)
    keys = [v.storage_key for v in dataset.versions]
    audit.record(db, action="dataset.deleted", user_id=user.id, project_id=project.id, entity_type="dataset", entity_id=dataset.id,
                 details={"name": dataset.name})
    dataset.current_version_id = None
    db.flush()
    db.delete(dataset)
    db.commit()
    for key in keys:
        get_storage().delete(key)
    return {"message": "Dataset deleted."}


def _version(db: Session, dataset, version_id: int | None) -> DatasetVersion:
    if version_id is None:
        if dataset.current_version is None:
            raise not_found("Dataset version")
        return dataset.current_version
    version = db.get(DatasetVersion, version_id)
    if version is None or version.dataset_id != dataset.id:
        raise not_found("Dataset version")
    return version


@router.get("/datasets/{dataset_id}/preview")
def preview_dataset(dataset_id: int, offset: int = 0, limit: int = 50, version_id: int | None = None,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One page of rows. The browser never loads the full dataset."""
    dataset, _ = get_dataset(db, dataset_id, user, READ)
    version = _version(db, dataset, version_id)
    page = profiling.preview(dataset_service.load_raw(version), offset, limit)
    return {**page, "version": version.to_dict(), "schema": dataset_service.schema_for(db, version)}


@router.get("/datasets/{dataset_id}/download")
def download_dataset(dataset_id: int, version_id: int | None = None, original: bool = False, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Download the cleaned working copy as CSV, or the untouched original file."""
    dataset, project = get_dataset(db, dataset_id, user, READ)
    if original:
        version = next((v for v in dataset.versions if v.kind == "original"), None)
        if version is None:
            raise not_found("Original file")
        filename = dataset.original_filename or f"{safe_name(dataset.name)}.json"
        media = "application/octet-stream"
    else:
        version = _version(db, dataset, version_id)
        filename = f"{safe_name(dataset.name)}_v{version.version_number}.csv"
        media = "text/csv"
    audit.record(db, action="dataset.downloaded", user_id=user.id, project_id=project.id, entity_type="dataset", entity_id=dataset.id,
                 details={"version": version.version_number, "original": original})
    db.commit()
    return Response(get_storage().load(version.storage_key), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---- data dictionary ------------------------------------------------------------
@router.get("/datasets/{dataset_id}/dictionary")
def dictionary(dataset_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dataset, _ = get_dataset(db, dataset_id, user, READ)
    return {"variables": dataset_service.data_dictionary(db, dataset),
            "version": dataset.current_version.to_dict() if dataset.current_version else None}


@router.put("/variables/{variable_id}")
def update_variable(variable_id: int, body: VariableIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    variable = db.get(Variable, variable_id)
    if variable is None:
        raise not_found("Variable")
    dataset, project = get_dataset(db, variable.dataset_id, user, WRITE)
    changes = body.model_dump(exclude_unset=True)
    level = changes.get("measurement_level")
    if level in ("interval", "ratio") and variable.data_type not in ("numeric", "integer", "datetime"):
        raise bad_request("Only numeric or date variables can be interval or ratio level.")
    if changes.get("valid_min") is not None and changes.get("valid_max") is not None and changes["valid_min"] > changes["valid_max"]:
        raise bad_request("The minimum valid value is larger than the maximum.")
    for field, value in changes.items():
        if field in ("measurement_level", "role") and value is None:
            continue
        setattr(variable, field, value)
    audit.record(db, action="variable.updated", user_id=user.id, project_id=project.id, entity_type="variable", entity_id=variable.id,
                 details={"name": variable.name, "fields": sorted(changes)})
    db.commit()
    return {"variables": dataset_service.data_dictionary(db, dataset)}


# ---- quality ---------------------------------------------------------------------
@router.post("/datasets/{dataset_id}/quality-check")
def quality_check(dataset_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dataset, _ = get_dataset(db, dataset_id, user, WRITE)
    version = _version(db, dataset, None)
    report = dataset_service.run_quality_check(db, dataset, version, user)
    db.commit()
    db.refresh(report)
    return report.to_dict()


@router.get("/datasets/{dataset_id}/quality-report")
def quality_report(dataset_id: int, version_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dataset, _ = get_dataset(db, dataset_id, user, READ)
    version = _version(db, dataset, version_id)
    report = dataset_service.latest_quality_report(db, version.id)
    if report is None:
        raise not_found("Quality report (run a quality check first)")
    return report.to_dict()


# ---- cleaning ----------------------------------------------------------------------
@router.get("/cleaning/operations")
def cleaning_operations(_: User = Depends(get_current_user)):
    return {"operations": [{"key": key, "label": spec["label"], "removes_rows": spec["removes_rows"]} for key, spec in cleaning.OPERATIONS.items()]}


@router.post("/datasets/{dataset_id}/clean", status_code=201)
def clean_dataset(dataset_id: int, body: CleanIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dataset, _ = get_dataset(db, dataset_id, user, WRITE)
    entry = dataset_service.apply_cleaning(db, dataset, user, body.operation, body.params, body.reason)
    db.refresh(dataset)
    report = dataset_service.latest_quality_report(db, dataset.current_version_id)
    return {"operation": entry.to_dict(), "dataset": dataset.to_dict(), "quality_score": float(report.score) if report else None}


@router.post("/datasets/{dataset_id}/auto-clean")
def auto_clean_dataset(dataset_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Clean the data automatically until its quality score cannot be raised further. The AI assistant decides per column
    when a provider is configured; otherwise fixed rules do. Each step is a version; flagged decisions can be undone."""
    dataset, _ = get_dataset(db, dataset_id, user, WRITE)
    project = db.get(Project, dataset.project_id)

    def decide(facts):
        service = ai_runtime.get_ai_service(db)
        if not service.available:
            return None
        context = ai_runtime.project_context(db, project, dataset, focus={"missing_columns": facts})
        return service.decide_missing(context, facts)

    summary = dataset_service.auto_clean(db, dataset, user, decide)
    db.commit()
    db.refresh(dataset)
    return {**summary, "dataset": dataset.to_dict()}


@router.get("/datasets/{dataset_id}/auto-decisions")
def auto_decisions(dataset_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dataset, _ = get_dataset(db, dataset_id, user, READ)
    return {"decisions": dataset_service.decision_log(db, dataset)}


@router.post("/datasets/{dataset_id}/auto-decisions/{decision_id}/undo")
def undo_auto_decision(dataset_id: int, decision_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dataset, _ = get_dataset(db, dataset_id, user, WRITE)
    dataset_service.undo_decision(db, dataset, user, decision_id)
    db.commit()
    db.refresh(dataset)
    return {"dataset": dataset.to_dict(), "decisions": dataset_service.decision_log(db, dataset)}


@router.get("/datasets/{dataset_id}/cleaning-history")
def cleaning_history(dataset_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dataset, _ = get_dataset(db, dataset_id, user, READ)
    current_lineage = set(dataset_service.lineage(db, dataset.current_version)) if dataset.current_version else set()
    return {"operations": [{**op.to_dict(), "label": cleaning.OPERATIONS.get(op.operation, {}).get("label", op.operation),
                            "in_current_version": op.output_version_id in current_lineage}
                           for op in dataset_service.cleaning_history(db, dataset.id)],
            "versions": [v.to_dict() for v in dataset.versions], "current_version_id": dataset.current_version_id}


@router.post("/datasets/{dataset_id}/versions/{version_id}/restore")
def restore_version(dataset_id: int, version_id: int, reason: str = "Restored an earlier version", user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    dataset, _ = get_dataset(db, dataset_id, user, WRITE)
    version = _version(db, dataset, version_id)
    return dataset_service.restore_version(db, dataset, version, user, reason[:500]).to_dict(with_versions=True)
