"""Request bodies (Pydantic v2). Responses are plain JSON built from the
models' ``to_dict`` methods and documented in docs/api.md."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

AcademicLevel = Literal["undergraduate", "masters", "phd"]
ProjectStatus = Literal["draft", "active", "completed", "archived"]
ProjectType = Literal["personal", "client"]
DataType = Literal["numeric", "integer", "categorical", "boolean", "datetime", "text", "identifier"]
MeasurementLevel = Literal["nominal", "ordinal", "interval", "ratio"]
VariableRole = Literal["dependent", "independent", "control", "moderator", "mediator", "identifier", "other"]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---- auth -------------------------------------------------------------------
class RegisterIn(Body):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    academic_level: AcademicLevel | None = None


class LoginIn(Body):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(Body):
    refresh_token: str = Field(min_length=20, max_length=200)


class LogoutIn(Body):
    refresh_token: str | None = Field(default=None, max_length=200)


class ForgotPasswordIn(Body):
    email: EmailStr


class ResetPasswordIn(Body):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=10, max_length=128)


class TokenIn(Body):
    token: str = Field(min_length=20, max_length=200)


class ProfileIn(Body):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    academic_level: AcademicLevel | None = None


class ChangePasswordIn(Body):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


# ---- projects ---------------------------------------------------------------
class ProjectIn(Body):
    title: str = Field(min_length=3, max_length=300)
    academic_level: AcademicLevel
    research_field: str | None = Field(default=None, max_length=150)
    institution: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    research_problem: str | None = Field(default=None, max_length=10000)
    general_objective: str | None = Field(default=None, max_length=5000)
    study_population: str | None = Field(default=None, max_length=5000)
    sample_size: int | None = Field(default=None, ge=1, le=100_000_000)
    sampling_technique: str | None = Field(default=None, max_length=150)
    research_methodology: str | None = Field(default=None, max_length=150)
    study_design: str | None = Field(default=None, max_length=150)
    data_collection_method: str | None = Field(default=None, max_length=255)
    status: ProjectStatus = "draft"
    objectives: list[str] | None = Field(default=None, max_length=30)
    # A client project needs the client's details (checked in project_service.client_details). Personal projects keep none.
    project_type: ProjectType = "personal"
    client_name: str | None = Field(default=None, max_length=200)
    client_email: str | None = Field(default=None, max_length=254)
    client_whatsapp: str | None = Field(default=None, max_length=30)


class ProjectUpdateIn(ProjectIn):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    academic_level: AcademicLevel | None = None
    status: ProjectStatus | None = None


class MemberIn(Body):
    email: EmailStr
    member_role: Literal["supervisor", "collaborator", "viewer"]


class ResearchQuestionIn(Body):
    text: str = Field(min_length=5, max_length=2000)
    code: str | None = Field(default=None, max_length=20)
    variables: list[dict[str, Any]] | None = None      # [{"variable_id": 1, "role": "dependent"}]


class HypothesisIn(Body):
    null_text: str = Field(min_length=5, max_length=2000)
    alternative_text: str = Field(min_length=5, max_length=2000)
    research_question_id: int | None = None
    code: str | None = Field(default=None, max_length=20)
    direction: Literal["non_directional", "greater", "less"] = "non_directional"
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    not_tested_reason: str | None = Field(default=None, max_length=1000)   # required when no test is run


# ---- datasets ---------------------------------------------------------------
class ManualDatasetIn(Body):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    columns: list[str] = Field(min_length=1, max_length=500)
    rows: list[list[Any]] = Field(min_length=1, max_length=20000)


class CleanIn(Body):
    operation: str = Field(min_length=2, max_length=50)
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=5, max_length=2000)


class AutoCleanIn(Body):
    drop_missing_rows: bool = False       # opt-in: removes records with any missing value, which shrinks the sample


class VariableIn(Body):
    label: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    measurement_level: MeasurementLevel | None = None
    role: VariableRole | None = None
    unit: str | None = Field(default=None, max_length=50)
    valid_min: float | None = None
    valid_max: float | None = None


# ---- analysis ---------------------------------------------------------------
class FilterIn(Body):
    column: str
    op: Literal["eq", "ne", "gt", "ge", "lt", "le", "in", "not_missing"]
    value: Any = None


class AnalysisIn(Body):
    analysis_type: Literal["eda", "descriptive", "inferential", "power"]
    dataset_id: int | None = None
    dataset_version_id: int | None = None           # default: the dataset's current version
    name: str | None = Field(default=None, max_length=255)
    research_question_id: int | None = None
    hypothesis_id: int | None = None
    method: str | None = Field(default=None, max_length=60)
    variables: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    filters: list[FilterIn] = Field(default_factory=list, max_length=20)
    justification: str | None = Field(default=None, max_length=2000)


class TestIn(Body):
    method: str = Field(max_length=60)
    variables: dict[str, Any]
    params: dict[str, Any] = Field(default_factory=dict)
    hypothesis_id: int | None = None
    justification: str | None = Field(default=None, max_length=2000)


class VisualizationIn(Body):
    chart_type: str = Field(max_length=40)
    dataset_id: int | None = None
    x: str | None = None
    y: str | None = None
    hue: str | None = None
    columns: list[str] | None = None
    title: str | None = Field(default=None, max_length=255)
    x_label: str | None = Field(default=None, max_length=120)
    y_label: str | None = Field(default=None, max_length=120)
    bins: int | None = Field(default=None, ge=2, le=200)
    method: Literal["pearson", "spearman", "kendall"] | None = None
    fit_line: bool | None = None
    category_order: list[str] | None = None
    width: float | None = Field(default=None, ge=4, le=14)
    height: float | None = Field(default=None, ge=3, le=10)
    include_in_report: bool = False


class ChartPreviewIn(VisualizationIn):
    """A chart drawn on demand, not saved. run_id draws from that analysis's dataset version and filters."""
    run_id: int | None = None


