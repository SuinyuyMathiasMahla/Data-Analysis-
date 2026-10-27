import { useEffect, useState } from "react";

import { useAction, useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { Dataset } from "../types";
import { Alert, Button, confirmAction, ErrorNote } from "./ui";

type Decision = {
  decision_id: number;
  kind: string;
  column: string | null;
  action: string;
  reason: string;
  source: "ai_assistant" | "rules";
  missing_pct: number;
  affects_results: boolean;
  undone: boolean;
};

type CleanResult = {
  score_before: number;
  score_after: number;
  rows_before: number;
  rows_after: number;
  applied: { code: string; column: string | null; operation: string; reason: string }[];
  decisions: Decision[];
  alerts: Decision[];
};

const ACTION_LABEL: Record<string, string> = {
  impute_median: "Filled with the median",
  impute_mode: "Filled with the most frequent value",
  delete_records: "Records removed",
  drop_column: "Variable removed",
};

function DecisionLine({ decision }: { decision: Decision }) {
  return (
    <li>
      <strong>{decision.column}</strong>: {ACTION_LABEL[decision.action] ?? decision.action}.{" "}
      <span>{decision.reason}</span>{" "}
      <span className="small muted">({decision.source === "ai_assistant" ? "decided by the AI assistant" : "decided by the cleaning rules"})</span>
    </li>
  );
}

/** One click cleans the data. The AI assistant decides per column when it is configured; otherwise fixed rules do. */
export function AutoClean({ dataset, onDone }: { dataset: Dataset; onDone: () => void }) {
  const [result, setResult] = useState<CleanResult | null>(null);
  const log = useApi<{ decisions: Decision[] }>(`/datasets/${dataset.id}/auto-decisions`);
  const { busy, error, run } = useAction();
  const [undoError, setUndoError] = useState<string | null>(null);

  useEffect(() => {
    log.reload();
    // reload the decision list when the dataset version changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset.current_version_id]);

  const clean = () => {
    if (!confirmAction("Clean the data automatically? Each change is saved as a new version, and every decision is recorded so it can be undone.")) return;
    run(() => api.post<CleanResult>(`/datasets/${dataset.id}/auto-clean`)).then((value) => {
      if (value) {
        setResult(value);
        log.reload();
        onDone();
      }
    });
  };

  const undo = (decision: Decision) => {
    setUndoError(null);
    api
      .post(`/datasets/${dataset.id}/auto-decisions/${decision.decision_id}/undo`)
      .then(() => {
        log.reload();
        onDone();
      })
      .catch((err: Error) => setUndoError(err.message));
  };

  // the saved log is the full history; a run that has just finished is shown from its own result until the log catches up
  const decisions = log.data?.decisions?.length ? log.data.decisions : result?.decisions ?? [];
  const flagged = decisions.filter((d) => d.affects_results && !d.undone);

  return (
    <section className="panel stack" aria-label="Clean data automatically">
      <h2 style={{ margin: 0 }}>Clean data automatically</h2>
      <p className="small muted">
        Fixes duplicates, impossible values, codes such as 999, inconsistent spelling and invalid numbers, then decides what to do with
        every missing value. The aim is a data quality score of 100.
      </p>
      <div><Button variant="primary" busy={busy} onClick={clean}>Clean data</Button></div>
      <ErrorNote message={error ?? undoError} />
      {result && (
        <Alert kind={result.score_after >= 100 ? "ok" : "info"}>
          Data quality {result.score_before.toFixed(1)} → {result.score_after.toFixed(1)}. Records {result.rows_before} → {result.rows_after}.
        </Alert>
      )}
      {flagged.length > 0 && (
        <Alert kind="warn">
          <div>These decisions change the results. Undo any you disagree with. The earlier version is restored; later versions stay in the history.</div>
          <ul className="stack">
            {flagged.map((decision) => (
              <li key={decision.decision_id} className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                <span className="grow"><DecisionLine decision={decision} /></span>
                <Button small variant="quiet" onClick={() => undo(decision)}>Undo</Button>
              </li>
            ))}
          </ul>
        </Alert>
      )}
      {decisions.length > 0 && (
        <details>
          <summary>All decisions ({decisions.length})</summary>
          <ul className="stack">
            {decisions.map((decision) => (
              <li key={decision.decision_id} style={{ opacity: decision.undone ? 0.5 : 1 }}>
                <DecisionLine decision={decision} />{decision.undone ? " (undone)" : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
