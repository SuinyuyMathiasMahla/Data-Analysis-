// Shapes returned by the backend API (see docs/api.md).

export type AcademicLevel = "undergraduate" | "masters" | "phd";
export type RunStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

export interface User {
  id: number;
  email: string;
  full_name: string;
  institution: string | null;
  department: string | null;
  academic_level: AcademicLevel | null;
  is_active: boolean;
  is_email_verified: boolean;
  roles: string[];
  permissions: string[];
  last_login_at: string | null;
  created_at: string | null;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: User;
}

export interface ProgressStep {
  key: string;
  label: string;
  done: boolean;
}

export interface Progress {
  percent: number;
  steps: ProgressStep[];
  next_step: string | null;
}

export interface Project {
  id: number;
  owner_id: number;
  owner_name: string | null;
  title: string;
  academic_level: AcademicLevel;
  research_field: string | null;
  institution: string | null;
  department: string | null;
  research_problem: string | null;
  general_objective: string | null;
  study_population: string | null;
  sample_size: number | null;
  sampling_technique: string | null;
  research_methodology: string | null;
  study_design: string | null;
  data_collection_method: string | null;
  status: "draft" | "active" | "completed" | "archived";
  project_type: "personal" | "client";
  client_name: string | null;
  client_email: string | null;
  client_whatsapp: string | null;
  approximate_cost?: number;
  cost_currency?: string;
  created_at: string;
  updated_at: string;
  progress?: Progress;
  my_role?: string | null;
}

export interface Member {
  id: number;
  user_id: number;
  member_role: string;
  full_name: string | null;
  email: string | null;
}

export interface ResearchQuestion {
  id: number;
  project_id: number;
  code: string;
  text: string;
  position: number;
  variables: { variable_id: number; role: string; name: string | null }[];
}

export interface Hypothesis {
  id: number;
  project_id: number;
  research_question_id: number | null;
  code: string;
  null_text: string;
  alternative_text: string;
  direction: "non_directional" | "greater" | "less";
  alpha: number;
  decision: "pending" | "reject_null" | "fail_to_reject_null";
}

export interface DatasetVersion {
  id: number;
  dataset_id: number;
  version_number: number;
  parent_version_id: number | null;
  kind: "original" | "working";
  file_format: string;
  checksum_sha256: string;
  size_bytes: number;
  row_count: number;
  column_count: number;
  note: string | null;
  created_at: string;
}

export interface Variable {
  id: number;
  dataset_id: number;
  name: string;
  label: string | null;
  description: string | null;
  data_type: "numeric" | "integer" | "categorical" | "boolean" | "datetime" | "text" | "identifier";
  measurement_level: "nominal" | "ordinal" | "interval" | "ratio";
  role: string;
  unit: string | null;
  valid_min: number | null;
  valid_max: number | null;
  n_unique?: number;
  n_missing?: number;
  position?: number;
  stats?: Record<string, any>;
}

export interface Dataset {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  source_type: string;
  original_filename: string | null;
  current_version_id: number | null;
  current_version_number: number | null;
  row_count: number | null;
  column_count: number | null;
  quality_score?: number | null;
  created_at: string;
  versions?: DatasetVersion[];
  variables?: Variable[];
}

export interface ProjectDetail extends Project {
  objectives: { id: number; position: number; text: string }[];
  members: Member[];
  progress: Progress;
  rights: string[];
  research_questions: ResearchQuestion[];
  hypotheses: Hypothesis[];
  datasets: Dataset[];
}

export interface QualityIssue {
  code: string;
  severity: "high" | "medium" | "low" | "info";
  column: string | null;
  count: number;
  message: string;
  examples: any[];
  suggestion: { operation: string; params: Record<string, any> } | null;
  affects_score: boolean;
}

export interface QualityReport {
  id: number;
  dataset_version_id: number;
  version_number: number | null;
  score: number;
  issue_count: number;
  summary: Record<string, number>;
  dimensions: Record<string, { weight: number; affected_share: number; points_lost: number }>;
  issues: QualityIssue[];
  created_at: string;
}

