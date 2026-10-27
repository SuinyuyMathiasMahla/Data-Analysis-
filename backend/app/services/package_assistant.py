"""The assistant's pass before a client package is built.

Each time the researcher clicks Build client package, this module runs the readiness gate and then works on what it finds:

- a hypothesis with no result: the planned analysis is re-planned; when it can run it is started, otherwise the reason is recorded;
- serious data problems left in the data: the automatic cleaning runs (the same as Clean data, with each step logged);
- every remaining issue gets a diagnosis (where it comes from and the next step) and an owner: "assistant" when the pass fixed or
  started it, "you" when only the researcher can decide it. The AI assistant writes the diagnosis when a provider is configured;
  otherwise fixed wording does.

The assistant never invents references, numbers or results, and it never chooses what a hypothesis should test.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from app.ai.service import AIService
from app.models import Dataset, Project, User
from app.reports import gate
from app.services import auto_analysis, dataset_service, report_service

RULE_DIAGNOSIS = {
    "missing_references": ("Paste the full reference for each method used (author, year, title, source). The assistant cannot create "
                           "citations, because that would mean inventing sources.", "you"),
    "unhandled_invalid_values": ("Serious data problems remain in the analysed data. The automatic cleaning should resolve them; if it cannot, "
                                 "the items it could not fix are listed on the Clean data page.", "assistant"),
    "number_mismatch": ("A sentence quotes a p-value that no table shows. Open that finding or conclusion and correct the number to the "
                        "value in the table.", "you"),
    "sample_size_mismatch": ("A sentence quotes a sample size that no table reports. Correct the sentence to the sample size in the tables.", "you"),
    "placeholder_text": ("A placeholder is still in the text. Replace it with the real content, or delete the sentence.", "you"),
    "empty_section": ("A section has nothing to report yet. Complete the step that feeds it.", "you"),
}


def _rule_explanation(issue: dict) -> str:
    return issue.get("diagnosis") or RULE_DIAGNOSIS.get(issue["code"], ("Check this item on the page it names.", "you"))[0]


def resolve(db: Session, project: Project, user: User, dataset: Dataset | None, ai: AIService, references: list[str],
            clean: Callable[[], dict] | None = None, explain: Callable[[list[dict]], dict | None] | None = None) -> dict:
    """One assistant pass. Returns {"actions": [...], "issues": [...]}; issues still open carry a diagnosis and an owner."""
    actions: list[dict] = []
    content, _ = report_service.build_report_content(db, project, user, project.title, dataset, None)
    issues = gate.check(content, references=references)

    # 1. serious data problems: run the automatic cleaning (every step is logged as a version)
    if clean is not None and any(i["code"] == "unhandled_invalid_values" for i in issues):
        summary = clean()
        actions.append({"code": "unhandled_invalid_values", "action": f"Cleaned the data automatically: quality score "
                        f"{summary['score_before']:.1f} → {summary['score_after']:.1f}."})
        content, _ = report_service.build_report_content(db, project, user, project.title, dataset, None)
        issues = gate.check(content, references=references)

    # 2. hypotheses without a result: start the planned analysis when it can run
    if dataset is not None and dataset.current_version is not None:
        version = dataset.current_version
        df, schema = dataset_service.load_typed(db, version)
        for issue in [i for i in issues if i["code"] == "hypothesis_without_result"]:
            hypothesis = next((h for h in project.hypotheses if h.code == issue["where"]), None)
            question = next((q for q in project.research_questions if hypothesis and q.id == hypothesis.research_question_id), None)
            plan = auto_analysis.plan_one(db, project, dataset, df, schema, ai, question, hypothesis)
            if plan.status == "ready":
                auto_analysis.start_runs(db, project, user, version, dataset, [plan])
                actions.append({"code": issue["code"], "action": f"Started {plan.method_name} for {issue['where']}. Build again when it "
                                                                 "has finished to include its result."})
                issue["fixed_by"], issue["diagnosis"] = "assistant", "The planned analysis has been started."
            else:
                issue["diagnosis"], issue["fixed_by"] = plan.reason, "you"

    # 3. diagnosis and owner for everything still open
    ai_text = explain(issues) if explain is not None and issues else None
    for issue in issues:
        if ai_text and issue["code"] in ai_text and not issue.get("diagnosis"):
            issue["diagnosis"] = ai_text[issue["code"]]
            issue["diagnosed_by"] = "ai_assistant"
        else:
            issue.setdefault("diagnosis", _rule_explanation(issue))
            issue.setdefault("diagnosed_by", "rules")
        issue.setdefault("fixed_by", RULE_DIAGNOSIS.get(issue["code"], ("", "you"))[1])
    return {"actions": actions, "issues": issues}
