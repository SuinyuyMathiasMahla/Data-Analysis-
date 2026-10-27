import { useEffect, useState } from "react";

import { ChartTitleDraft } from "./AssistantDrafts";
import { useApi, useAction } from "../hooks/useApi";
import { useProject } from "../layouts/ProjectLayout";
import { api } from "../services/api";
import type { AIReply, ChartIdea, Variable } from "../types";
import { Alert, Button, Field } from "./ui";
import { AIReplyView } from "./widgets";

function sameChart(a: ChartIdea, b: ChartIdea): boolean {
  return a.chart_type === b.chart_type && a.title === b.title && a.x === b.x && a.y === b.y;
}

/** The charts a reader can draw for a finding or conclusion, each opened inline below the list. */
export function ChartIdeas({ ideas, heading }: { ideas: ChartIdea[]; heading: string }) {
  const [drawn, setDrawn] = useState<ChartIdea | null>(null);
  if (ideas.length === 0) return null;
  return (
    <div className="stack" style={{ ["--gap" as string]: "0.45rem" }}>
      <h3>{heading}</h3>
      {ideas.map((chart, i) => (
        <div className="panel row between" key={i}>
          <div className="grow">
            <strong>{chart.title}</strong>
            <p className="small muted" style={{ margin: 0 }}>{chart.reason}</p>
          </div>
          <Button small variant="primary" onClick={() => setDrawn(chart)}>Draw this chart</Button>
        </div>
      ))}
      {drawn && (
        <ChartDrawer key={`${drawn.chart_type}-${drawn.title}-${drawn.run_id ?? ""}`} ideas={ideas} initial={drawn} onClose={() => setDrawn(null)} />
      )}
    </div>
  );
}

