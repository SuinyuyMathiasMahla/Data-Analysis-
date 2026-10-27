import { useEffect, useMemo, useState } from "react";
import { AutoClean } from "../components/AutoClean";
import type { FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { StepCheckPanel } from "../components/StepCheck";
import { Alert, Badge, Button, confirmAction, DataTable, Empty, ErrorNote, Field, Loading, PageHead } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { DatasetPicker, useProject } from "../layouts/ProjectLayout";
import { api, download } from "../services/api";
import type { CleaningOperation, Dataset, DatasetVersion, QualityIssue, QualityReport, Variable } from "../types";
import { fmtBytes, fmtDate, fmtNumber } from "../utils/format";

function NoDataset() {
  const { canWrite } = useProject();
  return (
    <Empty title="No dataset yet" action={canWrite ? <Link className="btn primary" to="../upload">Upload a dataset</Link> : undefined}>
      Upload your research data first. The original file is stored unchanged and all work happens on a copy.
    </Empty>
  );
}

// ---------------------------------------------------------------- upload ----
export function DatasetUpload() {
  const { project, reload, canWrite, selectDataset } = useProject();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [manual, setManual] = useState("");
  const [manualName, setManualName] = useState("");
  const { busy, error, run, setError } = useAction();

  const finish = (dataset: Dataset | undefined) => {
    if (!dataset) return;
    reload();
    selectDataset(dataset.id);
    navigate("../quality");
  };
  const upload = (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    if (description) form.append("description", description);
    run(() => api.upload<Dataset>(`/projects/${project.id}/datasets`, form)).then(finish);
  };
  const enter = (event: FormEvent) => {
    event.preventDefault();
    const lines = manual.split(/\r?\n/).filter((line) => line.trim() !== "");
    if (lines.length < 2) {
      setError("Enter a header row and at least one data row.");
      return;
    }
    const split = (line: string) => line.split(lines[0].includes("\t") ? "\t" : ",").map((cell) => cell.trim());
    const columns = split(lines[0]);
    const rows = lines.slice(1).map(split);
    run(() => api.post<Dataset>(`/projects/${project.id}/datasets/manual`, { name: manualName, columns, rows })).then(finish);
  };

  return (
    <div className="stack">
      <PageHead title="Upload dataset">
        Use one row per participant or observation and one column per variable, with the variable names in the first row.
      </PageHead>
      <StepCheckPanel step="dataset" />
      <ErrorNote message={error} />
      {project.datasets.length > 0 && (
        <section className="panel">
          <h2>Datasets in this project</h2>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {project.datasets.map((d) => (
              <li key={d.id} className="row between" style={{ padding: "0.4rem 0" }}>
                <span className="grow"><strong>{d.name}</strong> <span className="muted small">{d.row_count} rows, {d.column_count} variables, working version {d.current_version_number}, uploaded {fmtDate(d.created_at, false)}</span></span>
                <Button small onClick={() => { selectDataset(d.id); navigate("../preview"); }}>Open</Button>
                {canWrite && <Button small variant="quiet" onClick={() => confirmAction(`Delete dataset "${d.name}" and every analysis that used it?`) && run(() => api.del(`/datasets/${d.id}`)).then(reload)}>Delete</Button>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {canWrite && (
        <div className="grid cols-2">
          <form className="panel stack" onSubmit={upload}>
            <h2>Upload a file</h2>
            <Field label="Data file" hint="CSV, Excel (.xlsx, .xls) or JSON, up to 25 MB.">
              <input type="file" required accept=".csv,.xlsx,.xls,.json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </Field>
            <Field label="Dataset name (optional)"><input type="text" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Description (optional)" hint="How and when the data were collected."><textarea value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
            <div><Button type="submit" variant="primary" busy={busy} disabled={!file}>Upload and check quality</Button></div>
            <p className="small muted">The uploaded file is never modified. Types are detected, a working copy is created and a quality check runs straight away.</p>
          </form>
          <form className="panel stack" onSubmit={enter}>
            <h2>Or type the data in</h2>
            <Field label="Dataset name"><input type="text" required value={manualName} onChange={(e) => setManualName(e.target.value)} /></Field>
            <Field label="Data" hint="First line = variable names. Separate values with commas, or paste cells straight from a spreadsheet.">
              <textarea required style={{ minHeight: "11rem", fontFamily: "ui-monospace, monospace", fontSize: "0.85rem" }}
                placeholder={"group,score\nA,12\nA,15\nB,19"} value={manual} onChange={(e) => setManual(e.target.value)} />
            </Field>
            <div><Button type="submit" busy={busy}>Save entered data</Button></div>
          </form>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------- preview ----
interface Page { columns: string[]; rows: (string | null)[][]; offset: number; limit: number; total_rows: number; version: DatasetVersion; schema: Record<string, { type: string; measurement_level: string }> }

export function DatasetPreview() {
  const { dataset } = useProject();
  const [offset, setOffset] = useState(0);
  const [versionId, setVersionId] = useState<number | null>(null);
  const detail = useApi<Dataset>(dataset ? `/datasets/${dataset.id}` : null);
  useEffect(() => { setOffset(0); setVersionId(null); }, [dataset?.id]);
  const page = useApi<Page>(dataset ? `/datasets/${dataset.id}/preview?offset=${offset}&limit=50${versionId ? `&version_id=${versionId}` : ""}` : null);
  const { error, run } = useAction();
  if (!dataset) return <NoDataset />;
  const working = (detail.data?.versions ?? []).filter((v) => v.kind === "working");
  const original = (detail.data?.versions ?? []).find((v) => v.kind === "original");
  return (
    <div className="stack">
      <PageHead title="Dataset preview" actions={<DatasetPicker />}>
        {dataset.name}: 50 rows at a time. The full file stays on the server.
      </PageHead>
      <ErrorNote message={page.error ?? error} />
      <div className="row">
        <label className="row small">Version
          <select style={{ width: "auto" }} value={versionId ?? dataset.current_version_id ?? ""} onChange={(e) => { setVersionId(Number(e.target.value)); setOffset(0); }}>
            {working.map((v) => <option key={v.id} value={v.id}>v{v.version_number}{v.id === dataset.current_version_id ? " (current)" : ""}: {v.note?.slice(0, 60)}</option>)}
          </select>
        </label>
        <span className="grow" />
        <Button small onClick={() => run(() => download(`/datasets/${dataset.id}/download${versionId ? `?version_id=${versionId}` : ""}`, `${dataset.name}.csv`))}>Download this version (CSV)</Button>
        <Button small onClick={() => run(() => download(`/datasets/${dataset.id}/download?original=true`, dataset.original_filename ?? `${dataset.name}_original`))}>Download original file</Button>
      </div>
      {original && <p className="small muted">Original upload: {fmtBytes(original.size_bytes)}, SHA-256 {original.checksum_sha256.slice(0, 16)}… (stored unchanged).</p>}
      {page.loading && !page.data && <Loading />}
      {page.data && (
        <>
          <div className="panel flush">
            <div className="table-wrap" style={{ maxHeight: "62vh", overflowY: "auto" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col" className="num">Row</th>
                    {page.data.columns.map((c) => <th key={c} scope="col">{c}<div className="small muted" style={{ fontWeight: 400 }}>{page.data?.schema[c]?.type}</div></th>)}
                  </tr>
                </thead>
                <tbody>
                  {page.data.rows.map((row, i) => (
                    <tr key={i}>
                      <td className="num muted">{page.data!.offset + i + 1}</td>
                      {row.map((value, j) => <td key={j} className={value === null ? "missing" : undefined}>{value === null ? "missing" : value}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="row between">
            <span className="small muted">Rows {page.data.offset + 1} to {Math.min(page.data.offset + page.data.limit, page.data.total_rows)} of {page.data.total_rows}</span>
            <div className="row">
              <Button small disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous 50</Button>
              <Button small disabled={offset + 50 >= page.data.total_rows} onClick={() => setOffset(offset + 50)}>Next 50</Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------- quality ----
function exampleText(example: unknown): string {
  if (Array.isArray(example)) return example.map(String).join(" / ");
  if (example && typeof example === "object") {
    const item = example as Record<string, unknown>;
    if ("row" in item && "value" in item) return `row ${item.row}: ${item.value}`;
    return Object.entries(item).map(([key, value]) => `${key} ${Array.isArray(value) ? value.join(" and ") : value}`).join(", ");
  }
  return String(example);
}

const SEVERITY: Record<string, "danger" | "warn" | "info" | ""> = { high: "danger", medium: "warn", low: "info", info: "" };

export function DataQuality() {
  const { dataset, canWrite, reload } = useProject();
  const navigate = useNavigate();
  const report = useApi<QualityReport>(dataset ? `/datasets/${dataset.id}/quality-report` : null);
  const { busy, error, run } = useAction();
  if (!dataset) return <NoDataset />;
  const recheck = () => run(() => api.post<QualityReport>(`/datasets/${dataset.id}/quality-check`)).then((r) => { if (r) { report.setData(r); reload(); } });
  const fix = (issue: QualityIssue) => navigate("../cleaning", { state: { suggestion: issue.suggestion, why: issue.message } });
  const r = report.data;
  return (
    <div className="stack">
      <PageHead title="Data quality" actions={<><DatasetPicker />{canWrite && <Button busy={busy} onClick={recheck}>Run the check again</Button>}</>}>
        Problems found in {dataset.name}, version {r?.version_number ?? dataset.current_version_number}. Nothing has been changed: you decide what to fix.
      </PageHead>
      <ErrorNote message={error ?? (report.error && !report.error.includes("not found") ? report.error : null)} />
      <StepCheckPanel step="quality" />
      {report.loading && <Loading />}
      {!report.loading && !r && <Empty title="No quality report yet" action={canWrite ? <Button variant="primary" busy={busy} onClick={recheck}>Check data quality</Button> : undefined} />}
      {r && (
        <>
          <section className="panel row" style={{ gap: "2rem", alignItems: "flex-start" }}>
            <div>
              <div className="small muted">Data Quality Score</div>
              <div style={{ fontFamily: "var(--serif)", fontSize: "2.6rem", lineHeight: 1.1 }}>{fmtNumber(r.score, 1)}%</div>
              <div className="small muted">Checked {fmtDate(r.created_at)}</div>
            </div>
            <dl className="grid cols-4 grow" style={{ margin: 0 }}>
              {[["Rows", r.summary.rows], ["Variables", r.summary.columns], ["Missing values", r.summary.missing_cells], ["Duplicate rows", r.summary.duplicate_rows],
                ["Invalid values", r.summary.invalid_cells], ["Inconsistent categories", r.summary.inconsistent_category_cells], ["Possible outliers", r.summary.possible_outliers],
                ["Rows with a missing value", r.summary.rows_with_missing]].map(([label, value]) => (
                <div key={label}><dt className="small muted">{label}</dt><dd className="num" style={{ margin: 0, textAlign: "left", fontSize: "1.15rem" }}>{value}</dd></div>
              ))}
            </dl>
          </section>
          <details className="panel">
            <summary><strong>How the score is calculated</strong></summary>
            <DataTable table={{ title: "", columns: ["Dimension", "Maximum points", "Share of data affected", "Points lost"],
              rows: Object.entries(r.dimensions).map(([k, d]) => [k, d.weight, `${(100 * d.affected_share).toFixed(2)}%`, d.points_lost]) }} />
            <p className="table-note">Outliers and correlated variables are reported but never lower the score: an unusual value is not an error, and deleting observations to look better would be bad science.</p>
          </details>
          {r.issues.length === 0 ? <Alert kind="ok">No problems were found.</Alert> : (
            <section className="panel">
              <h2>{r.issues.length} thing(s) to review</h2>
              <ul className="checks">
                {r.issues.map((issue, i) => (
                  <li key={i}>
                    <div><Badge tone={SEVERITY[issue.severity]}>{issue.severity}</Badge></div>
                    <div>
                      {issue.message}
                      {issue.examples.length > 0 && <div className="small muted">Examples: {issue.examples.slice(0, 5).map(exampleText).join("; ")}</div>}
                      {canWrite && issue.suggestion && <Button small variant="quiet" onClick={() => fix(issue)}>Prepare a fix</Button>}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

// -------------------------------------------------------------- cleaning ----
type FieldSpec = { key: string; label: string; type: "column" | "columns" | "select" | "text" | "number" | "mapping" | "list"; options?: [string, string][]; hint?: string; optional?: boolean };
const NEW_COLUMN: FieldSpec = { key: "new_column", label: "Save as a new variable named (leave empty to overwrite)", type: "text", optional: true };
const OPERATION_FIELDS: Record<string, FieldSpec[]> = {
  remove_duplicates: [{ key: "subset", label: "Compare only these variables (empty = whole row)", type: "columns", optional: true }],
  drop_missing: [{ key: "columns", label: "Variables that must not be missing (empty = all)", type: "columns", optional: true },
    { key: "how", label: "Remove a row when", type: "select", options: [["any", "any of them is missing"], ["all", "all of them are missing"]] }],
  impute: [{ key: "column", label: "Variable", type: "column" },
    { key: "strategy", label: "Fill missing values with", type: "select", options: [["median", "the median"], ["mean", "the mean"], ["mode", "the most common value"], ["constant", "a fixed value"]] },
    { key: "value", label: "Fixed value (only for 'a fixed value')", type: "text", optional: true }],
  replace_values: [{ key: "column", label: "Variable", type: "column" }, { key: "mapping", label: "Replacements", type: "mapping", hint: "One per line as old=new. Leave the right side empty to make the value missing, e.g. 999=" }],
  recode: [{ key: "column", label: "Variable", type: "column" }, { key: "mapping", label: "Recoding", type: "mapping", hint: "One per line, e.g. Strongly agree=5" }, NEW_COLUMN],
  standardize_categories: [{ key: "column", label: "Variable", type: "column" },
    { key: "case", label: "Capitalisation", type: "select", options: [["none", "leave as it is"], ["title", "Title Case"], ["lower", "lower case"], ["upper", "UPPER CASE"]] },
    { key: "mapping", label: "Spelling corrections (optional)", type: "mapping", optional: true, hint: "One per line, e.g. Bussiness=Business" }],
  convert_type: [{ key: "column", label: "Variable", type: "column" },
    { key: "to", label: "New type", type: "select", options: [["numeric", "number"], ["integer", "whole number"], ["categorical", "category"], ["datetime", "date/time"], ["text", "free text"], ["identifier", "identifier"]] }],
  remove_invalid: [{ key: "column", label: "Variable", type: "column" }, { key: "min", label: "Smallest valid value", type: "number", optional: true }, { key: "max", label: "Largest valid value", type: "number", optional: true },
    { key: "invalid_values", label: "Specific invalid values (comma-separated)", type: "list", optional: true },
    { key: "action", label: "What to do", type: "select", options: [["set_missing", "make the value missing (keep the row)"], ["drop_rows", "remove the whole row"]] }],
  winsorize: [{ key: "column", label: "Variable", type: "column" }, { key: "lower_pct", label: "Lower percentile", type: "number" }, { key: "upper_pct", label: "Upper percentile", type: "number" }],
  transform: [{ key: "column", label: "Variable", type: "column" },
    { key: "function", label: "Transformation", type: "select", options: [["log", "natural log"], ["log10", "log base 10"], ["log1p", "log(1 + x)"], ["sqrt", "square root"], ["square", "square"], ["reciprocal", "1 / x"]] }, NEW_COLUMN],
  normalize: [{ key: "column", label: "Variable", type: "column" }, NEW_COLUMN],
  standardize: [{ key: "column", label: "Variable", type: "column" }, NEW_COLUMN],
  derive: [{ key: "new_column", label: "Name of the new variable", type: "text" },
    { key: "operation", label: "Calculate", type: "select", options: [["mean", "mean of the variables (scale score)"], ["sum", "sum of the variables"], ["difference", "first minus second"], ["product", "first times second"], ["ratio", "first divided by second"]] },
    { key: "columns", label: "Variables", type: "columns" }],
  drop_columns: [{ key: "columns", label: "Variables to remove", type: "columns" }],
  rename_column: [{ key: "column", label: "Variable", type: "column" }, { key: "new_name", label: "New name", type: "text" }],
};
const CAUTION: Record<string, string> = {
  winsorize: "Winsorizing replaces real observations. Do it only with a methodological justification, and report it.",
  impute: "Filling in many missing values with one number shrinks the variance and can bias results. It is reasonable only when few values are missing.",
  remove_invalid: "Remove values only when they are impossible or known errors, never because they weaken a result.",
  drop_missing: "Dropping rows reduces your sample. Most analyses already exclude rows with missing values on the variables they use.",
};

function parseMapping(text: string): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  text.split(/\r?\n/).forEach((line) => {
    const index = line.indexOf("=");
    if (index > 0) out[line.slice(0, index).trim()] = line.slice(index + 1).trim() || null;
  });
  return out;
}

function toFormValues(params: Record<string, unknown>): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined) return;
    if (Array.isArray(value)) out[key] = value.map(String);
    else if (typeof value === "object") out[key] = Object.entries(value as Record<string, unknown>).map(([a, b]) => `${a}=${b ?? ""}`).join("\n");
    else out[key] = String(value);
  });
  return out;
}

export function DataCleaning() {
  const { dataset, canWrite, reload } = useProject();
  const location = useLocation();
  const incoming = location.state as { suggestion?: { operation: string; params: Record<string, unknown> }; why?: string } | null;
  const operations = useApi<{ operations: { key: string; label: string }[] }>("/cleaning/operations");
  const history = useApi<{ operations: CleaningOperation[]; versions: DatasetVersion[]; current_version_id: number }>(dataset ? `/datasets/${dataset.id}/cleaning-history` : null);
  const dictionary = useApi<{ variables: Variable[] }>(dataset ? `/datasets/${dataset.id}/dictionary` : null);
  const [operation, setOperation] = useState(incoming?.suggestion?.operation ?? "remove_duplicates");
  const [values, setValues] = useState<Record<string, string | string[]>>(incoming?.suggestion ? toFormValues(incoming.suggestion.params) : {});
  const [reason, setReason] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const fields = OPERATION_FIELDS[operation] ?? [];
  const columns = useMemo(() => (dictionary.data?.variables ?? []).map((v) => v.name), [dictionary.data]);
  if (!dataset) return <NoDataset />;

  const change = (key: string, value: string | string[]) => setValues({ ...values, [key]: value });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const params: Record<string, unknown> = {};
    fields.forEach((f) => {
      const value = values[f.key] ?? (f.type === "select" && f.options ? f.options[0][0] : undefined);
      if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) return;
      if (f.type === "number") params[f.key] = Number(value);
      else if (f.type === "mapping") params[f.key] = parseMapping(String(value));
      else if (f.type === "list") params[f.key] = String(value).split(",").map((s) => s.trim()).filter(Boolean);
      else params[f.key] = value;
    });
    run(() => api.post<{ operation: CleaningOperation; quality_score: number | null }>(`/datasets/${dataset.id}/clean`, { operation, params, reason })).then((result) => {
      if (!result) return;
      setDone(`Saved as version ${result.operation.output_version_number}: rows ${result.operation.rows_before} to ${result.operation.rows_after}, ${result.operation.cells_changed} value(s) changed. Data Quality Score is now ${result.quality_score}%.`);
      setReason("");
      setValues({});
      history.reload();
      dictionary.reload();
      reload();
    });
  };
  const restore = (version: DatasetVersion) => {
    const why = window.prompt(`Make version ${version.version_number} the current version again? Later versions stay in the history. Reason:`, "");
    if (why) run(() => api.post(`/datasets/${dataset.id}/versions/${version.id}/restore?reason=${encodeURIComponent(why)}`)).then(() => { history.reload(); dictionary.reload(); reload(); });
  };

  return (
    <div className="stack">
      <PageHead title="Clean data" actions={<DatasetPicker />}>
        Each change creates a new version of {dataset.name} and is logged with your reason. The original upload is never altered, and you can go back to any version.
      </PageHead>
      {canWrite && dataset && <AutoClean dataset={dataset} onDone={() => { reload(); history.reload(); }} />}
      <ErrorNote message={error ?? history.error} />
      {done && <Alert kind="ok">{done}</Alert>}
      {canWrite && (
        <form className="panel stack" onSubmit={submit}>
          <h2>Apply a cleaning step</h2>
          {incoming?.why && <Alert kind="info">Prepared from the quality report: {incoming.why}</Alert>}
          <Field label="What do you want to do?">
            <select value={operation} onChange={(e) => { setOperation(e.target.value); setValues({}); }}>
              {(operations.data?.operations ?? []).map((op) => <option key={op.key} value={op.key}>{op.label}</option>)}
            </select>
          </Field>
          {CAUTION[operation] && <Alert kind="warn">{CAUTION[operation]}</Alert>}
          <div className="grid cols-2">
            {fields.map((f) => (
              <Field key={f.key} label={f.label} hint={f.hint}>
                {f.type === "column" && (
                  <select required={!f.optional} value={String(values[f.key] ?? "")} onChange={(e) => change(f.key, e.target.value)}>
                    <option value="">Choose a variable</option>
                    {columns.map((c) => <option key={c}>{c}</option>)}
                  </select>
                )}
                {f.type === "columns" && (
                  <select multiple required={!f.optional} value={(values[f.key] as string[]) ?? []} onChange={(e) => change(f.key, Array.from(e.target.selectedOptions).map((o) => o.value))}>
                    {columns.map((c) => <option key={c}>{c}</option>)}
                  </select>
                )}
                {f.type === "select" && (
                  <select value={String(values[f.key] ?? f.options![0][0])} onChange={(e) => change(f.key, e.target.value)}>
                    {f.options!.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                )}
                {(f.type === "text" || f.type === "list") && <input type="text" required={!f.optional} value={String(values[f.key] ?? "")} onChange={(e) => change(f.key, e.target.value)} />}
                {f.type === "number" && <input type="number" step="any" required={!f.optional} value={String(values[f.key] ?? "")} onChange={(e) => change(f.key, e.target.value)} />}
                {f.type === "mapping" && <textarea required={!f.optional} value={String(values[f.key] ?? "")} onChange={(e) => change(f.key, e.target.value)} />}
              </Field>
            ))}
          </div>
          <Field label="Reason for this change" hint="Required. It appears in the audit trail and in your report's data-cleaning section.">
            <textarea required minLength={5} placeholder="e.g. Ages below 0 are data-entry errors" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <div><Button type="submit" variant="primary" busy={busy}>Apply and save as a new version</Button></div>
        </form>
      )}
      <section className="panel">
        <h2>Audit trail</h2>
        {history.loading && <Loading />}
        {history.data && history.data.operations.length === 0 && <p className="muted">No cleaning steps yet. The data are as uploaded.</p>}
        <ol className="timeline">
          {history.data?.operations.map((op) => (
            <li key={op.id}>
              <div className="row between">
                <strong className="grow">v{op.input_version_number} to v{op.output_version_number}: {op.label}</strong>
                {!op.in_current_version && <Badge tone="warn">not part of the current version</Badge>}
                <span className="small muted">{fmtDate(op.created_at)}</span>
              </div>
              <div><strong>Reason:</strong> {op.reason}</div>
              <div className="small muted">Rows {op.rows_before} to {op.rows_after}; {op.cells_changed} value(s) changed. Settings: {JSON.stringify(op.params)}</div>
              {op.details.note && <div className="small" style={{ color: "var(--warn)" }}>{op.details.note}</div>}
              {(op.details.changes ?? []).length > 0 && (
                <details className="small">
                  <summary>Show changed values</summary>
                  <DataTable maxHeight={260} table={{ title: "", columns: ["Row", "Variable", "Before", "After"], rows: (op.details.changes ?? []).map((c) => [c.row, c.column, c.old ?? "missing", c.new ?? "missing"]) }} />
                </details>
              )}
              {(op.details.rows_removed ?? []).length > 0 && <div className="small muted">Rows removed: {(op.details.rows_removed ?? []).slice(0, 30).join(", ")}{(op.details.rows_removed ?? []).length > 30 ? ", …" : ""}</div>}
            </li>
          ))}
        </ol>
        {history.data && history.data.versions.filter((v) => v.kind === "working").length > 1 && (
          <details>
            <summary>All versions</summary>
            <ul className="small" style={{ listStyle: "none", padding: 0 }}>
              {history.data.versions.map((v) => (
                <li key={v.id} className="row between" style={{ padding: "0.3rem 0" }}>
                  <span className="grow">v{v.version_number} ({v.kind}): {v.row_count} rows, {v.column_count} variables. {v.note}</span>
                  {v.id === history.data!.current_version_id ? <Badge tone="ok">current</Badge> : v.kind === "working" && canWrite ? <Button small onClick={() => restore(v)}>Restore this version</Button> : null}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </div>
  );
}

// ------------------------------------------------------------ dictionary ----
export function DataDictionary() {
  const { dataset, canWrite } = useProject();
  const dictionary = useApi<{ variables: Variable[] }>(dataset ? `/datasets/${dataset.id}/dictionary` : null);
  const [editing, setEditing] = useState<Variable | null>(null);
  const [form, setForm] = useState({ label: "", description: "", measurement_level: "nominal", role: "other", unit: "", valid_min: "", valid_max: "" });
  const { busy, error, run } = useAction();
  if (!dataset) return <NoDataset />;
  const open = (v: Variable) => {
    setEditing(v);
    setForm({ label: v.label ?? "", description: v.description ?? "", measurement_level: v.measurement_level, role: v.role, unit: v.unit ?? "",
      valid_min: v.valid_min === null ? "" : String(v.valid_min), valid_max: v.valid_max === null ? "" : String(v.valid_max) });
  };
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (!editing) return;
    run(() => api.put<{ variables: Variable[] }>(`/variables/${editing.id}`, {
      label: form.label || null, description: form.description || null, measurement_level: form.measurement_level, role: form.role, unit: form.unit || null,
      valid_min: form.valid_min === "" ? null : Number(form.valid_min), valid_max: form.valid_max === "" ? null : Number(form.valid_max),
    })).then((result) => {
      if (result) {
        dictionary.setData(result);
        setEditing(null);
      }
    });
  };
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const numeric = editing && ["numeric", "integer"].includes(editing.data_type);
  return (
    <div className="stack">
      <PageHead title="Data dictionary" actions={<DatasetPicker />}>
        Generated from {dataset.name}, version {dataset.current_version_number}. Check the measurement level of each variable: it decides which statistical tests are recommended.
      </PageHead>
      <ErrorNote message={dictionary.error ?? error} />
      {dictionary.loading && <Loading />}
      {editing && (
        <form className="panel stack" onSubmit={save}>
          <h2>Edit "{editing.name}"</h2>
          <div className="grid cols-2">
            <Field label="Label" hint="Used on chart axes and in the report."><input type="text" value={form.label} onChange={set("label")} /></Field>
            <Field label="Unit"><input type="text" placeholder="e.g. hours per week" value={form.unit} onChange={set("unit")} /></Field>
            <Field label="Measurement level" hint="Nominal: categories. Ordinal: ordered categories or ratings. Interval/ratio: true numbers.">
              <select value={form.measurement_level} onChange={set("measurement_level")}>
                <option value="nominal">Nominal</option>
                <option value="ordinal">Ordinal</option>
                {(numeric || editing.data_type === "datetime") && <option value="interval">Interval</option>}
                {numeric && <option value="ratio">Ratio</option>}
              </select>
            </Field>
            <Field label="Role in the study">
              <select value={form.role} onChange={set("role")}>
                {["dependent", "independent", "control", "moderator", "mediator", "identifier", "other"].map((r) => <option key={r}>{r}</option>)}
              </select>
            </Field>
            {numeric && <Field label="Smallest valid value" hint="Values outside the range are flagged by the quality check."><input type="number" step="any" value={form.valid_min} onChange={set("valid_min")} /></Field>}
            {numeric && <Field label="Largest valid value"><input type="number" step="any" value={form.valid_max} onChange={set("valid_max")} /></Field>}
          </div>
          <Field label="Description"><textarea value={form.description} onChange={set("description")} /></Field>
          <div className="row"><Button type="submit" variant="primary" busy={busy}>Save variable</Button><Button onClick={() => setEditing(null)}>Cancel</Button></div>
        </form>
      )}
      {dictionary.data && (
        <div className="panel flush">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>{["Variable", "Label", "Type", "Level", "Role", "Unique", "Missing", "Valid range", "Mean", "Median", "SD", ""].map((h, i) => <th key={i} scope="col">{h}</th>)}</tr>
              </thead>
              <tbody>
                {dictionary.data.variables.map((v) => (
                  <tr key={v.id}>
                    <th scope="row">{v.name}</th>
                    <td>{v.label ?? <span className="muted">no label</span>}{v.unit ? ` (${v.unit})` : ""}</td>
                    <td>{v.data_type}</td><td>{v.measurement_level}</td><td>{v.role}</td>
                    <td className="num">{v.n_unique}</td><td className="num">{v.n_missing}</td>
                    <td className="num">{v.stats?.min !== undefined ? `${fmtNumber(v.stats.min, 2)} to ${fmtNumber(v.stats.max, 2)}` : "–"}</td>
                    <td className="num">{fmtNumber(v.stats?.mean, 2)}</td><td className="num">{fmtNumber(v.stats?.median, 2)}</td><td className="num">{fmtNumber(v.stats?.std, 2)}</td>
                    <td>{canWrite && <Button small variant="quiet" onClick={() => open(v)}>Edit</Button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