class VisualizationUpdateIn(VisualizationIn):
    chart_type: str | None = Field(default=None, max_length=40)
    include_in_report: bool | None = None


# ---- AI ---------------------------------------------------------------------
class AIRecommendIn(Body):
    dataset_id: int | None = None
    research_question_id: int | None = None
    outcome: str | None = None
    predictors: list[str] = Field(default_factory=list, max_length=30)
    paired: bool = False
    measures: list[str] = Field(default_factory=list, max_length=30)
    outcome_kind: Literal["auto", "continuous", "ordinal", "binary", "nominal", "count", "time_to_event"] = "auto"
    goal: str | None = Field(default=None, max_length=1000)


class AIPlanIn(Body):
    """Choose the variables and test for one research question and/or hypothesis (nothing is run)."""
    dataset_id: int | None = None
    research_question_id: int | None = None
    hypothesis_id: int | None = None


class AutoAnalyzeIn(Body):
    """Analyse every research question and hypothesis automatically. Optionally limit it to one.
    Items that already have a run are skipped unless ``rerun`` is true."""
    dataset_id: int | None = None
    research_question_id: int | None = None
    hypothesis_id: int | None = None
    rerun: bool = False


class AIExplainIn(Body):
    analysis_result_id: int | None = None
    visualization_id: int | None = None
    concept: str | None = Field(default=None, max_length=100)
    question: str | None = Field(default=None, max_length=2000)


class AIAnalyzeIn(Body):
    dataset_id: int | None = None


class AIChatIn(Body):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None


# ---- evidence ---------------------------------------------------------------
class FindingIn(Body):
    title: str = Field(min_length=3, max_length=255)
    statement: str = Field(min_length=5, max_length=10000)
    statistical_evidence: str | None = Field(default=None, max_length=5000)
    interpretation: str | None = Field(default=None, max_length=10000)
    confidence_level: Literal["low", "moderate", "high"] = "moderate"
    limitations_note: str | None = Field(default=None, max_length=5000)
    research_question_id: int | None = None
    hypothesis_id: int | None = None
    analysis_result_id: int | None = None


class FindingUpdateIn(FindingIn):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    statement: str | None = Field(default=None, min_length=5, max_length=10000)
    confidence_level: Literal["low", "moderate", "high"] | None = None


