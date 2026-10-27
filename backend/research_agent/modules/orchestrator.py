"""
orchestrator.py
---------------
The master agent brain. Runs the full analysis pipeline
end-to-end given a dataset and project context.

Called by main.py (FastAPI) for each project.
"""

import os
import io
import pandas as pd
from typing import Optional

from .profiler          import profile_dataset
from .cleaner           import auto_clean
from .test_selector     import select_tests
from .analysis_engine   import run_analysis
from .conclusion_writer import write_conclusions
from .prediction_engine import run_predictions
from .powerbi_builder   import build_powerbi_dashboard
from .report_generator  import generate_pdf_report


class ResearchAgent:
    """
    Stateful agent instance for one research project.
    Call run() to execute the full pipeline.
    """

    def __init__(self, project_context: dict):
        self.ctx     = project_context
        self.state   = {}   # Stores intermediate results for each step

    # ── Full Pipeline ─────────────────────────────────────────────────────────

    def run(
        self,
        df: pd.DataFrame,
        hypotheses: list[dict],
        build_powerbi: bool = False,
        generate_report: bool = True,
        report_output_path: str = "/tmp/research_report.pdf",
    ) -> dict:
        """
        Execute all pipeline steps in order.
        Returns a comprehensive result dict.
        """

        result = {
            "project":    self.ctx.get("title"),
            "steps":      {},
            "errors":     [],
        }

        # ── STEP 1: Profile ───────────────────────────────────────────────────
        print("[Agent] Step 1/7 — Profiling dataset...")
        try:
            profile = profile_dataset(df, [self.ctx.get("general_objective", "")])
            self.state["profile"] = profile
            result["steps"]["profile"] = {
                "status":    "complete",
                "row_count": profile["row_count"],
                "col_count": profile["column_count"],
                "warnings":  profile["warnings"],
                "quality":   profile["quality_summary"],
                "roles":     profile["suggested_roles"],
            }
        except Exception as e:
            result["errors"].append(f"Profiling failed: {e}")
            return result

        # ── STEP 2: Clean ─────────────────────────────────────────────────────
        print("[Agent] Step 2/7 — Cleaning data...")
        try:
            df_clean, cleaning_log = auto_clean(df, profile)
            self.state["df_clean"]     = df_clean
            self.state["cleaning_log"] = cleaning_log
            result["steps"]["cleaning"] = {
                "status":       "complete",
                "actions_taken": len(cleaning_log),
                "log":          cleaning_log,
                "rows_after":   len(df_clean),
                "cols_after":   len(df_clean.columns),
            }
        except Exception as e:
            df_clean = df.copy()
            self.state["df_clean"]     = df_clean
            self.state["cleaning_log"] = []
            result["errors"].append(f"Cleaning failed (using raw data): {e}")

        # ── STEP 3: Select Tests ──────────────────────────────────────────────
        print("[Agent] Step 3/7 — Selecting statistical tests...")
        try:
            test_plan = select_tests(df_clean, profile, hypotheses)
            self.state["test_plan"] = test_plan
            result["steps"]["test_selection"] = {
                "status":    "complete",
                "test_plan": [
                    {"hypothesis_id": t["hypothesis_id"],
                     "iv": t["iv"], "dv": t["dv"],
                     "test": t["test"], "reason": t["reason"]}
                    for t in test_plan
                ],
            }
        except Exception as e:
            result["errors"].append(f"Test selection failed: {e}")
            return result

        # ── STEP 4: Run Analysis ──────────────────────────────────────────────
        print("[Agent] Step 4/7 — Running statistical analysis...")
        try:
            analysis_results = run_analysis(df_clean, test_plan)
            self.state["analysis_results"] = analysis_results
            result["steps"]["analysis"] = {
                "status":          "complete",
                "findings_count":  len(analysis_results),
                "results":         analysis_results,
            }
        except Exception as e:
            result["errors"].append(f"Analysis failed: {e}")
            return result

        # ── STEP 5: Write Conclusions ─────────────────────────────────────────
        print("[Agent] Step 5/7 — Writing conclusions via AI...")
        try:
            conclusions = write_conclusions(analysis_results, self.ctx)
            self.state["conclusions"] = conclusions
            result["steps"]["conclusions"] = {
                "status":     "complete",
                "count":      len(conclusions),
                "conclusions": conclusions,
            }
        except Exception as e:
            result["errors"].append(f"Conclusion writing failed: {e}")
            conclusions = []
            self.state["conclusions"] = []

        # ── STEP 6: Predictions ───────────────────────────────────────────────
        print("[Agent] Step 6/7 — Training prediction models...")
        try:
            roles    = profile.get("suggested_roles", {})
            date_col = next(
                (c for c, r in roles.items() if r == "date"), None
            )
            pred_result = run_predictions(df_clean, profile, roles, date_col)
            self.state["predictions"] = pred_result
            result["steps"]["predictions"] = {
                "status":          "complete",
                "models_trained":  list(pred_result.get("model_scores", {}).keys()),
                "model_scores":    pred_result.get("model_scores", {}),
                "feature_importance": pred_result.get("feature_importance", {}),
                "forecast":        pred_result.get("forecast", {}),
                "errors":          pred_result.get("errors", []),
            }
        except Exception as e:
            result["errors"].append(f"Predictions failed: {e}")
            pred_result = {"predictions": {}, "feature_importance": {},
                           "forecast": {}, "model_scores": {}}
            self.state["predictions"] = pred_result

        # ── STEP 7a: Power BI (optional) ──────────────────────────────────────
        if build_powerbi:
            print("[Agent] Step 7a — Building Power BI dashboard...")
            try:
                pbi_result = build_powerbi_dashboard(
                    df=df_clean,
                    analysis_results=analysis_results,
                    predictions=pred_result,
                    forecast=pred_result.get("forecast", {}),
                    project_context=self.ctx,
                )
                self.state["powerbi"] = pbi_result
                result["steps"]["powerbi"] = pbi_result
            except Exception as e:
                result["errors"].append(f"Power BI build failed: {e}")
                result["steps"]["powerbi"] = {"status": "error", "message": str(e)}

        # ── STEP 7b: PDF Report (optional) ────────────────────────────────────
        if generate_report:
            print("[Agent] Step 7b — Generating PDF report...")
            try:
                pdf_path = generate_pdf_report(
                    project_context=self.ctx,
                    profile=profile,
                    cleaning_log=self.state.get("cleaning_log", []),
                    analysis_results=analysis_results,
                    conclusions=conclusions,
                    predictions=pred_result,
                    output_path=report_output_path,
                )
                self.state["report_path"] = pdf_path
                result["steps"]["report"] = {
                    "status": "complete",
                    "path":   pdf_path,
                }
            except Exception as e:
                result["errors"].append(f"Report generation failed: {e}")
                result["steps"]["report"] = {"status": "error", "message": str(e)}

        result["status"] = "complete" if not result["errors"] else "complete_with_errors"
        print(f"[Agent] Pipeline complete. Errors: {len(result['errors'])}")
        return result

    # ── Step-by-Step API (for incremental use) ────────────────────────────────

    def step_profile(self, df: pd.DataFrame) -> dict:
        profile = profile_dataset(df)
        self.state["profile"] = profile
        return profile

    def step_clean(self, df: pd.DataFrame) -> tuple:
        profile = self.state.get("profile") or profile_dataset(df)
        df_clean, log = auto_clean(df, profile)
        self.state["df_clean"]     = df_clean
        self.state["cleaning_log"] = log
        return df_clean, log

    def step_select_tests(self, hypotheses: list) -> list:
        return select_tests(
            self.state["df_clean"],
            self.state["profile"],
            hypotheses,
        )

    def step_run_analysis(self, test_plan: list) -> list:
        results = run_analysis(self.state["df_clean"], test_plan)
        self.state["analysis_results"] = results
        return results

    def step_conclude(self) -> list:
        conclusions = write_conclusions(
            self.state["analysis_results"], self.ctx
        )
        self.state["conclusions"] = conclusions
        return conclusions

    def step_predict(self) -> dict:
        profile  = self.state["profile"]
        roles    = profile.get("suggested_roles", {})
        date_col = next((c for c, r in roles.items() if r == "date"), None)
        return run_predictions(self.state["df_clean"], profile, roles, date_col)
