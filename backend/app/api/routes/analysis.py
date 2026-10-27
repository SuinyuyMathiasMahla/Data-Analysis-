"""Analysis runs, statistical tests, power analysis and visualizations."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import visualization
from app.api.deps import READ, WRITE, get_current_user, get_project, get_run, get_visualization, owned
from app.core.errors import bad_request, not_found
from app.database.session import get_db
from app.models import AnalysisRun, DatasetVersion, Hypothesis, Project, ResearchQuestion, User, Visualization
from app.schemas.requests import AnalysisIn, ChartPreviewIn, TestIn, VisualizationIn, VisualizationUpdateIn
from app.services import analysis_service, audit, dataset_service, project_service
from app.services.storage import get_storage, make_key, safe_name
from app.statistics import power
from app.statistics.registry import apply_filters, catalogue

router = APIRouter(tags=["analysis"])


@router.get("/methods")
def methods(_: User = Depends(get_current_user)):
    """Every statistical method the platform knows, including the ones that are
    registered but not implemented (flagged ``implemented: false``)."""
    return {"methods": catalogue(), "chart_types": [{"key": k, **v} for k, v in visualization.CHART_TYPES.items()],
            "power_designs": [{"key": k, **v} for k, v in power.DESIGNS.items()]}


@router.post("/power")
def power_calculator(params: dict = Body(...), _: User = Depends(get_current_user)):
    """Stateless power / sample-size calculator for planning before data exist."""
    allowed = {"design", "mode", "effect_size", "n", "power", "alpha", "two_sided", "k_groups", "df", "n_predictors", "ratio"}
    unknown = set(params) - allowed
    if unknown:
        raise bad_request(f"Unknown parameter(s): {', '.join(sorted(unknown))}")
    if "design" not in params:
        raise bad_request("Choose a study design.")
    return power.run_power_analysis(**params)


def _resolve_version(db: Session, project: Project, dataset_id: int | None, version_id: int | None) -> DatasetVersion | None:
    if version_id is not None:
        version = db.get(DatasetVersion, version_id)
        dataset = project_service.primary_dataset(db, project.id, version.dataset_id) if version else None
        if version is None or dataset is None or version.kind != "working":
            raise not_found("Dataset version")
        return version
    dataset = project_service.primary_dataset(db, project.id, dataset_id)
    if dataset_id is not None and dataset is None:
        raise not_found("Dataset")
    return dataset.current_version if dataset else None


@router.post("/projects/{project_id}/analysis", status_code=202)
def create_analysis(project_id: int, body: AnalysisIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create an analysis job. Returns immediately with status PENDING/PROCESSING;
    poll GET /api/analysis/{id} until COMPLETED or FAILED."""
    project = get_project(db, project_id, user, WRITE)
    owned(db, ResearchQuestion, body.research_question_id, project.id, "Research question")
    owned(db, Hypothesis, body.hypothesis_id, project.id, "Hypothesis")
    version = _resolve_version(db, project, body.dataset_id, body.dataset_version_id)
    if body.analysis_type == "inferential" and not body.method:
        raise bad_request("Choose a statistical method (or ask for a recommendation first).")
    payload = body.model_dump()
    payload["filters"] = [f.model_dump() for f in body.filters]
    run = analysis_service.create_run(db, project, user, version, payload)
    return run.to_dict(with_results=True)


