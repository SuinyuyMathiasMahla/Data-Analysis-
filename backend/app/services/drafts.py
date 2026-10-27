"""Drafts the assistant may offer: hypotheses from a question's linked variables, chart titles from the chart's axes, and the
questions it must ask for anything it cannot infer. A draft is only text returned to the user. Nothing is saved here."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, Project, Variable


def _name(variable: Variable) -> str:
    return variable.label or variable.name


def _unit(variable: Variable | None) -> str:
    return f" ({variable.unit})" if variable is not None and variable.unit else ""


def draft_hypothesis(db: Session, project: Project, research_question_id: int) -> dict:
    question = next((q for q in project.research_questions if q.id == research_question_id), None)
    if question is None:
        raise ValueError("Research question not found in this project.")
    linked = [(db.get(Variable, link.variable_id), link.role) for link in question.variable_links]
    outcomes = [v for v, role in linked if role == "dependent" and v is not None]
    predictors = [v for v, role in linked if role == "independent" and v is not None]
    questions: list[str] = []
    if not outcomes:
        questions.append("Which variable is the outcome this question is about? Set its role to dependent, or name it here.")
    if not predictors:
        questions.append("Which variable is the exposure or predictor? Set its role to independent, or name it here.")
    existing = [h for h in project.hypotheses if h.research_question_id == question.id]
    if existing and not questions:
        questions.append(f"{question.code} already has {existing[0].code}. Edit that hypothesis rather than adding another.")
    if questions:
        return {"kind": "hypothesis", "draft": None, "questions": questions}
    outcome, predictor = _name(outcomes[0]), _name(predictors[0])
    return {"kind": "hypothesis", "questions": [], "draft": {
        "null_text": f"There is no association between {predictor} and {outcome}.",
        "alternative_text": f"There is an association between {predictor} and {outcome}.",
    }, "note": "The wording is generic. Change it to the exact comparison the question asks (a difference, a prediction or an association)."}


def draft_chart_title(db: Session, project: Project, chart_type: str, x: str | None, y: str | None, hue: str | None) -> dict:
    variables = {v.name: v for v in db.scalars(select(Variable).where(Variable.project_id == project.id))}
    x_var, y_var = variables.get(x or ""), variables.get(y or "")
    questions: list[str] = []
    if x and x_var is None:
        raise ValueError(f"'{x}' is not a variable in this project.")
    if y and y_var is None:
        raise ValueError(f"'{y}' is not a variable in this project.")
    if y_var is not None and y_var.unit is None:
        questions.append(f"What unit is {_name(y_var)} measured in? The axis label needs it.")
    x_label = f"{_name(x_var)}{_unit(x_var)}" if x_var is not None else (x or "")
    y_label = f"{_name(y_var)}{_unit(y_var)}" if y_var is not None else ""
    if y_label:
        title = f"{y_label} by {x_label}" + (f", by {hue}" if hue else "")
    else:
        title = f"Distribution of {x_label}"
    return {"kind": "chart_title", "questions": questions, "draft": {
        "title": title, "x_label": x_label, "y_label": y_label or "Count", "chart_type": chart_type,
    }, "note": "Titles name the measures and the grouping. Add the one-line takeaway after you have read the chart."}


PROJECT_FIELDS = [
    ("research_problem", "Describe the problem the study addresses, in your own words."),
    ("general_objective", "State the aim of the study in one sentence."),
    ("study_population", "Who are the participants (population, age range, setting)?"),
    ("study_design", "What is the study design (for example cross-sectional, quasi-experimental, cohort)?"),
    ("sampling_technique", "How were participants selected (for example purposive, random)?"),
    ("sample_size", "How many participants were planned?"),
    ("data_collection_method", "How was the data collected (for example survey, measurement, records)?"),
]


def project_gaps(project: Project) -> dict:
    questions = [prompt for field, prompt in PROJECT_FIELDS if not getattr(project, field)]
    questions.append("Has ethics approval been granted? Give the committee, approval number and consent procedure.")
    return {"kind": "project_gaps", "draft": None, "questions": questions,
            "note": "The assistant does not write the project overview from memory. Answer these and it can help you word them."}
