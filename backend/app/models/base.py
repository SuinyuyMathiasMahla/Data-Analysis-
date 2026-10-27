"""Column helpers shared by all models."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Integer

# BIGINT UNSIGNED in MySQL (see database/schema.sql); plain INTEGER in the
# SQLite database used by the tests so that AUTOINCREMENT works there.
ID = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    """Naive UTC timestamp (the schema stores all DATETIMEs in UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.replace(microsecond=0).isoformat() + "Z"
