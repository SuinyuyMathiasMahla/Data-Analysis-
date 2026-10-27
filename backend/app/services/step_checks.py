"""Step checks for the research wizard: what must be fixed before the user moves on.

Each check returns two lists. Blocking items stop the user from moving on; warnings are shown but do not stop them.
Every item carries a message, a fix and a short explanation written for the researcher's level. Checks only read stored
results; they never change data, settings or text.

Stages (the wizard's own keys): project, research_questions, hypotheses, dataset, quality, cleaning, exploration, analysis,
findings, conclusions, charts, report.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.cleaning import OPERATIONS
from app.models import Conclusion, Project, User, Visualization
from app.reports import gate
from app.reports.gate import SERIOUS_QUALITY_CODES
from app.services import dataset_service, project_service, report_service

STAGES = ("project", "research_questions", "hypotheses", "dataset", "quality", "cleaning", "exploration", "analysis",
          "findings", "conclusions", "charts", "report")

LEVELS = {"undergraduate": "student", "masters": "analyst", "phd": "expert"}

# One plain-language explanation per check code, for each level. Falls back to the message when a code has no entry.
WHY: dict[str, dict[str, str]] = {
    "impossible_value": {"student": "Values that cannot be real (for example a blood pressure of 1450) make averages and tests wrong.",
                         "analyst": "Impossible values inflate variance and bias means and regression slopes.",
                         "expert": "Out-of-range values violate measurement validity and distort estimates and their intervals."},
    "suspicious_code": {"student": "Codes such as 999 are placeholders for missing data. Left in, they look like very large measurements.",
                        "analyst": "A sentinel such as 999 is read as a real value unless it is recoded to missing.",
                        "expert": "Unrecoded sentinel codes contaminate the distribution and any model using the variable."},
    "inconsistent_category": {"student": "The same answer written two ways (for example 'Female' and 'female ') is counted as two groups.",
                              "analyst": "Spelling variants split one category into several, which changes group sizes and frequency tables.",
                              "expert": "Category variants inflate the number of levels and bias comparisons across groups."},
    "duplicate_rows": {"student": "The same record counted twice gives it extra weight.",
                       "analyst": "Duplicates double-count observations and understate standard errors.",
                       "expert": "Duplicate rows violate independence and shrink standard errors."},
    "missing_values": {"student": "Participants with missing answers may differ from those who answered.",
                       "analyst": "Missing values reduce the sample; check whether they are random before choosing a method.",
                       "expert": "Missingness mechanism determines bias; state the handling and run a sensitivity analysis."},
    "hypothesis_untested": {"student": "Every planned question should have a test; an untested hypothesis has no answer.",
                            "analyst": "An untested hypothesis cannot be decided, so it cannot appear in the conclusions.",
                            "expert": "An untested primary hypothesis leaves the study's main inference undefined."},
    "rq_without_hypothesis": {"student": "Each question needs one testable hypothesis, so the test can answer it.",
                              "analyst": "Without a hypothesis a question cannot be linked to a test or a decision.",
                              "expert": "Each research question needs one pre-specified hypothesis to control the inferential path."},
    "rq_multiple_hypotheses": {"student": "One question should have one hypothesis, so each answer is clear.",
                               "analyst": "Several hypotheses per question multiply the tests and the risk of false positives.",
                               "expert": "Multiple hypotheses per question need a pre-specified primary and an adjustment plan."},
}


def _level(project: Project) -> str:
    return LEVELS.get(project.academic_level, "analyst")


def _item(code: str, message: str, fix: str, level: str, severity: str = "blocking") -> dict:
    return {"code": code, "severity": severity, "message": message, "fix": fix,
            "why": WHY.get(code, {}).get(level, message)}


def _fix_for(issue: dict) -> str:
    label = OPERATIONS.get((issue.get("suggestion") or {}).get("operation"), {}).get("label")
    if label:
        return f"Suggested fix: {label}. Review it and approve it in the cleaning step; nothing changes until you do."
    return "Decide how to handle these values in the cleaning step, and record the reason."


def _project(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    blocking, warnings = [], []
    if not project.general_objective:
        warnings.append(_item("aim_missing", "The project has no aim (general objective).", "Write the aim in the project overview.", level, "warning"))
    if not project.research_problem:
        warnings.append(_item("problem_missing", "The project has no problem statement.", "Describe the problem the study addresses.", level, "warning"))
    if not project.study_design:
        warnings.append(_item("design_missing", "The study design is not recorded.", "Name the design (for example cross-sectional, quasi-experimental).", level, "warning"))
    warnings.append(_item("ethics_reminder", "State the ethics approval number and the consent procedure in the report.",
                          "Add them to the project overview before generating the report.", level, "warning"))
    return {"blocking": blocking, "warnings": warnings}


def _research_questions(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    blocking, warnings = [], []
    questions = list(project.research_questions)
    if not questions:
        blocking.append(_item("no_research_questions", "No research question has been defined.", "Add at least one question that links to the aim.", level))
    texts = [q.text.strip().lower() for q in questions]
    for q in questions:
        if not q.variable_links:
            warnings.append(_item("rq_without_variables", f"{q.code} is not linked to any variable.",
                                  "Link the variables the question is about, so the test can be chosen.", level, "warning"))
    for q in questions:
        if texts.count(q.text.strip().lower()) > 1:
            warnings.append(_item("rq_duplicated", f"{q.code} repeats the text of another question.", "Keep one and remove the duplicate.", level, "warning"))
    return {"blocking": blocking, "warnings": warnings}


def _hypotheses(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    blocking, warnings = [], []
    for q in project.research_questions:
        linked = [h for h in project.hypotheses if h.research_question_id == q.id]
        if not linked:
            blocking.append(_item("rq_without_hypothesis", f"{q.code} has no hypothesis.", "Write H0 and H1 for this question.", level))
        elif len(linked) > 1:
            blocking.append(_item("rq_multiple_hypotheses", f"{q.code} has {len(linked)} hypotheses; each question needs exactly one.",
                                  "Keep one hypothesis for this question and move the rest.", level))
    if project.hypotheses and not any(h.research_question_id for h in project.hypotheses):
        warnings.append(_item("hypotheses_unlinked", "No hypothesis is linked to a research question.", "Link each hypothesis to its question.", level, "warning"))
    return {"blocking": blocking, "warnings": warnings}


def _dataset(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    dataset = project_service.primary_dataset(db, project.id, dataset_id)
    if dataset is None or dataset.current_version is None:
        return {"blocking": [_item("no_dataset", "No dataset has been uploaded.", "Upload the dataset in the upload step.", level)], "warnings": []}
    variables = dataset_service.data_dictionary(db, dataset, dataset.current_version)
    warnings = []
    if not any(v.get("role") == "dependent" for v in variables):
        warnings.append(_item("no_outcome_role", "No variable is marked as the outcome.",
                              "Confirm each variable's role (dependent, independent, control, identifier) in the data dictionary.", level, "warning"))
    return {"blocking": [], "warnings": warnings}


def _quality(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    dataset = project_service.primary_dataset(db, project.id, dataset_id)
    if dataset is None or dataset.current_version is None:
        return {"blocking": [_item("no_dataset", "No dataset has been uploaded.", "Upload the dataset in the upload step.", level)], "warnings": []}
    report = dataset_service.latest_quality_report(db, dataset.current_version.id)
    if report is None:
        return {"blocking": [_item("quality_not_checked", "The data quality check has not been run for this dataset version.",
                                   "Run the data quality check.", level)], "warnings": []}
    blocking, warnings = [], []
    for issue in report.to_dict().get("issues") or []:
        where = f" in '{issue['column']}'" if issue.get("column") else ""
        if issue["code"] in SERIOUS_QUALITY_CODES:
            blocking.append(_item(issue["code"], f"{issue['message']}{where} Unhandled, it biases every result that uses this variable.",
                                  _fix_for(issue), level))
        elif issue["code"] in {"duplicate_rows", "missing_values"}:
            warnings.append(_item(issue["code"], f"{issue['message']}{where}", _fix_for(issue), level, "warning"))
    return {"blocking": blocking, "warnings": warnings}


def _exploration(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    warnings = [_item("exploration_overread", "Exploratory results are hypothesis-generating. Do not decide hypotheses from them, and remember that "
                      "many comparisons raise the chance of a false positive.",
                      "Use the planned tests in the analysis step to answer the questions.", level, "warning")]
    return {"blocking": [], "warnings": warnings}


def _analysis(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    content, _ = report_service.build_report_content(db, project, user, project.title,
                                                     project_service.primary_dataset(db, project.id, dataset_id), None)
    blocking, warnings = [], []
    for index, h in enumerate(content.get("hypotheses") or []):
        if h.get("test") is not None or h.get("not_tested_reason"):
            continue
        # Hypotheses carry no recorded reason field, so an untested hypothesis always needs a test run.
        item = _item("hypothesis_untested", f"{h['code']} has no analysis result.",
                     "Run the planned test for this hypothesis in the analysis step.", level, severity="blocking" if index == 0 else "warning")
        (blocking if index == 0 else warnings).append(item)
    return {"blocking": blocking, "warnings": warnings}


def _findings(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    content, _ = report_service.build_report_content(db, project, user, project.title,
                                                     project_service.primary_dataset(db, project.id, dataset_id), None)
    explained = {f.get("analysis_result_id") for f in content.get("findings") or []}
    warnings = []
    for test in content.get("inferential") or []:
        if test["result_id"] not in explained:
            warnings.append(_item("test_not_explained", f"{test['method_name']} ({test.get('hypothesis_code') or 'no hypothesis'}) has no finding.",
                                  "Write a finding that explains this result with its effect size and 95% CI.", level, "warning"))
    return {"blocking": [], "warnings": warnings}


def _conclusions(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    blocking, warnings = [], []
    conclusions = list(db.scalars(select(Conclusion).where(Conclusion.project_id == project.id)))
    if not conclusions:
        blocking.append(_item("no_conclusions", "No conclusion has been written.", "Draft conclusions tied to specific findings.", level))
    for c in conclusions:
        if not c.findings:
            warnings.append(_item("conclusion_unlinked", "A conclusion is not linked to any finding.",
                                  "Link it to the finding it rests on.", level, "warning"))
    return {"blocking": blocking, "warnings": warnings}


def _charts(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    warnings = []
    for viz in db.scalars(select(Visualization).where(Visualization.project_id == project.id, Visualization.include_in_report.is_(True))
                          .order_by(Visualization.id)):
        if not (viz.title or "").strip():
            warnings.append(_item("chart_untitled", "A chart included in the report has no title.",
                                  "Give the chart a title that says what it shows.", level, "warning"))
    return {"blocking": [], "warnings": warnings}


def _report(db: Session, project: Project, level: str, dataset_id, user) -> dict:
    dataset = project_service.primary_dataset(db, project.id, dataset_id)
    content, _ = report_service.build_report_content(db, project, user, project.title, dataset, None)
    # the reference list is supplied on the package form, so it is not a blocker for moving through this step
    issues = [i for i in gate.check(content, references=None) if i["code"] != "missing_references"]
    return {"blocking": [_item(i["code"], i["message"], i["action"], level) for i in issues], "warnings": []}


CHECKS = {
    "project": _project, "research_questions": _research_questions, "hypotheses": _hypotheses, "dataset": _dataset,
    "quality": _quality, "cleaning": _quality, "exploration": _exploration, "analysis": _analysis, "findings": _findings,
    "conclusions": _conclusions, "charts": _charts, "report": _report,
}


LEVEL_NAMES = ("student", "analyst", "expert")


def check_step(db: Session, project: Project, step: str, user: User, dataset_id: int | None = None, level: str | None = None) -> dict:
    """The blocking issues and warnings for one stage. Unknown stages or levels raise ValueError.
    ``level`` overrides the level derived from the project's academic level."""
    if step not in CHECKS:
        raise ValueError(f"Unknown step '{step}'.")
    if level is not None and level not in LEVEL_NAMES:
        raise ValueError(f"Unknown level '{level}'.")
    chosen = level or _level(project)
    result = CHECKS[step](db, project, chosen, dataset_id, user)
    return {"step": step, "level": chosen, "passed": not result["blocking"], **result}


