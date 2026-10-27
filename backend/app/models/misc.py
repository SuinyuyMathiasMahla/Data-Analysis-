"""AI conversations, supervision, audit history, notifications, settings."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import ID, iso, utcnow


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    messages: Mapped[list["AIMessage"]] = relationship(cascade="all, delete-orphan", order_by="AIMessage.id", lazy="selectin")

    def to_dict(self, with_messages: bool = False) -> dict:
        data = {"id": self.id, "project_id": self.project_id, "title": self.title, "created_at": iso(self.created_at),
                "updated_at": iso(self.updated_at), "message_count": len(self.messages)}
        if with_messages:
            data["messages"] = [m.to_dict() for m in self.messages]
        return data


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ID, ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(100))
    context_json: Mapped[dict | None] = mapped_column(JSON)
    grounding_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    def to_dict(self) -> dict:
        grounding = self.grounding_json or {}
        return {"id": self.id, "role": self.role, "content": self.content, "provider": self.provider, "model": self.model,
                "source": grounding.get("source"), "notice": grounding.get("notice"), "grounding": grounding.get("check"),
                "created_at": iso(self.created_at)}


class AIRecommendation(Base):
    __tablename__ = "ai_recommendations"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    research_question_id: Mapped[int | None] = mapped_column(ID, ForeignKey("research_questions.id", ondelete="SET NULL"))
    dataset_version_id: Mapped[int | None] = mapped_column(ID, ForeignKey("dataset_versions.id", ondelete="SET NULL"))
    recommended_method: Mapped[str] = mapped_column(String(60), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(15), default="rule_engine", nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "research_question_id": self.research_question_id,
                "dataset_version_id": self.dataset_version_id, "recommended_method": self.recommended_method,
                "rationale": self.rationale, "recommendation": self.payload_json, "source": self.source, "status": self.status,
                "created_at": iso(self.created_at)}


class ReviewComment(Base):
    __tablename__ = "review_comments"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(ID)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    author = relationship("User", lazy="joined")

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "author_id": self.author_id,
                "author_name": self.author.full_name if self.author else None, "stage": self.stage,
                "entity_type": self.entity_type, "entity_id": self.entity_id, "body": self.body, "created_at": iso(self.created_at)}


class StageReview(Base):
    __tablename__ = "stage_reviews"
    __table_args__ = (UniqueConstraint("project_id", "stage", name="uq_stage_reviews"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="pending", nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    reviewer = relationship("User", lazy="joined")

    def to_dict(self) -> dict:
        return {"id": self.id, "stage": self.stage, "status": self.status, "reviewer_id": self.reviewer_id,
                "reviewer_name": self.reviewer.full_name if self.reviewer else None, "note": self.note,
                "reviewed_at": iso(self.reviewed_at)}


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(ID, ForeignKey("projects.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(ID)
    details_json: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    user = relationship("User", lazy="joined")

    def to_dict(self) -> dict:
        return {"id": self.id, "user_id": self.user_id, "user_name": self.user.full_name if self.user else None,
                "project_id": self.project_id, "action": self.action, "entity_type": self.entity_type, "entity_id": self.entity_id,
                "details": self.details_json or {}, "created_at": iso(self.created_at)}


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "type": self.type, "title": self.title, "body": self.body,
                "is_read": self.is_read, "created_at": iso(self.created_at)}


class SystemSetting(Base):
    __tablename__ = "system_settings"

    setting_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[object] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
