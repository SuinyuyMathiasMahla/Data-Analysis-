import { useState } from "react";
import type { FormEvent } from "react";

import { ClientPackageForm } from "../components/ClientPackage";
import { SendReportToClient } from "../components/ClientWhatsApp";
import { ReportDetailsForm } from "../components/ReportDetails";
import { StepCheckPanel } from "../components/StepCheck";
import { Alert, Badge, Button, confirmAction, Empty, ErrorNote, Field, Loading, PageHead } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { DatasetPicker, useProject } from "../layouts/ProjectLayout";
import { api, download } from "../services/api";
import type { HistoryEntry, Report } from "../types";
import { actionLabel, fmtBytes, fmtDate } from "../utils/format";

const FORMATS: [string, string][] = [["pdf", "PDF, ready to submit or print"], ["docx", "Word document, to edit and merge into your thesis"],
  ["xlsx", "Excel workbook with all result tables"], ["csv", "CSV with one row per statistical test"]];

export function ReportGenerator() {
  const { project, dataset, canWrite, reload } = useProject();
  const sections = useApi<{ sections: { key: string; title: string }[] }>("/report-sections");
  const reports = useApi<{ reports: Report[] }>(`/projects/${project.id}/reports`);
  const [format, setFormat] = useState("pdf");
  // suggested from the project it belongs to; the researcher can change it
  const suggestedTitle = `${project.title.trim()}: research report`.slice(0, 300);
  const [title, setTitle] = useState(suggestedTitle);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [includeData, setIncludeData] = useState(false);
  const [target, setTarget] = useState("");
  const { busy, error, run } = useAction();
  const missing = project.progress.steps.filter((s) => !s.done && s.key !== "report");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const all = (sections.data?.sections ?? []).map((s) => s.key);
    run(async () => {
      const report = await api.post<Report & { latest_version: { download_url: string; version_number: number; format: string } }>(`/projects/${project.id}/reports`, {
        format, title: title || null, report_id: target ? Number(target) : null, dataset_id: dataset?.id ?? null, include_data: includeData,
        sections: excluded.length ? all.filter((k) => !excluded.includes(k)) : null,
      });
      await download(report.latest_version.download_url, `${report.title}_v${report.latest_version.version_number}.${report.latest_version.format}`);
      reports.reload();
      reload();
    });
  };
  return (
    <div className="stack">
      <PageHead title="Generate report" actions={<DatasetPicker />}>
        The report is built from what is stored in this project at the moment you generate it, and that snapshot is kept with each version.
      </PageHead>
      <ErrorNote message={error ?? reports.error} />
      <StepCheckPanel step="report" />
      {missing.length > 0 && (
        <Alert kind="warn">These steps are not finished, so their sections will be thin or empty: {missing.map((s) => s.label.toLowerCase()).join(", ")}.</Alert>
      )}
      {canWrite && (
        <form className="panel stack" onSubmit={submit}>
          <div className="grid cols-2">
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend style={{ fontWeight: 500 }}>Format</legend>
              {FORMATS.map(([value, label]) => (
                <label className="check" key={value}><input type="radio" name="format" checked={format === value} onChange={() => setFormat(value)} /><span>{label}</span></label>
              ))}
              {format === "xlsx" && <label className="check" style={{ marginTop: "0.5rem" }}><input type="checkbox" checked={includeData} onChange={(e) => setIncludeData(e.target.checked)} /><span>Include the cleaned dataset as a sheet</span></label>}
            </fieldset>
            <div className="stack">
              <Field label="Report title" hint="Suggested from the project title. Change it if you like.">
                <div className="row">
                  <input className="grow" type="text" maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} />
                  {title !== suggestedTitle && <Button small variant="quiet" onClick={() => setTitle(suggestedTitle)}>Use suggested</Button>}
                </div>
              </Field>
              <Field label="Save as">
                <select value={target} onChange={(e) => setTarget(e.target.value)}>
                  <option value="">A new report</option>
                  {(reports.data?.reports ?? []).map((r) => <option key={r.id} value={r.id}>A new version of "{r.title}"</option>)}
                </select>
              </Field>
            </div>
          </div>
          {(format === "pdf" || format === "docx") && (
            <details>
              <summary>Choose sections (all are included by default)</summary>
              <div className="grid cols-3" style={{ marginTop: "0.6rem" }}>
                {(sections.data?.sections ?? []).map((s) => (
                  <label className="check" key={s.key}>
                    <input type="checkbox" checked={!excluded.includes(s.key)} onChange={() => setExcluded(excluded.includes(s.key) ? excluded.filter((k) => k !== s.key) : [...excluded, s.key])} />
                    <span>{s.title}</span>
                  </label>
                ))}
              </div>
            </details>
          )}
          <p className="small muted">Charts appear in the report when "Add to report" is switched on for them in the Visualization studio.</p>
          <div><Button type="submit" variant="primary" busy={busy}>Generate and download</Button></div>
        </form>
      )}
      <ReportDetailsForm projectId={project.id} canWrite={canWrite} />
      {canWrite && <ClientPackageForm projectId={project.id} datasetId={dataset?.id ?? null} projectTitle={project.title} />}
      <section className="panel">
        <h2>Report versions</h2>
        {reports.loading && <Loading />}
        {reports.data && reports.data.reports.length === 0 && <p className="muted">No reports have been generated yet.</p>}
        {reports.data?.reports.map((r) => (
          <div key={r.id} style={{ padding: "0.6rem 0", borderBottom: "1px solid var(--line)" }}>
            <div className="row between">
              <strong className="grow">{r.title}</strong>
              {canWrite && <Button small variant="quiet" onClick={() => confirmAction("Delete this report and all its versions?") && run(() => api.del(`/reports/${r.id}`)).then(reports.reload)}>Delete</Button>}
            </div>
            <ul className="small" style={{ listStyle: "none", padding: 0, margin: "0.3rem 0 0" }}>
              {[...r.versions].reverse().map((v) => (
                <li key={v.id} className="row" style={{ padding: "0.2rem 0" }}>
                  <span className="grow">Version {v.version_number} <Badge>{v.format.toUpperCase()}</Badge> {fmtBytes(v.size_bytes)}, {fmtDate(v.created_at)}</span>
                  <Button small onClick={() => run(() => download(v.download_url, `${r.title}_v${v.version_number}.${v.format}`))}>Download</Button>
                </li>
              ))}
            </ul>
            {project.project_type === "client" && project.client_name && project.client_whatsapp && r.versions.length > 0 && (
              <div style={{ margin: "0.4rem 0 0.2rem" }}>
                <SendReportToClient
                  clientName={project.client_name}
                  clientNumber={project.client_whatsapp}
                  projectTitle={project.title}
                  downloadUrl={r.versions[r.versions.length - 1].download_url}
                  filename={`${r.title}_v${r.versions[r.versions.length - 1].version_number}.${r.versions[r.versions.length - 1].format}`}
                />
              </div>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}

interface Reviews {
  comments: { id: number; author_name: string | null; stage: string; body: string; created_at: string }[];
  stages: { key: string; label: string; status: "pending" | "approved" | "rejected"; note: string | null; reviewer_name: string | null; reviewed_at: string | null }[];
}
const FILTERS: [string, string][] = [["", "Everything"], ["dataset", "Data and cleaning"], ["analysis", "Analyses"], ["visualization", "Charts"], ["ai", "AI interactions"],
  ["finding", "Findings"], ["report", "Reports"], ["review", "Supervision"]];

function describe(entry: HistoryEntry): string {
  const d = entry.details;
  const parts: string[] = [];
  if (d.label) parts.push(String(d.label));
  if (d.name) parts.push(String(d.name));
  if (d.reason) parts.push(`Reason: ${d.reason}`);
  if (d.from_version !== undefined && d.to_version !== undefined) parts.push(`version ${d.from_version} to ${d.to_version}`);
  if (d.rows_before !== undefined) parts.push(`rows ${d.rows_before} to ${d.rows_after}`);
  if (d.score !== undefined) parts.push(`quality score ${d.score}%`);
  if (d.method) parts.push(`method: ${d.method}`);
  if (d.dataset_version !== undefined) parts.push(`dataset version ${d.dataset_version}`);
  if (d.format) parts.push(`${String(d.format).toUpperCase()} version ${d.version}`);
  if (d.source) parts.push(d.source === "llm" ? "answered by the language model" : "answered by the rule engine");
  if (d.grounded === false) parts.push("contained unverified numbers");
  if (d.error) parts.push(`error: ${d.error}`);
  if (d.stage) parts.push(`stage: ${d.stage}`);
  if (d.note) parts.push(String(d.note));
  return parts.join("; ");
}

export function ProjectHistory() {
  const { project, canWrite, canReview } = useProject();
  const [filter, setFilter] = useState("");
  const history = useApi<{ history: HistoryEntry[] }>(`/projects/${project.id}/history?limit=300${filter ? `&action=${filter}` : ""}`);
  const reviews = useApi<Reviews>(`/projects/${project.id}/reviews`);
  const [stage, setStage] = useState("analysis");
  const [body, setBody] = useState("");
  const { busy, error, run } = useAction();
  const comment = (event: FormEvent) => {
    event.preventDefault();
    run(() => api.post(`/projects/${project.id}/comments`, { stage, body })).then((ok) => { if (ok) { setBody(""); reviews.reload(); } });
  };
  const decide = (key: string, status: "approved" | "rejected") => {
    const note = status === "rejected" ? window.prompt("What needs to change?") : window.prompt("Comment (optional)") ?? "";
    if (status === "rejected" && !note) return;
    run(() => api.put(`/projects/${project.id}/stage-review`, { stage: key, status, note: note || null })).then(reviews.reload);
  };
  return (
    <div className="stack">
      <PageHead title="Project history">A record of everything done in this project. It cannot be edited.</PageHead>
      <ErrorNote message={history.error ?? error} />
      <section className="panel stack">
        <h2>Supervisor review</h2>
        {reviews.data && (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Stage</th><th>Review</th><th>Reviewer and note</th>{canReview && <th>Decision</th>}</tr></thead>
              <tbody>
                {reviews.data.stages.map((s) => (
                  <tr key={s.key}>
                    <td>{s.label}</td>
                    <td><Badge tone={s.status === "approved" ? "ok" : s.status === "rejected" ? "danger" : ""}>{s.status === "pending" ? "not reviewed" : s.status}</Badge></td>
                    <td className="small">{s.reviewer_name ? `${s.reviewer_name}, ${fmtDate(s.reviewed_at)}` : ""}{s.note ? `: ${s.note}` : ""}</td>
                    {canReview && <td><Button small onClick={() => decide(s.key, "approved")}>Approve</Button> <Button small variant="quiet" onClick={() => decide(s.key, "rejected")}>Reject</Button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {(reviews.data?.comments ?? []).map((c) => (
          <div key={c.id} className="bubble assistant"><strong>{c.author_name}</strong> <span className="small muted">on {c.stage}, {fmtDate(c.created_at)}</span><div>{c.body}</div></div>
        ))}
        {(canWrite || canReview) && (
          <form className="row" onSubmit={comment} style={{ alignItems: "flex-end" }}>
            <Field label="Stage">
              <select value={stage} onChange={(e) => setStage(e.target.value)}>{(reviews.data?.stages ?? []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select>
            </Field>
            <label className="grow field"><span className="label">Comment</span><input type="text" required value={body} onChange={(e) => setBody(e.target.value)} /></label>
            <Button type="submit" busy={busy}>Add comment</Button>
          </form>
        )}
      </section>
      <section className="panel stack">
        <div className="row between">
          <h2 className="grow">Activity</h2>
          <label className="row small">Show
            <select style={{ width: "auto" }} value={filter} onChange={(e) => setFilter(e.target.value)}>{FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
          </label>
        </div>
        {history.loading && <Loading />}
        {history.data && history.data.history.length === 0 && <Empty title="Nothing recorded for this filter" />}
        <ol className="timeline">
          {history.data?.history.map((entry) => (
            <li key={entry.id}>
              <strong>{actionLabel(entry.action)}</strong> <span className="small muted">{fmtDate(entry.created_at)}{entry.user_name ? `, ${entry.user_name}` : ""}</span>
              {describe(entry) && <div className="small">{describe(entry)}</div>}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
