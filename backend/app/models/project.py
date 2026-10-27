"""Research projects and their design: objectives, questions, hypotheses."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import ID, iso, utcnow

PROJECT_FIELDS = ["title", "academic_level", "research_field", "institution", "department", "research_problem", "general_objective",
                  "study_population", "sample_size", "sampling_technique", "research_methodology", "study_design",
                  "data_collection_method", "status"]


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    academic_level: Mapped[str] = mapped_column(String(20), nullable=False)
    research_field: Mapped[str | None] = mapped_column(String(150))
    institution: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(200))
    research_problem: Mapped[str | None] = mapped_column(Text)
    general_objective: Mapped[str | None] = mapped_column(Text)
    study_population: Mapped[str | None] = mapped_column(Text)
    sample_size: Mapped[int | None] = mapped_column(Integer)
    sampling_technique: Mapped[str | None] = mapped_column(String(150))
    research_methodology: Mapped[str | None] = mapped_column(String(150))
    study_design: Mapped[str | None] = mapped_column(String(150))
    data_collection_method: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    owner = relationship("User", lazy="joined")
    objectives: Mapped[list["Objective"]] = relationship(cascade="all, delete-orphan", order_by="Objective.position", lazy="selectin")
    research_questions: Mapped[list["ResearchQuestion"]] = relationship(cascade="all, delete-orphan", order_by="ResearchQuestion.position", lazy="selectin")
    hypotheses: Mapped[list["Hypothesis"]] = relationship(cascade="all, delete-orphan", order_by="Hypothesis.id", lazy="selectin")
    members: Mapped[list["ProjectMember"]] = relationship(cascade="all, delete-orphan", lazy="selectin")

    def to_dict(self, full: bool = False) -> dict:
        data = {f: getattr(self, f) for f in PROJECT_FIELDS}
        data.update(id=self.id, owner_id=self.owner_id, owner_name=self.owner.full_name if self.owner else None,
                    created_at=iso(self.created_at), updated_at=iso(self.updated_at))
        if full:
            data["objectives"] = [o.to_dict() for o in self.objectives]
            data["members"] = [m.to_dict() for m in self.members]
        return data


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_members"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    member_role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    user = relationship("User", lazy="joined")

    def to_dict(self) -> dict:
        return {"id": self.id, "user_id": self.user_id, "member_role": self.member_role,
                "full_name": self.user.full_name if self.user else None, "email": self.user.email if self.user else None}


class Objective(Base):
    __tablename__ = "objectives"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {"id": self.id, "position": self.position, "text": self.text}


class ResearchQuestion(Base):
    __tablename__ = "research_questions"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_research_questions_code"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    variable_links: Mapped[list["ResearchQuestionVariable"]] = relationship(cascade="all, delete-orphan", lazy="selectin")

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "code": self.code, "text": self.text, "position": self.position,
                "variables": [{"variable_id": link.variable_id, "role": link.role, "name": link.variable.name if link.variable else None}
                              for link in self.variable_links]}


class ResearchQuestionVariable(Base):
    __tablename__ = "research_question_variables"

    research_question_id: Mapped[int] = mapped_column(ID, ForeignKey("research_questions.id", ondelete="CASCADE"), primary_key=True)
    variable_id: Mapped[int] = mapped_column(ID, ForeignKey("variables.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="other", nullable=False)

    variable = relationship("Variable", lazy="joined")


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_hypotheses_code"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    research_question_id: Mapped[int | None] = mapped_column(ID, ForeignKey("research_questions.id", ondelete="SET NULL"), index=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    null_text: Mapped[str] = mapped_column(Text, nullable=False)
    alternative_text: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String(20), default="non_directional", nullable=False)
    alpha: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.05"), nullable=False)
    decision: Mapped[str] = mapped_column(String(25), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "research_question_id": self.research_question_id, "code": self.code,
                "null_text": self.null_text, "alternative_text": self.alternative_text, "direction": self.direction,
                "alpha": float(self.alpha), "decision": self.decision}
