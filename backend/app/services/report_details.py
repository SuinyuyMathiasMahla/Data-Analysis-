"""Details only the researcher can supply for the report: the background and literature review, the references,
and the ethics approval. Kept as a small JSON file in the project's storage, like the client details, because the
database user the app runs as cannot add columns."""
from __future__ import annotations

import json

from app.services.storage import get_storage

EMPTY = {"background": None, "references": [], "ethics_committee": None, "ethics_reference": None, "consent_method": None}


def storage_key(project_id: int) -> str:
    return f"projects/{project_id}/report/details.json"


def get(project_id: int) -> dict:
    storage = get_storage()
    key = storage_key(project_id)
    if not storage.exists(key):
        return dict(EMPTY)
    return {**EMPTY, **json.loads(storage.load(key).decode("utf-8"))}


def put(project_id: int, details: dict) -> None:
    get_storage().save(storage_key(project_id), json.dumps(details).encode("utf-8"))
