"""Analysis jobs.

A run is created in state PENDING and executed by a worker thread
(PROCESSING -> COMPLETED | FAILED). The frontend polls GET /api/analysis/{id}.
With ANALYSIS_SYNC=true (tests) the job runs inline.

Everything needed to repeat a run is stored on it: the exact dataset version,
the variables, parameters, filters, the schema that was in force and the
library versions.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import eda
from app.core.config import get_settings
from app.core.errors import bad_request
from app.database.session import SessionLocal
from app.models import AnalysisResult, AnalysisRun, DatasetVersion, Hypothesis, Project, StatisticalTest, User
from app.models.base import utcnow
from app.services import audit, dataset_service
from app.statistics import descriptive, power
from app.statistics.registry import METHODS, apply_filters, run_method
from app.statistics.utils import AnalysisError, software_versions

logger = logging.getLogger("app.analysis")
_executor: ThreadPoolExecutor | None = None


def _pool() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=get_settings().ANALYSIS_WORKERS, thread_name_prefix="analysis")
    return _executor


def submit(run_id: int) -> None:
    if get_settings().ANALYSIS_SYNC:
        execute_run(run_id)
    else:
        _pool().submit(execute_run, run_id)


# --------------------------------------------------------------------------- #
# creating runs and tests
# --------------------------------------------------------------------------- #
def _validate_method(method: str | None) -> dict:
    if not method or method not in METHODS:
        raise bad_request("Choose a statistical method.", "unknown_method")
    return METHODS[method]


def _add_test(db: Session, run: AnalysisRun, *, method: str, variables: dict, params: dict, hypothesis_id: int | None,
              justification: str | None) -> StatisticalTest:
    spec = _validate_method(method)
    if hypothesis_id is not None:
        hypothesis = db.get(Hypothesis, hypothesis_id)
        if hypothesis is None or hypothesis.project_id != run.project_id:
            raise bad_request("The hypothesis does not belong to this project.")
        params = {"alpha": float(hypothesis.alpha), **params}       # the hypothesis' alpha unless overridden
    test = StatisticalTest(analysis_run_id=run.id, hypothesis_id=hypothesis_id, method=method, method_name=spec["name"],
                           variables_json=variables, params_json={**params, **({"justification": justification} if justification else {})},
                           status="PENDING")
    db.add(test)
    db.flush()
    return test


def create_run(db: Session, project: Project, user: User, version: DatasetVersion | None, body: dict) -> AnalysisRun:
    analysis_type = body["analysis_type"]
    if version is None:
        raise bad_request("Choose a dataset for this analysis. (For sample-size planning before data collection, use POST /api/power.)")
    schema = dataset_service.schema_for(db, version)
    method = body.get("method")
    name = body.get("name") or {
        "eda": "Exploratory data analysis", "descriptive": "Descriptive statistics", "power": "Power and sample-size analysis",
    }.get(analysis_type) or METHODS.get(method or "", {}).get("name", "Statistical analysis")
    config = {"analysis_type": analysis_type, "method": method, "variables": body.get("variables") or {}, "params": body.get("params") or {},
              "hypothesis_id": body.get("hypothesis_id"), "justification": body.get("justification"), "schema": schema,
              "automatic": body.get("automatic")}
    # a run for a hypothesis belongs to that hypothesis's research question, even when the question was not picked separately
    research_question_id = body.get("research_question_id")
    if research_question_id is None and config["hypothesis_id"]:
        hypothesis = db.get(Hypothesis, config["hypothesis_id"])
        research_question_id = hypothesis.research_question_id if hypothesis and hypothesis.project_id == project.id else None
    run = AnalysisRun(project_id=project.id, dataset_version_id=version.id, research_question_id=research_question_id,
                      reproduced_from_id=body.get("reproduced_from_id"), name=name[:255], analysis_type=analysis_type, status="PENDING",
                      config_json=config, filters_json=body.get("filters") or [], created_by=user.id)
    db.add(run)
    db.flush()
    if analysis_type == "inferential":
        _add_test(db, run, method=method, variables=config["variables"], params=config["params"],
                  hypothesis_id=config["hypothesis_id"], justification=config["justification"])
    audit.record(db, action="analysis.created", user_id=user.id, project_id=project.id, entity_type="analysis_run", entity_id=run.id,
                 details={"name": run.name, "analysis_type": analysis_type, "method": method, "dataset_version": version.version_number,
                          "reproduced_from": run.reproduced_from_id})
    db.commit()
    submit(run.id)
    return reload_run(db, run.id)


def reload_run(db: Session, run_id: int) -> AnalysisRun:
    """Fresh copy of a run after the worker (another session) has changed it."""
    db.expire_all()
    return db.get(AnalysisRun, run_id)


def add_test(db: Session, run: AnalysisRun, user: User, body: dict) -> AnalysisRun:
    """Add a further statistical test to an existing run (same dataset version)."""
    if run.status in ("PENDING", "PROCESSING"):
        raise bad_request("This analysis is still running. Wait for it to finish before adding a test.", "analysis_busy")
    _add_test(db, run, method=body["method"], variables=body["variables"], params=body.get("params") or {},
              hypothesis_id=body.get("hypothesis_id"), justification=body.get("justification"))
    run.status, run.error_message = "PENDING", None
    audit.record(db, action="analysis.test_added", user_id=user.id, project_id=run.project_id, entity_type="analysis_run",
                 entity_id=run.id, details={"method": body["method"]})
    db.commit()
    submit(run.id)
    return reload_run(db, run.id)


def reproduce(db: Session, run: AnalysisRun, project: Project, user: User) -> AnalysisRun:
    """Re-run an earlier analysis with its stored configuration on the SAME
    dataset version, as a new run that points back to the original."""
    config = dict(run.config_json or {})
    new_run = AnalysisRun(project_id=project.id, dataset_version_id=run.dataset_version_id, research_question_id=run.research_question_id,
                          reproduced_from_id=run.id, name=f"{run.name} (reproduction)"[:255], analysis_type=run.analysis_type,
                          status="PENDING", config_json=config, filters_json=run.filters_json or [], created_by=user.id)
    db.add(new_run)
    db.flush()
    for test in run.tests:
        db.add(StatisticalTest(analysis_run_id=new_run.id, hypothesis_id=None, method=test.method, method_name=test.method_name,
                               variables_json=test.variables_json, params_json=test.params_json, status="PENDING"))
    audit.record(db, action="analysis.reproduced", user_id=user.id, project_id=project.id, entity_type="analysis_run",
                 entity_id=new_run.id, details={"original_run": run.id})
    db.commit()
    submit(new_run.id)
    return reload_run(db, new_run.id)


def compare_runs(original: AnalysisRun, copy: AnalysisRun) -> dict:
    """Did the reproduction give the same numbers?"""
    rows, identical = [], True
    for a, b in zip(original.results, copy.results):
        same = True
        for field in ("statistic_value", "p_value", "effect_size_value"):
            x, y = getattr(a, field), getattr(b, field)
            if (x is None) != (y is None) or (x is not None and abs(x - y) > 1e-9 * max(1.0, abs(x))):
                same = False
        identical &= same
        rows.append({"result_type": a.result_type, "original": {"statistic": a.statistic_value, "p_value": a.p_value},
                     "reproduction": {"statistic": b.statistic_value, "p_value": b.p_value}, "identical": same})
    if len(original.results) != len(copy.results):
        identical = False
    return {"identical": identical, "results": rows, "original_software": original.software_json, "reproduction_software": copy.software_json}


# --------------------------------------------------------------------------- #
# execution
# --------------------------------------------------------------------------- #
def _store_result(db: Session, run: AnalysisRun, payload: dict, result_type: str, test: StatisticalTest | None = None) -> AnalysisResult:
    statistic = payload.get("statistic") or {}
    effect = next((e for e in payload.get("effect_sizes") or [] if e.get("value") is not None), {})
    df = payload.get("df")
    row = AnalysisResult(analysis_run_id=run.id, statistical_test_id=test.id if test else None, result_type=result_type,
                         statistic_name=statistic.get("name"), statistic_value=statistic.get("value"),
                         degrees_of_freedom=None if df is None else str(df)[:60], p_value=payload.get("p_value"),
                         effect_size_name=(effect.get("name") or None) and effect["name"][:60], effect_size_value=effect.get("value"),
                         is_significant=payload.get("significant"), sample_size=payload.get("n"), result_json=payload,
                         engine_summary=payload.get("summary"))
    db.add(row)
    return row


def execute_run(run_id: int) -> None:
    """Worker entry point. Uses its own database session."""
    db = SessionLocal()
    try:
        run = db.get(AnalysisRun, run_id)
        if run is None:
            return
        run.status, run.started_at, run.progress, run.error_message = "PROCESSING", utcnow(), 5, None
        db.commit()
        try:
            _execute(db, run)
            failed = [t for t in run.tests if t.status == "FAILED"]
            if failed and len(failed) == len(run.tests):
                run.status, run.error_message = "FAILED", failed[-1].error_message
            else:
                run.status = "COMPLETED"
        except AnalysisError as exc:                     # user-fixable: show the message
            db.rollback()
            run = db.get(AnalysisRun, run_id)
            run.status, run.error_message = "FAILED", str(exc)
        except Exception:                                # unexpected: log details, show a generic message
            logger.exception("Analysis run %s crashed", run_id)
            db.rollback()
            run = db.get(AnalysisRun, run_id)
            run.status, run.error_message = "FAILED", "The analysis failed because of an internal error. No results were produced."
        run.progress, run.completed_at = 100, utcnow()
        audit.record(db, action=f"analysis.{run.status.lower()}", user_id=run.created_by, project_id=run.project_id,
                     entity_type="analysis_run", entity_id=run.id, details={"name": run.name, "error": run.error_message})
        db.commit()
    finally:
        db.close()


def _execute(db: Session, run: AnalysisRun) -> None:
    config = run.config_json or {}
    version = db.get(DatasetVersion, run.dataset_version_id)
    schema = config.get("schema") or dataset_service.schema_for(db, version)
    run.software_json = software_versions()
    filters = run.filters_json or []

    if run.analysis_type == "power":
        if not any(r.result_type == "power" for r in run.results):
            _store_result(db, run, power.run_power_analysis(**(config.get("params") or {})), "power")
        db.commit()
        return

    df, schema = dataset_service.load_typed(db, version, schema)
    run.progress = 30
    db.commit()

    if run.analysis_type == "eda":
        if not any(r.result_type == "eda" for r in run.results):
            _store_result(db, run, eda.run_eda(apply_filters(df, filters), schema), "eda")
    elif run.analysis_type == "descriptive":
        if not any(r.result_type == "descriptive" for r in run.results):
            variables = config.get("variables") or {}
            payload = descriptive.run_descriptive(apply_filters(df, filters), schema, variables.get("variables") or None,
                                                  variables.get("group_by") or None)
            payload["filters"] = filters
            _store_result(db, run, payload, "descriptive")
    else:
        pending = [t for t in run.tests if t.status == "PENDING"]
        for index, test in enumerate(pending):
            test.status = "PROCESSING"
            db.commit()
            params = {k: v for k, v in (test.params_json or {}).items() if k != "justification"}
            try:
                payload = run_method(df, schema, test.method, test.variables_json, params, filters)
            except AnalysisError as exc:
                test.status, test.error_message, test.completed_at = "FAILED", str(exc), utcnow()
                db.commit()
                continue
            payload["dataset_version"] = version.version_number
            _store_result(db, run, payload, "test", test)
            test.status, test.completed_at = "COMPLETED", utcnow()
            if test.hypothesis_id and payload.get("decision"):
                hypothesis = db.get(Hypothesis, test.hypothesis_id)
                if hypothesis is not None:
                    hypothesis.decision = payload["decision"]
            run.progress = 30 + int(65 * (index + 1) / len(pending))
            db.commit()
    db.commit()


def project_results(db: Session, project_id: int, completed_only: bool = True) -> list[AnalysisResult]:
    query = select(AnalysisResult).join(AnalysisRun, AnalysisRun.id == AnalysisResult.analysis_run_id).where(AnalysisRun.project_id == project_id)
    if completed_only:
        query = query.where(AnalysisRun.status == "COMPLETED")
    return list(db.scalars(query.order_by(AnalysisResult.id)))
