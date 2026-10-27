"""AI research assistant endpoints.

Each endpoint always computes its engine/rule-based answer first; a configured
LLM only explains or rewrites it. Replies carry ``source`` ("llm" or
"rule_engine"), a ``notice`` when something needs the user's attention, and the
grounding check of the numbers in the reply.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import eda
from app.api.deps import READ, WRITE, get_current_user, get_project, get_result, get_visualization, owned
from app.core.config import get_settings
from app.core.errors import bad_request, not_found
from app.core.rate_limit import check_rate
from app.database.session import get_db
from app.models import AIConversation, AIMessage, AIRecommendation, Hypothesis, Project, ResearchQuestion, User
from app.schemas.requests import AIAnalyzeIn, AIChatIn, AIExplainIn, AIPlanIn, AIRecommendIn, AssistantDecisionIn, AssistantDraftIn, AutoAnalyzeIn
from app.services import ai_runtime, audit, auto_analysis, dataset_service, project_service, step_checks, drafts
from app.statistics import recommender

router = APIRouter(tags=["ai"])


def _guard(request: Request, user: User) -> None:
    if "ai.use" not in user.permission_codes:
        raise bad_request("Your account is not allowed to use the AI assistant.", "forbidden")
    check_rate(f"ai:{user.id}", get_settings().RATE_LIMIT_AI_PER_MINUTE)


def _log(db: Session, project: Project, user: User, kind: str, question: str, reply, context: dict) -> AIMessage:
    """Store the exchange (and exactly what context was sent) in the project's AI history."""
    conversation = AIConversation(project_id=project.id, user_id=user.id, title=f"{kind}: {question}"[:255])
    db.add(conversation)
    db.flush()
    db.add(AIMessage(conversation_id=conversation.id, role="user", content=question))
    message = AIMessage(conversation_id=conversation.id, role="assistant", content=reply.content, provider=reply.provider, model=reply.model,
                        context_json={"focus": context.get("focus"), "results_sent": len(context.get("statistical_results") or []),
                                      "variables_sent": len(context.get("variables") or [])},
                        grounding_json={"source": reply.source, "notice": reply.notice, "check": reply.grounding})
    db.add(message)
    audit.record(db, action=f"ai.{kind}", user_id=user.id, project_id=project.id, entity_type="ai_conversation", entity_id=conversation.id,
                 details={"source": reply.source, "provider": reply.provider, "grounded": (reply.grounding or {}).get("grounded")})
    return message


@router.get("/ai/status")
def ai_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ai_runtime.get_ai_service(db).status()


