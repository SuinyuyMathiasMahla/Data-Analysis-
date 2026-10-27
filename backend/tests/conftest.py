"""Shared test configuration.

API tests run against an in-memory SQLite database (so the suite needs no
MySQL server), with analysis jobs executed inline and files written to a
temporary directory. Environment variables are set BEFORE the app is imported.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": "sqlite://",
    "ANALYSIS_SYNC": "true",
    "SECRET_KEY": "test-secret-key-test-secret-key-test-secret-key",
    "STORAGE_DIR": tempfile.mkdtemp(prefix="arda-test-storage-"),
    "AI_PROVIDER": "none",
    "RATE_LIMIT_AUTH_PER_MINUTE": "1000",
    "RATE_LIMIT_AI_PER_MINUTE": "1000",
})

import pytest  # noqa: E402

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "sample_data" / "student_performance.csv"
PASSWORD = "Str0ngPassword!x"

ROLE_PERMISSIONS = {
    "researcher": ["project.manage_own", "dataset.manage_own", "analysis.run_own", "report.manage_own", "ai.use"],
    "supervisor": ["ai.use", "review.view_assigned", "review.comment", "review.approve"],
    "admin": ["project.manage_own", "dataset.manage_own", "analysis.run_own", "report.manage_own", "ai.use", "review.view_assigned",
              "review.comment", "review.approve", "admin.users", "admin.settings", "admin.stats"],
}


@pytest.fixture()
def client():
    """A TestClient on a freshly created database with roles and permissions."""
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient

    from app.core.rate_limit import reset_rate_limits
    from app.database.session import Base, SessionLocal, engine
    from app.main import app
    from app.models import Permission, Role
    from app.services import ai_runtime, email
    from app.services.storage import get_storage

    with engine.connect() as connection:
        # datasets <-> dataset_versions reference each other, so tables cannot be dropped
        # in dependency order; switch SQLite's FK enforcement off while rebuilding the schema.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(connection)
        Base.metadata.create_all(connection)
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    with SessionLocal() as db:
        permissions = {code: Permission(code=code) for codes in ROLE_PERMISSIONS.values() for code in codes}
        db.add_all(permissions.values())
        for name, codes in ROLE_PERMISSIONS.items():
            role = Role(name=name)
            role.permissions = [permissions[c] for c in codes]
            db.add(role)
        db.commit()
    # the database is rebuilt for every test, so project files from earlier tests must go too (ids are reused)
    shutil.rmtree(get_storage().root / "projects", ignore_errors=True)
    reset_rate_limits()
    email.sent_messages.clear()
    ai_runtime.set_ai_service(None)
    with TestClient(app) as test_client:
        yield test_client


def register(client, email: str, name: str = "Test User") -> dict:
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD, "full_name": name,
                                                       "institution": "Test University", "academic_level": "masters"})
    assert response.status_code == 201, response.text
    return response.json()["user"]


def login(client, email: str, password: str = PASSWORD) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(client, email: str, name: str = "Test User") -> dict:
    """Register (if needed) and sign in; returns the Authorization header."""
    if client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code != 200:
        register(client, email, name)
    return {"Authorization": f"Bearer {login(client, email)['access_token']}"}


def grant_role(email: str, role: str) -> None:
    from sqlalchemy import select

    from app.database.session import SessionLocal
    from app.models import Role
    from app.services.auth_service import find_user

    with SessionLocal() as db:
        user = find_user(db, email)
        user.roles = [*user.roles, db.scalar(select(Role).where(Role.name == role))]
        db.commit()


def make_project(client, headers: dict, **overrides) -> dict:
    payload = {"title": "Impact of Social Media Use on Academic Performance", "academic_level": "masters", "research_field": "Education",
               "study_design": "Cross-sectional survey", "sampling_technique": "Convenience sampling",
               "data_collection_method": "Self-administered questionnaire", "research_methodology": "Quantitative",
               "objectives": ["Relate social media use to GPA"], **overrides}
    response = client.post("/api/projects", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def upload_sample(client, headers: dict, project_id: int) -> dict:
    with SAMPLE_CSV.open("rb") as handle:
        response = client.post(f"/api/projects/{project_id}/datasets", headers=headers,
                               files={"file": ("student_performance.csv", handle, "text/csv")}, data={"name": "Student survey"})
    assert response.status_code == 201, response.text
    return response.json()