@router.get("/projects/{project_id}/analysis")
def list_analyses(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    runs = db.scalars(select(AnalysisRun).where(AnalysisRun.project_id == project.id).order_by(AnalysisRun.id.desc()))
    return {"analyses": [r.to_dict() for r in runs]}


@router.get("/analysis/{run_id}")
def read_analysis(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run, _ = get_run(db, run_id, user, READ)
    data = run.to_dict(with_results=True)
    if run.reproduced_from_id:
        original = db.get(AnalysisRun, run.reproduced_from_id)
        if original is not None and run.status == "COMPLETED":
            data["reproduction_check"] = analysis_service.compare_runs(original, run)
    return data


@router.delete("/analysis/{run_id}")
def delete_analysis(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run, project = get_run(db, run_id, user, WRITE)
    if run.status in ("PENDING", "PROCESSING"):
        raise bad_request("This analysis is still running.", "analysis_busy")
    audit.record(db, action="analysis.deleted", user_id=user.id, project_id=project.id, entity_type="analysis_run", entity_id=run.id,
                 details={"name": run.name})
    db.delete(run)
    db.commit()
    return {"message": "Analysis deleted. Findings that cited it are kept but no longer linked to a result."}


@router.post("/analysis/{run_id}/test", status_code=202)
def add_statistical_test(run_id: int, body: TestIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Run a further statistical test inside an existing analysis (same dataset version and filters)."""
    run, project = get_run(db, run_id, user, WRITE)
    if run.analysis_type != "inferential":
        raise bad_request("Statistical tests can only be added to an inferential analysis.")
    owned(db, Hypothesis, body.hypothesis_id, project.id, "Hypothesis")
    return analysis_service.add_test(db, run, user, body.model_dump()).to_dict(with_results=True)


@router.post("/analysis/{run_id}/reproduce", status_code=202)
def reproduce_analysis(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Re-run a stored analysis on the same dataset version with the same configuration."""
    run, project = get_run(db, run_id, user, WRITE)
    if run.status != "COMPLETED":
        raise bad_request("Only a completed analysis can be reproduced.")
    return analysis_service.reproduce(db, run, project, user).to_dict(with_results=True)


# ---- visualizations -----------------------------------------------------------
def _render(db: Session, project: Project, version: DatasetVersion, config: dict, run: AnalysisRun | None, user: User,
            include_in_report: bool) -> Visualization:
    df, _schema = dataset_service.load_typed(db, version)
    if run is not None and run.filters_json:
        df = apply_filters(df, run.filters_json)
    clean = {k: v for k, v in config.items() if v is not None and k not in ("dataset_id", "include_in_report")}
    png, meta = visualization.render_chart(df, clean, dataset_service.variable_labels(db, version.dataset_id))
    key = make_key("projects", project.id, "charts", filename=f"{safe_name(clean['chart_type'])}.png")
    get_storage().save(key, png)
    viz = Visualization(project_id=project.id, dataset_version_id=version.id, analysis_run_id=run.id if run else None,
                        chart_type=clean["chart_type"], title=meta["title"][:255], config_json={**clean, "_meta": meta}, storage_key=key,
                        include_in_report=include_in_report, created_by=user.id)
    db.add(viz)
    db.flush()
    audit.record(db, action="visualization.created", user_id=user.id, project_id=project.id, entity_type="visualization", entity_id=viz.id,
                 details={"chart_type": viz.chart_type, "title": viz.title})
    db.commit()
    db.refresh(viz)
    return viz


@router.post("/analysis/{run_id}/visualizations", status_code=201)
def create_analysis_visualization(run_id: int, body: VisualizationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run, project = get_run(db, run_id, user, WRITE)
    version = db.get(DatasetVersion, run.dataset_version_id)
    return _render(db, project, version, body.model_dump(), run, user, body.include_in_report).to_dict()


@router.get("/analysis/{run_id}/visualizations")
def list_analysis_visualizations(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run, _ = get_run(db, run_id, user, READ)
    items = db.scalars(select(Visualization).where(Visualization.analysis_run_id == run.id).order_by(Visualization.id.desc()))
    return {"visualizations": [v.to_dict() for v in items]}


@router.post("/analysis/{run_id}/diagnostic-plot", status_code=201)
def regression_diagnostic_plot(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Residual plots for a linear regression, drawn from the stored result."""
    run, project = get_run(db, run_id, user, WRITE)
    result = next((r for r in reversed(run.results) if (r.result_json or {}).get("diagnostics")), None)
    if result is None:
        raise bad_request("This analysis has no linear-regression diagnostics to plot.")
    outcome = (result.result_json.get("variables") or {}).get("outcome", "outcome")
    png = visualization.render_regression_diagnostics(result.result_json["diagnostics"], outcome)
    key = make_key("projects", project.id, "charts", filename="regression_diagnostics.png")
    get_storage().save(key, png)
    title = f"Regression diagnostics for {outcome}"
    meta = {"chart_type": "regression_diagnostics", "title": title, "n": result.sample_size,
            "notes": ["Left: residuals vs fitted values (look for curves or funnels). Middle: normal Q-Q plot of residuals. Right: residual distribution."]}
    viz = Visualization(project_id=project.id, dataset_version_id=run.dataset_version_id, analysis_run_id=run.id,
                        chart_type="regression_diagnostics", title=title, config_json={"chart_type": "regression_diagnostics", "_meta": meta},
                        storage_key=key, created_by=user.id)
    db.add(viz)
    db.commit()
    db.refresh(viz)
    return viz.to_dict()


@router.get("/projects/{project_id}/charts/suggested")
def suggested_charts(project_id: int, dataset_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Charts worth drawing, suggested by the latest exploration of the current dataset version (workflow step 'Charts worth drawing')."""
    project = get_project(db, project_id, user, READ)
    dataset = project_service.primary_dataset(db, project.id, dataset_id)
    if dataset is None or dataset.current_version is None:
        return {"run_id": None, "charts": []}
    latest = db.scalar(select(AnalysisRun).where(
        AnalysisRun.project_id == project.id, AnalysisRun.analysis_type == "eda", AnalysisRun.status == "COMPLETED",
        AnalysisRun.dataset_version_id == dataset.current_version_id).order_by(AnalysisRun.id.desc()).limit(1))
    if latest is None:
        return {"run_id": None, "charts": []}
    charts = [chart for result in latest.results for chart in ((result.result_json or {}).get("suggested_charts") or [])]
    return {"run_id": latest.id, "charts": [{**chart, "run_id": latest.id} for chart in charts]}


@router.post("/projects/{project_id}/visualizations/preview")
def preview_visualization(project_id: int, body: ChartPreviewIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Draw a chart and return the image without saving it, so charts can be tried out inline."""
    project = get_project(db, project_id, user, READ)
    if body.run_id is not None:
        run, _ = get_run(db, body.run_id, user, READ)
        version, filters = db.get(DatasetVersion, run.dataset_version_id), run.filters_json
    else:
        version, filters = _resolve_version(db, project, body.dataset_id, None), None
    if version is None:
        raise bad_request("Upload a dataset before drawing charts.")
    df, _schema = dataset_service.load_typed(db, version)
    if filters:
        df = apply_filters(df, filters)
    clean = {k: v for k, v in body.model_dump().items() if v is not None and k not in ("dataset_id", "include_in_report", "run_id")}
    png, _meta = visualization.render_chart(df, clean, dataset_service.variable_labels(db, version.dataset_id))
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/projects/{project_id}/visualizations", status_code=201)
def create_visualization(project_id: int, body: VisualizationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, WRITE)
    version = _resolve_version(db, project, body.dataset_id, None)
    if version is None:
        raise bad_request("Upload a dataset before creating charts.")
    return _render(db, project, version, body.model_dump(), None, user, body.include_in_report).to_dict()


@router.get("/projects/{project_id}/visualizations")
def list_visualizations(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, READ)
    items = db.scalars(select(Visualization).where(Visualization.project_id == project.id).order_by(Visualization.id.desc()))
    return {"visualizations": [v.to_dict() for v in items]}


@router.get("/visualizations/{viz_id}/image")
def visualization_image(viz_id: int, download: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    viz, _ = get_visualization(db, viz_id, user, READ)
    headers = {"Cache-Control": "private, max-age=60"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{safe_name(viz.title, "chart")}.png"'
    return Response(get_storage().load(viz.storage_key), media_type="image/png", headers=headers)


@router.put("/visualizations/{viz_id}")
def update_visualization(viz_id: int, body: VisualizationUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Customise and regenerate a chart, or toggle whether it goes into the report."""
    viz, project = get_visualization(db, viz_id, user, WRITE)
    changes = body.model_dump(exclude_unset=True)
    if "include_in_report" in changes and changes["include_in_report"] is not None:
        viz.include_in_report = changes.pop("include_in_report")
    changes.pop("include_in_report", None)
    changes.pop("dataset_id", None)
    if changes and viz.chart_type != "regression_diagnostics":
        config = {k: v for k, v in (viz.config_json or {}).items() if k != "_meta"}
        config.update(changes)
        config = {k: v for k, v in config.items() if v is not None}
        version = db.get(DatasetVersion, viz.dataset_version_id)
        df, _schema = dataset_service.load_typed(db, version)
        png, meta = visualization.render_chart(df, config, dataset_service.variable_labels(db, version.dataset_id))
        old_key = viz.storage_key
        viz.storage_key = make_key("projects", project.id, "charts", filename=f"{safe_name(config['chart_type'])}.png")
        get_storage().save(viz.storage_key, png)
        get_storage().delete(old_key)
        viz.chart_type, viz.title, viz.config_json = config["chart_type"], meta["title"][:255], {**config, "_meta": meta}
        audit.record(db, action="visualization.regenerated", user_id=user.id, project_id=project.id, entity_type="visualization",
                     entity_id=viz.id, details={"changed": sorted(changes)})
    db.commit()
    db.refresh(viz)
    return viz.to_dict()


@router.delete("/visualizations/{viz_id}")
def delete_visualization(viz_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    viz, project = get_visualization(db, viz_id, user, WRITE)
    key = viz.storage_key
    audit.record(db, action="visualization.deleted", user_id=user.id, project_id=project.id, entity_type="visualization", entity_id=viz.id)
    db.delete(viz)
    db.commit()
    get_storage().delete(key)
    return {"message": "Chart deleted."}
