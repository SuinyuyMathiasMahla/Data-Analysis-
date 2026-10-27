"""A fingerprint of what the automatic conclusions and recommendations were last written from, kept as a small JSON file in the
project's storage.

It lets the platform tell whether the findings or the analysis status have changed since they were written, so they are
rewritten only when needed. It is not stored in the database because the database user cannot change the schema.

Conclusions and recommendations update different keys of the same file, so changes are merged under a lock. Without it, two
updates that read the file before either wrote it would overwrite each other's keys. The lock is per process, which is enough
for the single-server deployment this app targets; several server processes would need a shared lock or a database table."""
from __future__ import annotations

import json
import threading

from app.services.storage import get_storage

_lock = threading.Lock()


def storage_key(project_id: int) -> str:
    return f"projects/{project_id}/evidence/state.json"


def get(project_id: int) -> dict:
    storage = get_storage()
    key = storage_key(project_id)
    return json.loads(storage.load(key).decode("utf-8")) if storage.exists(key) else {}


def put(project_id: int, state: dict) -> None:
    get_storage().save(storage_key(project_id), json.dumps(state).encode("utf-8"))


def merge(project_id: int, changes: dict) -> None:
    """Set the given keys and keep every other key as it is, even when another update was made since this one started."""
    with _lock:
        state = get(project_id)
        state.update(changes)
        put(project_id, state)
