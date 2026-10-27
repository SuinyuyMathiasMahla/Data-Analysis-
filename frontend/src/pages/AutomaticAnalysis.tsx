import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ResultView } from "../components/ResultView";
import { Alert, Button, Empty, ErrorNote, Loading, PageHead, Source } from "../components/ui";
import { DatasetPicker, useProject } from "../layouts/ProjectLayout";
import { useAction } from "../hooks/useApi";
import { api } from "../services/api";
import type { AutomaticItem, AutomaticOverview, EngineResult } from "../types";
import { StatisticalAnalysis } from "./AnalysisPages";

const STATUS_TEXT: Record<AutomaticItem["status"], string> = {
  running: "Running",
  completed: "Analysed",
  failed: "Failed",
  skipped: "Cannot be analysed yet",
  not_run: "Waiting to be analysed",
};

function ItemCard({ item, versionNumber }: { item: AutomaticItem; versionNumber: number }) {
  const label = [item.research_question?.code, item.hypothesis?.code].filter(Boolean).join(" · ") || "Not linked to a question";
  return (
    <section className="panel stack">
      <div className="row between">
        <div className="grow">
          <h2>{label}</h2>
          {item.research_question && <p>{item.research_question.text}</p>}
          {item.hypothesis && <p className="small muted">Hypothesis: {item.hypothesis.alternative_text}</p>}
        </div>
        <span className="small muted">{STATUS_TEXT[item.status]}</span>
      </div>

      {item.method_name && item.status !== "skipped" && (
        <p>
          <strong>Test:</strong> {item.method_name}{" "}
          {item.reason_source && (
            <Source kind={item.reason_source} label={item.reason_source === "llm" ? "Chosen by the AI assistant" : "Chosen by the rule engine (AI not used)"} />
          )}
        </p>
      )}
      {item.reason && item.status !== "skipped" && (
        <div>
          <h3>Why this test</h3>
          <p>{item.reason}</p>
        </div>
      )}
      {item.variables_source === "ai" && (
        <Alert kind="info">The variables were identified from this question's wording by the AI assistant and saved to the research question. Change them on the Research questions page if they are wrong.</Alert>
      )}
      {item.notice && <Alert kind="warn">{item.notice}</Alert>}
      {item.status === "skipped" && <Alert kind="warn">{item.reason}</Alert>}
      {item.status === "not_run" && <Alert kind="info">{item.reason}</Alert>}
      {item.status === "failed" && <Alert kind="error"><strong>No result was produced.</strong> {item.run?.error_message}</Alert>}
      {item.hypothesis?.decision_text && <p className="small"><strong>Decision on {item.hypothesis.code}:</strong> {item.hypothesis.decision_text}</p>}

      {item.run?.results?.map((row) => row.result && <ResultView key={row.id} result={row.result as EngineResult} datasetVersion={versionNumber} />)}
    </section>
  );
}

/** Workflow step 8: the analysis runs by itself, and this page shows the results for every research question and hypothesis. */
export function AutomaticAnalysis() {
  const { project, dataset, canWrite, reload } = useProject();
  const [overview, setOverview] = useState<AutomaticOverview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const action = useAction();
  const triggered = useRef(false);

  const load = useCallback(() => {
    if (!dataset) return Promise.resolve();
    return api
      .get<AutomaticOverview>(`/projects/${project.id}/ai/automatic-analysis?dataset_id=${dataset.id}`)
      .then((data) => { setOverview(data); setLoadError(null); })
      .catch((err: Error) => setLoadError(err.message));
  }, [project.id, dataset]);

  const start = (rerun: boolean) =>
    action.run(() => api.post(`/projects/${project.id}/ai/auto-analyze`, { dataset_id: dataset?.id, rerun })).then(() => { reload(); return load(); });

  useEffect(() => {
    load();
  }, [load]);

  // The analysis runs by itself the first time the page is opened, when nothing has been analysed yet.
  useEffect(() => {
    if (!overview || triggered.current || overview.running || !canWrite) return;
    const anyRun = overview.items.some((item) => item.run !== null);
    if (!anyRun && overview.items.length > 0) {
      triggered.current = true;
      start(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overview, canWrite]);

  // While analyses are running, refresh until they finish.
  useEffect(() => {
    if (!overview?.running) return;
    const timer = setTimeout(() => load(), 3000);
    return () => clearTimeout(timer);
  }, [overview, load]);

  if (!dataset) {
    return <Empty title="Upload a dataset first" action={<Link className="btn primary" to="../upload">Upload a dataset</Link>}>Analyses run on a dataset version stored on the server.</Empty>;
  }

  const busy = action.busy || !!overview?.running;
  return (
    <div className="stack">
      <PageHead
        title="Statistical analysis"
        actions={<><DatasetPicker />{canWrite && <Button variant="primary" busy={busy} onClick={() => start(true)}>Rerun all analyses</Button>}</>}
      >
        Every research question and hypothesis is analysed automatically. The engine finds the variables and the tests that fit the data, and
        the AI assistant chooses the most suitable test for the whole analysis and gives the reason. Dataset {dataset.name}, version {dataset.current_version_number}.
      </PageHead>
      <ErrorNote message={loadError ?? action.error} />
      {busy && <Loading label="Analysing every research question and hypothesis" />}
      {overview && overview.items.length === 0 && (
        <Empty title="Nothing to analyse yet">Add research questions, link them to variables, then open this page again.</Empty>
      )}
      {overview?.items.map((item, i) => <ItemCard key={i} item={item} versionNumber={overview.version_number} />)}

      <details className="panel">
        <summary><strong>Advanced: choose and run a test yourself</strong></summary>
        <div className="stack" style={{ marginTop: "1rem" }}>
          <StatisticalAnalysis embedded />
        </div>
      </details>
    </div>
  );
}