class FindingFromResultIn(Body):
    analysis_result_id: int
    research_question_id: int | None = None
    hypothesis_id: int | None = None


class TextItemIn(Body):
    text: str = Field(min_length=5, max_length=10000)
    finding_ids: list[int] = Field(default_factory=list, max_length=100)
    audience: str | None = Field(default=None, max_length=150)


class AutoEvidenceIn(Body):
    """Findings, conclusions and recommendations, built automatically. regenerate replaces the automatic conclusions and recommendations."""
    regenerate: bool = False


class GenerateIn(Body):
    use_ai: bool = False
    replace_engine_drafts: bool = True


class LimitationIn(Body):
    category: str = Field(default="other", max_length=60)
    description: str = Field(min_length=5, max_length=5000)


class LimitationStatusIn(Body):
    status: Literal["active", "acknowledged", "not_applicable"]
    status_note: str | None = Field(default=None, max_length=2000)

    @field_validator("status_note")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        return value or None


# ---- reports / review / admin ------------------------------------------------
class ReportIn(Body):
    format: Literal["pdf", "docx", "xlsx", "csv"] = "pdf"
    title: str | None = Field(default=None, max_length=300)
    report_id: int | None = None                      # add a new version to an existing report
    sections: list[str] | None = None
    dataset_id: int | None = None
    include_data: bool = False                        # XLSX only: add the cleaned data as a sheet


CostCategory = Literal["Data collection", "Materials and supplies", "Travel", "Software and online services",
                       "Printing and binding", "Participant incentives", "Other"]


class CostItemIn(Body):
    description: str = Field(min_length=2, max_length=200)
    category: CostCategory = "Other"
    amount: float = Field(ge=0, le=1_000_000_000)


class CostsIn(Body):
    currency: str = Field(default="USD", min_length=1, max_length=10)
    items: list[CostItemIn] = Field(default_factory=list, max_length=200)


class ReportDetailsIn(Body):
    background: str | None = Field(default=None, max_length=20000)
    references: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=200)   # one source per entry
    ethics_committee: str | None = Field(default=None, max_length=300)
    ethics_reference: str | None = Field(default=None, max_length=300)
    consent_method: str | None = Field(default=None, max_length=300)


class ClientPackageIn(Body):
    title: str | None = Field(default=None, max_length=300)
    dataset_id: int | None = None
    references: list[str] = Field(default_factory=list, max_length=200)   # the bibliography the gate requires when methods are named
    deliverables: list[Literal["summary", "report", "charts", "data", "workbook", "log", "dashboard", "deck"]] = Field(
        default_factory=lambda: ["summary", "report", "charts", "data", "workbook", "log", "dashboard", "deck"])
    audience: Literal["executive", "technical", "academic"] = "academic"
    length: Literal["one_page", "full"] = "full"      # one_page: the summary and README only


class AssistantDraftIn(Body):
    kind: Literal["hypothesis", "chart_title", "project_gaps"]
    research_question_id: int | None = None
    chart_type: str | None = Field(default=None, max_length=40)
    x: str | None = Field(default=None, max_length=190)
    y: str | None = Field(default=None, max_length=190)
    hue: str | None = Field(default=None, max_length=190)


class AssistantDecisionIn(Body):
    step: str = Field(max_length=40)
    kind: Literal["suggestion", "decision"]           # a suggestion the assistant made, or the user's decision on one
    text: str = Field(min_length=1, max_length=2000)
    decision: Literal["accepted", "rejected", "edited"] | None = None
    note: str | None = Field(default=None, max_length=1000)


class CommentIn(Body):
    stage: str = Field(max_length=40)
    body: str = Field(min_length=1, max_length=5000)
    entity_type: str | None = Field(default=None, max_length=40)
    entity_id: int | None = None


class StageReviewIn(Body):
    stage: str = Field(max_length=40)
    status: Literal["approved", "rejected", "pending"]
    note: str | None = Field(default=None, max_length=5000)


class AdminUserIn(Body):
    is_active: bool | None = None
    roles: list[Literal["researcher", "supervisor", "admin"]] | None = None


class SettingIn(Body):
    value: Any
