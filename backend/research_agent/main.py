"""
main.py
-------
FastAPI entry point for the Research AI Agent.
Mount this service alongside your existing FastAPI backend.

Base URL: /agent/v1
"""

import io
import os
import json
import tempfile
from typing import Optional

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from modules.orchestrator import ResearchAgent
from modules.profiler     import profile_dataset
from modules.cleaner      import auto_clean
from modules.test_selector import select_tests
from modules.analysis_engine import run_analysis
from modules.conclusion_writer import write_conclusions
from modules.prediction_engine import run_predictions
from modules.powerbi_builder   import build_powerbi_dashboard


# ── App Setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Research AI Agent",
    description="Autonomous research analyst agent — plug into your data analysis app.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restrict to your React app origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store (use Redis in production)
_sessions: dict = {}


# ── Request / Response Models ─────────────────────────────────────────────────

class ProjectContext(BaseModel):
    title:                str
    general_objective:    str
    specific_objectives:  list[str]
    research_problem:     str = ""
    institution:          str = ""
    department:           str = ""
    methodology:          str = "Quantitative"
    study_design:         str = ""
    sampling_technique:   str = ""
    sample_size:          int = 0
    study_population:     str = ""
    data_collection_method: str = ""


class Hypothesis(BaseModel):
    id:  int
    iv:  str   # Independent variable column name
    dv:  str   # Dependent variable column name
    h0:  str
    h1:  str


class RunRequest(BaseModel):
    project_id:     str
    hypotheses:     list[Hypothesis]
    build_powerbi:  bool = False
    generate_report: bool = True


# ── Helper ────────────────────────────────────────────────────────────────────

def _load_df(session_id: str) -> pd.DataFrame:
    session = _sessions.get(session_id)
    if not session or "df" not in session:
        raise HTTPException(status_code=404,
                             detail="Dataset not found. Upload a file first.")
    return session["df"]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/agent/v1/health")
def health():
    return {"status": "ok", "agent": "Research AI Agent v1.0"}


# ── 1. Create Project Session ─────────────────────────────────────────────────

@app.post("/agent/v1/project")
def create_project(ctx: ProjectContext):
    """
    Create a new project session. Returns a project_id.
    Call this when the user creates a project in your app.
    """
    import uuid
    project_id = str(uuid.uuid4())
    _sessions[project_id] = {
        "context": ctx.dict(),
        "agent":   ResearchAgent(ctx.dict()),
    }
    return {"project_id": project_id, "status": "created"}


# ── 2. Upload Dataset ─────────────────────────────────────────────────────────

