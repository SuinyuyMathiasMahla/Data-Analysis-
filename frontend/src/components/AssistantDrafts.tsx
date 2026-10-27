import { useState } from "react";

import { api } from "../services/api";
import { errorMessage } from "../utils/format";
import { Alert, Button, ErrorNote } from "./ui";

type ChartDraft = { draft: { title: string; x_label: string; y_label: string } | null; questions: string[]; note?: string };
type GapDraft = { questions: string[]; note?: string };

/** A chart title and axis labels from the chart's variables. Filled into the form only when the user chooses to use them. */
export function ChartTitleDraft({ projectId, chartType, x, y, hue, onUse }: {
  projectId: number; chartType: string; x?: string; y?: string; hue?: string;
  onUse: (draft: { title: string; xLabel: string; yLabel: string }) => void;
}) {
  const [result, setResult] = useState<ChartDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const draft = () =>
    api
      .post<ChartDraft>(`/projects/${projectId}/assistant/draft`, { kind: "chart_title", chart_type: chartType, x: x ?? null, y: y ?? null, hue: hue ?? null })
      .then(setResult)
      .catch((err) => setError(errorMessage(err)));
  return (
    <div className="stack">
      <div className="row">
        <Button small onClick={draft}>Draft a title from the variables</Button>
      </div>
      <ErrorNote message={error} />
      {result?.draft && (
        <Alert kind="info">
          <div><strong>Title:</strong> {result.draft.title}</div>
          <div><strong>X axis:</strong> {result.draft.x_label} · <strong>Y axis:</strong> {result.draft.y_label}</div>
          <Button small variant="primary" onClick={() => onUse({ title: result.draft!.title, xLabel: result.draft!.x_label, yLabel: result.draft!.y_label })}>
            Use this title and labels
          </Button>
        </Alert>
      )}
      {result && result.questions.length > 0 && (
        <Alert kind="warn">
          <div>The assistant needs this first:</div>
          <ul>{result.questions.map((text) => <li key={text}>{text}</li>)}</ul>
        </Alert>
      )}
    </div>
  );
}

/** The questions the assistant still needs the researcher to answer about the project overview. */
export function ProjectGaps({ projectId }: { projectId: number }) {
  const [result, setResult] = useState<GapDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const check = () =>
    api.post<GapDraft>(`/projects/${projectId}/assistant/draft`, { kind: "project_gaps" }).then(setResult).catch((err) => setError(errorMessage(err)));
  return (
    <section className="panel stack" aria-label="What the assistant still needs">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>What the assistant still needs</h2>
        <Button small onClick={check}>Ask the assistant</Button>
      </div>
      <ErrorNote message={error} />
      {result && (
        <>
          <p className="small muted">{result.note}</p>
          <ul className="stack">{result.questions.map((text) => <li key={text}>{text}</li>)}</ul>
        </>
      )}
    </section>
  );
}
