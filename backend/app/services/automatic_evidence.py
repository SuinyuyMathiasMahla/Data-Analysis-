"""Workflow steps 9 and 10 done automatically.

Step 9 (findings): a plain-language finding for each completed analysis result that does not have one yet.
Step 10 (conclusions and recommendations): written from those findings.

Everything is built from the engine's results. The AI assistant only rewrites the wording; each AI reply is
checked against the numbers in its context (see ai/guard.py), and the engine's own wording is used when the AI
is unavailable. Findings the researcher has already edited, and items they wrote themselves, are never changed.
"""
from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.service import AIService
from app.analysis import evidence
from app.models import AnalysisResult, Conclusion, Project, Recommendation, User
from app.services import ai_runtime, audit, auto_analysis, evidence_service, evidence_state, project_service

AUTOMATIC_SOURCES = ("engine", "ai")


def _create_missing_findings(db: Session, project: Project, user: User, ai: AIService, dataset, version) -> int:
    """A finding for every completed analysis result that has none yet. Existing findings are never changed."""
    overview = auto_analysis.overview(db, project, dataset, version, AIService(None))
    existing = {f.analysis_result_id for f in evidence_service.list_findings(db, project.id) if f.analysis_result_id}
    created = 0
    for item in overview["items"]:
        if item["status"] != "completed" or not item["run"]:
            continue
        for row in item["run"].get("results") or []:
            if row["result_type"] != "test" or row["id"] in existing:
                continue
            rq_id = item["research_question"]["id"] if item["research_question"] else None
            hyp_id = item["hypothesis"]["id"] if item["hypothesis"] else None
            finding = evidence_service.finding_from_result(db, project, user, db.get(AnalysisResult, row["id"]), rq_id, hyp_id)
            plain = ai.plain_finding(ai_runtime.project_context(db, project, dataset, focus={
                "finding": finding.to_dict(), "research_question": item["research_question"], "hypothesis": item["hypothesis"]}))
            if plain:
                finding.title = plain["title"][:250]
                finding.statement = plain["what_we_found"]
                finding.interpretation = plain["what_it_means"]
                finding.source = "ai"
            db.commit()
            created += 1
    return created


def _has_automatic(db: Session, model, project_id: int) -> bool:
    return db.scalar(select(model.id).where(model.project_id == project_id, model.source.in_(AUTOMATIC_SOURCES))) is not None


def _delete_automatic(db: Session, model, project_id: int) -> None:
    for old in db.scalars(select(model).where(model.project_id == project_id, model.source.in_(AUTOMATIC_SOURCES))):
        db.delete(old)
    db.flush()


def _fingerprint(drafts: list[dict]) -> str:
    """Identifies what the conclusions are built from: each draft's text (engine wording) and the findings it rests on."""
    return hashlib.sha256(json.dumps([[d["text"], d["finding_ids"]] for d in drafts], sort_keys=True).encode("utf-8")).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _written_hashes(db: Session, model, project_id: int) -> dict[str, str]:
    """What each automatic item says right now, by id. Stored after writing, so later edits can be detected."""
    return {str(item.id): _text_hash(item.text)
            for item in db.scalars(select(model).where(model.project_id == project_id, model.source.in_(AUTOMATIC_SOURCES)))}


# Wording the platform wrote in earlier versions. Text in this wording was never typed by the researcher, so it is automatic.
EARLIER_CONCLUSION = re.compile(r"^RQ\d+ ?[:-] .*(\? Answer: |Based on the analysis:)", re.DOTALL)
EARLIER_RECOMMENDATION = re.compile(r'^Finding "')


def _earlier_engine_text(model, text: str) -> bool:
    pattern = EARLIER_CONCLUSION if model is Conclusion else EARLIER_RECOMMENDATION
    return bool(pattern.match(text or ""))


def _protect_edited(db: Session, model, project_id: int, state: dict, key: str) -> None:
    """An automatic item whose text no longer matches the text that was written belongs to the researcher now.

    Items edited through the app are already 'manual'. This also catches edits made before that tracking existed, and any
    automatic item with no record at all: those are kept rather than risk replacing the researcher's own wording. The cost
    is that such an old automatic item can sit beside its rewritten version, and the researcher can delete the older one."""
    written = state.get(key, {})
    for item in db.scalars(select(model).where(model.project_id == project_id, model.source.in_(AUTOMATIC_SOURCES + ("manual",)))):
        if item.source == "manual":
            # marked as the researcher's earlier, when it was only a draft from an earlier version: hand it back to the platform
            if _earlier_engine_text(model, item.text):
                item.source = "engine"
            continue
        if written.get(str(item.id)) != _text_hash(item.text) and not _earlier_engine_text(model, item.text):
            item.source = "manual"
    db.flush()


