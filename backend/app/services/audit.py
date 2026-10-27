"""Audit trail and notifications."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog, Notification


def record(db: Session, *, action: str, user_id: int | None = None, project_id: int | None = None, entity_type: str | None = None,
           entity_id: int | None = None, details: dict | None = None, ip: str | None = None) -> AuditLog:
    """Append one history entry. The caller commits."""
    entry = AuditLog(action=action, user_id=user_id, project_id=project_id, entity_type=entity_type, entity_id=entity_id,
                     details_json=details or {}, ip_address=ip)
    db.add(entry)
    return entry


def notify(db: Session, *, user_id: int, title: str, type: str = "info", body: str | None = None, project_id: int | None = None) -> None:
    db.add(Notification(user_id=user_id, project_id=project_id, type=type, title=title[:255], body=body))
