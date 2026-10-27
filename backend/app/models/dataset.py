"""Datasets, immutable versions, the data dictionary, quality and cleaning."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import ID, iso, utcnow


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    data_kind: Mapped[str] = mapped_column(String(20), default="quantitative", nullable=False)
    source_type: Mapped[str] = mapped_column(String(10), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    current_version_id: Mapped[int | None] = mapped_column(ID, ForeignKey("dataset_versions.id", ondelete="SET NULL", use_alter=True,
                                                                          name="fk_datasets_current_version"))
    created_by: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    versions: Mapped[list["DatasetVersion"]] = relationship(foreign_keys="DatasetVersion.dataset_id", cascade="all, delete-orphan",
                                                            order_by="DatasetVersion.version_number", lazy="selectin")
    current_version: Mapped[Optional["DatasetVersion"]] = relationship(foreign_keys=[current_version_id], post_update=True, lazy="joined")

    def to_dict(self, with_versions: bool = False) -> dict:
        cv = self.current_version
        data = {"id": self.id, "project_id": self.project_id, "name": self.name, "description": self.description,
                "data_kind": self.data_kind, "source_type": self.source_type, "original_filename": self.original_filename,
                "current_version_id": self.current_version_id, "current_version_number": cv.version_number if cv else None,
                "row_count": cv.row_count if cv else None, "column_count": cv.column_count if cv else None,
                "created_at": iso(self.created_at), "updated_at": iso(self.updated_at)}
        if with_versions:
            data["versions"] = [v.to_dict() for v in self.versions]
        return data


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number", name="uq_dataset_versions_number"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(ID, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[int | None] = mapped_column(ID, ForeignKey("dataset_versions.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    schema_json: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {"id": self.id, "dataset_id": self.dataset_id, "version_number": self.version_number,
                "parent_version_id": self.parent_version_id, "kind": self.kind, "file_format": self.file_format,
                "checksum_sha256": self.checksum_sha256, "size_bytes": self.size_bytes, "row_count": self.row_count,
                "column_count": self.column_count, "note": self.note, "created_at": iso(self.created_at)}


class Variable(Base):
    __tablename__ = "variables"
    __table_args__ = (UniqueConstraint("dataset_id", "name", name="uq_variables_dataset_name"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id: Mapped[int] = mapped_column(ID, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(190), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)
    measurement_level: Mapped[str] = mapped_column(String(10), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    valid_min: Mapped[float | None] = mapped_column(Float)
    valid_max: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self, column: "DatasetColumn | None" = None) -> dict:
        data = {"id": self.id, "dataset_id": self.dataset_id, "name": self.name, "label": self.label, "description": self.description,
                "data_type": self.data_type, "measurement_level": self.measurement_level, "role": self.role, "unit": self.unit,
                "valid_min": self.valid_min, "valid_max": self.valid_max}
        if column is not None:
            data.update(n_unique=column.n_unique, n_missing=column.n_missing, stats=column.stats_json or {}, position=column.position)
        return data


class DatasetColumn(Base):
    __tablename__ = "dataset_columns"
    __table_args__ = (UniqueConstraint("dataset_version_id", "name", name="uq_dataset_columns_name"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    dataset_version_id: Mapped[int] = mapped_column(ID, ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False)
    variable_id: Mapped[int | None] = mapped_column(ID, ForeignKey("variables.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(190), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inferred_type: Mapped[str] = mapped_column(String(20), nullable=False)
    n_unique: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_missing: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stats_json: Mapped[dict | None] = mapped_column(JSON)


class DataQualityReport(Base):
    __tablename__ = "data_quality_reports"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    dataset_version_id: Mapped[int] = mapped_column(ID, ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    issues_json: Mapped[list] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    version = relationship("DatasetVersion", lazy="joined")

    def to_dict(self) -> dict:
        summary = dict(self.summary_json or {})
        return {"id": self.id, "dataset_version_id": self.dataset_version_id,
                "version_number": self.version.version_number if self.version else None, "score": float(self.score),
                "issue_count": self.issue_count, "summary": summary.get("summary", {}), "dimensions": summary.get("dimensions", {}),
                "issues": self.issues_json or [], "created_at": iso(self.created_at)}


class CleaningOperation(Base):
    __tablename__ = "cleaning_operations"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(ID, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    input_version_id: Mapped[int] = mapped_column(ID, ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False)
    output_version_id: Mapped[int] = mapped_column(ID, ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    rows_before: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_after: Mapped[int] = mapped_column(Integer, nullable=False)
    cells_changed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    details_json: Mapped[dict | None] = mapped_column(JSON)
    performed_by: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    input_version = relationship("DatasetVersion", foreign_keys=[input_version_id], lazy="joined")
    output_version = relationship("DatasetVersion", foreign_keys=[output_version_id], lazy="joined")

    def to_dict(self, with_details: bool = True) -> dict:
        data = {"id": self.id, "dataset_id": self.dataset_id, "operation": self.operation, "params": self.params_json,
                "reason": self.reason, "rows_before": self.rows_before, "rows_after": self.rows_after,
                "cells_changed": self.cells_changed, "input_version_id": self.input_version_id,
                "output_version_id": self.output_version_id,
                "input_version_number": self.input_version.version_number if self.input_version else None,
                "output_version_number": self.output_version.version_number if self.output_version else None,
                "created_at": iso(self.created_at)}
        if with_details:
            data["details"] = self.details_json or {}
        return data
