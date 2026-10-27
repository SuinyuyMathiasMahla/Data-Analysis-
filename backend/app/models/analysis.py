"""Analysis runs (jobs), statistical tests, results and visualizations."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import ID, iso, utcnow


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_version_id: Mapped[int] = mapped_column(ID, ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False)
    research_question_id: Mapped[int | None] = mapped_column(ID, ForeignKey("research_questions.id", ondelete="SET NULL"))
    reproduced_from_id: Mapped[int | None] = mapped_column(ID, ForeignKey("analysis_runs.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="PENDING", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    filters_json: Mapped[list | None] = mapped_column(JSON)
    software_json: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    version = relationship("DatasetVersion", lazy="joined")
    tests: Mapped[list["StatisticalTest"]] = relationship(cascade="all, delete-orphan", order_by="StatisticalTest.id", lazy="selectin")
    results: Mapped[list["AnalysisResult"]] = relationship(back_populates="run", cascade="all, delete-orphan",
                                                           order_by="AnalysisResult.id", lazy="selectin")

    def to_dict(self, with_results: bool = False) -> dict:
        data = {"id": self.id, "project_id": self.project_id, "dataset_version_id": self.dataset_version_id,
                "dataset_id": self.version.dataset_id if self.version else None,
                "version_number": self.version.version_number if self.version else None,
                "research_question_id": self.research_question_id, "reproduced_from_id": self.reproduced_from_id, "name": self.name,
                "analysis_type": self.analysis_type, "status": self.status, "progress": self.progress, "config": self.config_json,
                "filters": self.filters_json or [], "software": self.software_json or {}, "error_message": self.error_message,
                "created_at": iso(self.created_at), "started_at": iso(self.started_at), "completed_at": iso(self.completed_at),
                "tests": [t.to_dict() for t in self.tests],
                "result_summaries": [r.to_dict(with_payload=False) for r in self.results]}
        if with_results:
            tests = {t.id: t for t in self.tests}
            data["results"] = [{**r.to_dict(), "test": tests[r.statistical_test_id].to_dict() if r.statistical_test_id in tests else None}
                               for r in self.results]
        return data


class StatisticalTest(Base):
    __tablename__ = "statistical_tests"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    analysis_run_id: Mapped[int] = mapped_column(ID, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    hypothesis_id: Mapped[int | None] = mapped_column(ID, ForeignKey("hypotheses.id", ondelete="SET NULL"), index=True)
    method: Mapped[str] = mapped_column(String(60), nullable=False)
    method_name: Mapped[str] = mapped_column(String(150), nullable=False)
    variables_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    params_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12), default="PENDING", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    def to_dict(self) -> dict:
        return {"id": self.id, "analysis_run_id": self.analysis_run_id, "hypothesis_id": self.hypothesis_id, "method": self.method,
                "method_name": self.method_name, "variables": self.variables_json, "params": self.params_json or {},
                "status": self.status, "error_message": self.error_message, "completed_at": iso(self.completed_at)}


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    analysis_run_id: Mapped[int] = mapped_column(ID, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    statistical_test_id: Mapped[int | None] = mapped_column(ID, ForeignKey("statistical_tests.id", ondelete="CASCADE"), index=True)
    result_type: Mapped[str] = mapped_column(String(40), nullable=False)
    statistic_name: Mapped[str | None] = mapped_column(String(40))
    statistic_value: Mapped[float | None] = mapped_column(Float)
    degrees_of_freedom: Mapped[str | None] = mapped_column(String(60))
    p_value: Mapped[float | None] = mapped_column(Float)
    effect_size_name: Mapped[str | None] = mapped_column(String(60))
    effect_size_value: Mapped[float | None] = mapped_column(Float)
    is_significant: Mapped[bool | None] = mapped_column(Boolean)
    sample_size: Mapped[int | None] = mapped_column(Integer)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    engine_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    run: Mapped["AnalysisRun"] = relationship(back_populates="results")

    def to_dict(self, with_payload: bool = True) -> dict:
        data = {"id": self.id, "analysis_run_id": self.analysis_run_id, "statistical_test_id": self.statistical_test_id,
                "result_type": self.result_type, "statistic_name": self.statistic_name, "statistic_value": self.statistic_value,
                "degrees_of_freedom": self.degrees_of_freedom, "p_value": self.p_value, "effect_size_name": self.effect_size_name,
                "effect_size_value": self.effect_size_value, "is_significant": self.is_significant, "sample_size": self.sample_size,
                "engine_summary": self.engine_summary, "created_at": iso(self.created_at)}
        if with_payload:
            data["result"] = self.result_json
        return data


class Visualization(Base):
    __tablename__ = "visualizations"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_version_id: Mapped[int] = mapped_column(ID, ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False)
    analysis_run_id: Mapped[int | None] = mapped_column(ID, ForeignKey("analysis_runs.id", ondelete="SET NULL"), index=True)
    chart_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    include_in_report: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    version = relationship("DatasetVersion", lazy="joined")

    def to_dict(self) -> dict:
        config = dict(self.config_json or {})
        return {"id": self.id, "project_id": self.project_id, "dataset_version_id": self.dataset_version_id,
                "dataset_id": self.version.dataset_id if self.version else None,
                "version_number": self.version.version_number if self.version else None,
                "analysis_run_id": self.analysis_run_id, "chart_type": self.chart_type, "title": self.title,
                "config": {k: v for k, v in config.items() if k != "_meta"}, "meta": config.get("_meta", {}),
                "include_in_report": self.include_in_report, "image_url": f"/api/visualizations/{self.id}/image",
                "created_at": iso(self.created_at), "updated_at": iso(self.updated_at)}
