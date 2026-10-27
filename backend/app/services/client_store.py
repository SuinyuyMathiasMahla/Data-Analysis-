"""Client details of a client's project, kept as a small JSON file in the project's storage.

The database user the app runs as cannot add columns, so these details are not in the projects table.
A project without the file is a personal project."""
from __future__ import annotations

import json

from app.services.storage import get_storage

PERSONAL = {"project_type": "personal", "client_name": None, "client_email": None, "client_whatsapp": None}


def storage_key(project_id: int) -> str:
    return f"projects/{project_id}/client/details.json"


def get(project_id: int) -> dict:
    storage = get_storage()
    key = storage_key(project_id)
    if not storage.exists(key):
        return dict(PERSONAL)
    return {**PERSONAL, **json.loads(storage.load(key).decode("utf-8"))}


def put(project_id: int, details: dict) -> None:
    get_storage().save(storage_key(project_id), json.dumps(details).encode("utf-8"))
