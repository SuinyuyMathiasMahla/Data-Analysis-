"""
powerbi_builder.py
------------------
Pushes analysis results to a Power BI workspace via the REST API.
Creates a dataset with tables, then posts rows.
Returns a dashboard embed URL.

Prerequisites (set as env vars):
  POWERBI_CLIENT_ID      — Azure App Registration client ID
  POWERBI_CLIENT_SECRET  — Azure App Registration client secret
  POWERBI_TENANT_ID      — Azure tenant ID
  POWERBI_WORKSPACE_ID   — Power BI workspace (group) ID
"""

import os
import json
import requests
from typing import Optional
import pandas as pd


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_access_token() -> str:
    tenant_id     = os.environ["POWERBI_TENANT_ID"]
    client_id     = os.environ["POWERBI_CLIENT_ID"]
    client_secret = os.environ["POWERBI_CLIENT_SECRET"]

    url  = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
        "scope":         "https://analysis.windows.net/powerbi/api/.default",
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }


# ── Dataset Schema Builder ────────────────────────────────────────────────────

def _df_to_pbi_columns(df: pd.DataFrame) -> list:
    """Convert pandas dtypes to Power BI column definitions."""
    type_map = {
        "int64":   "Int64",
        "float64": "Double",
        "bool":    "Boolean",
        "object":  "String",
        "datetime64[ns]": "DateTime",
    }
    cols = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        pbi_type = type_map.get(dtype, "String")
        cols.append({"name": col, "dataType": pbi_type})
    return cols


# ── Push Dataset ──────────────────────────────────────────────────────────────

def _create_push_dataset(
    token: str,
    workspace_id: str,
    dataset_name: str,
    tables: dict,   # {table_name: pd.DataFrame}
) -> str:
    """Create a push dataset in Power BI. Returns dataset ID."""
    pbi_tables = []
    for tname, df in tables.items():
        pbi_tables.append({
            "name":    tname,
            "columns": _df_to_pbi_columns(df),
        })

    body = {
        "name":              dataset_name,
        "defaultMode":       "Push",
        "tables":            pbi_tables,
    }

    url = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets"
    r = requests.post(url, headers=_headers(token), json=body, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def _push_rows(
    token: str,
    workspace_id: str,
    dataset_id: str,
    table_name: str,
    df: pd.DataFrame,
    batch_size: int = 9000,
):
    """Push rows to a Power BI push dataset table in batches."""
    url = (f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}"
           f"/datasets/{dataset_id}/tables/{table_name}/rows")

    records = df.fillna("").to_dict(orient="records")
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        r = requests.post(url, headers=_headers(token),
                          json={"rows": batch}, timeout=60)
        r.raise_for_status()


# ── Dashboard Builder ─────────────────────────────────────────────────────────

def _create_dashboard(
    token: str, workspace_id: str, name: str
) -> str:
    """Create a blank dashboard. Returns dashboard ID."""
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/dashboards"
    r = requests.post(url, headers=_headers(token),
                      json={"name": name}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


# ── Main Public Function ──────────────────────────────────────────────────────

def build_powerbi_dashboard(
    df: pd.DataFrame,
    analysis_results: list[dict],
    predictions: dict,
    forecast: dict,
    project_context: dict,
) -> dict:
    """
    Full Power BI pipeline:
      1. Authenticate
      2. Create push dataset with 3 tables:
         - RawData (cleaned dataset)
         - AnalysisSummary (test results per hypothesis)
         - ForecastData (if available)
      3. Push all rows
      4. Create dashboard
      5. Return dataset ID, dashboard ID, and embed URL

    Returns dict with status and URLs.
    """
    try:
        workspace_id = os.environ["POWERBI_WORKSPACE_ID"]
        project_name = project_context.get("title", "Research Dashboard")
        token = _get_access_token()

        # ── Table 1: Raw Data (max 10,000 rows)
        raw_df = df.head(10000).copy()
        for col in raw_df.select_dtypes(include=["datetime64"]).columns:
            raw_df[col] = raw_df[col].astype(str)

        # ── Table 2: Analysis Summary
        summary_rows = []
        for r in analysis_results:
            summary_rows.append({
                "Hypothesis_ID":  str(r.get("hypothesis_id", "")),
                "IV":             str(r.get("iv", "")),
                "DV":             str(r.get("dv", "")),
                "Test_Used":      str(r.get("test", "")),
                "P_Value":        float(r.get("p_value") or 0),
                "Significant":    bool(r.get("significant", False)),
                "Effect_Size":    float((r.get("effect_size") or {}).get("value", 0)),
                "Effect_Label":   str((r.get("effect_size") or {}).get("magnitude", "")),
                "Interpretation": str(r.get("interpretation", "")),
            })
        summary_df = pd.DataFrame(summary_rows)

        # ── Table 3: Forecast Data
        forecast_rows = []
        for dv_name, fc in forecast.items():
            for date, val in zip(fc["historical"]["dates"], fc["historical"]["values"]):
                forecast_rows.append({
                    "DV": dv_name, "Date": date,
                    "Value": val, "Type": "Historical"
                })
            for date, val in zip(fc["forecast"]["dates"], fc["forecast"]["values"]):
                forecast_rows.append({
                    "DV": dv_name, "Date": date,
                    "Value": val, "Type": "Forecast"
                })
        forecast_df = pd.DataFrame(forecast_rows) if forecast_rows else \
                      pd.DataFrame(columns=["DV","Date","Value","Type"])

        tables = {
            "RawData":         raw_df,
            "AnalysisSummary": summary_df,
            "ForecastData":    forecast_df,
        }

        # Create dataset
        dataset_id = _create_push_dataset(token, workspace_id, project_name, tables)

        # Push rows
        _push_rows(token, workspace_id, dataset_id, "RawData",         raw_df)
        _push_rows(token, workspace_id, dataset_id, "AnalysisSummary", summary_df)
        if not forecast_df.empty:
            _push_rows(token, workspace_id, dataset_id, "ForecastData", forecast_df)

        # Create dashboard
        dashboard_id = _create_dashboard(token, workspace_id, f"{project_name} — Dashboard")

        embed_url = (f"https://app.powerbi.com/groups/{workspace_id}"
                     f"/dashboards/{dashboard_id}")

        return {
            "status":       "success",
            "dataset_id":   dataset_id,
            "dashboard_id": dashboard_id,
            "embed_url":    embed_url,
            "tables_pushed": list(tables.keys()),
            "message": (
                f"Power BI dataset '{project_name}' created with "
                f"{len(raw_df)} rows across {len(tables)} tables. "
                f"Open the dashboard at: {embed_url}"
            ),
        }

    except KeyError as e:
        return {
            "status": "env_missing",
            "message": f"Missing environment variable: {e}. "
                       "Set POWERBI_CLIENT_ID, POWERBI_CLIENT_SECRET, "
                       "POWERBI_TENANT_ID, and POWERBI_WORKSPACE_ID.",
        }
    except requests.HTTPError as e:
        return {"status": "http_error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
