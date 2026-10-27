"""Projects, objectives, research questions, hypotheses, members, dashboard."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import READ, WRITE, get_current_user, get_project, project_rights, require_permission
from app.core.errors import ApiError, bad_request, not_found
from app.database.session import get_db
from app.models import Hypothesis, Objective, Project, ProjectMember, ResearchQuestion, ResearchQuestionVariable, User, Variable
from app.schemas.requests import CostsIn, HypothesisIn, MemberIn, ProjectIn, ProjectUpdateIn, ReportDetailsIn, ResearchQuestionIn
from app.services import audit, auth_service, client_store, evidence_state, project_costs, project_service, report_details
from app.services.storage import get_storage

router = APIRouter(tags=["projects"])


@router.get("/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return project_service.dashboard(db, user)


@router.get("/projects")
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = project_service.accessible_projects(db, user)
    rows = []
    for p in projects:
        costs = project_costs.get(p.id)                 # read once per project; the file is not read again for the currency
        rows.append({**project_service.with_client(p.id, p.to_dict()), "progress": project_service.progress(db, p),
                     "approximate_cost": costs["total"], "cost_currency": costs["currency"],
                     "my_role": "owner" if p.owner_id == user.id else next((m.member_role for m in p.members if m.user_id == user.id), None)})
    return {"projects": rows}


def _set_objectives(project: Project, objectives: list[str] | None) -> None:
    if objectives is None:
        return
    project.objectives = [Objective(position=i, text=text.strip()) for i, text in enumerate(objectives) if text and text.strip()]


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, user: User = Depends(require_permission("project.manage_own")), db: Session = Depends(get_db)):
    details = {"project_type": body.project_type, **project_service.client_details(body.project_type, body.model_dump())}
    data = body.model_dump(exclude={"objectives", "project_type", *project_service.CLIENT_FIELDS})
    project = Project(owner_id=user.id, **data)
    _set_objectives(project, body.objectives)
    db.add(project)
    db.flush()
    audit.record(db, action="project.created", user_id=user.id, project_id=project.id, entity_type="project", entity_id=project.id,
                 details={"title": project.title, "academic_level": project.academic_level, "project_type": body.project_type})
    db.commit()
    db.refresh(project)
    client_store.put(project.id, details)
    return project_service.with_client(project.id, project.to_dict(full=True))


@router.get("/projects/{project_id}")
def read_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    return {**project_service.with_client(project.id, project.to_dict(full=True)), "progress": project_service.progress(db, project),
            "rights": sorted(project_rights(db, project, user)),
            "research_questions": project_service.question_dicts(project), "hypotheses": project_service.hypothesis_dicts(project),
            "datasets": [d.to_dict() for d in project_service.datasets_of(db, project.id)]}


@router.put("/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    changes = body.model_dump(exclude_unset=True, exclude={"objectives"})
    for field in ("title", "academic_level", "status"):
        if field in changes and changes[field] is None:
            raise bad_request(f"{field} cannot be empty.")
    current = client_store.get(project.id)
    if "project_type" in changes and changes.pop("project_type") != current["project_type"]:
        raise bad_request("A project's type cannot be changed after it is created.")
    client_changes = {field: changes.pop(field) for field in project_service.CLIENT_FIELDS if field in changes}
    if current["project_type"] == "client" or client_changes:
        details = project_service.client_details(current["project_type"], {**current, **client_changes})
        client_store.put(project.id, {"project_type": current["project_type"], **details})
    changed = {k: v for k, v in changes.items() if getattr(project, k) != v}
    for field, value in changed.items():
        setattr(project, field, value)
    if "objectives" in body.model_fields_set:
        _set_objectives(project, body.objectives or [])
    audit.record(db, action="project.updated", user_id=user.id, project_id=project.id, entity_type="project", entity_id=project.id,
                 details={"fields": sorted(changed)})
    db.commit()
    db.refresh(project)
    return project_service.with_client(project.id, project.to_dict(full=True))


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    if project.owner_id != user.id and not user.is_admin:
        raise ApiError(403, "forbidden", "Only the project owner can delete a project.")
    keys = project_service.storage_keys(db, project.id) + [client_store.storage_key(project.id), report_details.storage_key(project.id),
                                                           project_costs.storage_key(project.id), evidence_state.storage_key(project.id)]
    audit.record(db, action="project.deleted", user_id=user.id, entity_type="project", entity_id=project.id, details={"title": project.title})
    for dataset in project_service.datasets_of(db, project.id):
        dataset.current_version_id = None            # break the datasets <-> dataset_versions cycle before the cascade
    db.flush()
    db.delete(project)
    db.commit()
    for key in keys:                                 # remove the files only after the database delete has succeeded
        get_storage().delete(key)
    return {"message": "Project deleted."}


# ---- report details (background, references, ethics) --------------------------
@router.get("/projects/{project_id}/report-details")
def read_report_details(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    return report_details.get(project.id)


@router.put("/projects/{project_id}/report-details")
def update_report_details(project_id: int, body: ReportDetailsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    details = {**body.model_dump(), "references": [r.strip() for r in body.references if r.strip()]}
    report_details.put(project.id, details)
    audit.record(db, action="report_details.updated", user_id=user.id, project_id=project.id, entity_type="project", entity_id=project.id)
    db.commit()
    return details


# ---- approximate costs (entered by the researcher) ------------------------------
@router.get("/projects/{project_id}/costs")
def read_costs(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    return project_costs.get(project.id)


@router.put("/projects/{project_id}/costs")
def update_costs(project_id: int, body: CostsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    saved = project_costs.put(project.id, body.currency.strip(), [{**item.model_dump(), "description": item.description.strip()} for item in body.items])
    audit.record(db, action="project.costs_updated", user_id=user.id, project_id=project.id, entity_type="project", entity_id=project.id,
                 details={"items": len(body.items), "total": saved["total"]})
    db.commit()
    return saved


# ---- members (explicit collaboration permissions) ----------------------------
@router.post("/projects/{project_id}/members", status_code=201)
def add_member(project_id: int, body: MemberIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    if project.owner_id != user.id and not user.is_admin:
        raise ApiError(403, "forbidden", "Only the project owner can manage members.")
    target = auth_service.find_user(db, body.email)
    if target is None:
        raise not_found("A user with that e-mail address")
    if target.id == project.owner_id:
        raise bad_request("The owner already has full access.")
    if body.member_role == "supervisor" and "supervisor" not in target.role_names and not target.is_admin:
        raise bad_request("That account does not have the supervisor role. An administrator can grant it.")
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == target.id))
    if member is None:
        member = ProjectMember(project_id=project.id, user_id=target.id, member_role=body.member_role)
        db.add(member)
    else:
        member.member_role = body.member_role
    audit.record(db, action="project.member_added", user_id=user.id, project_id=project.id, entity_type="user", entity_id=target.id,
                 details={"member_role": body.member_role})
    audit.notify(db, user_id=target.id, project_id=project.id, type="membership",
                 title=f"You were added to '{project.title}' as {body.member_role}")
    db.commit()
    db.refresh(project)
    return {"members": [m.to_dict() for m in project.members]}


@router.delete("/projects/{project_id}/members/{member_id}")
def remove_member(project_id: int, member_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    if project.owner_id != user.id and not user.is_admin:
        raise ApiError(403, "forbidden", "Only the project owner can manage members.")
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project.id:
        raise not_found("Member")
    audit.record(db, action="project.member_removed", user_id=user.id, project_id=project.id, entity_type="user", entity_id=member.user_id)
    db.delete(member)
    db.commit()
    return {"message": "Member removed."}


# ---- research questions -------------------------------------------------------
def _link_variables(db: Session, project: Project, question: ResearchQuestion, links: list[dict] | None) -> None:
    if links is None:
        return
    question.variable_links = []
    db.flush()
    seen: set[int] = set()
    for link in links:
        variable = db.get(Variable, int(link.get("variable_id", 0)))
        if variable is None or variable.project_id != project.id:
            raise bad_request("A linked variable does not belong to this project.")
        if variable.id in seen:
            continue
        seen.add(variable.id)
        role = link.get("role") or "other"
        if role not in ("dependent", "independent", "control", "moderator", "mediator", "other"):
            raise bad_request(f"Unknown variable role: {role}")
        question.variable_links.append(ResearchQuestionVariable(variable_id=variable.id, role=role))


@router.get("/projects/{project_id}/research-questions")
def list_research_questions(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    return {"research_questions": project_service.research_question_evaluation(db, project)}


@router.post("/projects/{project_id}/research-questions", status_code=201)
def create_research_question(project_id: int, body: ResearchQuestionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    codes = [q.code for q in project.research_questions]
    code = (body.code or project_service.next_code("RQ", codes)).strip()
    if code in codes:
        raise ApiError(409, "duplicate_code", f"{code} already exists in this project.")
    question = ResearchQuestion(project_id=project.id, code=code, text=body.text, position=len(codes))
    db.add(question)
    db.flush()
    _link_variables(db, project, question, body.variables)
    audit.record(db, action="research_question.created", user_id=user.id, project_id=project.id, entity_type="research_question",
                 entity_id=question.id, details={"code": code})
    db.commit()
    db.refresh(question)
    return question.to_dict()


@router.put("/research-questions/{question_id}")
def update_research_question(question_id: int, body: ResearchQuestionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    question = db.get(ResearchQuestion, question_id)
    if question is None:
        raise not_found("Research question")
    project = get_project(db, question.project_id, user, WRITE)
    question.text = body.text
    if body.code and body.code != question.code:
        if body.code in [q.code for q in project.research_questions]:
            raise ApiError(409, "duplicate_code", f"{body.code} already exists in this project.")
        question.code = body.code
    _link_variables(db, project, question, body.variables)
    audit.record(db, action="research_question.updated", user_id=user.id, project_id=project.id, entity_type="research_question",
                 entity_id=question.id)
    db.commit()
    db.refresh(question)
    return question.to_dict()


@router.delete("/research-questions/{question_id}")
def delete_research_question(question_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    question = db.get(ResearchQuestion, question_id)
    if question is None:
        raise not_found("Research question")
    project = get_project(db, question.project_id, user, WRITE)
    audit.record(db, action="research_question.deleted", user_id=user.id, project_id=project.id, entity_type="research_question",
                 entity_id=question.id, details={"code": question.code, "text": question.text})
    db.delete(question)
    db.commit()
    return {"message": "Research question deleted."}


# ---- hypotheses ---------------------------------------------------------------
@router.get("/projects/{project_id}/hypotheses")
def list_hypotheses(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    return {"hypotheses": project_service.hypothesis_dicts(project)}


def _check_question(project: Project, question_id: int | None) -> None:
    if question_id is not None and question_id not in [q.id for q in project.research_questions]:
        raise bad_request("The research question does not belong to this project.")


@router.post("/projects/{project_id}/hypotheses", status_code=201)
def create_hypothesis(project_id: int, body: HypothesisIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    _check_question(project, body.research_question_id)
    codes = [h.code for h in project.hypotheses]
    code = (body.code or project_service.next_code("H", codes)).strip()
    if code in codes:
        raise ApiError(409, "duplicate_code", f"{code} already exists in this project.")
    hypothesis = Hypothesis(project_id=project.id, research_question_id=body.research_question_id, code=code, null_text=body.null_text,
                            alternative_text=body.alternative_text, direction=body.direction, alpha=body.alpha)
    db.add(hypothesis)
    db.flush()
    audit.record(db, action="hypothesis.created", user_id=user.id, project_id=project.id, entity_type="hypothesis",
                 entity_id=hypothesis.id, details={"code": code})
    db.commit()
    db.refresh(hypothesis)
    return hypothesis.to_dict()


@router.put("/hypotheses/{hypothesis_id}")
def update_hypothesis(hypothesis_id: int, body: HypothesisIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    hypothesis = db.get(Hypothesis, hypothesis_id)
    if hypothesis is None:
        raise not_found("Hypothesis")
    project = get_project(db, hypothesis.project_id, user, WRITE)
    _check_question(project, body.research_question_id)
    hypothesis.null_text, hypothesis.alternative_text = body.null_text, body.alternative_text
    hypothesis.direction, hypothesis.alpha, hypothesis.research_question_id = body.direction, body.alpha, body.research_question_id
    audit.record(db, action="hypothesis.updated", user_id=user.id, project_id=project.id, entity_type="hypothesis", entity_id=hypothesis.id)
    db.commit()
    db.refresh(hypothesis)
    return hypothesis.to_dict()


@router.delete("/hypotheses/{hypothesis_id}")
def delete_hypothesis(hypothesis_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    hypothesis = db.get(Hypothesis, hypothesis_id)
    if hypothesis is None:
        raise not_found("Hypothesis")
    project = get_project(db, hypothesis.project_id, user, WRITE)
    audit.record(db, action="hypothesis.deleted", user_id=user.id, project_id=project.id, entity_type="hypothesis",
                 entity_id=hypothesis.id, details={"code": hypothesis.code})
    db.delete(hypothesis)
    db.commit()
    return {"message": "Hypothesis deleted."}