@router.post("/projects/{project_id}/ai/analyze")
def ai_analyze(project_id: int, body: AIAnalyzeIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Overview of the project and dataset with suggested next steps."""
    _guard(request, user)
    project = get_project(db, project_id, user, READ)
    dataset = project_service.primary_dataset(db, project.id, body.dataset_id)
    if dataset is None or dataset.current_version is None:
        raise bad_request("Upload a dataset first; there is nothing to analyse yet.")
    df, schema = dataset_service.load_typed(db, dataset.current_version)
    overview = eda.run_eda(df, schema)
    progress = project_service.progress(db, project)
    evaluation = project_service.research_question_evaluation(db, project)
    next_steps = [f"{rq['code']} has not been analysed yet: use 'Recommend a method' for it." for rq in evaluation if rq["status"] == "not_analysed"]
    next_steps += [f"{rq['code']} has results but no recorded finding." for rq in evaluation if rq["status"] == "analysed"]
    if not project.research_questions:
        next_steps.append("Define at least one research question so that analyses can be traced to it.")
    context = ai_runtime.project_context(db, project, dataset, focus={"eda_highlights": overview["highlights"], "workflow_progress": progress})
    reply = ai_runtime.get_ai_service(db).analyze_project(context, overview["highlights"], next_steps)
    _log(db, project, user, "analyze", "Review my project and dataset", reply, context)
    db.commit()
    return {**reply.as_dict(), "highlights": overview["highlights"], "suggested_charts": overview["suggested_charts"], "next_steps": next_steps}


@router.post("/projects/{project_id}/ai/recommend")
def ai_recommend(project_id: int, body: AIRecommendIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Recommend a statistical method. The recommendation itself comes from the
    rule engine (variable types + assumption checks on the real data)."""
    _guard(request, user)
    project = get_project(db, project_id, user, WRITE)
    question = owned(db, ResearchQuestion, body.research_question_id, project.id, "Research question")
    dataset = project_service.primary_dataset(db, project.id, body.dataset_id)
    if dataset is None or dataset.current_version is None:
        raise bad_request("Upload a dataset first.")
    version = dataset.current_version
    df, schema = dataset_service.load_typed(db, version)
    outcome, predictors = body.outcome, list(body.predictors)
    if question is not None and not outcome and not body.measures:
        links = question.to_dict()["variables"]
        outcome = next((v["name"] for v in links if v["role"] == "dependent"), None)
        predictors = predictors or [v["name"] for v in links if v["role"] in ("independent", "control", "moderator", "mediator")]
    result = recommender.recommend(df, schema, outcome=outcome, predictors=predictors, paired=body.paired, measures=body.measures,
                                   outcome_kind=body.outcome_kind, academic_level=project.academic_level,
                                   study_design=project.study_design, goal=body.goal or (question.text if question else None))
    context = ai_runtime.project_context(db, project, dataset, focus={"method_recommendation": result})
    reply = ai_runtime.get_ai_service(db).comment_on_recommendation(context, result)
    row = AIRecommendation(project_id=project.id, research_question_id=question.id if question else None, dataset_version_id=version.id,
                           recommended_method=result["primary"]["method"], rationale=" ".join(result["why"]), payload_json=result,
                           source="rule_engine")
    db.add(row)
    db.flush()
    _log(db, project, user, "recommend", body.goal or (question.text if question else "Recommend a statistical method"), reply, context)
    db.commit()
    return {"id": row.id, "recommendation": result, "explanation": reply.as_dict(), "dataset_id": dataset.id,
            "dataset_version_id": version.id, "research_question_id": question.id if question else None}


def _dataset_version(db: Session, project: Project, dataset_id: int | None):
    dataset = project_service.primary_dataset(db, project.id, dataset_id)
    if dataset is None or dataset.current_version is None:
        raise bad_request("Upload a dataset first.")
    return dataset, dataset.current_version


@router.post("/projects/{project_id}/ai/plan")
def ai_plan(project_id: int, body: AIPlanIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Choose the variables and the statistical test for one research question or hypothesis.
    Nothing is run: the result fills in the 'Help me choose' and 'Run a statistical test' fields."""
    _guard(request, user)
    project = get_project(db, project_id, user, WRITE)
    owned(db, ResearchQuestion, body.research_question_id, project.id, "Research question")
    owned(db, Hypothesis, body.hypothesis_id, project.id, "Hypothesis")
    if body.research_question_id is None and body.hypothesis_id is None:
        raise bad_request("Provide a research_question_id or hypothesis_id.")
    dataset = project_service.primary_dataset(db, project.id, body.dataset_id)
    if dataset is None or dataset.current_version is None:
        raise bad_request("Upload a dataset first.")
    context = ai_runtime.project_context(db, project, dataset, focus={"planning": True})
    reply = ai_runtime.get_ai_service(db).plan_analysis(context, body.goal or "")
    _log(db, project, user, "plan", body.goal or "Plan an analysis", reply, context)
    db.commit()
    return reply.as_dict()


@router.post("/projects/{project_id}/ai/explain")
def ai_explain(project_id: int, body: AIExplainIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Explain a statistical result, a chart or a statistical concept."""
    _guard(request, user)
    project = get_project(db, project_id, user, READ)
    service = ai_runtime.get_ai_service(db)
    if body.analysis_result_id is not None:
        result, _run, result_project = get_result(db, body.analysis_result_id, user, READ)
        if result_project.id != project.id:
            raise not_found("Analysis result")
        context = ai_runtime.project_context(db, project, focus={"result_to_explain": result.result_json, "question": body.question})
        reply = service.explain_result(context, result.result_json, body.question)
        label = body.question or f"Explain result #{result.id}"
    elif body.visualization_id is not None:
        viz, viz_project = get_visualization(db, body.visualization_id, user, READ)
        if viz_project.id != project.id:
            raise not_found("Visualization")
        # ── CHANGED: build rich chart info from the DB record + any extra fields
        #    the frontend sent (chart_type, title, x, y, hue, columns, meta)
        config = viz.config_json or {}
        stored_meta = config.get("_meta", {})
        chart_info = {
            "chart_type": body.chart_type or viz.chart_type,
            "title":      body.title      or viz.title,
            "x":          body.x          or config.get("x"),
            "y":          body.y          or config.get("y"),
            "hue":        body.hue        or config.get("hue"),
            "columns":    body.columns    or config.get("columns"),
            "n":          stored_meta.get("n") or (body.meta or {}).get("n"),
            "notes":      stored_meta.get("notes") or (body.meta or {}).get("notes") or [],
        }
        context = ai_runtime.project_context(db, project, focus={"chart": chart_info})
        reply = service.explain_chart(context, chart_info)
        # ─────────────────────────────────────────────────────────────────────
        label = f"Explain chart: {chart_info['title']}"
    elif body.concept:
        context = ai_runtime.project_context(db, project, focus={"concept": body.concept})
        reply = service.explain_concept(context, body.concept)
        label = f"Explain concept: {body.concept}"
    else:
        raise bad_request("Say what to explain: analysis_result_id, visualization_id or concept.")
    _log(db, project, user, "explain", label, reply, context)
    db.commit()
    return reply.as_dict()


@router.post("/projects/{project_id}/ai/chat")
def ai_chat(project_id: int, body: AIChatIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _guard(request, user)
    project = get_project(db, project_id, user, READ)
    if body.conversation_id is not None:
        conversation = db.get(AIConversation, body.conversation_id)
        if conversation is None or conversation.project_id != project.id or conversation.user_id != user.id:
            raise not_found("Conversation")
    else:
        conversation = AIConversation(project_id=project.id, user_id=user.id, title=body.message[:120])
        db.add(conversation)
        db.flush()
    history = [{"role": m.role, "content": m.content} for m in conversation.messages]
    context = ai_runtime.project_context(db, project)
    reply = ai_runtime.get_ai_service(db).chat(context, history, body.message)
    db.add(AIMessage(conversation_id=conversation.id, role="user", content=body.message))
    db.add(AIMessage(conversation_id=conversation.id, role="assistant", content=reply.content, provider=reply.provider, model=reply.model,
                     context_json={"results_sent": len(context.get("statistical_results") or []), "variables_sent": len(context.get("variables") or [])},
                     grounding_json={"source": reply.source, "notice": reply.notice, "check": reply.grounding}))
    audit.record(db, action="ai.chat", user_id=user.id, project_id=project.id, entity_type="ai_conversation", entity_id=conversation.id,
                 details={"source": reply.source, "grounded": (reply.grounding or {}).get("grounded")})
    db.commit()
    return {"conversation_id": conversation.id, **reply.as_dict()}


@router.get("/projects/{project_id}/ai/conversations")
def list_conversations(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    rows = db.scalars(select(AIConversation).where(AIConversation.project_id == project.id, AIConversation.user_id == user.id)
                      .order_by(AIConversation.id.desc()).limit(50))
    return {"conversations": [c.to_dict() for c in rows]}


@router.get("/ai/conversations/{conversation_id}")
def read_conversation(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = db.get(AIConversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise not_found("Conversation")
    get_project(db, conversation.project_id, user, READ)
    return conversation.to_dict(with_messages=True)


@router.post("/projects/{project_id}/assistant/draft")
def draft(project_id: int, body: AssistantDraftIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A draft for the user to review, or the questions the assistant needs answered first. Nothing is saved."""
    project = get_project(db, project_id, user, READ)
    try:
        if body.kind == "hypothesis":
            if body.research_question_id is None:
                raise bad_request("A research question is needed to draft a hypothesis.", code="missing_question")
            result = drafts.draft_hypothesis(db, project, body.research_question_id)
        elif body.kind == "chart_title":
            if not body.chart_type:
                raise bad_request("A chart type is needed to draft a title.", code="missing_chart")
            result = drafts.draft_chart_title(db, project, body.chart_type, body.x, body.y, body.hue)
        else:
            result = drafts.project_gaps(project)
    except ValueError as exc:
        raise bad_request(str(exc), code="draft_failed") from exc
    audit.record(db, action="assistant.suggestion", user_id=user.id, project_id=project.id, entity_type="project", entity_id=project.id,
                 details={"step": body.kind, "text": str(result.get("draft") or result.get("questions")), "source": "rule_engine"})
    db.commit()
    return {**result, "source": "rule_engine"}


@router.get("/projects/{project_id}/steps/summary")
def read_steps_summary(project_id: int, dataset_id: int | None = None, level: str | None = None,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Blocking and warning counts for every stage, and which earlier stages lock each one."""
    project = get_project(db, project_id, user, READ)
    try:
        return step_checks.summary(db, project, user, dataset_id, level)
    except ValueError as exc:
        raise bad_request(str(exc), code="unknown_level") from exc


@router.get("/projects/{project_id}/steps/{step}/check")
def read_step_check(project_id: int, step: str, dataset_id: int | None = None, level: str | None = None,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What must be fixed before the user moves past this step. Blocking items stop progress; warnings do not."""
    project = get_project(db, project_id, user, READ)
    try:
        return step_checks.check_step(db, project, step, user, dataset_id, level)
    except ValueError as exc:
        raise bad_request(str(exc), code="unknown_step") from exc


@router.post("/projects/{project_id}/assistant/decisions", status_code=201)
def log_assistant_decision(project_id: int, body: AssistantDecisionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Record a suggestion the assistant made, or the user's decision on it, in the audit log with a timestamp."""
    project = get_project(db, project_id, user, WRITE)
    audit.record(db, action=f"assistant.{body.kind}", user_id=user.id, project_id=project.id, entity_type="project", entity_id=project.id,
                 details={"step": body.step, "text": body.text, "decision": body.decision, "note": body.note})
    db.commit()
    return {"logged": True}