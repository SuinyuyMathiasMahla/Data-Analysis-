"""File storage abstraction.

MySQL holds only metadata and a ``storage_key``; the bytes live behind this
interface. ``LocalStorage`` writes below STORAGE_DIR. To move to object storage
implement the same four methods (see ``S3Storage``) and set STORAGE_BACKEND -
no other code changes.
"""
from __future__ import annotations

import os
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import get_settings

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(filename: str | None, default: str = "file") -> str:
    """Strip directories and unusual characters from a user-supplied filename."""
    name = _SAFE.sub("_", os.path.basename(filename or "")).strip("._")
    return name[:120] or default


def make_key(*parts: object, filename: str) -> str:
    """Storage key such as ``projects/12/datasets/5/3f2a..._data.csv``. The
    random prefix means a key can never be guessed or collide."""
    return "/".join([*(str(p) for p in parts), f"{uuid.uuid4().hex}_{safe_name(filename)}"])


class Storage(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def load(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class LocalStorage(Storage):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root != path and self.root not in path.parents:      # path traversal guard
            raise ValueError("Invalid storage key")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)                                             # atomic on the same filesystem

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class S3Storage(Storage):
    """TODO (not implemented): Amazon S3 / S3-compatible storage.

    Implement the four methods with boto3 (put_object, get_object,
    delete_object, head_object) using a bucket name and credentials from the
    environment. Until then, selecting STORAGE_BACKEND=s3 fails loudly at
    start-up rather than silently writing somewhere else.
    """

    def __init__(self) -> None:
        raise NotImplementedError("STORAGE_BACKEND=s3 is not implemented yet. Use STORAGE_BACKEND=local.")

    def save(self, key: str, data: bytes) -> None: ...
    def load(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        settings = get_settings()
        _storage = S3Storage() if settings.STORAGE_BACKEND.lower() == "s3" else LocalStorage(settings.STORAGE_DIR)
    return _storage


def set_storage(storage: Storage | None) -> None:
    """Override the storage backend (used by tests)."""
    global _storage
    _storage = storage
