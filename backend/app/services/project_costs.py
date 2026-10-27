"""Approximate costs of a project, entered by the researcher: one list of items in one currency.

Kept as a small JSON file in the project's storage, like the client and report details, because the database user the
app runs as cannot add columns. The total is always worked out from the items, never stored separately."""
from __future__ import annotations

import json

from app.services.storage import get_storage

EMPTY = {"currency": "USD", "items": []}


def storage_key(project_id: int) -> str:
    return f"projects/{project_id}/costs/costs.json"


def get(project_id: int) -> dict:
    storage = get_storage()
    key = storage_key(project_id)
    stored = json.loads(storage.load(key).decode("utf-8")) if storage.exists(key) else {}
    costs = {**EMPTY, **stored}
    return {**costs, "total": round(sum(item["amount"] for item in costs["items"]), 2)}


def put(project_id: int, currency: str, items: list[dict]) -> dict:
    get_storage().save(storage_key(project_id), json.dumps({"currency": currency, "items": items}).encode("utf-8"))
    return get(project_id)
