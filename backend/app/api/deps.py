"""Shared FastAPI dependencies: authentication and project-level access control."""
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, forbidden, not_found
from app.core.security import decode_access_token
from app.database.session import get_db
from app.models import (AnalysisResult, AnalysisRun, Dataset, DatasetVersion, Project, ProjectMember, Report, User,
                        Visualization)

_bearer = HTTPBearer(auto_error=False)

# what each project membership may do
READ, WRITE, REVIEW = "read", "write", "review"
_MEMBER_RIGHTS = {"collaborator": {READ, WRITE}, "supervisor": {READ, REVIEW}, "viewer": {READ}}


def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
                     db: Session = Depends(get_db)) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "unauthorized", "Sign in to continue.")
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise ApiError(401, "token_invalid", "Your session has expired. Please sign in again.")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise ApiError(401, "unauthorized", "This account is not active.")
    request.state.user_id = user.id
    return user


def require_permission(code: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if code not in user.permission_codes:
            raise forbidden()
        return user
    return dependency


def project_rights(db: Session, project: Project, user: User) -> set[str]:
    """Rights of ``user`` on ``project``. Empty set = no access at all."""
    if project.owner_id == user.id or user.is_admin:
        return {READ, WRITE, REVIEW}
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id))
    return set(_MEMBER_RIGHTS.get(member.member_role, set())) if member else set()


def get_project(db: Session, project_id: int, user: User, right: str = READ) -> Project:
    """Load a project the user may access. A project the user has no access to
    is reported as 'not found' so that its existence is not revealed."""
    project = db.get(Project, project_id)
    if project is None:
        raise not_found("Project")
    rights = project_rights(db, project, user)
    if not rights:
        raise not_found("Project")
    if right not in rights:
        raise forbidden("Your role on this project does not allow this action.")
    return project


def get_dataset(db: Session, dataset_id: int, user: User, right: str = READ) -> tuple[Dataset, Project]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise not_found("Dataset")
    return dataset, get_project(db, dataset.project_id, user, right)


def get_version(db: Session, version_id: int, user: User, right: str = READ) -> tuple[DatasetVersion, Dataset, Project]:
    version = db.get(DatasetVersion, version_id)
    if version is None:
        raise not_found("Dataset version")
    dataset, project = get_dataset(db, version.dataset_id, user, right)
    return version, dataset, project


def get_run(db: Session, run_id: int, user: User, right: str = READ) -> tuple[AnalysisRun, Project]:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise not_found("Analysis")
    return run, get_project(db, run.project_id, user, right)


def get_result(db: Session, result_id: int, user: User, right: str = READ) -> tuple[AnalysisResult, AnalysisRun, Project]:
    result = db.get(AnalysisResult, result_id)
    if result is None:
        raise not_found("Analysis result")
    run, project = get_run(db, result.analysis_run_id, user, right)
    return result, run, project


def get_visualization(db: Session, viz_id: int, user: User, right: str = READ) -> tuple[Visualization, Project]:
    viz = db.get(Visualization, viz_id)
    if viz is None:
        raise not_found("Visualization")
    return viz, get_project(db, viz.project_id, user, right)


def get_report(db: Session, report_id: int, user: User, right: str = READ) -> tuple[Report, Project]:
    report = db.get(Report, report_id)
    if report is None:
        raise not_found("Report")
    return report, get_project(db, report.project_id, user, right)


def owned(db: Session, model, entity_id: int | None, project_id: int, what: str):
    """Load a child entity and make sure it belongs to the given project."""
    if entity_id is None:
        return None
    entity = db.get(model, entity_id)
    if entity is None or entity.project_id != project_id:
        raise not_found(what)
    return entity