def _write_conclusions(db: Session, project: Project, regenerate: bool) -> int:
    """One plain-English conclusion per research question, including the ones that could not be answered yet.

    The text is written by the platform from the statistical results, in the same layout every time (see evidence.draft_conclusions),
    so it does not depend on the AI assistant. The automatic conclusions are rewritten only when their basis has changed. Conclusions
    the researcher has edited are no longer automatic, so they are never replaced."""
    findings, unanswered, labels = evidence_service.analysis_basis(db, project)
    drafts = evidence.draft_conclusions(findings, project_service.question_dicts(project), unanswered, labels, project.title)
    basis = _fingerprint(drafts)
    state = evidence_state.get(project.id)
    _protect_edited(db, Conclusion, project.id, state, "conclusion_text")
    if not regenerate and state.get("conclusions") == basis and _has_automatic(db, Conclusion, project.id):
        return 0
    _delete_automatic(db, Conclusion, project.id)
    start = len(list(db.scalars(select(Conclusion.id).where(Conclusion.project_id == project.id))))
    for i, draft in enumerate(drafts):
        item = Conclusion(project_id=project.id, text=draft["text"], source="engine", position=start + i)
        item.findings = evidence_service._findings_by_ids(db, project.id, draft["finding_ids"])
        db.add(item)
    db.flush()
    evidence_state.merge(project.id, {"conclusions": basis, "conclusion_text": _written_hashes(db, Conclusion, project.id)})
    return len(drafts)


def _write_recommendations(db: Session, project: Project, regenerate: bool) -> int:
    """Plain-English recommendations for the findings. Rewritten only when the findings they rest on have changed; edited ones are kept."""
    findings, _, labels = evidence_service.analysis_basis(db, project)
    drafts = evidence.draft_recommendations(findings, project.study_design, labels, project.title)
    state = evidence_state.get(project.id)
    _protect_edited(db, Recommendation, project.id, state, "recommendation_text")
    basis = _fingerprint(drafts)
    if not regenerate and state.get("recommendations") == basis and _has_automatic(db, Recommendation, project.id):
        return 0
    _delete_automatic(db, Recommendation, project.id)
    start = len(list(db.scalars(select(Recommendation.id).where(Recommendation.project_id == project.id))))
    for i, draft in enumerate(drafts):
        item = Recommendation(project_id=project.id, text=draft["text"], source="engine", position=start + i)
        item.findings = evidence_service._findings_by_ids(db, project.id, draft["finding_ids"])
        db.add(item)
    db.flush()
    evidence_state.merge(project.id, {"recommendations": basis, "recommendation_text": _written_hashes(db, Recommendation, project.id)})
    return len(drafts)


def auto_evidence(db: Session, project: Project, user: User, ai: AIService, regenerate: bool = False) -> dict:
    """Create the missing findings, then write conclusions and recommendations from them.

    Conclusions and recommendations are written only when no automatic ones exist yet, or when ``regenerate``
    is set (which replaces the automatic ones; the researcher's own items are kept).
    """
    dataset = project_service.primary_dataset(db, project.id)
    has_data = dataset is not None and dataset.current_version is not None
    summary = {"findings_created": 0, "conclusions": 0, "recommendations": 0, "limitations": 0}
    if has_data:
        summary["findings_created"] = _create_missing_findings(db, project, user, ai, dataset, dataset.current_version)
        summary["limitations"] = len(evidence_service.detect_limitations(db, project, user))
    # every research question gets a conclusion, even without data: evidence_service.unanswered_notes says why it is unanswered
    if project.research_questions or evidence_service.list_findings(db, project.id):
        summary["conclusions"] = _write_conclusions(db, project, regenerate)
        if evidence_service.list_findings(db, project.id):
            summary["recommendations"] = _write_recommendations(db, project, regenerate)
    audit.record(db, action="evidence.auto", user_id=user.id, project_id=project.id, details=summary)
    db.commit()
    return summary
