import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useLocation } from "react-router-dom";

import { Button, confirmAction, Empty, ErrorNote, Field, Loading, PageHead } from "../components/ui";
import { AIReplyView, AuthImage, VariableMultiSelect, VariableSelect } from "../components/widgets";
import { useAction, useApi } from "../hooks/useApi";
import { DatasetPicker, useProject } from "../layouts/ProjectLayout";
import { api, download } from "../services/api";
import type { AIReply, Variable, Visualization } from "../types";
import { fmtDate } from "../utils/format";

// which inputs each chart type needs: [x kind, y kind, hue allowed, uses a list of columns]
const NEEDS: Record<string, { x?: "numeric" | "categorical" | "any"; y?: "numeric"; yOptional?: boolean; hue?: boolean; columns?: boolean }> = {
  bar: { x: "categorical", y: "numeric", yOptional: true },
  pie: { x: "categorical" },
  histogram: { x: "numeric" },
  box: { x: "categorical", y: "numeric" },
  violin: { x: "categorical", y: "numeric" },
  scatter: { x: "numeric", y: "numeric", hue: true },
  line: { x: "any", y: "numeric", hue: true },
  heatmap: { x: "categorical" },
  correlation_matrix: { columns: true },
  regression: { x: "numeric", y: "numeric" },
  group_comparison: { x: "categorical", y: "numeric" },
  time_series: { x: "any", y: "numeric", hue: true },
  qq: { x: "numeric" },
};
const BLANK = { chart_type: "histogram", x: "", y: "", hue: "", title: "", x_label: "", y_label: "", category_order: "" };