export interface CleaningOperation {
  id: number;
  operation: string;
  label: string;
  params: Record<string, any>;
  reason: string;
  rows_before: number;
  rows_after: number;
  cells_changed: number;
  input_version_number: number | null;
  output_version_number: number | null;
  output_version_id: number;
  in_current_version: boolean;
  created_at: string;
  details: {
    changes?: { row: number; column: string; old: string | null; new: string | null }[];
    rows_removed?: number[];
    note?: string | null;
    [key: string]: any;
  };
}

export interface ResultTable {
  title: string;
  columns: string[];
  rows: any[][];
  note?: string | null;
}

export interface EffectSize {
  name: string;
  value: number | null;
  magnitude: string | null;
  ci_low: number | null;
  ci_high: number | null;
  note?: string | null;
}

export interface AssumptionCheck {
  name: string;
  test: string | null;
  statistic: number | null;
  p_value: number | null;
  satisfied: boolean | null;
  note: string;
}

/** Standard result produced by the statistical engine. */
export interface EngineResult {
  method: string;
  method_name: string;
  n: number;
  variables: Record<string, any>;
  alpha?: number;
  statistic?: { name: string; value: number | null } | null;
  df?: string | number | null;
  p_value?: number | null;
  significant?: boolean | null;
  decision?: string | null;
  estimates?: { name: string; value: number | null; ci_low: number | null; ci_high: number | null }[];
  effect_sizes?: EffectSize[];
  assumptions?: AssumptionCheck[];
  tables?: ResultTable[];
  warnings?: string[];
  apa?: string | null;
  summary?: string | null;
  highlights?: string[];
  suggested_charts?: Record<string, any>[];
  software?: Record<string, string>;
  [key: string]: any;
}

export interface AnalysisResultRow {
  id: number;
  analysis_run_id: number;
  statistical_test_id: number | null;
  result_type: string;
  statistic_name: string | null;
  statistic_value: number | null;
  p_value: number | null;
  is_significant: boolean | null;
  engine_summary: string | null;
  result?: EngineResult;
  test?: { id: number; method: string; method_name: string; hypothesis_id: number | null; status: RunStatus; error_message: string | null } | null;
}

export interface AnalysisRun {
  id: number;
  project_id: number;
  dataset_id: number | null;
  dataset_version_id: number;
  version_number: number | null;
  research_question_id: number | null;
  reproduced_from_id: number | null;
  name: string;
  analysis_type: "eda" | "descriptive" | "inferential" | "power";
  status: RunStatus;
  progress: number;
  config: Record<string, any>;
  filters: any[];
  software: Record<string, string>;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  tests: { id: number; method: string; method_name: string; status: RunStatus; error_message: string | null; hypothesis_id: number | null }[];
  result_summaries: AnalysisResultRow[];
  results?: AnalysisResultRow[];
  reproduction_check?: { identical: boolean; results: any[] };
}

export interface MethodRole {
  name: string;
  label: string;
  kind: "numeric" | "categorical" | "any";
  multiple: boolean;
  min: number;
}

export interface MethodInfo {
  key: string;
  name: string;
  category: string;
  roles: MethodRole[];
  implemented: boolean;
  typical_level: AcademicLevel;
  description: string;
  options: string[];
  not_implemented_reason: string | null;
}

export interface Recommendation {
  source: string;
  primary: { method: string; name: string; implemented: boolean; reason: string };
  alternatives: { method: string; name: string; implemented: boolean; reason: string }[];
  why: string[];
  assumption_checks: AssumptionCheck[];
  failed_assumptions: string[];
  warnings: string[];
  config: { method: string; variables: Record<string, any> };
  level_notes: string[];
  academic_level: string;
  disclaimer: string;
}

export interface AIReply {
  content: string;
  source: "llm" | "rule_engine";
  provider: string | null;
  model: string | null;
  notice: string | null;
  grounding: { checked: number; unverified: string[]; grounded: boolean } | null;
}

