# REST API

Base URL: `/api`. Interactive documentation (OpenAPI): `/api/docs` when the backend is running.

## Conventions

- **Authentication.** Send `Authorization: Bearer <access_token>` on every
  request except the `/auth/*` endpoints marked public and `/health`.
- **Access control.** A project is visible to its owner, to members added by
  the owner, and to administrators. Anything else returns `404` (not `403`), so
  the existence of other people's projects is not revealed. Members have a
  role: `collaborator` (read + write), `supervisor` (read + comment + review),
  `viewer` (read).
- **Errors** always have this shape, with a message that can be shown to the user:

  ```json
  {"error": {"code": "analysis_error", "message": "Choose two different variables.", "details": null}}
  ```

  | Status | Codes |
  |---|---|
  | 400 | `bad_request`, `weak_password`, `unsupported_file_type`, `invalid_file_content`, `empty_file`, `token_invalid`, … |
  | 401 | `unauthorized`, `invalid_credentials`, `token_invalid` |
  | 403 | `forbidden`, `account_disabled`, `email_not_verified` |
  | 404 | `not_found` |
  | 409 | `email_taken`, `duplicate_code` |
  | 413 | `payload_too_large` |
  | 422 | `validation_error` (request body), `analysis_error`, `insufficient_data` |
  | 423 | `account_locked` |
  | 429 | `rate_limited` |
  | 501 | `method_not_implemented` |
  | 503 | `ai_unavailable` |
  | 500 | `internal_error` (generic message plus a reference id; details are only in the server log) |

- **Jobs.** `POST /projects/{id}/analysis`, `POST /analysis/{id}/test` and
  `POST /analysis/{id}/reproduce` return `202` with a run whose `status` is
  `PENDING` or `PROCESSING`. Poll `GET /analysis/{id}` until it is `COMPLETED`
  or `FAILED` (`error_message` says why).