export default function VisualizationStudio() {
  const { project, dataset, canWrite } = useProject();
  const location = useLocation();
  const suggested = (location.state as { chart?: Record<string, any> } | null)?.chart;
  const types = useApi<{ chart_types: { key: string; label: string; needs: string }[] }>("/methods");
  const dictionary = useApi<{ variables: Variable[] }>(dataset ? `/datasets/${dataset.id}/dictionary` : null);
  const charts = useApi<{ visualizations: Visualization[] }>(`/projects/${project.id}/visualizations`);
  const [form, setForm] = useState(BLANK);
  const [columns, setColumns] = useState<string[]>([]);
  const [editing, setEditing] = useState<Visualization | null>(null);
  const [explained, setExplained] = useState<Record<number, AIReply>>({});
  const { busy, error, run } = useAction();
  const variables = dictionary.data?.variables ?? [];
  const needs = NEEDS[form.chart_type] ?? {};
  const set = (key: keyof typeof BLANK) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  useEffect(() => {
    if (suggested) {
      setForm({ ...BLANK, chart_type: suggested.chart_type, x: suggested.x ?? "", y: suggested.y ?? "", title: suggested.title ?? "" });
      setColumns(suggested.columns ?? []);
    }
  }, [suggested]);

  if (!dataset) return <Empty title="Upload a dataset first">Charts are drawn from the stored dataset version.</Empty>;

  const body = () => ({
    chart_type: form.chart_type, dataset_id: dataset.id, x: form.x || null, y: form.y || null, hue: needs.hue && form.hue ? form.hue : null,
    columns: needs.columns ? columns : null, title: form.title || null, x_label: form.x_label || null, y_label: form.y_label || null,
    category_order: form.category_order ? form.category_order.split(",").map((s) => s.trim()).filter(Boolean) : null,
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(() => (editing ? api.put(`/visualizations/${editing.id}`, body()) : api.post(`/projects/${project.id}/visualizations`, body()))).then((ok) => {
      if (ok) {
        setEditing(null);
        setForm(BLANK);
        setColumns([]);
        charts.reload();
      }
    });
  };
  const customise = (chart: Visualization) => {
    setEditing(chart);
    const c = chart.config;
    setForm({ chart_type: chart.chart_type, x: c.x ?? "", y: c.y ?? "", hue: c.hue ?? "", title: chart.title, x_label: c.x_label ?? "", y_label: c.y_label ?? "",
      category_order: (c.category_order ?? []).join(", ") });
    setColumns(c.columns ?? []);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const toggleReport = (chart: Visualization) => run(() => api.put(`/visualizations/${chart.id}`, { include_in_report: !chart.include_in_report })).then(charts.reload);

  // ── CHANGED: pass chart context so the AI can write a meaningful explanation ──
  const explain = (chart: Visualization) =>
    run(() =>
      api.post<AIReply>(`/projects/${project.id}/ai/explain`, {
        visualization_id: chart.id,
        chart_type: chart.chart_type,
        title: chart.title,
        x: chart.config?.x ?? null,
        y: chart.config?.y ?? null,
        hue: chart.config?.hue ?? null,
        columns: chart.config?.columns ?? null,
        meta: chart.meta ?? {},
      })
    ).then((reply) => reply && setExplained({ ...explained, [chart.id]: reply }));
  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <div className="stack">
      <PageHead title="Visualization studio" actions={<DatasetPicker />}>
        Charts are drawn on the server from {dataset.name}, version {dataset.current_version_number}, so the image you see is the one that goes into the report.
      </PageHead>
      <ErrorNote message={error ?? charts.error} />
      {canWrite && (
        <form className="panel stack" onSubmit={submit}>
          <h2>{editing ? `Customise "${editing.title}"` : "Create a chart"}</h2>
          <div className="grid cols-3">
            <Field label="Chart type" hint={types.data?.chart_types.find((t) => t.key === form.chart_type)?.needs}>
              <select value={form.chart_type} disabled={editing?.chart_type === "regression_diagnostics"} onChange={(e) => setForm({ ...form, chart_type: e.target.value })}>
                {(types.data?.chart_types ?? []).map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select>
            </Field>
            {needs.x && (
              <Field label={form.chart_type === "heatmap" ? "Columns (category)" : needs.x === "categorical" ? "Category (x-axis)" : "x-axis"}>
                <VariableSelect variables={variables} kind={needs.x} value={form.x} onChange={(v) => setForm({ ...form, x: v })} />
              </Field>
            )}
            {(needs.y || form.chart_type === "heatmap") && (
              <Field label={form.chart_type === "heatmap" ? "Rows (category)" : needs.yOptional ? "Numeric variable (optional: shows its mean)" : "y-axis (numeric)"}>
                <VariableSelect variables={variables} kind={form.chart_type === "heatmap" ? "categorical" : "numeric"} value={form.y} onChange={(v) => setForm({ ...form, y: v })} />
              </Field>
            )}
            {needs.hue && (
              <Field label="Separate series by (optional)"><VariableSelect variables={variables} kind="categorical" value={form.hue} onChange={(v) => setForm({ ...form, hue: v })} /></Field>
            )}
            {needs.columns && (
              <Field label="Numeric variables" hint="Hold Ctrl (Cmd on Mac) to choose several."><VariableMultiSelect variables={variables} kind="numeric" value={columns} onChange={setColumns} /></Field>
            )}
          </div>
          <details open={!!editing}>
            <summary>Titles and labels</summary>
            <div className="grid cols-2" style={{ marginTop: "0.75rem" }}>
              <Field label="Chart title" hint="Leave empty for a descriptive title."><input type="text" value={form.title} onChange={set("title")} /></Field>
              <Field label="Order of categories" hint="Comma-separated, e.g. Low, Moderate, High"><input type="text" value={form.category_order} onChange={set("category_order")} /></Field>
              <Field label="x-axis label" hint="Defaults to the label and unit in the data dictionary."><input type="text" value={form.x_label} onChange={set("x_label")} /></Field>
              <Field label="y-axis label"><input type="text" value={form.y_label} onChange={set("y_label")} /></Field>
            </div>
          </details>
          <div className="row">
            <Button type="submit" variant="primary" busy={busy}>{editing ? "Regenerate chart" : "Create chart"}</Button>
            {editing && <Button onClick={() => { setEditing(null); setForm(BLANK); }}>Cancel</Button>}
          </div>
        </form>
      )}
      {charts.loading && <Loading />}
      {charts.data && charts.data.visualizations.length === 0 && <Empty title="No charts yet">Create one above, or start from the suggestions on the Explore data page.</Empty>}
      <div className="grid cols-2">
        {charts.data?.visualizations.map((chart) => (
          <figure className="panel stack" key={chart.id} style={{ margin: 0, ["--gap" as string]: "0.6rem" }}>
            <div className="chart-frame"><AuthImage path={chart.image_url} alt={chart.title} version={chart.updated_at} /></div>
            <figcaption>
              <strong>{chart.title}</strong>
              <div className="small muted">
                n = {chart.meta.n ?? "–"}, dataset version {chart.version_number}, {fmtDate(chart.updated_at)}. {(chart.meta.notes ?? []).join(" ")}
              </div>
            </figcaption>
            <div className="row">
              <Button small onClick={() => run(() => download(`${chart.image_url}?download=true`, `${chart.title}.png`))}>Download PNG</Button>
              {canWrite && <Button small onClick={() => toggleReport(chart)}>{chart.include_in_report ? "Remove from report" : "Add to report"}</Button>}
              {canWrite && chart.chart_type !== "regression_diagnostics" && <Button small onClick={() => customise(chart)}>Customise</Button>}
              <Button small onClick={() => explain(chart)}>How to read this</Button>
              {canWrite && <Button small variant="quiet" onClick={() => confirmAction("Delete this chart?") && run(() => api.del(`/visualizations/${chart.id}`)).then(charts.reload)}>Delete</Button>}
            </div>
            {explained[chart.id] && <AIReplyView reply={explained[chart.id]} />}
          </figure>
        ))}
      </div>
    </div>
  );
}