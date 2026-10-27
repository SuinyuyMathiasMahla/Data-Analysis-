# Academic Research Data Analysis Platform

A web application that takes a student or researcher from a raw dataset to a
statistically valid, fully traceable research report:

```
Research project → research questions → hypotheses → data upload → data quality
→ audited cleaning → exploration → descriptive statistics → method recommendation
→ statistical tests (assumptions, effect sizes, confidence intervals)
→ AI-assisted interpretation → findings → conclusions → recommendations
→ limitations → PDF / DOCX / XLSX / CSV report
```

Every claim in the final report can be traced back:

**raw data → dataset version → analysis → statistical evidence → interpretation → finding → conclusion**

It supports undergraduate, Master's and PhD projects. The academic level changes
the depth of the guidance, never the method: methods are chosen from the
research question, design, variable types and assumption checks.

---

## Verification status (read this first)

The project was written in a sandbox that could not download packages, so not
everything could be executed there. This is exactly what was and was not run:

| Part | Status |
|---|---|
| Statistical engine (descriptive, correlation, association, group tests, linear / logistic / Poisson regression, PCA, factor analysis, clustering, reliability, power) | **Run.** 86 tests pass, including published R outputs (`sleep`, `PlantGrowth`, `mtcars`, Anscombe) and G\*Power sample sizes. |
| Data import, type inference, data-quality engine, all 15 cleaning operations, audit trail | **Run** on the sample dataset. |
| Charts (13 types + regression diagnostics) | **Run** and inspected visually. |
| Findings / conclusions / recommendations / limitations logic, AI guardrails and number-grounding check, rule-engine fallback | **Run.** |
| PDF, DOCX, XLSX, CSV report renderers | **Run**; the PDF was inspected page by page. |
| Whole pipeline on the sample data (`backend/scripts/demo_workflow.py`) | **Run** end to end. |
| `database/schema.sql` ↔ SQLAlchemy models | **Checked** by `backend/scripts/check_schema_sync.py` (39 tables, 336 columns, 75 foreign keys agree). **Not executed on MySQL.** |
| FastAPI layer (auth, routes, services, jobs) | **Written, linted and type-checked, but never started.** FastAPI and SQLAlchemy were not installable. Its tests (`tests/test_auth.py`, `tests/test_api_workflow.py`) are written and unrun. |
| statsmodels-backed models (negative binomial, mixed effects) and the statsmodels cross-checks | **Unrun** (statsmodels not installable). |
| React frontend | Compiles with esbuild and four pages were rendered against mocked API data and checked at desktop and phone width. **`npm install`, `vite build` and the Vitest suite were not run**, and the frontend has not talked to a live backend. |

So: expect the analysis engine to behave as tested, and expect to fix some
first-run issues in the API and frontend wiring. Start with
`pytest` (backend) and `npm run build` (frontend); both are designed to surface
those issues quickly.

---

## Architecture

```
frontend/  React 18 + TypeScript + Vite + React Router (fetch API, own component set)
    │  JSON over HTTPS, JWT bearer token
backend/   FastAPI
    ├── api/          routes (thin) + access control
    ├── services/     use-cases: auth, datasets, analysis jobs, evidence, reports, storage
    ├── analysis/     profiling, data quality, cleaning, EDA, charts, evidence rules   ← no web/DB code
    ├── statistics/   the statistical engine, method registry, recommender, power     ← no web/DB code
    ├── ai/           provider abstraction, context builder, integrity guard
    ├── reports/      report snapshot assembly + PDF/DOCX/XLSX/CSV renderers
    └── models/       SQLAlchemy ORM
database/  schema.sql (complete MySQL 8 schema) + seed.sql (development data)
storage/   uploaded files, working copies, charts, reports (local disk; S3 is an extension point)
```

Three rules shape the code:

1. **The statistical engine is the only source of numbers.** The AI layer
   receives engine results and may explain them; a post-check compares every
   number in an AI reply with the engine output and flags anything it cannot match.
2. **Nothing is edited in place.** The upload is stored byte-for-byte; every
   cleaning step writes a new dataset version with a mandatory reason.
3. **Every analysis is reproducible.** A run stores the dataset version,
   variables, parameters, filters, schema and library versions.

More detail: [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md),
[docs/statistical-methods.md](docs/statistical-methods.md), [docs/database.md](docs/database.md).

## Features

- Accounts: registration, login, logout, Argon2id password hashing, JWT access
  tokens, rotating refresh tokens with re-use detection, password reset, e-mail
  verification, account lockout, session list.
