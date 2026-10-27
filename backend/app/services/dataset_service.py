"""Dataset lifecycle: import, immutable versions, data dictionary, quality
checks and audited cleaning."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis import cleaning, profiling, quality
from app.core.config import get_settings
from app.core.errors import ApiError, bad_request
from app.models import (AuditLog, CleaningOperation, DataQualityReport, Dataset, DatasetColumn, DatasetVersion, Project, User, Variable)
from app.services import audit
from app.services.storage import get_storage, make_key
from app.statistics.utils import AnalysisError

ALLOWED_FORMATS = {"csv", "xlsx", "xls", "json"}
# First bytes that identify the real file type, so a renamed file is rejected.
_MAGIC = {"xlsx": b"PK\x03\x04", "xls": b"\xd0\xcf\x11\xe0"}


def detect_format(filename: str | None, content: bytes) -> str:
    """Validate an upload by extension AND content; return the format."""
    settings = get_settings()
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext not in ALLOWED_FORMATS:
        raise bad_request("Unsupported file type. Upload a CSV, XLSX, XLS or JSON file.", "unsupported_file_type")
    if not content:
        raise bad_request("The uploaded file is empty.", "empty_file")
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise ApiError(413, "payload_too_large", f"The file is larger than the {settings.MAX_UPLOAD_MB} MB limit.")
    if ext in _MAGIC and not content.startswith(_MAGIC[ext]):
        raise bad_request(f"The file does not look like a real .{ext} file.", "invalid_file_content")
    if ext in ("csv", "json") and b"\x00" in content[:4096]:
        raise bad_request(f"The file does not look like a text .{ext} file.", "invalid_file_content")
    return ext


def _check_size(raw: pd.DataFrame) -> None:
    settings = get_settings()
    if raw.shape[0] > settings.MAX_DATASET_ROWS or raw.shape[1] > settings.MAX_DATASET_COLUMNS:
        raise bad_request(f"The dataset has {raw.shape[0]} rows and {raw.shape[1]} columns; the limit is "
                          f"{settings.MAX_DATASET_ROWS} rows and {settings.MAX_DATASET_COLUMNS} columns.", "dataset_too_large")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def load_raw(version: DatasetVersion) -> pd.DataFrame:
    """Raw frame of a WORKING version (the original upload is parsed with read_raw)."""
    data = get_storage().load(version.storage_key)
    if version.kind == "original":
        if version.file_format == "manual":
            payload = json.loads(data.decode("utf-8"))
            return profiling.frame_from_manual(payload["columns"], payload["rows"])
        return profiling.read_raw(data, version.file_format)
    return profiling.raw_from_csv_bytes(data)


def schema_for(db: Session, version: DatasetVersion) -> dict[str, dict[str, str]]:
    """Schema used for analysis: the version's stored types, with the
    measurement level the researcher set in the data dictionary."""
    schema = {k: dict(v) for k, v in (version.schema_json or {}).items()}
    for var in db.scalars(select(Variable).where(Variable.dataset_id == version.dataset_id)):
        if var.name in schema:
            schema[var.name]["measurement_level"] = var.measurement_level
    return schema


def load_typed(db: Session, version: DatasetVersion, schema: dict | None = None) -> tuple[pd.DataFrame, dict]:
    schema = schema or schema_for(db, version)
    return profiling.typed_frame(load_raw(version), schema), schema


def variable_labels(db: Session, dataset_id: int) -> dict[str, str]:
    labels = {}
    for var in db.scalars(select(Variable).where(Variable.dataset_id == dataset_id)):
        if var.label:
            labels[var.name] = f"{var.label} ({var.unit})" if var.unit else var.label
    return labels


# --------------------------------------------------------------------------- #
# versions, dictionary and profile
# --------------------------------------------------------------------------- #
def _next_version_number(db: Session, dataset_id: int) -> int:
    # Lock the dataset row until the transaction ends, so two cleaning requests at the same moment cannot both take the same number.
    db.execute(select(Dataset.id).where(Dataset.id == dataset_id).with_for_update()).first()
    current = db.scalar(select(func.max(DatasetVersion.version_number)).where(DatasetVersion.dataset_id == dataset_id))
    return 0 if current is None else current + 1


def _store_working(db: Session, dataset: Dataset, raw: pd.DataFrame, schema: dict, parent: DatasetVersion | None, user: User,
                   note: str) -> DatasetVersion:
    data = profiling.raw_to_csv_bytes(raw)
    key = make_key("projects", dataset.project_id, "datasets", dataset.id, filename="working.csv")
    get_storage().save(key, data)
    version = DatasetVersion(dataset_id=dataset.id, version_number=_next_version_number(db, dataset.id),
                             parent_version_id=parent.id if parent else None, kind="working", storage_key=key, file_format="csv",
                             checksum_sha256=_sha256(data), size_bytes=len(data), row_count=int(raw.shape[0]),
                             column_count=int(raw.shape[1]), schema_json=schema, note=note[:500], created_by=user.id)
    db.add(version)
    db.flush()
    return version


def _sync_dictionary(db: Session, dataset: Dataset, version: DatasetVersion, raw: pd.DataFrame, schema: dict,
                     renamed: dict[str, str] | None = None) -> None:
    """Create/update data-dictionary rows and write the column profile of ``version``.
    Labels, descriptions, roles and valid ranges entered by the researcher are kept."""
    existing = {v.name: v for v in db.scalars(select(Variable).where(Variable.dataset_id == dataset.id))}
    for old, new in (renamed or {}).items():
        if old in existing and new not in existing:
            existing[old].name = new
            existing[new] = existing.pop(old)
    profiles = profiling.profile_columns(raw, schema)
    for prof in profiles:
        var = existing.get(prof["name"])
        if var is None:
            var = Variable(project_id=dataset.project_id, dataset_id=dataset.id, name=prof["name"], data_type=prof["type"],
                           measurement_level=prof["measurement_level"],
                           role="identifier" if prof["type"] == "identifier" else "other")
            db.add(var)
            db.flush()
        else:
            if var.data_type != prof["type"]:           # type was changed by a cleaning operation
                var.data_type = prof["type"]
                var.measurement_level = prof["measurement_level"]
        db.add(DatasetColumn(dataset_version_id=version.id, variable_id=var.id, name=prof["name"], position=prof["position"],
                             inferred_type=prof["type"], n_unique=prof["n_unique"], n_missing=prof["n_missing"],
                             stats_json=prof["stats"]))
    db.flush()


def data_dictionary(db: Session, dataset: Dataset, version: DatasetVersion | None = None) -> list[dict]:
    version = version or dataset.current_version
    if version is None:
        return []
    columns = {c.name: c for c in db.scalars(select(DatasetColumn).where(DatasetColumn.dataset_version_id == version.id))}
    variables = {v.name: v for v in db.scalars(select(Variable).where(Variable.dataset_id == dataset.id))}
    rows = [variables[name].to_dict(col) for name, col in columns.items() if name in variables]
    return sorted(rows, key=lambda r: r.get("position", 0))


def valid_ranges(db: Session, dataset_id: int) -> dict[str, tuple[float | None, float | None]]:
    return {v.name: (v.valid_min, v.valid_max) for v in db.scalars(select(Variable).where(Variable.dataset_id == dataset_id))
            if v.valid_min is not None or v.valid_max is not None}


# --------------------------------------------------------------------------- #
# import
# --------------------------------------------------------------------------- #
def create_dataset(db: Session, project: Project, user: User, *, name: str, description: str | None, source_type: str,
                   original_bytes: bytes, original_filename: str | None, raw: pd.DataFrame) -> Dataset:
    """Store the untouched original (version 0), create the working copy
    (version 1), build the data dictionary and run the first quality check."""
    _check_size(raw)
    dataset = Dataset(project_id=project.id, name=name[:200], description=description, source_type=source_type,
                      original_filename=original_filename, created_by=user.id)
    db.add(dataset)
    db.flush()

    storage = get_storage()
    key = make_key("projects", project.id, "datasets", dataset.id, filename=original_filename or f"manual_entry.{source_type}")
    storage.save(key, original_bytes)
    original = DatasetVersion(dataset_id=dataset.id, version_number=0, kind="original", storage_key=key,
                              file_format="manual" if source_type == "manual" else source_type,
                              checksum_sha256=_sha256(original_bytes), size_bytes=len(original_bytes), row_count=int(raw.shape[0]),
                              column_count=int(raw.shape[1]), note="Original upload (never modified)", created_by=user.id)
    db.add(original)
    db.flush()

    schema = profiling.infer_schema(raw)
    working = _store_working(db, dataset, raw, schema, original, user, "Working copy created from the original upload")
    _sync_dictionary(db, dataset, working, raw, schema)
    dataset.current_version_id = working.id
    audit.record(db, action="dataset.uploaded", user_id=user.id, project_id=project.id, entity_type="dataset", entity_id=dataset.id,
                 details={"name": dataset.name, "source_type": source_type, "rows": int(raw.shape[0]), "columns": int(raw.shape[1]),
                          "original_sha256": original.checksum_sha256})
    run_quality_check(db, dataset, working, user, raw=raw)
    if project.status == "draft":
        project.status = "active"
    db.commit()
    db.refresh(dataset)
    return dataset


# --------------------------------------------------------------------------- #
# quality
# --------------------------------------------------------------------------- #
def run_quality_check(db: Session, dataset: Dataset, version: DatasetVersion, user: User, raw: pd.DataFrame | None = None) -> DataQualityReport:
    raw = raw if raw is not None else load_raw(version)
    result = quality.assess_quality(raw, schema_for(db, version), valid_ranges(db, dataset.id))
    report = DataQualityReport(dataset_version_id=version.id, score=result["score"], issue_count=len(result["issues"]),
                               summary_json={"summary": result["summary"], "dimensions": result["dimensions"]},
                               issues_json=result["issues"], created_by=user.id)
    db.add(report)
    audit.record(db, action="dataset.quality_checked", user_id=user.id, project_id=dataset.project_id, entity_type="dataset",
                 entity_id=dataset.id, details={"version": version.version_number, "score": result["score"], "issues": len(result["issues"])})
    db.flush()
    return report


def latest_quality_report(db: Session, version_id: int) -> DataQualityReport | None:
    return db.scalar(select(DataQualityReport).where(DataQualityReport.dataset_version_id == version_id)
                     .order_by(DataQualityReport.id.desc()).limit(1))


# --------------------------------------------------------------------------- #
# cleaning
# --------------------------------------------------------------------------- #
def apply_cleaning(db: Session, dataset: Dataset, user: User, operation: str, params: dict[str, Any], reason: str) -> CleaningOperation:
    """Apply one operation to the current version and save the result as a NEW
    version. The input version is never modified."""
    current = dataset.current_version
    if current is None:
        raise bad_request("This dataset has no working version.")
    raw = load_raw(current)
    schema = {k: dict(v) for k, v in (current.schema_json or {}).items()}
    outcome = cleaning.apply_operation(raw, schema, operation, params, reason)
    if outcome.rows_after == outcome.rows_before and outcome.cells_changed == 0 and outcome.raw.shape[1] == raw.shape[1] \
            and list(outcome.raw.columns) == list(raw.columns) and outcome.schema == schema:
        raise AnalysisError("This operation would not change anything, so no new version was created.")
    label = cleaning.OPERATIONS[operation]["label"]
    version = _store_working(db, dataset, outcome.raw, outcome.schema, current, user, f"{label}: {reason}")
    _sync_dictionary(db, dataset, version, outcome.raw, outcome.schema, renamed=(outcome.details or {}).get("renamed"))
    entry = CleaningOperation(dataset_id=dataset.id, input_version_id=current.id, output_version_id=version.id, operation=operation,
                              params_json=params, reason=reason.strip(), rows_before=outcome.rows_before, rows_after=outcome.rows_after,
                              cells_changed=outcome.cells_changed, details_json=outcome.details, performed_by=user.id)
    db.add(entry)
    dataset.current_version_id = version.id
    audit.record(db, action="dataset.cleaned", user_id=user.id, project_id=dataset.project_id, entity_type="dataset", entity_id=dataset.id,
                 details={"operation": operation, "label": label, "reason": reason.strip(), "from_version": current.version_number,
                          "to_version": version.version_number, "rows_before": outcome.rows_before, "rows_after": outcome.rows_after,
                          "cells_changed": outcome.cells_changed})
    run_quality_check(db, dataset, version, user, raw=outcome.raw)
    db.commit()
    db.refresh(entry)
    return entry


def restore_version(db: Session, dataset: Dataset, version: DatasetVersion, user: User, reason: str) -> Dataset:
    """Make an earlier working version current again. Nothing is deleted: later
    versions and their audit entries remain in the history."""
    if version.dataset_id != dataset.id or version.kind != "working":
        raise bad_request("Only a working version of this dataset can be restored.")
    previous = dataset.current_version
    dataset.current_version_id = version.id
    audit.record(db, action="dataset.version_restored", user_id=user.id, project_id=dataset.project_id, entity_type="dataset",
                 entity_id=dataset.id, details={"from_version": previous.version_number if previous else None,
                                                "to_version": version.version_number, "reason": reason})
    db.commit()
    db.refresh(dataset)
    return dataset


def cleaning_history(db: Session, dataset_id: int) -> list[CleaningOperation]:
    return list(db.scalars(select(CleaningOperation).where(CleaningOperation.dataset_id == dataset_id).order_by(CleaningOperation.id)))


def lineage(db: Session, version: DatasetVersion) -> list[int]:
    """Ids of ``version`` and all its ancestors (the versions that led to it)."""
    ids, current = [], version
    while current is not None:
        ids.append(current.id)
        current = db.get(DatasetVersion, current.parent_version_id) if current.parent_version_id else None
    return ids


def cleaning_for_version(db: Session, version: DatasetVersion) -> list[CleaningOperation]:
    """Only the operations that actually produced ``version`` (ignores branches
    that were abandoned by restoring an earlier version)."""
    ids = set(lineage(db, version))
    return [op for op in cleaning_history(db, version.dataset_id) if op.output_version_id in ids]


# ---- automatic cleaning ------------------------------------------------------
# Safe fixes: one mechanical correction per issue type, never a judgement call.
AUTO_ISSUE_CODES = {"duplicate_rows", "empty_column", "empty_rows", "impossible_value", "invalid_numeric", "invalid_date",
                    "suspicious_code", "inconsistent_category"}
ALERT_SHARE_PCT = 5.0          # a decision touching more than this share of records is flagged for review and can be undone
MAX_AUTO_STEPS = 200


def _safe_fixes(db: Session, dataset: Dataset, user: User, summary: dict) -> None:
    tried: set[str] = set()
    for _ in range(MAX_AUTO_STEPS):
        issues = latest_quality_report(db, dataset.current_version_id).to_dict()["issues"]
        candidates = [i for i in issues if i["code"] in AUTO_ISSUE_CODES and i.get("suggestion")
                      and json.dumps(i["suggestion"], sort_keys=True, default=str) not in tried]
        if not candidates:
            return
        issue = candidates[0]
        tried.add(json.dumps(issue["suggestion"], sort_keys=True, default=str))
        try:
            entry = apply_cleaning(db, dataset, user, issue["suggestion"]["operation"], issue["suggestion"]["params"],
                                   f"Automatic: {issue['message']}")
            summary["applied"].append({"code": issue["code"], "column": issue.get("column"), "operation": issue["suggestion"]["operation"],
                                       "reason": entry.to_dict().get("reason")})
        except AnalysisError as exc:
            summary["skipped"].append({"code": issue["code"], "column": issue.get("column"), "message": issue["message"], "reason": str(exc)})
        db.refresh(dataset)


def _missing_facts(db: Session, dataset: Dataset, raw: pd.DataFrame, schema: dict) -> list[dict]:
    roles = {v.name: v.role for v in db.scalars(select(Variable).where(Variable.dataset_id == dataset.id))}
    n = len(raw)
    facts = []
    for col in raw.columns:
        missing = int(raw[col].isna().sum())
        if missing == 0:
            continue
        numeric = schema.get(col, {}).get("type") in profiling.NUMERIC_TYPES
        role = roles.get(col, "other")
        allowed = []
        if role != "identifier":
            allowed.append("impute_median" if numeric else "impute_mode")
        allowed += ["delete_records", "drop_column"]
        facts.append({"column": col, "missing": missing, "missing_pct": round(100 * missing / n, 2) if n else 0.0,
                      "type": "numeric" if numeric else "categorical", "role": role, "rows": n, "allowed": allowed})
    return facts


def _rule_decision(fact: dict) -> dict:
    """Fixed rules. Used when no AI provider is configured, or when the model's answer does not suit the column."""
    pct, role, missing = fact["missing_pct"], fact["role"], fact["missing"]
    if pct > 20:
        action, reason = "drop_column", (f"{pct}% of the values are missing. Filling most of a variable would invent it, so the variable "
                                         "is removed from the analysis.")
    elif role == "identifier":
        action, reason = "delete_records", f"{missing} identifier value(s) are missing. An identifier cannot be filled in, so those records are removed."
    elif role == "dependent":
        action, reason = "delete_records", (f"{missing} outcome value(s) are missing. The outcome cannot be filled in without inventing the result, "
                                            "so those records are removed.")
    elif pct <= 1:
        action, reason = "delete_records", f"{missing} record(s) ({pct}%) are missing. Removing them barely changes the sample."
    elif fact["type"] == "numeric":
        action, reason = "impute_median", (f"{pct}% of the values are missing. The median fills them, keeps every record, and is not pulled "
                                           "by extreme values.")
    else:
        action, reason = "impute_mode", f"{pct}% of the values are missing. The most frequent category fills them and keeps every record."
    return {"column": fact["column"], "action": action, "reason": reason, "source": "rules"}