## Authentication and account

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/auth/register` | `email, password, full_name, institution?, department?, academic_level?` | Public. Sends a verification e-mail. |
| POST | `/auth/login` | `email, password` | Public. Returns `access_token`, `refresh_token`, `expires_in`, `user`. 5 failures lock the account for 15 minutes. |
| POST | `/auth/refresh` | `refresh_token` | Public. Rotates the refresh token. Re-using an old one revokes all sessions. |
| POST | `/auth/logout` | `refresh_token?` | `?everywhere=true` signs out all sessions. |
| POST | `/auth/forgot-password` | `email` | Public. Always answers 200. |
| POST | `/auth/reset-password` | `token, new_password` | Public. Single use; signs out all sessions. |
| POST | `/auth/verify-email` | `token` | Public. |
| POST | `/auth/resend-verification` | – | |
| GET | `/auth/sessions` | – | Active sessions. |
| GET / PUT | `/users/me` | `full_name?, institution?, department?, academic_level?` | Profile. |
| PUT | `/users/me/password` | `current_password, new_password` | |
| GET | `/notifications` · POST `/notifications/read` | – | |

## Projects and research design

| Method | Path | Notes |
|---|---|---|
| GET | `/dashboard` | Counts, active project with progress, recent datasets and analyses, quality warnings, open recommendations. |
| GET / POST | `/projects` | Create needs `title`, `academic_level` (`undergraduate` \| `masters` \| `phd`); all other project fields optional; `objectives: string[]`. `project_type` is `personal` (default) or `client`; a `client` project also needs `client_name`, `client_email` and `client_whatsapp` (country code and number, e.g. `237677000000`). The type cannot be changed after creation. |
| GET / PUT / DELETE | `/projects/{id}` | GET includes `progress`, `rights`, research questions, hypotheses, datasets, members. |
| POST | `/projects/{id}/members` | `email, member_role` (owner only). |
| DELETE | `/projects/{id}/members/{member_id}` | |
| GET / POST | `/projects/{id}/research-questions` | GET returns the evaluation of each question: linked variables, analyses, results, findings and `status` (`not_analysed`, `analysed`, `answered`). POST: `text, code?, variables?: [{variable_id, role}]`. |
| PUT / DELETE | `/research-questions/{id}` | |
| GET / POST | `/projects/{id}/hypotheses` | `null_text, alternative_text, research_question_id?, direction, alpha`. |
| PUT / DELETE | `/hypotheses/{id}` | |

## Datasets

| Method | Path | Notes |
|---|---|---|
| POST | `/projects/{id}/datasets` | `multipart/form-data`: `file` (csv, xlsx, xls, json), `name?`, `description?`. Stores the original, creates the working copy, profiles it and runs a quality check. |
| POST | `/projects/{id}/datasets/manual` | `name, columns: string[], rows: any[][]`. |
| GET | `/projects/{id}/datasets` | |
| GET / DELETE | `/datasets/{id}` | GET includes versions and the data dictionary. |
| GET | `/datasets/{id}/preview?offset=&limit=&version_id=` | One page of rows (max 500). |
| GET | `/datasets/{id}/download?version_id=&original=` | Working copy as CSV, or the untouched original file. |
| GET | `/datasets/{id}/dictionary` | |
| PUT | `/variables/{id}` | `label?, description?, measurement_level?, role?, unit?, valid_min?, valid_max?`. |
| POST | `/datasets/{id}/quality-check` | Runs the engine on the current version. |
| GET | `/datasets/{id}/quality-report?version_id=` | `score`, `summary`, `dimensions`, `issues[]` (each with `severity`, `message`, `examples`, `suggestion`). |
| GET | `/cleaning/operations` | Available operations. |
| POST | `/datasets/{id}/clean` | `operation, params, reason` (reason is mandatory). Creates a new version and re-runs the quality check. |
| GET | `/datasets/{id}/cleaning-history` | The audit trail with changed values, plus all versions. |
| POST | `/datasets/{id}/versions/{version_id}/restore?reason=` | Makes an earlier version current. Nothing is deleted. |

Cleaning operations and their `params`:

| Operation | Params |
|---|---|
| `remove_duplicates` | `subset?: string[]` |
| `drop_missing` | `columns?: string[]`, `how: "any" \| "all"` |
| `impute` | `column`, `strategy: "mean" \| "median" \| "mode" \| "constant"`, `value?` |
| `replace_values` | `column`, `mapping: {old: new \| null}` |
| `recode` | `column`, `mapping`, `new_column?`, `else_value?`, `measurement_level?` |
| `standardize_categories` | `column`, `case: "none" \| "lower" \| "upper" \| "title"`, `strip?`, `mapping?` |
| `convert_type` | `column`, `to` (data type), `measurement_level?` |
| `remove_invalid` | `column`, `min?`, `max?`, `invalid_values?`, `non_numeric?`, `action: "set_missing" \| "drop_rows"` |
| `winsorize` | `column`, `lower_pct`, `upper_pct` |
| `transform` | `column`, `function: "log" \| "log10" \| "log1p" \| "sqrt" \| "square" \| "reciprocal"`, `new_column?` |
| `normalize`, `standardize` | `column`, `new_column?` |
| `derive` | `new_column`, `operation: "sum" \| "mean" \| "difference" \| "product" \| "ratio"`, `columns`, `min_valid?` |
| `drop_columns` | `columns` |
| `rename_column` | `column`, `new_name` |

## Analysis

| Method | Path | Notes |
|---|---|---|
| GET | `/methods` | Method catalogue (with `implemented`, `roles`, `options`), chart types, power designs. |
| POST | `/projects/{id}/analysis` | See below. |
| GET | `/projects/{id}/analysis` | All runs. |
| GET / DELETE | `/analysis/{id}` | GET returns the run with `results[].result` (the engine output). A reproduction also returns `reproduction_check`. |
| POST | `/analysis/{id}/test` | Adds a test to an inferential run: `method, variables, params?, hypothesis_id?, justification?`. |
| POST | `/analysis/{id}/reproduce` | Re-runs the stored configuration on the same dataset version. |
| POST | `/power` | Stateless calculator: `design, mode, effect_size, n?, power?, alpha?, two_sided?, k_groups?, df?, n_predictors?, ratio?`. |

`POST /projects/{id}/analysis` body:

```json
{
  "analysis_type": "inferential",
  "dataset_id": 3,
  "method": "pearson",
  "variables": {"x": "social_media_hours", "y": "gpa"},
  "params": {"alpha": 0.05, "alternative": "two-sided"},
  "filters": [{"column": "age", "op": "not_missing"}],
  "research_question_id": 1,
  "hypothesis_id": 1,
  "justification": "Both variables are continuous."
}
```

- `analysis_type`: `eda`, `descriptive` (`variables: {"variables": [...], "group_by": "..."}`),
  `inferential` (needs `method`), `power` (`params` as for `/power`).
- `dataset_version_id` may be given instead of `dataset_id` to analyse an earlier version.
- Filter operators: `eq, ne, gt, ge, lt, le, in, not_missing`.
- When `hypothesis_id` is given, the hypothesis' alpha is used and its decision
  is updated when the test completes.

Every statistical result has the same shape: `method, method_name, n, variables,
statistic{name,value}, df, p_value, alpha, significant, decision, estimates[],
effect_sizes[], assumptions[], tables[], warnings[], apa, summary, software, source`.

## Visualizations

| Method | Path | Notes |
|---|---|---|
| POST / GET | `/projects/{id}/visualizations` | `chart_type, dataset_id?, x?, y?, hue?, columns?, title?, x_label?, y_label?, bins?, method?, fit_line?, category_order?, width?, height?, include_in_report?` |
| POST / GET | `/analysis/{id}/visualizations` | Same, drawn on the run's dataset version and filters. |
| POST | `/analysis/{id}/diagnostic-plot` | Residual plots for a linear regression. |
| GET | `/visualizations/{id}/image?download=` | PNG. |
| PUT | `/visualizations/{id}` | Customise and regenerate, or toggle `include_in_report`. |
| DELETE | `/visualizations/{id}` | |

## AI assistant

All replies have `content`, `source` (`llm` or `rule_engine`), `provider`, `model`,
`notice` and `grounding` (`{checked, unverified[], grounded}`).

| Method | Path | Notes |
|---|---|---|
| GET | `/ai/status` | Whether a language model is configured. |
| POST | `/projects/{id}/ai/analyze` | `dataset_id?` – project and dataset review with next steps. |
| POST | `/projects/{id}/ai/recommend` | `dataset_id?, research_question_id?, outcome?, predictors[], paired, measures[], outcome_kind, goal?` – returns `recommendation` (from the rule engine) and `explanation`. |
| POST | `/projects/{id}/ai/explain` | One of `analysis_result_id`, `visualization_id`, `concept`; `question?`. |
| POST | `/projects/{id}/ai/chat` | `message, conversation_id?`. |
| GET | `/projects/{id}/ai/recommendations` · `/projects/{id}/ai/conversations` · `/ai/conversations/{id}` | History. |
| PUT | `/ai/recommendations/{id}?status=` | `open`, `accepted`, `dismissed`. |

## Findings, conclusions, recommendations, limitations

| Method | Path | Notes |
|---|---|---|
| GET / POST | `/projects/{id}/findings` | Manual finding. |
| POST | `/projects/{id}/findings/from-result` | `analysis_result_id, research_question_id?, hypothesis_id?` – drafts a finding from an engine result. |
| PUT / DELETE | `/findings/{id}` | Editing a drafted finding sets `is_edited`. |
| GET / POST | `/projects/{id}/conclusions` | `text, finding_ids[]`. |
| POST | `/projects/{id}/conclusions/generate` | `use_ai?, replace_engine_drafts?` – drafts built only from findings. |
| PUT / DELETE | `/conclusions/{id}` | |
| GET / POST | `/projects/{id}/recommendations` · POST `…/recommendations/generate` · PUT / DELETE `/recommendations/{id}` | Same shape as conclusions, plus `audience?`. |
| GET / POST | `/projects/{id}/limitations` | Manual limitation: `description, category?`. |
| POST | `/projects/{id}/limitations/detect` | Adds limitations detected from design, data and results. |
| PUT | `/limitations/{id}/status` | `status, status_note` – a note is required unless `active`. |
| DELETE | `/limitations/{id}` | Manual limitations only. |

## Reports, history and supervision

| Method | Path | Notes |
|---|---|---|
| GET | `/report-sections` | Section keys and formats. |
| POST | `/projects/{id}/reports` | `format` (`pdf`, `docx`, `xlsx`, `csv`), `title?`, `report_id?` (new version of an existing report), `sections?`, `dataset_id?`, `include_data?`. |
| GET | `/projects/{id}/reports` · `/reports/{id}` | |
| GET | `/reports/{id}/download?version=` | The file. |
| GET | `/reports/{id}/versions/{n}/content` | The stored snapshot the file was rendered from. |
| DELETE | `/reports/{id}` | |
| GET | `/projects/{id}/history?limit=&offset=&action=` | Audit trail (`action` is a prefix filter, e.g. `dataset`). |
| GET | `/projects/{id}/reviews` | Comments and the review status of each stage. |
| POST | `/projects/{id}/comments` | `stage, body, entity_type?, entity_id?`. |
| PUT | `/projects/{id}/stage-review` | `stage, status` (`approved`, `rejected`, `pending`), `note` (required to reject). Supervisor, owner or admin. |

## Administration (permission-protected)

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/users?search=&limit=&offset=` | |
| PUT | `/admin/users/{id}` | `is_active?, roles?`. |
| GET | `/admin/roles` · `/admin/stats` · `/admin/activity` | |
| GET | `/admin/settings` · PUT `/admin/settings/{key}` | Keys: `ai.enabled`, `ai.provider_override`, `uploads.max_mb`. Secrets are never settings. |
| GET | `/health` | Public liveness check. |
