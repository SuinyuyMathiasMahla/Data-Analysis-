# Database

MySQL 8, `utf8mb4`. The complete schema is `database/schema.sql`; it creates the
`academic_research` database from scratch, including the roles and permissions
the application needs. `database/seed.sql` adds development accounts and a
sample project.

```bash
mysql -u root -p < database/schema.sql
mysql -u root -p academic_research < database/seed.sql     # development only
```

`schema.sql` drops and recreates the database. Never run it against data you want to keep.

## Design rules

- Surrogate `BIGINT UNSIGNED` keys; join tables use composite keys.
- All timestamps are UTC.
- **Files are not stored in MySQL.** Tables hold a `storage_key`; the storage
  layer resolves it (local disk now, object storage later).
- Engine output that is always read as a whole (a result, a quality report, a
  report snapshot) is JSON. Anything filtered or joined on has a typed column;
  for example `analysis_results` repeats `statistic_value`, `p_value` and
  `is_significant` beside `result_json`.
- Deleting a project cascades to everything it owns. `audit_logs` uses
  `SET NULL` instead, so system-level history survives.

## Tables (39)

**Identity** – `users`, `roles`, `permissions`, `role_permissions`, `user_roles`,
`refresh_tokens` (one row per session, token stored as SHA-256), `user_tokens`
(password reset and e-mail verification, single use, hashed).

**Research design** – `projects`, `project_members`, `objectives`,
`research_questions`, `hypotheses`, `research_question_variables`.

**Data** – `datasets`, `dataset_versions`, `variables` (the editable data
dictionary), `dataset_columns` (machine profile of each column in one version),
`data_quality_reports`, `cleaning_operations`.

**Analysis** – `analysis_runs`, `statistical_tests`, `analysis_results`, `visualizations`.

**Evidence** – `findings`, `conclusions`, `conclusion_findings`, `recommendations`,
`recommendation_findings`, `limitations`.

**Reports** – `reports`, `report_versions`.

**AI** – `ai_conversations`, `ai_messages`, `ai_recommendations`.

**Supervision and operations** – `review_comments`, `stage_reviews`, `audit_logs`,
`notifications`, `system_settings`.

## The relationships that carry the evidence trail

```
projects ─┬─ research_questions ─┬─ hypotheses
          │                      └─ research_question_variables ── variables
          ├─ datasets ── dataset_versions ◄── cleaning_operations (input → output version, reason)
          │                    ▲
          ├─ analysis_runs ────┘ (pins one version; config, filters, software)
          │      └─ statistical_tests ── analysis_results
          │                                   ▲
          ├─ findings ────────────────────────┘ (+ research question, hypothesis)
          │      ▲
          ├─ conclusions ── conclusion_findings
          ├─ recommendations ── recommendation_findings
          └─ reports ── report_versions (content_json = frozen snapshot)
```

Following the foreign keys backwards from a conclusion gives: findings →
analysis result → statistical test and run → dataset version → the cleaning
operations that produced it → the original upload.

## Versioning

`dataset_versions.version_number = 0` is always the untouched upload
(`kind = 'original'`). Version 1 is the first working copy. Each cleaning
operation inserts a new working version whose `parent_version_id` is its input,
and one `cleaning_operations` row. `datasets.current_version_id` points at the
version new analyses use; restoring an earlier version only moves this pointer.
`datasets` and `dataset_versions` reference each other, so the second foreign
key is added with `ALTER TABLE` after both tables exist.

## Keeping the schema and the code in step

- `python backend/scripts/check_schema_sync.py` compares table and column names
  in `schema.sql` with the ORM models and checks every foreign key's target and
  type. Run it after changing either side.
- For changes after the first install use Alembic: `alembic stamp 0001_baseline`
  once, then `alembic revision --autogenerate -m "..."` and `alembic upgrade head`.
  Update `schema.sql` in the same change so that new installs match.

## Notes

- The API tests run on SQLite. The models therefore use portable types (string
  columns where MySQL has `ENUM`), and MySQL enforces the enumerations.
- JSON columns need MySQL 5.7.8+; the script targets 8.0.
- `ai_messages.context_json` records what was sent to the model (counts and the
  focus item), and `grounding_json` the result of the number check.
