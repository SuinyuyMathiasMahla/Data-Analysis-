import { useState } from "react";
import type { FormEvent } from "react";

import { api, ApiError } from "../services/api";
import { Alert, Button, Field } from "./ui";

type Issue = { code: string; where: string; message: string; action: string; diagnosis?: string; fixed_by?: "assistant" | "you" };
type Action = { code: string; action: string };

const AUDIENCES: [string, string][] = [
  ["academic", "Academic (examiners and supervisors)"],
  ["technical", "Technical (analysts)"],
  ["executive", "Executive (decision-makers)"],
];
const LENGTHS: [string, string][] = [["full", "Full package"], ["one_page", "One-page summary only"]];
const DELIVERABLES: [string, string][] = [
  ["summary", "One-page summary (PDF)"],
  ["report", "Full report (PDF and Word)"],
  ["charts", "Charts (PNG)"],
  ["data", "Cleaned dataset and data dictionary (CSV)"],
  ["workbook", "Excel workbook of the result tables"],
  ["log", "Analysis log (JSON) and README"],
  ["dashboard", "Interactive dashboard (HTML) and BI export (CSV)"],
  ["deck", "Handover presentation (PowerPoint, 8 to 12 slides)"],
];

/** Builds the client package zip. The server runs the readiness gate first and lists anything that must be fixed. */
export function ClientPackageForm({ projectId, datasetId, projectTitle }: { projectId: number; datasetId: number | null; projectTitle: string }) {
  const [audience, setAudience] = useState("academic");
  const [length, setLength] = useState("full");
  const [deliverables, setDeliverables] = useState<string[]>(DELIVERABLES.map(([value]) => value));
  const [references, setReferences] = useState("");
  const [busy, setBusy] = useState(false);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [actions, setActions] = useState<Action[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const toggle = (value: string) =>
    setDeliverables((list) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setIssues([]);
    setActions([]);
    setError(null);
    setDone(null);
    try {
      const blob = await api.postBlob(`/projects/${projectId}/client-package`, {
        dataset_id: datasetId,
        audience,
        length,
        deliverables: length === "one_page" ? ["summary"] : deliverables,
        references: references.split("\n").map((line) => line.trim()).filter(Boolean),
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${projectTitle.replace(/[^a-z0-9]+/gi, "_").slice(0, 60) || "client_package"}.zip`;
      link.click();
      URL.revokeObjectURL(url);
      setDone("The client package has been downloaded.");
    } catch (err) {
      if (err instanceof ApiError && err.code === "readiness_failed" && err.details && typeof err.details === "object") {
        const details = err.details as { issues?: Issue[]; assistant_actions?: Action[] };
        setIssues(details.issues ?? []);
        setActions(details.assistant_actions ?? []);
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : "The client package could not be built.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="panel stack" onSubmit={submit} aria-label="Client package">
      <h2 style={{ margin: 0 }}>Client package</h2>
      <p className="small muted">
        One zip for a client: a one-page summary, the full report, charts, data, a workbook, and the analysis log.
        It is refused until every blocking issue below is fixed.
      </p>
      <div className="grid cols-2">
        <Field label="Audience" hint="Sets the reading notes in the summary and the README.">
          <select value={audience} onChange={(e) => setAudience(e.target.value)}>
            {AUDIENCES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
        <Field label="Length">
          <select value={length} onChange={(e) => setLength(e.target.value)}>
            {LENGTHS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
      </div>
      <fieldset style={{ border: 0, padding: 0, margin: 0 }} disabled={length === "one_page"}>
        <legend style={{ fontWeight: 500 }}>Deliverables</legend>
        <div className="grid cols-2" style={{ marginTop: "0.4rem" }}>
          {DELIVERABLES.map(([value, label]) => (
            <label className="check" key={value}>
              <input type="checkbox" checked={deliverables.includes(value)} onChange={() => toggle(value)} />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <Field label="References" hint="One per line, in full (author, year, title, source). Required when methods are named in the report.">
        <textarea rows={4} value={references} onChange={(e) => setReferences(e.target.value)} aria-label="References" />
      </Field>
      {error && <Alert kind="error">{error}</Alert>}
      {actions.length > 0 && (
        <Alert kind="info">
          <div>The assistant has already done this:</div>
          <ul>{actions.map((item, index) => <li key={index}>{item.action}</li>)}</ul>
        </Alert>
      )}
      {issues.length > 0 && (
        <ul className="stack" aria-label="Items to fix">
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`}>
              <strong>{issue.message}</strong> <span className="small muted">({issue.where})</span>{" "}
              <span className="small">{issue.fixed_by === "assistant" ? "Assistant is working on this" : "Needs your decision"}</span>
              <div>{issue.diagnosis ?? issue.action}</div>
            </li>
          ))}
        </ul>
      )}
      {done && <Alert kind="ok">{done}</Alert>}
      <div>
        <Button type="submit" variant="primary" busy={busy} disabled={deliverables.length === 0 && length === "full"}>Build client package</Button>
      </div>
    </form>
  );
}