@app.post("/agent/v1/project/{project_id}/upload")
async def upload_dataset(project_id: str, file: UploadFile = File(...)):
    """
    Upload a CSV or Excel file for the project.
    Returns a column profile and data quality report immediately.
    """
    if project_id not in _sessions:
        raise HTTPException(status_code=404, detail="Project not found.")

    content = await file.read()
    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        elif file.filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise HTTPException(status_code=400,
                                 detail="Only CSV and Excel files are supported.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"File read error: {e}")

    session = _sessions[project_id]
    session["df"] = df

    # Immediately profile the data
    ctx     = session["context"]
    profile = profile_dataset(df, [ctx.get("general_objective", "")])
    session["profile"] = profile

    return {
        "status":   "uploaded",
        "filename": file.filename,
        "rows":     len(df),
        "columns":  list(df.columns),
        "profile":  profile,
    }


# ── 3. Clean Data ─────────────────────────────────────────────────────────────

@app.post("/agent/v1/project/{project_id}/clean")
def clean_data(project_id: str):
    """
    Auto-clean the uploaded dataset.
    Returns the cleaning log and updated profile.
    """
    if project_id not in _sessions:
        raise HTTPException(status_code=404, detail="Project not found.")

    session = _sessions[project_id]
    df      = _load_df(project_id)
    profile = session.get("profile") or profile_dataset(df)

    df_clean, log = auto_clean(df, profile)
    session["df_clean"]     = df_clean
    session["cleaning_log"] = log

    # Re-profile after cleaning
    new_profile = profile_dataset(df_clean)
    session["profile"] = new_profile

    return {
        "status":       "cleaned",
        "rows_after":   len(df_clean),
        "cols_after":   len(df_clean.columns),
        "cleaning_log": log,
        "profile":      new_profile,
    }


# ── 4. Select Tests ───────────────────────────────────────────────────────────

@app.post("/agent/v1/project/{project_id}/select-tests")
def select_statistical_tests(project_id: str, hypotheses: list[Hypothesis]):
    """
    Given the hypotheses, select the correct statistical test for each.
    Returns the full test plan.
    """
    if project_id not in _sessions:
        raise HTTPException(status_code=404, detail="Project not found.")

    session = _sessions[project_id]
    df      = session.get("df_clean") or _load_df(project_id)
    profile = session.get("profile") or profile_dataset(df)

    hyp_dicts = [h.dict() for h in hypotheses]
    test_plan = select_tests(df, profile, hyp_dicts)
    session["test_plan"] = test_plan

    return {"status": "complete", "test_plan": test_plan}


# ── 5. Run Analysis ───────────────────────────────────────────────────────────

@app.post("/agent/v1/project/{project_id}/run-analysis")
def run_statistical_analysis(project_id: str):
    """
    Run all statistical tests in the test plan.
    Returns structured findings for each hypothesis.
    """
    if project_id not in _sessions:
        raise HTTPException(status_code=404, detail="Project not found.")

    session   = _sessions[project_id]
    df        = session.get("df_clean") or _load_df(project_id)
    test_plan = session.get("test_plan")

    if not test_plan:
        raise HTTPException(status_code=400,
                             detail="No test plan found. Call /select-tests first.")

    results = run_analysis(df, test_plan)
    session["analysis_results"] = results

    return {"status": "complete", "findings": results}


# ── 6. Write Conclusions ──────────────────────────────────────────────────────

@app.post("/agent/v1/project/{project_id}/conclusions")
def generate_conclusions(project_id: str):
    """
    Generate professional academic conclusions and recommendations
    for all findings using the Claude API.
    """
    if project_id not in _sessions:
        raise HTTPException(status_code=404, detail="Project not found.")

    session = _sessions[project_id]
    results = session.get("analysis_results")

    if not results:
        raise HTTPException(status_code=400,
                             detail="No analysis results found. Run /run-analysis first.")

    conclusions = write_conclusions(results, session["context"])
    session["conclusions"] = conclusions

    return {"status": "complete", "conclusions": conclusions}


# ── 7. Predictions ────────────────────────────────────────────────────────────

@app.post("/agent/v1/project/{project_id}/predict")
def generate_predictions(project_id: str):
    """
    Train ML models and generate predictions + forecast for the project DVs.
    """
    if project_id not in _sessions:
        raise HTTPException(status_code=404, detail="Project not found.")

    session = _sessions[project_id]
    df      = session.get("df_clean") or _load_df(project_id)
    profile = session.get("profile") or profile_dataset(df)
    roles   = profile.get("suggested_roles", {})
    date_col = next((c for c, r in roles.items() if r == "date"), None)

    pred_result = run_predictions(df, profile, roles, date_col)
    session["predictions"] = pred_result

    return {"status": "complete", "predictions": pred_result}


# ── 8. Power BI Dashboard ─────────────────────────────────────────────────────

@app.post("/agent/v1/project/{project_id}/powerbi")
def build_dashboard(project_id: str):
    """
    Push data and analysis results to Power BI.
    Returns the dashboard embed URL.
    Requires POWERBI_* environment variables to be set.
    """
    if project_id not in _sessions:
        raise HTTPException(status_code=404, detail="Project not found.")

    session  = _sessions[project_id]
    df       = session.get("df_clean") or _load_df(project_id)
    results  = session.get("analysis_results", [])
    preds    = session.get("predictions", {})
    forecast = preds.get("forecast", {})

    pbi_result = build_powerbi_dashboard(
        df=df,
        analysis_results=results,
        predictions=preds,
        forecast=forecast,
        project_context=session["context"],
    )

    session["powerbi"] = pbi_result
    return pbi_result


# ── 9. Generate PDF Report ────────────────────────────────────────────────────

@app.post("/agent/v1/project/{project_id}/report")
def generate_report(project_id: str):
    """
    Generate and download the full academic PDF report.
    """
    if project_id not in _sessions:
        raise HTTPException(status_code=404, detail="Project not found.")

    from modules.report_generator import generate_pdf_report

    session     = _sessions[project_id]
    profile     = session.get("profile", {})
    cleaning_log = session.get("cleaning_log", [])
    results     = session.get("analysis_results", [])
    conclusions = session.get("conclusions", [])
    predictions = session.get("predictions", {})

    out_path = f"/tmp/report_{project_id}.pdf"

    try:
        generate_pdf_report(
            project_context=session["context"],
            profile=profile,
            cleaning_log=cleaning_log,
            analysis_results=results,
            conclusions=conclusions,
            predictions=predictions,
            output_path=out_path,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")

    return FileResponse(
        out_path,
        media_type="application/pdf",
        filename=f"research_report_{project_id[:8]}.pdf",
    )


# ── 10. Full Pipeline (one-shot) ──────────────────────────────────────────────

@app.post("/agent/v1/project/{project_id}/run-all")
def run_full_pipeline(project_id: str, req: RunRequest):
    """
    Run the COMPLETE pipeline in one call:
    Profile → Clean → Select Tests → Analyse → Conclude → Predict
    Optionally: Power BI → PDF Report

    Use this for background processing while showing a progress bar.
    """
    if project_id not in _sessions:
        raise HTTPException(status_code=404, detail="Project not found.")

    session = _sessions[project_id]
    df      = _load_df(project_id)
    agent   = session["agent"]

    hyp_dicts = [h.dict() for h in req.hypotheses]

    result = agent.run(
        df=df,
        hypotheses=hyp_dicts,
        build_powerbi=req.build_powerbi,
        generate_report=req.generate_report,
        report_output_path=f"/tmp/report_{project_id}.pdf",
    )

    # Save agent state back to session
    session.update(agent.state)

    return result


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
