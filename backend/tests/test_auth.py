"""Accounts, sessions and access control."""
import pytest

from tests.conftest import PASSWORD, auth_headers, grant_role, login, make_project, register


def test_register_login_and_profile(client):
    user = register(client, "ada@example.org", "Ada Lovelace")
    assert user["roles"] == ["researcher"] and user["is_email_verified"] is False
    tokens = login(client, "ADA@example.org")                       # e-mail is case-insensitive
    assert tokens["token_type"] == "bearer" and tokens["refresh_token"]
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/users/me", headers=headers).json()
    assert me["email"] == "ada@example.org" and "password_hash" not in me
    updated = client.put("/api/users/me", json={"department": "Mathematics"}, headers=headers).json()
    assert updated["department"] == "Mathematics"


def test_passwords_are_hashed_with_argon2(client):
    from app.database.session import SessionLocal
    from app.services.auth_service import find_user

    register(client, "hash@example.org")
    with SessionLocal() as db:
        stored = find_user(db, "hash@example.org").password_hash
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


def test_registration_validation(client):
    weak = client.post("/api/auth/register", json={"email": "w@example.org", "password": "alllowercase1", "full_name": "Weak"})
    assert weak.status_code == 400 and weak.json()["error"]["code"] == "weak_password"
    bad_email = client.post("/api/auth/register", json={"email": "not-an-email", "password": PASSWORD, "full_name": "X Y"})
    assert bad_email.status_code == 422 and bad_email.json()["error"]["code"] == "validation_error"
    register(client, "dup@example.org")
    again = client.post("/api/auth/register", json={"email": "dup@example.org", "password": PASSWORD, "full_name": "Dup"})
    assert again.status_code == 409


def test_wrong_password_and_lockout(client):
    register(client, "lock@example.org")
    for _ in range(5):
        response = client.post("/api/auth/login", json={"email": "lock@example.org", "password": "Wrong-password1"})
        assert response.status_code == 401 and response.json()["error"]["code"] == "invalid_credentials"
    locked = client.post("/api/auth/login", json={"email": "lock@example.org", "password": PASSWORD})
    assert locked.status_code == 423
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.org", "password": PASSWORD})
    assert unknown.status_code == 401                               # same answer as a wrong password


def test_protected_routes_require_a_valid_token(client):
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get("/api/health").status_code == 200


def test_refresh_rotation_and_reuse_detection(client):
    register(client, "rot@example.org")
    first = login(client, "rot@example.org")
    second = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200 and second.json()["refresh_token"] != first["refresh_token"]
    # replaying the old token is treated as theft: it fails and revokes the newer session too
    assert client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}).status_code == 401


def test_logout_revokes_the_session(client):
    register(client, "out@example.org")
    tokens = login(client, "out@example.org")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/api/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_password_reset_flow(client):
    from app.services import email

    register(client, "reset@example.org")
    old_session = login(client, "reset@example.org")
    email.sent_messages.clear()
    assert client.post("/api/auth/forgot-password", json={"email": "reset@example.org"}).status_code == 200
    assert client.post("/api/auth/forgot-password", json={"email": "ghost@example.org"}).status_code == 200   # no account enumeration
    assert len(email.sent_messages) == 1
    token = email.sent_messages[0]["body"].split("token=")[1].split()[0]
    new_password = "An0ther-Strong-Pass"
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": new_password}).status_code == 200
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": new_password}).status_code == 400   # single use
    assert client.post("/api/auth/login", json={"email": "reset@example.org", "password": PASSWORD}).status_code == 401
    assert login(client, "reset@example.org", new_password)["access_token"]
    assert client.post("/api/auth/refresh", json={"refresh_token": old_session["refresh_token"]}).status_code == 401


def test_email_verification(client):
    from app.services import email

    register(client, "verify@example.org")
    token = email.sent_messages[-1]["body"].split("token=")[1].split()[0]
    response = client.post("/api/auth/verify-email", json={"token": token})
    assert response.status_code == 200 and response.json()["user"]["is_email_verified"] is True


def test_users_cannot_see_each_others_projects(client):
    alice = auth_headers(client, "alice@example.org", "Alice")
    bob = auth_headers(client, "bob@example.org", "Bob")
    project = make_project(client, alice)
    assert client.get(f"/api/projects/{project['id']}", headers=alice).status_code == 200
    assert client.get(f"/api/projects/{project['id']}", headers=bob).status_code == 404          # existence is not revealed
    assert client.put(f"/api/projects/{project['id']}", json={"title": "Hijacked"}, headers=bob).status_code == 404
    assert client.delete(f"/api/projects/{project['id']}", headers=bob).status_code == 404
    assert client.get("/api/projects", headers=bob).json()["projects"] == []
    assert client.get(f"/api/projects/{project['id']}/history", headers=bob).status_code == 404


