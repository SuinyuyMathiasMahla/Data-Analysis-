-- =============================================================================
-- Academic Research Data Analysis Platform — complete database schema
-- Target: MySQL 8.0+
--
-- Usage (from the project root, on a fresh MySQL server):
--     mysql -u root -p < database/schema.sql
-- or, inside the mysql client:
--     SOURCE database/schema.sql;
--
-- The script is idempotent for a development machine: it drops and recreates
-- the `academic_research` database. Do NOT run it against a database that
-- holds data you want to keep.
--
-- Conventions
--   * Every table has a surrogate BIGINT UNSIGNED primary key unless it is a
--     pure join table.
--   * All timestamps are stored in UTC.
--   * Large files (datasets, charts, reports) are NOT stored here. Tables hold
--     a `storage_key` that the storage layer resolves (local disk or S3).
--   * JSON columns hold engine output that is read back as a whole document;
--     anything that is filtered or joined on has its own typed column.
-- =============================================================================

DROP DATABASE IF EXISTS academic_research;
CREATE DATABASE academic_research
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE academic_research;

SET NAMES utf8mb4;
SET time_zone = '+00:00';

-- -----------------------------------------------------------------------------
-- 1. Identity, roles and permissions
-- -----------------------------------------------------------------------------

CREATE TABLE roles (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  name          VARCHAR(50)     NOT NULL,
  description   VARCHAR(255)    NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_roles_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE permissions (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code          VARCHAR(100)    NOT NULL,
  description   VARCHAR(255)    NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_permissions_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE role_permissions (
  role_id       BIGINT UNSIGNED NOT NULL,
  permission_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (role_id, permission_id),
  KEY ix_role_permissions_permission (permission_id),
  CONSTRAINT fk_role_permissions_role FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE,
  CONSTRAINT fk_role_permissions_permission FOREIGN KEY (permission_id) REFERENCES permissions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE users (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  email              VARCHAR(255)    NOT NULL,
  password_hash      VARCHAR(255)    NOT NULL,
  full_name          VARCHAR(200)    NOT NULL,
  institution        VARCHAR(200)    NULL,
  department         VARCHAR(200)    NULL,
  academic_level     ENUM('undergraduate','masters','phd') NULL,
  is_active          TINYINT(1)      NOT NULL DEFAULT 1,
  is_email_verified  TINYINT(1)      NOT NULL DEFAULT 0,
  failed_login_count INT UNSIGNED    NOT NULL DEFAULT 0,
  locked_until       DATETIME        NULL,
  last_login_at      DATETIME        NULL,
  created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email (email),
  KEY ix_users_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE user_roles (
  user_id       BIGINT UNSIGNED NOT NULL,
  role_id       BIGINT UNSIGNED NOT NULL,
  assigned_at   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, role_id),
  KEY ix_user_roles_role (role_id),
  CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- One row per signed-in session. Only a SHA-256 hash of the refresh token is
-- stored, so a database leak does not expose usable tokens.
CREATE TABLE refresh_tokens (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id       BIGINT UNSIGNED NOT NULL,
  token_hash    CHAR(64)        NOT NULL,
  user_agent    VARCHAR(255)    NULL,
  ip_address    VARCHAR(45)     NULL,
  expires_at    DATETIME        NOT NULL,
  revoked_at    DATETIME        NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_refresh_tokens_hash (token_hash),
  KEY ix_refresh_tokens_user (user_id),
  KEY ix_refresh_tokens_expires (expires_at),
  CONSTRAINT fk_refresh_tokens_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Single-use tokens for password reset and e-mail verification (hashed).
CREATE TABLE user_tokens (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id       BIGINT UNSIGNED NOT NULL,
  purpose       ENUM('password_reset','email_verify') NOT NULL,
  token_hash    CHAR(64)        NOT NULL,
  expires_at    DATETIME        NOT NULL,
  used_at       DATETIME        NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_user_tokens_hash (token_hash),
  KEY ix_user_tokens_user_purpose (user_id, purpose),
  CONSTRAINT fk_user_tokens_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 2. Research projects and design
-- -----------------------------------------------------------------------------

CREATE TABLE projects (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  owner_id               BIGINT UNSIGNED NOT NULL,
  title                  VARCHAR(300)    NOT NULL,
  academic_level         ENUM('undergraduate','masters','phd') NOT NULL,
  research_field         VARCHAR(150)    NULL,
  institution            VARCHAR(200)    NULL,
  department             VARCHAR(200)    NULL,
  research_problem       TEXT            NULL,
  general_objective      TEXT            NULL,
  study_population       TEXT            NULL,
  sample_size            INT UNSIGNED    NULL,
  sampling_technique     VARCHAR(150)    NULL,
  research_methodology   VARCHAR(150)    NULL,
  study_design           VARCHAR(150)    NULL,
  data_collection_method VARCHAR(255)    NULL,
  status                 ENUM('draft','active','completed','archived') NOT NULL DEFAULT 'draft',
  created_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_projects_owner_status (owner_id, status),
  CONSTRAINT fk_projects_owner FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Explicit collaboration permissions (supervisors, collaborators, viewers).
CREATE TABLE project_members (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  user_id       BIGINT UNSIGNED NOT NULL,
  member_role   ENUM('supervisor','collaborator','viewer') NOT NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_project_members (project_id, user_id),
  KEY ix_project_members_user (user_id),
  CONSTRAINT fk_project_members_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_project_members_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE objectives (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  position      INT UNSIGNED    NOT NULL DEFAULT 0,
  text          TEXT            NOT NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_objectives_project (project_id, position),
  CONSTRAINT fk_objectives_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE research_questions (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  code          VARCHAR(20)     NOT NULL,
  text          TEXT            NOT NULL,
  position      INT UNSIGNED    NOT NULL DEFAULT 0,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_research_questions_code (project_id, code),
  CONSTRAINT fk_research_questions_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE hypotheses (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id           BIGINT UNSIGNED NOT NULL,
  research_question_id BIGINT UNSIGNED NULL,
  code                 VARCHAR(20)     NOT NULL,
  null_text            TEXT            NOT NULL,
  alternative_text     TEXT            NOT NULL,
  direction            ENUM('non_directional','greater','less') NOT NULL DEFAULT 'non_directional',
  alpha                DECIMAL(5,4)    NOT NULL DEFAULT 0.0500,
  decision             ENUM('pending','reject_null','fail_to_reject_null') NOT NULL DEFAULT 'pending',
  created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_hypotheses_code (project_id, code),
  KEY ix_hypotheses_rq (research_question_id),
  CONSTRAINT fk_hypotheses_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_hypotheses_rq FOREIGN KEY (research_question_id) REFERENCES research_questions (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 3. Datasets, versions and the data dictionary
-- -----------------------------------------------------------------------------

CREATE TABLE datasets (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id         BIGINT UNSIGNED NOT NULL,
  name               VARCHAR(200)    NOT NULL,
  description        TEXT            NULL,
  data_kind          ENUM('quantitative','qualitative') NOT NULL DEFAULT 'quantitative',
  source_type        ENUM('csv','xlsx','xls','json','manual') NOT NULL,
  original_filename  VARCHAR(255)    NULL,
  current_version_id BIGINT UNSIGNED NULL,
  created_by         BIGINT UNSIGNED NULL,
  created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_datasets_project (project_id),
  KEY ix_datasets_created_by (created_by),
  KEY ix_datasets_current_version (current_version_id),
  CONSTRAINT fk_datasets_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_datasets_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Version 0 is always the untouched original upload (kind = 'original').
-- Every cleaning operation writes a NEW 'working' version; nothing is edited
-- in place, which is what makes analyses reproducible.
CREATE TABLE dataset_versions (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  dataset_id        BIGINT UNSIGNED NOT NULL,
  version_number    INT UNSIGNED    NOT NULL,
  parent_version_id BIGINT UNSIGNED NULL,
  kind              ENUM('original','working') NOT NULL,
  storage_key       VARCHAR(500)    NOT NULL,
  file_format       VARCHAR(20)     NOT NULL,
  checksum_sha256   CHAR(64)        NOT NULL,
  size_bytes        BIGINT UNSIGNED NOT NULL DEFAULT 0,
  row_count         INT UNSIGNED    NOT NULL DEFAULT 0,
  column_count      INT UNSIGNED    NOT NULL DEFAULT 0,
  schema_json       JSON            NULL,
  note              VARCHAR(500)    NULL,
  created_by        BIGINT UNSIGNED NULL,
  created_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_dataset_versions_number (dataset_id, version_number),
  KEY ix_dataset_versions_parent (parent_version_id),
  KEY ix_dataset_versions_created_by (created_by),
  CONSTRAINT fk_dataset_versions_dataset FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE,
  CONSTRAINT fk_dataset_versions_parent FOREIGN KEY (parent_version_id) REFERENCES dataset_versions (id) ON DELETE SET NULL,
  CONSTRAINT fk_dataset_versions_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE datasets
  ADD CONSTRAINT fk_datasets_current_version FOREIGN KEY (current_version_id) REFERENCES dataset_versions (id) ON DELETE SET NULL;

-- Researcher-facing data dictionary: one row per variable of a dataset.
-- Labels, measurement level, role and valid range are editable by the user.
CREATE TABLE variables (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id        BIGINT UNSIGNED NOT NULL,
  dataset_id        BIGINT UNSIGNED NOT NULL,
  name              VARCHAR(190)    NOT NULL,
  label             VARCHAR(255)    NULL,
  description       TEXT            NULL,
  data_type         ENUM('numeric','integer','categorical','boolean','datetime','text','identifier') NOT NULL,
  measurement_level ENUM('nominal','ordinal','interval','ratio') NOT NULL,
  role              ENUM('dependent','independent','control','moderator','mediator','identifier','other') NOT NULL DEFAULT 'other',
  unit              VARCHAR(50)     NULL,
  valid_min         DOUBLE          NULL,
  valid_max         DOUBLE          NULL,
  created_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_variables_dataset_name (dataset_id, name),
  KEY ix_variables_project (project_id),
  CONSTRAINT fk_variables_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_variables_dataset FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Machine-computed profile of each column in one specific dataset version.
CREATE TABLE dataset_columns (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  dataset_version_id BIGINT UNSIGNED NOT NULL,
  variable_id        BIGINT UNSIGNED NULL,
  name               VARCHAR(190)    NOT NULL,
  position           INT UNSIGNED    NOT NULL DEFAULT 0,
  inferred_type      VARCHAR(20)     NOT NULL,
  n_unique           INT UNSIGNED    NOT NULL DEFAULT 0,
  n_missing          INT UNSIGNED    NOT NULL DEFAULT 0,
  stats_json         JSON            NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_dataset_columns_name (dataset_version_id, name),
  KEY ix_dataset_columns_variable (variable_id),
  CONSTRAINT fk_dataset_columns_version FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions (id) ON DELETE CASCADE,
  CONSTRAINT fk_dataset_columns_variable FOREIGN KEY (variable_id) REFERENCES variables (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Which variables answer which research question (traceability).
CREATE TABLE research_question_variables (
  research_question_id BIGINT UNSIGNED NOT NULL,
  variable_id          BIGINT UNSIGNED NOT NULL,
  role                 ENUM('dependent','independent','control','moderator','mediator','other') NOT NULL DEFAULT 'other',
  PRIMARY KEY (research_question_id, variable_id),
  KEY ix_rq_variables_variable (variable_id),
  CONSTRAINT fk_rq_variables_rq FOREIGN KEY (research_question_id) REFERENCES research_questions (id) ON DELETE CASCADE,
  CONSTRAINT fk_rq_variables_variable FOREIGN KEY (variable_id) REFERENCES variables (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE data_quality_reports (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  dataset_version_id BIGINT UNSIGNED NOT NULL,
  score              DECIMAL(5,2)    NOT NULL,
  issue_count        INT UNSIGNED    NOT NULL DEFAULT 0,
  summary_json       JSON            NOT NULL,
  issues_json        JSON            NOT NULL,
  created_by         BIGINT UNSIGNED NULL,
  created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_dq_reports_version (dataset_version_id, created_at),
  KEY ix_dq_reports_created_by (created_by),
  CONSTRAINT fk_dq_reports_version FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions (id) ON DELETE CASCADE,
  CONSTRAINT fk_dq_reports_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Audit trail of every transformation: what was done, why, by whom, and the
-- exact input and output versions.
CREATE TABLE cleaning_operations (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  dataset_id        BIGINT UNSIGNED NOT NULL,
  input_version_id  BIGINT UNSIGNED NOT NULL,
  output_version_id BIGINT UNSIGNED NOT NULL,
  operation         VARCHAR(50)     NOT NULL,
  params_json       JSON            NOT NULL,
  reason            TEXT            NOT NULL,
  rows_before       INT UNSIGNED    NOT NULL,
  rows_after        INT UNSIGNED    NOT NULL,
  cells_changed     INT UNSIGNED    NOT NULL DEFAULT 0,
  details_json      JSON            NULL,
  performed_by      BIGINT UNSIGNED NULL,
  created_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_cleaning_dataset (dataset_id, created_at),
  KEY ix_cleaning_input (input_version_id),
  KEY ix_cleaning_output (output_version_id),
  KEY ix_cleaning_performed_by (performed_by),
  CONSTRAINT fk_cleaning_dataset FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE,
  CONSTRAINT fk_cleaning_input FOREIGN KEY (input_version_id) REFERENCES dataset_versions (id) ON DELETE CASCADE,
  CONSTRAINT fk_cleaning_output FOREIGN KEY (output_version_id) REFERENCES dataset_versions (id) ON DELETE CASCADE,
  CONSTRAINT fk_cleaning_performed_by FOREIGN KEY (performed_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 4. Analysis: runs (jobs), statistical tests and results
-- -----------------------------------------------------------------------------

-- An analysis run is one reproducible job: it pins the dataset version, the
-- configuration, the filters and the library versions it was executed with.
CREATE TABLE analysis_runs (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id           BIGINT UNSIGNED NOT NULL,
  dataset_version_id   BIGINT UNSIGNED NOT NULL,
  research_question_id BIGINT UNSIGNED NULL,
  reproduced_from_id   BIGINT UNSIGNED NULL,
  name                 VARCHAR(255)    NOT NULL,
  analysis_type        ENUM('eda','descriptive','inferential','power') NOT NULL,
  status               ENUM('PENDING','PROCESSING','COMPLETED','FAILED') NOT NULL DEFAULT 'PENDING',
  progress             TINYINT UNSIGNED NOT NULL DEFAULT 0,
  config_json          JSON            NOT NULL,
  filters_json         JSON            NULL,
  software_json        JSON            NULL,
  error_message        TEXT            NULL,
  created_by           BIGINT UNSIGNED NULL,
  created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at           DATETIME        NULL,
  completed_at         DATETIME        NULL,
  PRIMARY KEY (id),
  KEY ix_analysis_runs_project (project_id, created_at),
  KEY ix_analysis_runs_version (dataset_version_id),
  KEY ix_analysis_runs_rq (research_question_id),
  KEY ix_analysis_runs_status (status),
  KEY ix_analysis_runs_reproduced (reproduced_from_id),
  KEY ix_analysis_runs_created_by (created_by),
  CONSTRAINT fk_analysis_runs_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_analysis_runs_version FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions (id) ON DELETE CASCADE,
  CONSTRAINT fk_analysis_runs_rq FOREIGN KEY (research_question_id) REFERENCES research_questions (id) ON DELETE SET NULL,
  CONSTRAINT fk_analysis_runs_reproduced FOREIGN KEY (reproduced_from_id) REFERENCES analysis_runs (id) ON DELETE SET NULL,
  CONSTRAINT fk_analysis_runs_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE statistical_tests (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  analysis_run_id BIGINT UNSIGNED NOT NULL,
  hypothesis_id   BIGINT UNSIGNED NULL,
  method          VARCHAR(60)     NOT NULL,
  method_name     VARCHAR(150)    NOT NULL,
  variables_json  JSON            NOT NULL,
  params_json     JSON            NULL,
  status          ENUM('PENDING','PROCESSING','COMPLETED','FAILED') NOT NULL DEFAULT 'PENDING',
  error_message   TEXT            NULL,
  created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at    DATETIME        NULL,
  PRIMARY KEY (id),
  KEY ix_statistical_tests_run (analysis_run_id),
  KEY ix_statistical_tests_hypothesis (hypothesis_id),
  KEY ix_statistical_tests_method (method),
  CONSTRAINT fk_statistical_tests_run FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs (id) ON DELETE CASCADE,
  CONSTRAINT fk_statistical_tests_hypothesis FOREIGN KEY (hypothesis_id) REFERENCES hypotheses (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Results come ONLY from the statistical engine. The headline numbers are
-- duplicated into typed columns for querying; result_json is the full output.
CREATE TABLE analysis_results (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  analysis_run_id     BIGINT UNSIGNED NOT NULL,
  statistical_test_id BIGINT UNSIGNED NULL,
  result_type         VARCHAR(40)     NOT NULL,
  statistic_name      VARCHAR(40)     NULL,
  statistic_value     DOUBLE          NULL,
  degrees_of_freedom  VARCHAR(60)     NULL,
  p_value             DOUBLE          NULL,
  effect_size_name    VARCHAR(60)     NULL,
  effect_size_value   DOUBLE          NULL,
  is_significant      TINYINT(1)      NULL,
  sample_size         INT UNSIGNED    NULL,
  result_json         JSON            NOT NULL,
  engine_summary      TEXT            NULL,
  created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_analysis_results_run (analysis_run_id),
  KEY ix_analysis_results_test (statistical_test_id),
  CONSTRAINT fk_analysis_results_run FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs (id) ON DELETE CASCADE,
  CONSTRAINT fk_analysis_results_test FOREIGN KEY (statistical_test_id) REFERENCES statistical_tests (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE visualizations (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id         BIGINT UNSIGNED NOT NULL,
  dataset_version_id BIGINT UNSIGNED NOT NULL,
  analysis_run_id    BIGINT UNSIGNED NULL,
  chart_type         VARCHAR(40)     NOT NULL,
  title              VARCHAR(255)    NOT NULL,
  config_json        JSON            NOT NULL,
  storage_key        VARCHAR(500)    NOT NULL,
  include_in_report  TINYINT(1)      NOT NULL DEFAULT 0,
  created_by         BIGINT UNSIGNED NULL,
  created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_visualizations_project (project_id),
  KEY ix_visualizations_version (dataset_version_id),
  KEY ix_visualizations_run (analysis_run_id),
  KEY ix_visualizations_created_by (created_by),
  CONSTRAINT fk_visualizations_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_visualizations_version FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions (id) ON DELETE CASCADE,
  CONSTRAINT fk_visualizations_run FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs (id) ON DELETE SET NULL,
  CONSTRAINT fk_visualizations_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 5. Evidence trail: findings -> conclusions / recommendations / limitations
-- -----------------------------------------------------------------------------

CREATE TABLE findings (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id           BIGINT UNSIGNED NOT NULL,
  research_question_id BIGINT UNSIGNED NULL,
  hypothesis_id        BIGINT UNSIGNED NULL,
  analysis_result_id   BIGINT UNSIGNED NULL,
  title                VARCHAR(255)    NOT NULL,
  statement            TEXT            NOT NULL,
  statistical_evidence TEXT            NULL,
  interpretation       TEXT            NULL,
  confidence_level     ENUM('low','moderate','high') NOT NULL DEFAULT 'moderate',
  limitations_note     TEXT            NULL,
  source               ENUM('engine','ai','manual') NOT NULL DEFAULT 'engine',
  is_edited            TINYINT(1)      NOT NULL DEFAULT 0,
  created_by           BIGINT UNSIGNED NULL,
  created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_findings_project (project_id),
  KEY ix_findings_rq (research_question_id),
  KEY ix_findings_hypothesis (hypothesis_id),
  KEY ix_findings_result (analysis_result_id),
  KEY ix_findings_created_by (created_by),
  CONSTRAINT fk_findings_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_findings_rq FOREIGN KEY (research_question_id) REFERENCES research_questions (id) ON DELETE SET NULL,
  CONSTRAINT fk_findings_hypothesis FOREIGN KEY (hypothesis_id) REFERENCES hypotheses (id) ON DELETE SET NULL,
  CONSTRAINT fk_findings_result FOREIGN KEY (analysis_result_id) REFERENCES analysis_results (id) ON DELETE SET NULL,
  CONSTRAINT fk_findings_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE conclusions (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  text          TEXT            NOT NULL,
  source        ENUM('engine','ai','manual') NOT NULL DEFAULT 'engine',
  position      INT UNSIGNED    NOT NULL DEFAULT 0,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_conclusions_project (project_id, position),
  CONSTRAINT fk_conclusions_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE conclusion_findings (
  conclusion_id BIGINT UNSIGNED NOT NULL,
  finding_id    BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (conclusion_id, finding_id),
  KEY ix_conclusion_findings_finding (finding_id),
  CONSTRAINT fk_conclusion_findings_conclusion FOREIGN KEY (conclusion_id) REFERENCES conclusions (id) ON DELETE CASCADE,
  CONSTRAINT fk_conclusion_findings_finding FOREIGN KEY (finding_id) REFERENCES findings (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE recommendations (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  text          TEXT            NOT NULL,
  audience      VARCHAR(150)    NULL,
  source        ENUM('engine','ai','manual') NOT NULL DEFAULT 'manual',
  position      INT UNSIGNED    NOT NULL DEFAULT 0,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_recommendations_project (project_id, position),
  CONSTRAINT fk_recommendations_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE recommendation_findings (
  recommendation_id BIGINT UNSIGNED NOT NULL,
  finding_id        BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (recommendation_id, finding_id),
  KEY ix_recommendation_findings_finding (finding_id),
  CONSTRAINT fk_recommendation_findings_rec FOREIGN KEY (recommendation_id) REFERENCES recommendations (id) ON DELETE CASCADE,
  CONSTRAINT fk_recommendation_findings_finding FOREIGN KEY (finding_id) REFERENCES findings (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Auto-detected limitations are never deleted by the system; a researcher can
-- only change their status and must record why (status_note).
CREATE TABLE limitations (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  category      VARCHAR(60)     NOT NULL,
  description   TEXT            NOT NULL,
  source        ENUM('auto','ai','manual') NOT NULL DEFAULT 'auto',
  status        ENUM('active','acknowledged','not_applicable') NOT NULL DEFAULT 'active',
  status_note   TEXT            NULL,
  evidence_json JSON            NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_limitations_project (project_id, category),
  CONSTRAINT fk_limitations_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 6. Reports
-- -----------------------------------------------------------------------------

CREATE TABLE reports (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  title         VARCHAR(300)    NOT NULL,
  created_by    BIGINT UNSIGNED NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_reports_project (project_id),
  KEY ix_reports_created_by (created_by),
  CONSTRAINT fk_reports_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_reports_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- content_json is the frozen snapshot the file was rendered from, so an old
-- report can be re-rendered or audited even after the project has moved on.
CREATE TABLE report_versions (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  report_id      BIGINT UNSIGNED NOT NULL,
  version_number INT UNSIGNED    NOT NULL,
  format         ENUM('pdf','docx','xlsx','csv') NOT NULL,
  storage_key    VARCHAR(500)    NOT NULL,
  size_bytes     BIGINT UNSIGNED NOT NULL DEFAULT 0,
  content_json   JSON            NOT NULL,
  created_by     BIGINT UNSIGNED NULL,
  created_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_report_versions_number (report_id, version_number),
  KEY ix_report_versions_created_by (created_by),
  CONSTRAINT fk_report_versions_report FOREIGN KEY (report_id) REFERENCES reports (id) ON DELETE CASCADE,
  CONSTRAINT fk_report_versions_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 7. AI assistant
-- -----------------------------------------------------------------------------

CREATE TABLE ai_conversations (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  user_id       BIGINT UNSIGNED NOT NULL,
  title         VARCHAR(255)    NOT NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_ai_conversations_project (project_id, updated_at),
  KEY ix_ai_conversations_user (user_id),
  CONSTRAINT fk_ai_conversations_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_ai_conversations_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- context_json records exactly which engine results were sent to the model;
-- grounding_json records the post-check of numbers in the reply against them.
CREATE TABLE ai_messages (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  conversation_id BIGINT UNSIGNED NOT NULL,
  role            ENUM('user','assistant','system') NOT NULL,
  content         MEDIUMTEXT      NOT NULL,
  provider        VARCHAR(40)     NULL,
  model           VARCHAR(100)    NULL,
  context_json    JSON            NULL,
  grounding_json  JSON            NULL,
  created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_ai_messages_conversation (conversation_id, created_at),
  CONSTRAINT fk_ai_messages_conversation FOREIGN KEY (conversation_id) REFERENCES ai_conversations (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE ai_recommendations (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id           BIGINT UNSIGNED NOT NULL,
  research_question_id BIGINT UNSIGNED NULL,
  dataset_version_id   BIGINT UNSIGNED NULL,
  recommended_method   VARCHAR(60)     NOT NULL,
  rationale            TEXT            NOT NULL,
  payload_json         JSON            NOT NULL,
  source               ENUM('rule_engine','llm') NOT NULL DEFAULT 'rule_engine',
  status               ENUM('open','accepted','dismissed') NOT NULL DEFAULT 'open',
  created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_ai_recommendations_project (project_id, status),
  KEY ix_ai_recommendations_rq (research_question_id),
  KEY ix_ai_recommendations_version (dataset_version_id),
  CONSTRAINT fk_ai_recommendations_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_ai_recommendations_rq FOREIGN KEY (research_question_id) REFERENCES research_questions (id) ON DELETE SET NULL,
  CONSTRAINT fk_ai_recommendations_version FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 8. Supervision, history, notifications and configuration
-- -----------------------------------------------------------------------------

CREATE TABLE review_comments (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  author_id     BIGINT UNSIGNED NOT NULL,
  stage         VARCHAR(40)     NOT NULL,
  entity_type   VARCHAR(40)     NULL,
  entity_id     BIGINT UNSIGNED NULL,
  body          TEXT            NOT NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_review_comments_project (project_id, stage),
  KEY ix_review_comments_author (author_id),
  CONSTRAINT fk_review_comments_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_review_comments_author FOREIGN KEY (author_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE stage_reviews (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  stage         VARCHAR(40)     NOT NULL,
  status        ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  reviewer_id   BIGINT UNSIGNED NULL,
  note          TEXT            NULL,
  reviewed_at   DATETIME        NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_stage_reviews (project_id, stage),
  KEY ix_stage_reviews_reviewer (reviewer_id),
  CONSTRAINT fk_stage_reviews_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_stage_reviews_reviewer FOREIGN KEY (reviewer_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Append-only history. Rows survive the deletion of the user or project they
-- refer to (SET NULL) so that system-level activity can still be audited.
CREATE TABLE audit_logs (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id       BIGINT UNSIGNED NULL,
  project_id    BIGINT UNSIGNED NULL,
  action        VARCHAR(80)     NOT NULL,
  entity_type   VARCHAR(40)     NULL,
  entity_id     BIGINT UNSIGNED NULL,
  details_json  JSON            NULL,
  ip_address    VARCHAR(45)     NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_audit_logs_project (project_id, created_at),
  KEY ix_audit_logs_user (user_id, created_at),
  KEY ix_audit_logs_action (action),
  CONSTRAINT fk_audit_logs_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
  CONSTRAINT fk_audit_logs_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE notifications (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id       BIGINT UNSIGNED NOT NULL,
  project_id    BIGINT UNSIGNED NULL,
  type          VARCHAR(40)     NOT NULL,
  title         VARCHAR(255)    NOT NULL,
  body          TEXT            NULL,
  is_read       TINYINT(1)      NOT NULL DEFAULT 0,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_notifications_user (user_id, is_read, created_at),
  KEY ix_notifications_project (project_id),
  CONSTRAINT fk_notifications_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_notifications_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Non-secret, admin-editable configuration (e.g. which AI provider is active).
-- API keys are NEVER stored here; they live in environment variables.
CREATE TABLE system_settings (
  setting_key   VARCHAR(100)    NOT NULL,
  value_json    JSON            NOT NULL,
  updated_by    BIGINT UNSIGNED NULL,
  updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (setting_key),
  KEY ix_system_settings_updated_by (updated_by),
  CONSTRAINT fk_system_settings_updated_by FOREIGN KEY (updated_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 9. Reference data required by the application (roles and permissions)
-- -----------------------------------------------------------------------------

INSERT INTO roles (id, name, description) VALUES
  (1, 'researcher', 'Student or researcher: owns and manages their own research projects'),
  (2, 'supervisor', 'Supervisor or research advisor: reviews projects they are assigned to'),
  (3, 'admin',      'System administrator: manages users, roles and configuration');

INSERT INTO permissions (id, code, description) VALUES
  (1,  'project.manage_own',  'Create, edit and delete own projects'),
  (2,  'dataset.manage_own',  'Upload, clean and version datasets in own projects'),
  (3,  'analysis.run_own',    'Run analyses and visualizations in own projects'),
  (4,  'report.manage_own',   'Generate and download reports for own projects'),
  (5,  'ai.use',              'Use the AI research assistant'),
  (6,  'review.view_assigned','View projects assigned for supervision'),
  (7,  'review.comment',      'Comment on assigned projects'),
  (8,  'review.approve',      'Approve or reject analysis stages of assigned projects'),
  (9,  'admin.users',         'Manage users and roles'),
  (10, 'admin.settings',      'Manage system and AI configuration'),
  (11, 'admin.stats',         'View system-level statistics and activity');

INSERT INTO role_permissions (role_id, permission_id) VALUES
  (1, 1), (1, 2), (1, 3), (1, 4), (1, 5),
  (2, 5), (2, 6), (2, 7), (2, 8),
  (3, 1), (3, 2), (3, 3), (3, 4), (3, 5), (3, 6), (3, 7), (3, 8), (3, 9), (3, 10), (3, 11);

INSERT INTO system_settings (setting_key, value_json) VALUES
  ('ai.enabled',           'true'),
  ('ai.provider_override', 'null'),
  ('uploads.max_mb',       '25');