# Which earlier stages must have no blocking items before a stage can be opened. Quality and cleaning are fixed together, so
# cleaning is not gated by quality; analysis needs clean data and a complete question set.
GATES: dict[str, tuple[str, ...]] = {
    "project": (), "research_questions": (), "hypotheses": (), "dataset": (),
    "quality": (), "cleaning": (), "charts": (),
    "exploration": ("quality", "cleaning"),
    "analysis": ("research_questions", "hypotheses", "quality", "cleaning"),
    "findings": (),                       # findings explain the analyses that did complete; untested items do not lock them
    "conclusions": ("findings",),
    "report": ("research_questions", "hypotheses", "quality", "cleaning", "analysis", "findings", "conclusions"),
}


def summary(db: Session, project: Project, user: User, dataset_id: int | None = None, level: str | None = None) -> dict:
    """Blocking and warning counts for every stage, and which stages each one is locked by."""
    counts = {}
    for stage in STAGES:
        result = check_step(db, project, stage, user, dataset_id, level)
        counts[stage] = {"blocking": len(result["blocking"]), "warnings": len(result["warnings"])}
    stages = {}
    for stage in STAGES:
        locked_by = [s for s in GATES.get(stage, ()) if counts[s]["blocking"] > 0]
        stages[stage] = {**counts[stage], "locked_by": locked_by}
    return {"stages": stages}
