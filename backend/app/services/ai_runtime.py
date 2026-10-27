"""Wires the AI service to configuration and project data."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.context import build_context
from app.ai.providers import AIUnavailableError, build_provider
from app.ai.service import AIService
from app.core.config import get_settings
from app.models import Dataset, Project, SystemSetting, Visualization
from app.services import analysis_service, dataset_service, project_service

_override: AIService | None = None


def set_ai_service(service: AIService | None) -> None:
    """Replace the AI service (used by tests to inject a fake provider)."""
    global _override
    _override = service


def get_setting(db: Session, key: str, default=None):
    row = db.get(SystemSetting, key)
    return default if row is None else row.value_json


def get_ai_service(db: Session) -> AIService:
    """Provider from the environment; an administrator can switch AI off, or
    pick another configured provider name, through system settings."""
    if _override is not None:
        return _override
    settings = get_settings()
    enabled = bool(get_setting(db, "ai.enabled", True))
    name = get_setting(db, "ai.provider_override", None) or settings.AI_PROVIDER
    try:
        provider = build_provider(name, settings.AI_MODEL, settings.AI_API_KEY or None, settings.AI_BASE_URL or None)
    except AIUnavailableError:
        provider = None            # mis-configured provider: fall back to the rule engine, status endpoint reports it
    return AIService(provider, enabled=enabled)


def project_context(db: Session, project: Project, dataset: Dataset | None = None, focus: dict | None = None) -> dict:
    """Context for the AI: this project only, summaries only (see ai/context.py)."""
    dataset = dataset or project_service.primary_dataset(db, project.id)
    dataset_info, variables, quality = None, [], None
    if dataset is not None and dataset.current_version is not None:
        version = dataset.current_version
        dataset_info = {"name": dataset.name, "rows": version.row_count, "columns": version.column_count,
                        "version": version.version_number}
        variables = dataset_service.data_dictionary(db, dataset, version)
        report = dataset_service.latest_quality_report(db, version.id)
        quality = report.to_dict() if report else None
    results = project_service.results_as_dicts(analysis_service.project_results(db, project.id))
    charts = [{"title": v.title, "chart_type": v.chart_type, **{k: (v.config_json or {}).get(k) for k in ("x", "y")},
               "notes": ((v.config_json or {}).get("_meta") or {}).get("notes")}
              for v in db.scalars(select(Visualization).where(Visualization.project_id == project.id).order_by(Visualization.id.desc()).limit(10))]
    return build_context(project=project.to_dict(), research_questions=project_service.question_dicts(project),
                         hypotheses=project_service.hypothesis_dicts(project), dataset=dataset_info, variables=variables,
                         quality=quality, results=results, visualizations=charts, focus=focus)