export interface Visualization {
  id: number;
  project_id: number;
  dataset_id: number | null;
  version_number: number | null;
  analysis_run_id: number | null;
  chart_type: string;
  title: string;
  config: Record<string, any>;
  meta: { notes?: string[]; n?: number };
  include_in_report: boolean;
  image_url: string;
  created_at: string;
  updated_at: string;
}

export interface Finding {
  id: number;
  project_id: number;
  research_question_id: number | null;
  hypothesis_id: number | null;
  analysis_result_id: number | null;
  analysis_run_id: number | null;
  significant: boolean | null;
  title: string;
  statement: string;
  statistical_evidence: string | null;
  interpretation: string | null;
  confidence_level: "low" | "moderate" | "high";
  limitations_note: string | null;
  source: "engine" | "ai" | "manual";
  is_edited: boolean;
  breakdown?: { title: string; what_was_tested: string; what_we_found: string; what_it_means: string; how_sure: string } | null;
  charts?: ChartIdea[];
}

/** A chart that helps a reader see a finding or a conclusion; drawn in the Visualization studio. */
export interface ChartIdea {
  chart_type: string;
  title: string;
  reason: string;
  x?: string;
  y?: string;
  columns?: string[];
  finding_id?: number;
  run_id?: number;
}

export interface TextItem {
  id: number;
  text: string;
  source: "engine" | "ai" | "manual";
  finding_ids: number[];
  audience?: string | null;
  chart?: ChartIdea | null;
}

export interface Limitation {
  id: number;
  category: string;
  description: string;
  source: "auto" | "ai" | "manual";
  status: "active" | "acknowledged" | "not_applicable";
  status_note: string | null;
}

export interface ReportVersion {
  id: number;
  report_id: number;
  version_number: number;
  format: "pdf" | "docx" | "xlsx" | "csv";
  size_bytes: number;
  created_at: string;
  download_url: string;
}

export interface Report {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  versions: ReportVersion[];
}

export interface HistoryEntry {
  id: number;
  user_name: string | null;
  action: string;
  entity_type: string | null;
  entity_id: number | null;
  details: Record<string, any>;
  created_at: string;
}

/** The AI-assisted choice of variables and test for one research question or hypothesis. */
export interface AIPlan {
  research_question_id: number | null;
  hypothesis_id: number | null;
  status: "ready" | "skipped";
  reason: string | null;
  method: string | null;
  method_name: string | null;
  variables: Record<string, any> | null;
  justification: string | null;
  source: "llm" | "rule_engine" | null;
  notice: string | null;
  outcome: string | null;
  predictors: string[] | null;
  recommendation: Recommendation | null;
  run_id: number | null;
  dataset_id?: number;
  dataset_version_id?: number;
}

export interface AutoAnalysisResult {
  summary: { ready: number; skipped: number; ai_chosen: number };
  plans: AIPlan[];
}

/** One research question and/or hypothesis on the automatic analysis page (workflow step 8). */
export interface AutomaticItem {
  research_question: { id: number; code: string; text: string } | null;
  hypothesis: { id: number; code: string; alternative_text: string; decision: string; decision_text?: string } | null;
  status: "running" | "completed" | "failed" | "skipped" | "not_run";
  method_name: string | null;
  reason: string | null;
  reason_source: "llm" | "rule_engine" | null;
  notice: string | null;
  variables_source: "linked" | "ai";
  run: AnalysisRun | null;
}

export interface AutomaticOverview {
  dataset_id: number;
  dataset_version_id: number;
  version_number: number;
  running: boolean;
  items: AutomaticItem[];
}

export interface StepCheckItem {
  code: string;
  severity: "blocking" | "warning";
  message: string;
  fix: string;
  why: string;
}

export interface StepCheck {
  step: string;
  level: "student" | "analyst" | "expert";
  passed: boolean;
  blocking: StepCheckItem[];
  warnings: StepCheckItem[];
}

/** Details only the researcher can supply for the report (kept with the project, not in the database). */
export interface ReportDetails {
  background: string | null;
  references: string[];
  ethics_committee: string | null;
  ethics_reference: string | null;
  consent_method: string | null;
}

export interface ProjectCosts {
  currency: string;
  items: { description: string; category: string; amount: number }[];
  total: number;
}
