"""Findings, conclusions, recommendations, limitations and reports."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.analysis import chart_advice
from app.database.session import Base
from app.models.base import ID, iso, utcnow


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    research_question_id: Mapped[int | None] = mapped_column(ID, ForeignKey("research_questions.id", ondelete="SET NULL"))
    hypothesis_id: Mapped[int | None] = mapped_column(ID, ForeignKey("hypotheses.id", ondelete="SET NULL"))
    analysis_result_id: Mapped[int | None] = mapped_column(ID, ForeignKey("analysis_results.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    statistical_evidence: Mapped[str | None] = mapped_column(Text)
    interpretation: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str] = mapped_column(String(10), default="moderate", nullable=False)
    limitations_note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), default="engine", nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    analysis_result = relationship("AnalysisResult", lazy="joined")
    research_question = relationship("ResearchQuestion", lazy="joined")

    def chart_suggestions(self) -> list[dict]:
        """Charts that help a reader see this finding, from the test that produced it."""
        result = self.analysis_result
        if result is None or result.statistical_test_id is None or result.run is None:
            return []
        test = next((t for t in result.run.tests if t.id == result.statistical_test_id), None)
        if test is None:
            return []
        schema = (result.run.config_json or {}).get("schema") or {}
        return [{**idea, "run_id": result.run.id} for idea in chart_advice.chart_ideas(test.method, test.variables_json or {}, schema)]

    def breakdown(self) -> dict:
        """Plain-language breakdown for a reader who is not an analyst, built from what the finding already stores."""
        method = (self.analysis_result.result_json or {}).get("method_name") if self.analysis_result else None
        name = method or "A statistical test"
        question = self.research_question.text if self.research_question else None
        return {"title": self.title,
                "what_was_tested": f"{name} was used to examine: {question}" if question else f"{name} was run on the data.",
                "what_we_found": self.statement,
                "what_it_means": self.interpretation or self.statement,
                "how_sure": self.limitations_note or f"The strength of the evidence is rated {self.confidence_level}."}

    def to_dict(self) -> dict:
        result = self.analysis_result
        return {"id": self.id, "project_id": self.project_id, "research_question_id": self.research_question_id,
                "hypothesis_id": self.hypothesis_id, "analysis_result_id": self.analysis_result_id,
                "analysis_run_id": result.analysis_run_id if result else None,
                "significant": result.is_significant if result else None, "title": self.title, "statement": self.statement,
                "statistical_evidence": self.statistical_evidence, "interpretation": self.interpretation,
                "confidence_level": self.confidence_level, "limitations_note": self.limitations_note, "breakdown": self.breakdown(),
                "source": self.source,
                "is_edited": self.is_edited, "charts": self.chart_suggestions(),
                "created_at": iso(self.created_at), "updated_at": iso(self.updated_at)}


class Conclusion(Base):
    __tablename__ = "conclusions"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(10), default="engine", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    findings: Mapped[list[Finding]] = relationship(secondary="conclusion_findings", lazy="selectin")

    def chart_suggestion(self) -> dict | None:
        """One chart that relates to this conclusion: the first chart of its findings."""
        for finding in self.findings:
            ideas = finding.chart_suggestions()
            if ideas:
                return {**ideas[0], "finding_id": finding.id}
        return None

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "text": self.text, "source": self.source, "position": self.position,
                "finding_ids": [f.id for f in self.findings], "chart": self.chart_suggestion(), "updated_at": iso(self.updated_at)}


class ConclusionFinding(Base):
    __tablename__ = "conclusion_findings"

    conclusion_id: Mapped[int] = mapped_column(ID, ForeignKey("conclusions.id", ondelete="CASCADE"), primary_key=True)
    finding_id: Mapped[int] = mapped_column(ID, ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str | None] = mapped_column(String(150))
    source: Mapped[str] = mapped_column(String(10), default="manual", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    findings: Mapped[list[Finding]] = relationship(secondary="recommendation_findings", lazy="selectin")

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "text": self.text, "audience": self.audience, "source": self.source,
                "position": self.position, "finding_ids": [f.id for f in self.findings], "updated_at": iso(self.updated_at)}


class RecommendationFinding(Base):
    __tablename__ = "recommendation_findings"

    recommendation_id: Mapped[int] = mapped_column(ID, ForeignKey("recommendations.id", ondelete="CASCADE"), primary_key=True)
    finding_id: Mapped[int] = mapped_column(ID, ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True)


class Limitation(Base):
    __tablename__ = "limitations"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(10), default="auto", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    status_note: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "category": self.category, "description": self.description,
                "source": self.source, "status": self.status, "status_note": self.status_note, "evidence": self.evidence_json or {},
                "updated_at": iso(self.updated_at)}


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    versions: Mapped[list["ReportVersion"]] = relationship(cascade="all, delete-orphan", order_by="ReportVersion.version_number", lazy="selectin")

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "title": self.title, "created_at": iso(self.created_at),
                "updated_at": iso(self.updated_at), "versions": [v.to_dict() for v in self.versions]}


class ReportVersion(Base):
    __tablename__ = "report_versions"
    __table_args__ = (UniqueConstraint("report_id", "version_number", name="uq_report_versions_number"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ID, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {"id": self.id, "report_id": self.report_id, "version_number": self.version_number, "format": self.format,
                "size_bytes": self.size_bytes, "created_at": iso(self.created_at),
                "download_url": f"/api/reports/{self.report_id}/download?version={self.version_number}"}
