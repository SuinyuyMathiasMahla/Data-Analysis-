# Architecture

## Layers

```
┌──────────────────────────── frontend (React + TypeScript) ────────────────────────────┐
│ pages → hooks (useApi, useAction, waitForRun) → services/api.ts (fetch, token refresh) │
└───────────────────────────────────────┬───────────────────────────────────────────────┘
                                        │ REST / JSON
┌───────────────────────────────────────▼───────────────────────────────────────────────┐
│ api/routes      thin handlers; request validation (Pydantic); access control (deps.py)  │
│ services        use-cases, transactions, audit log, jobs, storage, e-mail              │
│ ─────────────────────────────────────────────────────────────────────────────────────  │
│ analysis  statistics  ai  reports      pure Python: no web framework, no database      │
│ ─────────────────────────────────────────────────────────────────────────────────────  │
│ models (SQLAlchemy) → MySQL            services/storage → files                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

The middle band is the important design decision. Profiling, quality,
cleaning, statistics, recommendation, evidence rules, AI guardrails and report
rendering take data frames and dictionaries and return dictionaries. That makes
them testable against published results without a server, and it is why
`scripts/demo_workflow.py` can run the whole pipeline with no database.

## Request flow for an analysis

1. `POST /api/projects/{id}/analysis` – the route checks access, the service
   stores an `analysis_runs` row (`PENDING`) with the dataset version id,
   variables, parameters, filters and the schema in force, and submits it.
2. A worker thread (`services/analysis_service.py`) sets `PROCESSING`, loads the
   stored version, applies the schema and filters, and calls
   `statistics.registry.run_method`.
3. The engine returns the standard result dictionary. It is stored in
   `analysis_results` (headline numbers in typed columns, the whole result as
   JSON) with the library versions. A linked hypothesis gets its decision.
4. Status becomes `COMPLETED`, or `FAILED` with a message. User-fixable problems
   (`AnalysisError`) keep their message; unexpected exceptions are logged and
   shown generically.
5. The frontend polls `GET /api/analysis/{id}`.

## AI pipeline

```
Research question → study design → variable types → dataset characteristics
→ assumption checks → method recommendation (rule engine) → statistical engine
→ numerical results → AI interpretation → grounding check → research finding
```

- `ai/providers.py` – `AIProvider` with `OpenAIProvider`, `GeminiProvider`,
  `AnthropicProvider`, `LocalModelProvider`; selected by configuration; plain
  HTTPS calls, no vendor SDKs.
- `ai/context.py` – builds the minimal context: summaries only, no rows, no
  account data, no example values from text or identifier columns.
- `ai/guard.py` – the system prompt and `check_grounding`.
- `ai/service.py` – one method per task (explain result, explain concept,
  explain chart, comment on a recommendation, review project, draft section,
  chat). Each has a deterministic rule-engine answer that is used when no
  provider is configured or the provider fails, and is labelled as such.

The model never executes SQL or code and has no tools; it sees one project's
context per request.

## Reproducibility

An `analysis_runs` row stores `dataset_version_id`, `config_json` (method,
variables, parameters, schema snapshot), `filters_json`, `software_json`
(Python, NumPy, pandas, SciPy, scikit-learn, statsmodels versions) and
timestamps. Dataset versions are immutable and checksummed. `POST
/api/analysis/{id}/reproduce` re-runs the stored configuration on the stored
version and reports whether statistics and p-values are identical.

## Report snapshot

`reports/content.py` assembles one dictionary from serialised rows;
`reports/renderers.py` renders it to PDF (ReportLab), DOCX (python-docx), XLSX
(openpyxl) or CSV. The dictionary is saved in `report_versions.content_json`,
so an old report can be audited or re-rendered after the project has changed.

Shapes passed to `assemble_report_content`:

- `runs[]`: `{id, name, status, research_question_id, version_number, filters, software, completed_at, results[]}`
  where each result is `{id, result_type, result (engine dict), test: {hypothesis_id, params}, justification}`
- `findings[]`: the `Finding.to_dict()` shape; `conclusions[]` / `recommendations[]`: `{text, finding_ids, source}`
- `figures[]`: `{image_key, title, note, section}` with PNG bytes passed separately

## Security

| Concern | Measure |
|---|---|
| Passwords | Argon2id (argon2-cffi), server-side policy, lockout after 5 failures |
| Sessions | 30-minute JWT access token; opaque refresh token stored hashed, rotated on use, re-use revokes all sessions; password reset signs out everywhere |
| Authorisation | Permissions per role; per-project rights (owner, collaborator, supervisor, viewer); every child entity is checked against its project; inaccessible projects return 404 |
| Input | Pydantic models with `extra="forbid"`, length limits; SQLAlchemy bound parameters only |
| Uploads | Extension allow-list, content signature check, size limit read from the stream, generated storage keys, path-traversal guard, files outside the web root |
| Data cleaning | Fixed list of operations; no user-supplied code or formulas |
| Errors | Uniform JSON errors; stack traces only in the server log with a reference id |
| Abuse | Rate limits on authentication and AI endpoints |
| Secrets | Environment variables only; `.env` is git-ignored; production refuses weak settings |
| Audit | `audit_logs` records account, data, analysis, AI and report events |
| Browser | CORS allow-list, `nosniff`, `X-Frame-Options: DENY`, `no-store` on API responses |

The frontend keeps the access token in memory and the refresh token in
`localStorage`. That is a deliberate trade-off for a single-page app served
from a different origin than the API; if both are served from one origin,
moving the refresh token to an `HttpOnly` cookie is the stronger option.

## Performance and scale

- The browser receives pages of 50 rows and server-rendered chart images, never
  the dataset.
- Analyses run in a thread pool with job status; NumPy and SciPy release the
  GIL for the heavy parts. For larger loads replace the pool with a queue
  (Celery or RQ) — `submit()` and `execute_run()` are the only touch points.
- Working copies are CSV files of raw values. For datasets beyond a few hundred
  thousand rows, switching `_store_working` / `load_raw` to Parquet is the next step.
- Limits are configurable: `MAX_UPLOAD_MB`, `MAX_DATASET_ROWS`, `MAX_DATASET_COLUMNS`.

## Extension points

| To add | Where |
|---|---|
| A statistical method | implement a function returning the standard result; register it in `statistics/registry.py` with its roles; add a recommender rule and a known-answer test |
| A cleaning operation | `analysis/cleaning.py` (`OPERATIONS`) and the field list in `frontend/src/pages/DataPages.tsx` |
| A chart type | `analysis/visualization.py` (`CHART_TYPES`, `render_chart`) and `NEEDS` in `Charts.tsx` |
| An AI provider | subclass `AIProvider`, add to `PROVIDERS` |
| A storage backend | implement `Storage` (see the `S3Storage` TODO) |
| A data source | produce a raw frame as `profiling.read_raw` does and call `dataset_service.create_dataset` |
| Qualitative analysis | `datasets.data_kind` already distinguishes it; add its own analysis package beside `statistics/` and its own result types. Findings, conclusions and reports are independent of how a result was produced. Statistical tests are not applied to qualitative material. |