def _accepted(fact: dict, decision: dict | None) -> dict | None:
    """An AI decision is used only when it names this column, an option that suits it, and gives a reason."""
    if not decision or decision.get("action") not in fact["allowed"] or not decision.get("reason"):
        return None
    return {"column": fact["column"], "action": decision["action"], "reason": str(decision["reason"])[:400], "source": "ai_assistant"}


MISSING_OPERATIONS = {
    "impute_median": lambda col: ("impute", {"column": col, "strategy": "median"}),
    "impute_mode": lambda col: ("impute", {"column": col, "strategy": "mode"}),
    "delete_records": lambda col: ("drop_missing", {"columns": [col], "how": "any"}),
    "drop_column": lambda col: ("drop_columns", {"columns": [col]}),
}


def _apply_decision(db: Session, dataset: Dataset, user: User, decision: dict, fact: dict) -> dict:
    operation, params = MISSING_OPERATIONS[decision["action"]](decision["column"])
    previous = dataset.current_version_id
    who = "AI assistant" if decision["source"] == "ai_assistant" else "rules"
    entry = apply_cleaning(db, dataset, user, operation, params, f"Automatic ({who}): {decision['reason']}")
    affects = decision["action"] == "drop_column" or fact["missing_pct"] > ALERT_SHARE_PCT
    record = {"kind": "missing_value", "column": decision["column"], "action": decision["action"], "reason": decision["reason"],
              "source": decision["source"], "missing_pct": fact["missing_pct"], "affects_results": affects,
              "previous_version_id": previous, "output_version_id": dataset.current_version_id, "entry_id": entry.id}
    audit.record(db, action="dataset.auto_decision", user_id=user.id, project_id=dataset.project_id, entity_type="dataset",
                 entity_id=dataset.id, details=record)
    db.flush()
    db.refresh(dataset)
    return record


