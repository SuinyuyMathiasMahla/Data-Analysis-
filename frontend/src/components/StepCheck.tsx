import { useEffect, useRef, useState } from "react";

import { useApi } from "../hooks/useApi";
import { useProject } from "../layouts/ProjectLayout";
import { api } from "../services/api";
import type { StepCheck as StepCheckResult, StepCheckItem } from "../types";
import { errorMessage } from "../utils/format";
import { Alert, Button, ErrorNote, Loading } from "./ui";

const LEVELS: [string, string][] = [["", "My level (from the project)"], ["student", "Student"], ["analyst", "Analyst"], ["expert", "Expert"]];

/** The assistant's check for one wizard step: what blocks moving on, and what to review. Nothing here changes data. */
export function StepCheckPanel({ step }: { step: string }) {
  const { project, dataset, canWrite } = useProject();
  const [level, setLevel] = useState("");
  const params = new URLSearchParams();
  if (dataset) params.set("dataset_id", String(dataset.id));
  if (level) params.set("level", level);
  const query = params.toString() ? `?${params.toString()}` : "";
  const check = useApi<StepCheckResult>(`/projects/${project.id}/steps/${step}/check${query}`);
  // warnings the user has dealt with on this page visit: accepted, rejected or edited
  const [handled, setHandled] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  // each suggestion is logged once per page visit, the first time it is shown
  const logged = useRef(new Set<string>());

  const key = (item: StepCheckItem) => `${step}:${item.code}:${item.message}`;
  const log = (kind: "suggestion" | "decision", item: StepCheckItem, decision?: "accepted" | "rejected" | "edited", noteText?: string) =>
    api
      .post(`/projects/${project.id}/assistant/decisions`, {
        step, kind, text: item.message, ...(decision ? { decision } : {}), ...(noteText ? { note: noteText } : {}),
      })
      .catch((err) => setError(errorMessage(err)));

  const decide = (item: StepCheckItem, decision: "accepted" | "rejected" | "edited", noteText?: string) => {
    log("decision", item, decision, noteText);
    setHandled((list) => ({ ...list, [key(item)]: decision }));
    setEditing(null);
    setNote("");
  };

  const result = check.data;
  // log the suggestions on screen (once per page visit); this is an effect, not a render-time side effect
  useEffect(() => {
    [...(result?.blocking ?? []), ...(result?.warnings ?? [])].forEach((item) => {
      if (!logged.current.has(key(item))) {
        logged.current.add(key(item));
        log("suggestion", item);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  if (check.loading && !check.data) return <Loading label="Checking this step" />;
  if (check.error) return <ErrorNote message={check.error} />;
  if (!result) return null;

  const warnings = result.warnings.filter((w) => !handled[key(w)]);

  return (
    <section className="panel stack" aria-label="Assistant check">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
        <h2 style={{ margin: 0 }}>Assistant check</h2>
        <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
          <select aria-label="Explanation level" value={level} onChange={(e) => setLevel(e.target.value)}>
            {LEVELS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <Button small onClick={() => check.reload()}>Check again</Button>
        </div>
      </div>
      <ErrorNote message={error} />
      {result.passed && warnings.length === 0 && <Alert kind="ok">Nothing blocks you from moving on from this step.</Alert>}
      {result.blocking.length > 0 && (
        <Alert kind="error">
          Moving on is blocked until these are fixed. The assistant suggests; you decide, and nothing changes until you approve it.
          <ul className="stack" style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
            {result.blocking.map((item) => (
              <li key={key(item)}>
                <strong>{item.message}</strong> <span>{item.fix}</span>
                <div className="small muted">{item.why}</div>
              </li>
            ))}
          </ul>
        </Alert>
      )}
      {warnings.length > 0 && (
        <Alert kind="warn">
          <span>Review these. They do not block you, but they can change the results.</span>
          <ul className="stack" style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
            {warnings.map((item) => (
              <li key={key(item)}>
                <span>{item.message} {item.fix}</span>
                <div className="small muted">{item.why}</div>
                {canWrite && editing !== key(item) && (
                  <div className="row" style={{ gap: "0.4rem", marginTop: "0.3rem" }}>
                    <Button small variant="quiet" onClick={() => decide(item, "accepted")}>Accept</Button>
                    <Button small variant="quiet" onClick={() => { setEditing(key(item)); setNote(""); }}>Edit</Button>
                    <Button small variant="quiet" onClick={() => decide(item, "rejected")}>Reject</Button>
                  </div>
                )}
                {canWrite && editing === key(item) && (
                  <div className="stack" style={{ marginTop: "0.3rem" }}>
                    <textarea aria-label="Your note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
                    <div className="row" style={{ gap: "0.4rem" }}>
                      <Button small variant="primary" disabled={!note.trim()} onClick={() => decide(item, "edited", note.trim())}>Save my note</Button>
                      <Button small variant="quiet" onClick={() => setEditing(null)}>Cancel</Button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Alert>
      )}
    </section>
  );
}