/** Draws one chart inline, with the customisation, explanation and report options the Visualization studio has. */
export function ChartDrawer({ ideas, initial, onClose }: { ideas: ChartIdea[]; initial: ChartIdea; onClose: () => void }) {
  const { project, dataset, canWrite } = useProject();
  const types = useApi<{ chart_types: { key: string; label: string }[] }>("/methods");
  const dictionary = useApi<{ variables: Variable[] }>(dataset ? `/datasets/${dataset.id}/dictionary` : null);
  const variables = dictionary.data?.variables ?? [];
  const [config, setConfig] = useState<ChartIdea>(initial);
  const [categoryOrder, setCategoryOrder] = useState("");
  const [xLabel, setXLabel] = useState("");
  const [yLabel, setYLabel] = useState("");
  const [url, setUrl] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [included, setIncluded] = useState(false);
  const [explanation, setExplanation] = useState<AIReply | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const explain = useAction();

  // the request body shared by preview, save and update (the chart settings the studio uses)
  const body = (next: ChartIdea) => ({
    chart_type: next.chart_type, x: next.x ?? null, y: next.y ?? null, columns: next.columns ?? null, title: next.title || null,
    x_label: xLabel || null, y_label: yLabel || null, dataset_id: dataset?.id ?? null,
    category_order: categoryOrder ? categoryOrder.split(",").map((s) => s.trim()).filter(Boolean) : null,
  });

  const draw = (next: ChartIdea) => {
    if (!dataset) return;
    setConfig(next);
    setBusy(true);
    setError(null);
    setExplanation(null);
    const preview = api
      .postBlob(`/projects/${project.id}/visualizations/preview`, { ...body(next), run_id: next.run_id ?? null })
      .then((blob) => setUrl(URL.createObjectURL(blob)));
    // a chart already saved for this panel is updated to match what is drawn
    const update = savedId !== null ? api.put(`/visualizations/${savedId}`, body(next)) : Promise.resolve(null);
    Promise.all([preview, update])
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false));
  };

  // draw the suggested chart when opened; release each image when it is replaced or the panel closes
  useEffect(() => {
    draw(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  // the report and explanation need a saved chart; save it the first time either is used
  const ensureSaved = async (): Promise<number> => {
    if (savedId !== null) return savedId;
    const created = config.run_id != null
      ? await api.post<{ id: number }>(`/analysis/${config.run_id}/visualizations`, body(config))
      : await api.post<{ id: number }>(`/projects/${project.id}/visualizations`, body(config));
    setSavedId(created.id);
    return created.id;
  };
  const toggleReport = () =>
    explain.run(async () => {
      const id = await ensureSaved();
      await api.put(`/visualizations/${id}`, { include_in_report: !included });
      setIncluded(!included);
    });
  const howToRead = () =>
    explain.run(async () => {
      const id = await ensureSaved();
      setExplanation(await api.post<AIReply>(`/projects/${project.id}/ai/explain`, { visualization_id: id }));
    });

  const changed = (patch: Partial<ChartIdea>) => setConfig({ ...config, ...patch, title: "" });
  const others = ideas.filter((idea) => !sameChart(idea, config));

  return (
    <div className="panel stack" style={{ ["--gap" as string]: "0.6rem", borderLeft: "3px solid var(--accent, #6d5efc)" }}>
      <div className="row between">
        <h3 className="grow">{config.title || `${config.chart_type} chart`}</h3>
        <Button small variant="quiet" onClick={onClose}>Close</Button>
      </div>

      <div className="grid cols-3">
        <Field label="Chart type">
          <select value={config.chart_type} onChange={(e) => changed({ chart_type: e.target.value })}>
            {(types.data?.chart_types ?? [{ key: config.chart_type, label: config.chart_type }]).map((t) => (
              <option key={t.key} value={t.key}>{t.label}</option>
            ))}
          </select>
        </Field>
        <Field label="Across (x)">
          <select value={config.x ?? ""} onChange={(e) => changed({ x: e.target.value || undefined })}>
            <option value="">None</option>
            {variables.map((v) => <option key={v.name} value={v.name}>{v.name}</option>)}
          </select>
        </Field>
        <Field label="Measured (y)">
          <select value={config.y ?? ""} onChange={(e) => changed({ y: e.target.value || undefined })}>
            <option value="">None</option>
            {variables.map((v) => <option key={v.name} value={v.name}>{v.name}</option>)}
          </select>
        </Field>
      </div>

      <details>
        <summary className="small"><strong>Customise the chart</strong></summary>
        <div className="grid cols-3" style={{ marginTop: "0.6rem" }}>
          <Field label="Title"><input type="text" value={config.title} placeholder="Chart title" onChange={(e) => setConfig({ ...config, title: e.target.value })} /></Field>
          <ChartTitleDraft projectId={project.id} chartType={config.chart_type} x={config.x ?? undefined} y={config.y ?? undefined}
            onUse={(draft) => { setConfig({ ...config, title: draft.title }); setXLabel(draft.xLabel); setYLabel(draft.yLabel); }} />
          <Field label="x-axis label"><input type="text" value={xLabel} onChange={(e) => setXLabel(e.target.value)} /></Field>
          <Field label="y-axis label"><input type="text" value={yLabel} onChange={(e) => setYLabel(e.target.value)} /></Field>
          <Field label="Category order" hint="Comma-separated, for categories on the x-axis."><input type="text" value={categoryOrder} onChange={(e) => setCategoryOrder(e.target.value)} /></Field>
        </div>
      </details>

      <div className="row">
        <Button variant="primary" busy={busy} onClick={() => draw(config)}>Draw</Button>
        {canWrite && (
          <>
            <Button busy={explain.busy} onClick={toggleReport}>{included ? "Remove from report" : "Add to report"}</Button>
            <Button busy={explain.busy} onClick={howToRead}>How to read this chart</Button>
          </>
        )}
      </div>
      {included && <p className="small muted" style={{ margin: 0 }}>This chart is included in the generated report.</p>}
      {error && <Alert kind="error">{error}</Alert>}
      {explain.error && <Alert kind="error">{explain.error}</Alert>}
      {busy && <p className="muted" role="status">Drawing the chart…</p>}
      {url && !busy && <img src={url} alt={config.title || config.chart_type} style={{ maxWidth: "100%", height: "auto" }} />}
      {explanation && <AIReplyView reply={explanation} />}

      {others.length > 0 && (
        <div className="stack" style={{ ["--gap" as string]: "0.35rem" }}>
          <h3>Other charts you could draw</h3>
          {others.map((idea, i) => (
            <div className="row between" key={i}>
              <span><strong>{idea.title}</strong> <span className="small muted">{idea.reason}</span></span>
              <Button small onClick={() => draw(idea)}>Draw</Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