def auto_clean(db: Session, dataset: Dataset, user: User, decide=None) -> dict:
    """Clean the dataset until no automatic step can raise its quality score.

    1. Safe fixes for mechanical problems (duplicates, impossible values, 999 codes, spelling, invalid numbers, empty columns).
    2. A decision for each column with missing values: fill it, delete the affected records, or remove the variable.
       ``decide(facts)`` (optional) is the AI assistant and returns {column: decision}. Its answers are used only when they suit
       the column; otherwise the fixed rules decide.
    3. Constant columns (one value for every record) are removed: they carry no information and lower the score.

    Every step is a new version with its reason recorded. A decision that removes a variable, or touches more than
    ALERT_SHARE_PCT of the records, is flagged ``affects_results`` so the assistant can review it and it can be undone.
    """
    if dataset.current_version is None:
        raise bad_request("This dataset has no working version.")
    report = latest_quality_report(db, dataset.current_version.id)
    if report is None:
        report = run_quality_check(db, dataset, dataset.current_version, user)
    score_before, rows_before = float(report.score), dataset.current_version.row_count
    summary: dict[str, Any] = {"applied": [], "skipped": [], "decisions": []}

    _safe_fixes(db, dataset, user, summary)

    for _ in range(MAX_AUTO_STEPS):
        raw = load_raw(dataset.current_version)
        schema = {k: dict(v) for k, v in (dataset.current_version.schema_json or {}).items()}
        facts = _missing_facts(db, dataset, raw, schema)
        if not facts:
            break
        fact = facts[0]
        ai = (decide(facts) if decide else None) or {}
        decision = _accepted(fact, ai.get(fact["column"])) or _rule_decision(fact)
        try:
            summary["decisions"].append(_apply_decision(db, dataset, user, decision, fact))
        except AnalysisError as exc:
            summary["skipped"].append({"column": fact["column"], "message": "Missing values", "reason": str(exc)})
            break

    raw = load_raw(dataset.current_version)
    for col in list(raw.columns):
        if len(raw.columns) > 1 and raw[col].notna().any() and raw[col].nunique(dropna=True) <= 1:
            fact = {"column": col, "missing": 0, "missing_pct": 0.0, "type": "constant", "role": "other", "rows": len(raw),
                    "allowed": ["drop_column"]}
            decision = {"column": col, "action": "drop_column", "source": "rules",
                        "reason": "Every record has the same value, so the variable cannot separate groups or show a relationship. It is removed."}
            try:
                summary["decisions"].append(_apply_decision(db, dataset, user, decision, fact))
            except AnalysisError as exc:
                summary["skipped"].append({"column": col, "message": "Constant variable", "reason": str(exc)})

    final = latest_quality_report(db, dataset.current_version_id)
    alerts = [d for d in summary["decisions"] if d["affects_results"]]
    audit.record(db, action="dataset.auto_cleaned", user_id=user.id, project_id=dataset.project_id, entity_type="dataset",
                 entity_id=dataset.id, details={"score_before": score_before, "score_after": float(final.score),
                                                "steps": len(summary["applied"]) + len(summary["decisions"]), "alerts": len(alerts)})
    return {"score_before": score_before, "score_after": float(final.score), "rows_before": rows_before,
            "rows_after": dataset.current_version.row_count, "applied": summary["applied"], "decisions": summary["decisions"],
            "alerts": alerts, "skipped": summary["skipped"]}