- Roles: researcher, supervisor, administrator, with per-project membership
  (supervisor / collaborator / viewer). A project a user has no access to is
  reported as "not found".
- Projects with research questions, hypotheses (null / alternative, directional
  or not, alpha), objectives and methodology.
- Import of CSV, XLSX, XLS, JSON and manual entry; type and measurement-level
  inference; data dictionary with editable labels, roles, units and valid ranges.
- Data-quality engine with a documented 0–100 score.
- 15 audited cleaning operations; restore any earlier version.
- EDA, descriptive statistics, 23 implemented statistical methods, 7 registered
  but not implemented (they refuse rather than produce output).
- Rule-based method recommendation with reasons, assumption checks on the real
  data and alternatives.
- 13 chart types rendered server-side, downloadable, customisable and
  includable in reports.
- AI assistant behind a provider abstraction (OpenAI, Gemini, Anthropic, local
  OpenAI-compatible server) with a labelled rule-engine fallback.
- Findings, conclusions, recommendations and limitations with evidence links.
- Reports in PDF, DOCX, XLSX and CSV, versioned, each with a stored snapshot.
- Project history (audit log), supervisor comments and stage approval.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- MySQL 8.0 or newer

## Installation

### 1. Database

```bash
mysql -u root -p < database/schema.sql          # creates the academic_research database
```

Create an application user (do not run the app as root):

```sql
CREATE USER 'research_app'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT SELECT, INSERT, UPDATE, DELETE ON academic_research.* TO 'research_app'@'localhost';
```

Optional development data (three accounts and a sample project):

```bash
mysql -u root -p academic_research < database/seed.sql
```

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
```

Edit `backend/.env`:

- `SECRET_KEY` – generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `DATABASE_URL` – put in the password you chose above

Run it:

```bash
uvicorn app.main:app --reload --port 8000
```

API docs: <http://localhost:8000/api/docs>. Health check: <http://localhost:8000/api/health>.

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env                 # VITE_API_URL=http://localhost:8000/api
npm run dev                          # http://localhost:5173
```

### Development accounts

After loading `database/seed.sql`:

| E-mail | Role | Password |
|---|---|---|
| `student@example.org` | researcher | `ResearchDev#2026` |
| `supervisor@example.org` | supervisor | `ResearchDev#2026` |
| `admin@example.org` | administrator | `ResearchDev#2026` |

These are for local development only. Never load `seed.sql` on a server that is
reachable by others. To create your own first administrator instead:

```bash
cd backend
python scripts/create_user.py --email you@university.edu --name "Your Name" --role admin
```

## Environment configuration

All settings are environment variables (read from `backend/.env`); nothing
secret is in the code. See `backend/.env.example` for the full list.

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development`, `test` or `production`. In production the app refuses to start with a weak `SECRET_KEY` or the placeholder database password. |
| `SECRET_KEY` | JWT signing key. |
| `DATABASE_URL` | `mysql+pymysql://user:password@host:3306/academic_research?charset=utf8mb4` |
| `CORS_ORIGINS` | Comma-separated list of allowed frontend origins. |
| `STORAGE_DIR`, `MAX_UPLOAD_MB` | Where files are stored and the upload limit. |
| `AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY`, `AI_BASE_URL` | AI assistant (see below). |
| `SMTP_*`, `FRONTEND_URL` | Outgoing e-mail. With `SMTP_HOST` empty, e-mails are printed in the server log. |
| `REQUIRE_EMAIL_VERIFICATION` | Refuse login until the address is verified. |

## Running tests

Backend (needs no MySQL: API tests use in-memory SQLite, jobs run inline):

```bash
cd backend
pytest                               # everything
pytest tests/test_statistics.py tests/test_regression.py     # known-answer statistics
python scripts/check_schema_sync.py  # schema.sql and the ORM models agree
python scripts/demo_workflow.py      # whole pipeline on the sample data, writes reports/demo/
```

Frontend:

```bash
cd frontend
npm run typecheck
npm test
npm run build
```

| Test file | What it covers |
|---|---|
| `tests/test_statistics.py` | Descriptives, correlation, chi-square, Fisher, t-tests, ANOVA, Tukey, Welch, Kruskal-Wallis, repeated measures, effect sizes, power, PCA, factor analysis, clustering, reliability, registry |
| `tests/test_regression.py` | OLS, logistic and Poisson against R, SciPy, scikit-learn and direct likelihood maximisation; statsmodels cross-checks |
| `tests/test_data_pipeline.py` | Import, type inference, quality, every cleaning operation, recommender, evidence rules, charts, report rendering |
| `tests/test_ai.py` | Grounding check, privacy of the AI context, rule-engine fallback, provider factory |
| `tests/test_auth.py` | Registration, login, lockout, token rotation, password reset, access control, admin, upload validation |
| `tests/test_api_workflow.py` | The complete workflow through the REST API |

