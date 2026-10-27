"""Automatic analysis for a whole project (workflow step 8).

For every research question (and for every hypothesis linked to it) the planner:

1. takes the dependent and independent variables linked to the question;
2. asks the rule engine (statistics/recommender) which tests fit those variables
   on the real data, and keeps only the tests that are implemented;
3. lets the AI choose one of those tests in the context of the whole analysis and
   write the reason for the methodology section (see AIService.choose_method).

Variables, candidate tests and assumption checks always come from the engine. The
AI can only pick from the engine's candidates. Items that cannot be analysed are
reported with the reason instead of being guessed at.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.service import AIService
from app.models import AnalysisRun, Dataset, DatasetVersion, Hypothesis, Project, ResearchQuestion, ResearchQuestionVariable, User, Variable
from app.analysis import variable_choice
from app.services import ai_runtime, analysis_service, dataset_service
from app.statistics import recommender
from app.statistics.registry import apply_filters
from app.statistics.utils import AnalysisError

PREDICTOR_ROLES = ("independent", "control", "moderator", "mediator")
LIVE_STATUSES = ("PENDING", "PROCESSING")


@dataclass
class Plan:
    research_question_id: int | None
    hypothesis_id: int | None
    status: str                          # "ready" or "skipped"
    reason: str | None = None            # why it was skipped, or the AI's reason when ready
    method: str | None = None
    method_name: str | None = None
    variables: dict | None = None
    justification: str | None = None
    source: str | None = None            # "llm" or "rule_engine"
    notice: str | None = None
    rule_method: str | None = None       # the engine's own first choice
    variables_source: str = "linked"    # "linked" (set on the question), "ai" (identified by the AI) or "rules" (chosen from the wording)
    variables_basis: str | None = None  # plain explanation of how the variables were chosen, when they were not set by the researcher
    filters: list[dict] = field(default_factory=list)   # rows left out of this comparison, e.g. groups with too few records
    filter_note: str | None = None      # plain explanation of those exclusions
    candidates: list[str] = field(default_factory=list)
    outcome: str | None = None
    predictors: list[str] | None = None
    recommendation: dict | None = None
    run_id: int | None = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _linked_variables(question: ResearchQuestion) -> tuple[str | None, list[str]]:
    links = question.to_dict()["variables"]
    outcome = next((v["name"] for v in links if v["role"] == "dependent"), None)
    predictors = [v["name"] for v in links if v["role"] in PREDICTOR_ROLES]
    return outcome, predictors


def items(project: Project) -> list[tuple[ResearchQuestion | None, Hypothesis | None]]:
    """Every analysis item: each question (once per linked hypothesis), and each hypothesis not linked to a question."""
    out: list[tuple[ResearchQuestion | None, Hypothesis | None]] = []
    for question in project.research_questions:
        linked = [h for h in project.hypotheses if h.research_question_id == question.id]
        out += [(question, h) for h in linked] if linked else [(question, None)]
    out += [(None, h) for h in project.hypotheses if h.research_question_id is None]
    return out


def _thin_groups(df, predictors: list[str]) -> tuple[list[dict], str | None]:
    """A grouping variable with groups of fewer than two records cannot be compared, so those groups are left out of this
    comparison (and the exclusion is stated with the answer). Returns no filter when nothing needs to be left out."""
    if not predictors or predictors[0] not in df.columns or pd.api.types.is_numeric_dtype(df[predictors[0]]):
        return [], None
    column = predictors[0]
    counts = df[column].dropna().astype(str).value_counts()
    small = [level for level, count in counts.items() if count < 2]
    keep = [level for level, count in counts.items() if count >= 2]
    if not small or len(keep) < 2:
        return [], None
    listed = ", ".join(f"'{level}' ({counts[level]} record{'s' if counts[level] != 1 else ''})" for level in small)
    note = f"Groups with fewer than two records were left out of this comparison: {listed}."
    return [{"column": column, "op": "in", "value": keep}], note


def plan_one(db: Session, project: Project, dataset: Dataset, df, schema: dict, ai: AIService,
             question: ResearchQuestion | None, hypothesis: Hypothesis | None) -> Plan:
    ids = {"research_question_id": question.id if question else None, "hypothesis_id": hypothesis.id if hypothesis else None}
    if question is None:
        return Plan(**ids, status="skipped", reason="Not linked to a research question, so the variables to analyse cannot be determined. "
                                                     "Link it to a question on the Hypotheses page.")
    outcome, predictors = _linked_variables(question)
    if not outcome:
        return Plan(**ids, status="skipped", reason=f"{question.code} has no dependent (outcome) variable, and none could be identified from the "
                                                    "question's wording. Link one on the Research questions page.")
    # groups too small to compare are left out first, so that the method is chosen for the groups that are actually compared
    filters, filter_note = _thin_groups(df, predictors)
    try:
        analysed = apply_filters(df, filters) if filters else df
        rec = recommender.recommend(analysed, schema, outcome=outcome, predictors=predictors, academic_level=project.academic_level,
                                    study_design=project.study_design, goal=question.text)
    except AnalysisError as exc:
        return Plan(**ids, status="skipped", reason=str(exc), outcome=outcome, predictors=predictors)

    candidates: list[dict] = []
    for option in [rec["primary"], *rec["alternatives"]]:
        if option["implemented"] and option["method"] not in {c["method"] for c in candidates}:
            candidates.append(option)
    if not candidates:
        return Plan(**ids, status="skipped", reason=f"The appropriate test ({rec['primary']['name']}) is not implemented in this version.",
                    outcome=outcome, predictors=predictors, recommendation=rec)

    rule_choice = candidates[0]["method"]          # the primary method when it is implemented
    focus = {"plan_for": {"research_question": question.to_dict(), "hypothesis": hypothesis.to_dict() if hypothesis else None},
             "candidates": [{"method": c["method"], "name": c["name"], "reason": c["reason"]} for c in candidates],
             "failed_assumptions_on_this_data": rec["failed_assumptions"],
             "method_recommendation": rec, "analysis_plan": _plan_overview(project)}
    context = ai_runtime.project_context(db, project, dataset, focus=focus)
    choice = ai.choose_method(context, focus["candidates"], rule_choice)
    chosen = next(c for c in candidates if c["method"] == choice["method"])
    return Plan(**ids, status="ready", method=chosen["method"], method_name=chosen["name"], variables=rec["config"]["variables"],
                justification=choice["reason"] or " ".join(rec["why"]), source=choice["source"], notice=choice.get("notice"),
                rule_method=rule_choice, candidates=[c["name"] for c in candidates],
                outcome=outcome, predictors=predictors, recommendation=rec, filters=filters, filter_note=filter_note)


def _plan_overview(project: Project) -> list[dict]:
    """The other research questions and hypotheses, so each choice fits the whole analysis."""
    questions = []
    for q in project.research_questions:
        outcome, predictors = _linked_variables(q)
        questions.append({"research_question": q.code, "text": q.text, "outcome": outcome, "predictors": predictors})
    return questions + [{"hypothesis": h.code, "alternative": h.alternative_text, "direction": h.direction} for h in project.hypotheses]


def unidentified_outcome_reason(code: str, ai_available: bool, failure_reason: str | None) -> str:
    """Why a question has no outcome variable, and what the researcher can do about it. Used on the status page and at analysis start."""
    if not ai_available:
        return (f"{code} has no dependent (outcome) variable. The AI assistant is turned off, so the outcome variable was not identified "
                "automatically. Link one on the Research questions page.")
    return (f"{code} has no dependent (outcome) variable. The AI assistant could not identify the outcome variable: {failure_reason}. "
            "Link one on the Research questions page, or try again.")


def link_missing_variables(db: Session, project: Project, dataset: Dataset, ai: AIService,
                           questions: list[ResearchQuestion]) -> tuple[dict[int, str], dict[int, str], dict[int, str]]:
    """Choose the outcome and predictor variables of each question that lacks them, and save them as links.

    The AI assistant is asked first. When it cannot answer, or its answer is unusable, the platform chooses from the wording of the
    question and the dataset's variable names (analysis/variable_choice.py), so every question can still be analysed. A question
    that compares or relates things also gets a predictor when none is linked. Links the researcher set are never changed.
    Returns (question id -> who chose the variables: "ai" or "rules"), (question id -> plain explanation of the choice) and
    (question id -> why the AI could not answer, for the questions it did not answer). A question is left without variables only
    when the dataset has nothing that can be analysed.
    """
    variables = list(db.scalars(select(Variable).where(Variable.dataset_id == dataset.id)))
    by_name = {v.name: v for v in variables}
    rows = [{"name": v.name, "label": v.label, "data_type": v.data_type, "role": v.role} for v in variables]
    chosen_by: dict[int, str] = {}
    basis: dict[int, str] = {}
    failed: dict[int, str] = {}

    def link(question: ResearchQuestion, dependent: str | None, independent: list[str]) -> None:
        # the table allows one row per question and variable, so a variable already linked changes role instead of being added again
        existing = {link.variable_id: link for link in question.variable_links}
        dependent_id = by_name[dependent].id if dependent else None
        if dependent_id is not None and not any(link.role == "dependent" for link in question.variable_links):
            if dependent_id in existing:
                existing[dependent_id].role = "dependent"
            else:
                question.variable_links.append(ResearchQuestionVariable(variable_id=dependent_id, role="dependent"))
        for name in independent:
            variable_id = by_name[name].id
            if variable_id in existing or variable_id == dependent_id:
                continue
            question.variable_links.append(ResearchQuestionVariable(variable_id=variable_id, role="independent"))
            existing[variable_id] = question.variable_links[-1]

    for question in questions:
        outcome, predictors = _linked_variables(question)
        if outcome:
            if predictors or not variable_choice.needs_predictor(question.text):
                continue
            choice = variable_choice.choose_variables(question.text, rows, dependent=outcome)
            if choice["independent"]:
                link(question, None, choice["independent"])
                chosen_by[question.id] = "rules"
                basis[question.id] = choice["basis"]
            continue
        focus = {"plan_for": {"research_question": question.to_dict(),
                              "hypotheses": [h.to_dict() for h in project.hypotheses if h.research_question_id == question.id]},
                 "dataset_variables": [{"name": v.name, "label": v.label, "type": v.data_type, "measurement_level": v.measurement_level}
                                       for v in variables]}
        result = ai.map_variables(ai_runtime.project_context(db, project, dataset, focus=focus), list(by_name))
        if result["status"] == "mapped":
            link(question, result["dependent"], result["independent"])
            chosen_by[question.id] = "ai"
            basis[question.id] = "identified by the AI assistant from the wording of the question"
            continue
        failed[question.id] = result["reason"]
        choice = variable_choice.choose_variables(question.text, rows)
        if choice["dependent"] is None:
            continue
        link(question, choice["dependent"], choice["independent"])
        chosen_by[question.id] = "rules"
        basis[question.id] = choice["basis"]
    db.flush()
    return chosen_by, basis, failed


def plan_project(db: Session, project: Project, dataset: Dataset, version: DatasetVersion, ai: AIService,
                 question_id: int | None = None, hypothesis_id: int | None = None) -> list[Plan]:
    """A plan for every item, or for the one question/hypothesis that was asked for."""
    question = next((q for q in project.research_questions if q.id == question_id), None) if question_id else None
    hypothesis = next((h for h in project.hypotheses if h.id == hypothesis_id), None) if hypothesis_id else None
    if hypothesis is not None and question is None and hypothesis.research_question_id:
        question = next((q for q in project.research_questions if q.id == hypothesis.research_question_id), None)
    pairs = [(question, hypothesis)] if (question_id is not None or hypothesis_id is not None) else items(project)

    mapped, bases, failed = link_missing_variables(db, project, dataset, ai, sorted({q.id: q for q, _ in pairs if q is not None}.values(), key=lambda q: q.id))
    df, schema = dataset_service.load_typed(db, version)
    plans = [plan_one(db, project, dataset, df, schema, ai, q, h) for q, h in pairs]
    for plan in plans:
        if plan.research_question_id in mapped:
            plan.variables_source = mapped[plan.research_question_id]
            plan.variables_basis = bases.get(plan.research_question_id)
        if plan.status == "skipped" and plan.research_question_id in failed:
            code = next(q.code for q in project.research_questions if q.id == plan.research_question_id)
            plan.reason = unidentified_outcome_reason(code, ai.available, failed[plan.research_question_id])
    return plans


def _existing_run(db: Session, project: Project, plan: Plan, version_id: int) -> AnalysisRun | None:
    """A run for the same question, hypothesis and method, on the SAME dataset version, that is pending, running, completed or failed.
    Runs on an older version do not count: the data has changed, so the analysis must be run again.
    A failed run is not retried automatically, because it fails again on the same data; use rerun to try again."""
    rows = db.scalars(select(AnalysisRun).where(
        AnalysisRun.project_id == project.id, AnalysisRun.analysis_type == "inferential", AnalysisRun.dataset_version_id == version_id,
        AnalysisRun.research_question_id == plan.research_question_id, AnalysisRun.status.in_(("PENDING", "PROCESSING", "COMPLETED", "FAILED")),
    ).order_by(AnalysisRun.id.desc()))
    for run in rows:
        config = run.config_json or {}
        if config.get("hypothesis_id") == plan.hypothesis_id and config.get("method") == plan.method:
            return run
    return None


def start_runs(db: Session, project: Project, user: User, version: DatasetVersion, dataset: Dataset, plans: list[Plan],
               rerun: bool = False) -> list[Plan]:
    """Create and start one inferential analysis per ready plan.

    A plan that already has a run for the same question, hypothesis and method is
    not started again; it is reported with the existing run. ``rerun=True`` starts it anyway.
    """
    for plan in plans:
        if plan.status != "ready":
            continue
        existing = None if rerun else _existing_run(db, project, plan, version.id)
        if existing is not None:
            plan.status = "skipped"
            if existing.status == "FAILED":
                plan.reason = (f"Already tried with {plan.method_name} (run {existing.id}), which failed: {existing.error_message or 'unknown error'} "
                               "Fix the data, then start it again.")
            else:
                plan.reason = (f"Already analysed with {plan.method_name} (run {existing.id}, {existing.status.lower()}). "
                               "Open that run, or start the analysis again.")
            plan.run_id = existing.id
            continue
        run = analysis_service.create_run(db, project, user, version, {
            "analysis_type": "inferential", "dataset_id": dataset.id, "method": plan.method, "name": f"{plan.method_name} (automatic)",
            "variables": plan.variables or {}, "params": {}, "research_question_id": plan.research_question_id,
            "hypothesis_id": plan.hypothesis_id, "justification": plan.justification, "filters": plan.filters,
            "automatic": {"source": plan.source, "notice": plan.notice, "rule_method": plan.rule_method, "candidates": plan.candidates,
                          "variables_source": plan.variables_source, "variables_basis": plan.variables_basis,
                          "filter_note": plan.filter_note},
        })
        plan.run_id = run.id
    return plans


def plan_summary(plans: list[Plan]) -> dict:
    return {"ready": sum(p.status == "ready" for p in plans), "skipped": sum(p.status == "skipped" for p in plans),
            "ai_chosen": sum(p.source == "llm" for p in plans)}


def overview(db: Session, project: Project, dataset: Dataset, version: DatasetVersion, ai: AIService) -> dict:
    """The page's view: for every item, its latest automatic run (with results) or why it has none yet.

    Questions without outcome or predictor variables are completed first, exactly as analysis start does. Accepted links are saved
    on the question (the caller commits them, see ai.py), so a question the AI can map becomes analysable on this page."""
    mapped, bases, failed = link_missing_variables(db, project, dataset, ai, list(project.research_questions))
    runs = db.scalars(select(AnalysisRun).where(
        AnalysisRun.project_id == project.id, AnalysisRun.analysis_type == "inferential", AnalysisRun.dataset_version_id == version.id,
    ).order_by(AnalysisRun.id.desc())).all()
    # the latest inferential run for each question and hypothesis, however it was started
    latest: dict[tuple, AnalysisRun] = {}
    for run in runs:
        config = run.config_json or {}
        latest.setdefault((run.research_question_id, config.get("hypothesis_id")), run)

    df, schema = dataset_service.load_typed(db, version)
    out = []
    for question, hypothesis in items(project):
        run = latest.get((question.id if question else None, hypothesis.id if hypothesis else None))
        item = {"research_question": question.to_dict() if question else None,
                "hypothesis": hypothesis.to_dict() if hypothesis else None}
        if run is not None:
            automatic = (run.config_json or {}).get("automatic") or {}
            justification = next(((t.params_json or {}).get("justification") for t in run.tests), None)
            item.update(run=run.to_dict(with_results=True), method_name=run.tests[0].method_name if run.tests else run.name,
                        status={"PENDING": "running", "PROCESSING": "running", "COMPLETED": "completed", "FAILED": "failed"}[run.status],
                        reason=justification, reason_source=automatic.get("source"), notice=automatic.get("notice"),
                        variables_source=automatic.get("variables_source", "linked"))
        else:
            plan = plan_one(db, project, dataset, df, schema, AIService(None), question, hypothesis)
            reason = plan.reason
            if plan.status == "skipped" and question is not None and question.id in failed:
                reason = unidentified_outcome_reason(question.code, ai.available, failed[question.id])
            item.update(run=None, method_name=plan.method_name, status="skipped" if plan.status == "skipped" else "not_run",
                        reason=reason if plan.status == "skipped" else "Not analysed yet. Use Rerun to analyse it.",
                        reason_source=None, notice=None,
                        variables_source=mapped.get(question.id, plan.variables_source) if question else plan.variables_source,
                        variables_basis=bases.get(question.id) if question else None)
        out.append(item)
    return {"dataset_version_id": version.id, "version_number": version.version_number,
            "running": any(i["status"] == "running" for i in out), "items": out, "linked_questions": sorted(mapped)}