def test_supervisor_can_review_but_not_edit(client):
    owner = auth_headers(client, "owner@example.org", "Owner")
    register(client, "prof@example.org", "Professor")
    grant_role("prof@example.org", "supervisor")
    prof = {"Authorization": f"Bearer {login(client, 'prof@example.org')['access_token']}"}
    project = make_project(client, owner)
    pid = project["id"]
    assert client.get(f"/api/projects/{pid}", headers=prof).status_code == 404                    # not assigned yet
    added = client.post(f"/api/projects/{pid}/members", json={"email": "prof@example.org", "member_role": "supervisor"}, headers=owner)
    assert added.status_code == 201
    assert client.get(f"/api/projects/{pid}", headers=prof).status_code == 200
    assert client.put(f"/api/projects/{pid}", json={"title": "Changed by supervisor"}, headers=prof).status_code == 403
    comment = client.post(f"/api/projects/{pid}/comments", json={"stage": "analysis", "body": "Check the normality assumption."}, headers=prof)
    assert comment.status_code == 201
    assert client.put(f"/api/projects/{pid}/stage-review", json={"stage": "analysis", "status": "rejected"}, headers=prof).status_code == 400
    review = client.put(f"/api/projects/{pid}/stage-review", json={"stage": "analysis", "status": "rejected", "note": "Use Welch's test."}, headers=prof)
    assert review.status_code == 200 and review.json()["status"] == "rejected"
    assert client.put(f"/api/projects/{pid}/stage-review", json={"stage": "analysis", "status": "approved"}, headers=owner).status_code == 200  # owner has all rights
    notes = client.get("/api/notifications", headers=owner).json()
    assert notes["unread"] >= 2


def test_admin_endpoints_are_restricted(client):
    user = auth_headers(client, "plain@example.org")
    assert client.get("/api/admin/users", headers=user).status_code == 403
    register(client, "root@example.org", "Root")
    grant_role("root@example.org", "admin")
    admin = {"Authorization": f"Bearer {login(client, 'root@example.org')['access_token']}"}
    users = client.get("/api/admin/users", headers=admin).json()
    assert users["total"] == 2
    target = next(u for u in users["users"] if u["email"] == "plain@example.org")
    assert client.put(f"/api/admin/users/{target['id']}", json={"is_active": False}, headers=admin).status_code == 200
    assert client.get("/api/projects", headers=user).status_code == 401                         # deactivated account is locked out at once
    assert client.put("/api/admin/settings/ai.enabled", json={"value": False}, headers=admin).status_code == 200
    assert client.put("/api/admin/settings/SECRET_KEY", json={"value": "x"}, headers=admin).status_code == 404
    assert client.get("/api/admin/stats", headers=admin).json()["users"] == 2


@pytest.mark.parametrize("filename,content,code", [
    ("data.exe", b"MZ\x90\x00", "unsupported_file_type"),
    ("data.xlsx", b"this is not a zip archive", "invalid_file_content"),
    ("data.csv", b"", "empty_file"),
])
def test_upload_validation(client, filename, content, code):
    headers = auth_headers(client, "up@example.org")
    project = make_project(client, headers)
    response = client.post(f"/api/projects/{project['id']}/datasets", headers=headers, files={"file": (filename, content, "application/octet-stream")})
    assert response.status_code == 400 and response.json()["error"]["code"] == code


def test_deleting_a_project_removes_its_data_and_files(client):
    from tests.conftest import upload_sample
    from app.services.storage import get_storage

    headers = auth_headers(client, "del@example.org")
    project = make_project(client, headers)
    dataset = upload_sample(client, headers, project["id"])
    from app.database.session import SessionLocal
    from app.models import DatasetVersion
    with SessionLocal() as db:
        keys = [v.storage_key for v in db.query(DatasetVersion).filter(DatasetVersion.dataset_id == dataset["id"])]
    assert keys and all(get_storage().exists(k) for k in keys)
    assert client.delete(f"/api/projects/{project['id']}", headers=headers).status_code == 200
    assert client.get(f"/api/datasets/{dataset['id']}", headers=headers).status_code == 404
    assert not any(get_storage().exists(k) for k in keys)