## AI configuration

| `AI_PROVIDER` | Needs | Notes |
|---|---|---|
| `none` (default) | nothing | The built-in rule engine answers and says so. No data leaves the server. |
| `openai` | `AI_API_KEY`, `AI_MODEL` | Chat-completions API. |
| `gemini` | `AI_API_KEY`, `AI_MODEL` | Google Generative Language API. |
| `anthropic` | `AI_API_KEY`, `AI_MODEL` | Messages API. |
| `local` | `AI_MODEL`, optional `AI_BASE_URL` | Any OpenAI-compatible server, e.g. Ollama at `http://localhost:11434/v1`. |

Set `AI_MODEL` to a model name your provider currently offers. Switching
provider is a configuration change only. An administrator can also switch the
assistant off, or choose another configured provider, in the Administration page.

What is sent to a provider: the project description, research questions,
hypotheses, variable names with summary statistics, the data-quality summary and
engine results. Never raw rows, account data, or example values from free-text
and identifier columns.

## Dataset workflow

1. **Upload.** The file is validated (extension, content signature, size) and
   stored unchanged as version 0. A working copy (version 1) is created.
2. **Profile.** Types and measurement levels are inferred and the data
   dictionary is built. Check the measurement levels: they drive method choice.
3. **Quality check.** Missing values, duplicates, invalid and impossible values,
   inconsistent categories, outliers, constant columns, collinearity and
   suspicious patterns are reported with a score.
4. **Clean.** Each operation needs a written reason and produces a new version.
   Values that do not fit their type are treated as missing in analyses but are
   not changed in the stored data until you clean them.
5. **Analyse.** Each analysis pins the version it ran on.
6. **Report.** The report states the version analysed and lists the cleaning steps.

`sample_data/student_performance.csv` is a simulated dataset with deliberate
problems for trying this out (see `sample_data/README.md`).

## Deployment

- Set `APP_ENV=production`, a strong `SECRET_KEY`, real `DATABASE_URL`,
  `CORS_ORIGINS` and SMTP settings.
- Run the API with several workers behind a reverse proxy that terminates TLS:
  `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 127.0.0.1:8000`
  (add `gunicorn` to the requirements).
- Build the frontend with `npm run build` and serve `frontend/dist/` as static
  files, with all unknown paths falling back to `index.html`.
- Back up both the MySQL database and the `STORAGE_DIR` directory; a database
  without its files cannot reproduce analyses.
- Two components are in-process and should be replaced before scaling beyond
  one server: the rate limiter (`core/rate_limit.py`, replace with Redis) and
  the job runner (`services/analysis_service.py`, a thread pool; replace with a
  queue such as Celery or RQ). A job that is running when the server restarts
  stays in `PROCESSING`; re-run it.
- After the initial install, mark the schema as the migration baseline with
  `cd backend && alembic stamp 0001_baseline`, and use Alembic for later changes.

## Not implemented (stated, not faked)

- Survival analysis, time-series models, MANOVA, factorial ANOVA / ANCOVA,
  ordinal and multinomial regression, other GLM families, structural equation
  modelling. They are registered so the recommender can name them as the right
  method, and they return a clear "not implemented" error.
- S3 storage (`services/storage.py` has the interface and a TODO class).
- Qualitative analysis (transcripts, coding, themes). The schema has a
  `data_kind` column and the layering leaves room for it.
- Real-time collaboration, subscriptions and usage limits.
- Multiple imputation, Mauchly's test (Greenhouse-Geisser correction is applied instead).

## Project structure

```
academic-data-analysis/
├── backend/
│   ├── app/{api,core,models,schemas,services,analysis,statistics,ai,reports,database}/
│   ├── tests/
│   ├── scripts/        create_user.py, demo_workflow.py, check_schema_sync.py, generate_sample_data.py
│   ├── alembic/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/{components,pages,layouts,services,hooks,types,utils,__tests__}/
│   └── package.json
├── database/           schema.sql, seed.sql
├── docs/               architecture.md, api.md, database.md, statistical-methods.md
├── sample_data/
├── uploads/  reports/  (kept for layout; runtime files go to storage/)
└── README.md
```
#   D a t a - A n a l y s i s -  
 