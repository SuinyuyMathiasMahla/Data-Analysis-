"""System administration: users, roles, settings, activity and statistics."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.errors import bad_request, not_found
from app.database.session import get_db
from app.models import AnalysisRun, AuditLog, Dataset, Project, Report, Role, SystemSetting, User
from app.schemas.requests import AdminUserIn, SettingIn
from app.services import ai_runtime, audit, auth_service

router = APIRouter(prefix="/admin", tags=["admin"])
# Only these keys may be changed through the API. Secrets (API keys, passwords) are never settings.
EDITABLE_SETTINGS = {"ai.enabled": bool, "ai.provider_override": (str, type(None)), "uploads.max_mb": int}


@router.get("/users")
def list_users(search: str | None = None, limit: int = 100, offset: int = 0, _: User = Depends(require_permission("admin.users")),
               db: Session = Depends(get_db)):
    query = select(User)
    if search:
        like = f"%{search.strip().lower()}%"
        query = query.where(func.lower(User.email).like(like) | func.lower(User.full_name).like(like))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(User.id).offset(max(offset, 0)).limit(min(max(limit, 1), 500)))
    return {"users": [u.to_dict() for u in rows], "total": total}


@router.put("/users/{user_id}")
def update_user(user_id: int, body: AdminUserIn, admin: User = Depends(require_permission("admin.users")), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise not_found("User")
    changes = body.model_dump(exclude_unset=True)
    if target.id == admin.id and (changes.get("is_active") is False or ("roles" in changes and "admin" not in (changes["roles"] or []))):
        raise bad_request("You cannot deactivate your own account or remove your own admin role.")
    if changes.get("is_active") is not None:
        target.is_active = changes["is_active"]
        if not target.is_active:
            auth_service.revoke_all_sessions(db, target.id)
    if changes.get("roles") is not None:
        if not changes["roles"]:
            raise bad_request("A user needs at least one role.")
        target.roles = list(db.scalars(select(Role).where(Role.name.in_(changes["roles"]))))
    audit.record(db, action="admin.user_updated", user_id=admin.id, entity_type="user", entity_id=target.id, details=changes)
    db.commit()
    db.refresh(target)
    return target.to_dict()


@router.get("/roles")
def list_roles(_: User = Depends(require_permission("admin.users")), db: Session = Depends(get_db)):
    return {"roles": [{"id": r.id, "name": r.name, "description": r.description, "permissions": sorted(p.code for p in r.permissions)}
                      for r in db.scalars(select(Role).order_by(Role.id))]}


@router.get("/stats")
def system_stats(_: User = Depends(require_permission("admin.stats")), db: Session = Depends(get_db)):
    def count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0
    by_level = dict(db.execute(select(Project.academic_level, func.count()).group_by(Project.academic_level)).all())
    by_status = dict(db.execute(select(AnalysisRun.status, func.count()).group_by(AnalysisRun.status)).all())
    return {"users": count(User), "active_users": count(User, User.is_active.is_(True)), "projects": count(Project),
            "projects_by_level": by_level, "datasets": count(Dataset), "analysis_runs": count(AnalysisRun),
            "analysis_runs_by_status": by_status, "reports": count(Report), "ai": ai_runtime.get_ai_service(db).status()}


@router.get("/activity")
def system_activity(limit: int = 100, action: str | None = None, _: User = Depends(require_permission("admin.stats")),
                    db: Session = Depends(get_db)):
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action.like(f"{action}%"))
    rows = db.scalars(query.order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 500)))
    return {"activity": [r.to_dict() for r in rows]}


@router.get("/settings")
def list_settings(_: User = Depends(require_permission("admin.settings")), db: Session = Depends(get_db)):
    stored = {s.setting_key: s.value_json for s in db.scalars(select(SystemSetting))}
    return {"settings": {key: stored.get(key) for key in EDITABLE_SETTINGS}, "ai": ai_runtime.get_ai_service(db).status(),
            "note": "API keys and other secrets are configured in the server environment (.env), never here."}


@router.put("/settings/{key}")
def update_setting(key: str, body: SettingIn, admin: User = Depends(require_permission("admin.settings")), db: Session = Depends(get_db)):
    if key not in EDITABLE_SETTINGS:
        raise not_found("Setting")
    if not isinstance(body.value, EDITABLE_SETTINGS[key]) or (EDITABLE_SETTINGS[key] is int and isinstance(body.value, bool)):
        raise bad_request(f"Invalid value for {key}.")
    if key == "ai.provider_override" and body.value not in (None, "none", "openai", "gemini", "anthropic", "local"):
        raise bad_request("Provider must be none, openai, gemini, anthropic or local.")
    if key == "uploads.max_mb" and not 1 <= body.value <= 500:
        raise bad_request("uploads.max_mb must be between 1 and 500.")
    row = db.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(setting_key=key, value_json=body.value)
        db.add(row)
    row.value_json, row.updated_by = body.value, admin.id
    audit.record(db, action="admin.setting_updated", user_id=admin.id, details={"key": key, "value": body.value})
    db.commit()
    return {"key": key, "value": row.value_json}