def decision_log(db: Session, dataset: Dataset) -> list[dict]:
    """Every automatic decision for this dataset, and whether it has since been undone."""
    rows = list(db.scalars(select(AuditLog).where(AuditLog.action == "dataset.auto_decision", AuditLog.entity_id == dataset.id).order_by(AuditLog.id)))
    undone = {int((r.details_json or {}).get("decision_id", 0)) for r in db.scalars(
        select(AuditLog).where(AuditLog.action == "dataset.auto_decision_reverted", AuditLog.entity_id == dataset.id))}
    return [{**(r.details_json or {}), "decision_id": r.id, "undone": r.id in undone, "created_at": r.created_at.isoformat()} for r in rows]


def undo_decision(db: Session, dataset: Dataset, user: User, decision_id: int) -> Dataset:
    """Restore the version that existed before one automatic decision. Later versions stay in the history."""
    entry = db.get(AuditLog, decision_id)
    if entry is None or entry.action != "dataset.auto_decision" or entry.entity_id != dataset.id:
        raise bad_request("That automatic decision does not belong to this dataset.", code="not_found")
    if any(d["decision_id"] == decision_id and d["undone"] for d in decision_log(db, dataset)):
        raise bad_request("This decision has already been undone.", code="already_undone")
    previous = db.get(DatasetVersion, (entry.details_json or {}).get("previous_version_id"))
    if previous is None:
        raise bad_request("The earlier version is no longer available.", code="not_found")
    restore_version(db, dataset, previous, user, f"Undid automatic decision on '{(entry.details_json or {}).get('column')}'")
    audit.record(db, action="dataset.auto_decision_reverted", user_id=user.id, project_id=dataset.project_id, entity_type="dataset",
                 entity_id=dataset.id, details={"decision_id": decision_id})
    db.flush()
    return dataset
