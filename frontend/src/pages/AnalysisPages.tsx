import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { AssumptionList, ResultView } from "../components/ResultView";
import { StepCheckPanel } from "../components/StepCheck";
import { Alert, Badge, Button, DataTable, Empty, ErrorNote, Field, Loading, PageHead, Source, StatusBadge } from "../components/ui";
import { AIReplyView, VariableMultiSelect, VariableSelect } from "../components/widgets";
import { useAction, useApi, waitForRun } from "../hooks/useApi";
import { DatasetPicker, useProject } from "../layouts/ProjectLayout";
import { api } from "../services/api";
import type { AIPlan, AIReply, AnalysisRun, EngineResult, Finding, MethodInfo, Recommendation, Variable } from "../types";
import { fmtDate, fmtNumber, LEVEL_LABELS, variablesText } from "../utils/format";

function NeedsData() {
  return <Empty title="Upload a dataset first" action={<Link className="btn primary" to="../upload">Upload a dataset</Link>}>Analyses run on a dataset version stored on the server.</Empty>;
}

/** Run one eda/descriptive job and keep the latest result on screen. */
function useJob() {
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const action = useAction();
  const start = (projectId: number, body: Record<string, unknown>) =>
    action.run(async () => {
      const created = await api.post<AnalysisRun>(`/projects/${projectId}/analysis`, body);
      setRun(created);
      const finished = await waitForRun(created, setRun);
      setRun(finished);
      return finished;
    });
  return { run, setRun, start, busy: action.busy, error: action.error };
}

// ------------------------------------------------------------ exploratory ----
export function Exploratory() {
  const { project, dataset, canWrite, reload } = useProject();
  const job = useJob();
  const runs = useApi<{ analyses: AnalysisRun[] }>(`/projects/${project.id}/analysis`);
  // show the latest stored EDA of the current version without recomputing
  useEffect(() => {
    const latest = runs.data?.analyses.find((r) => r.analysis_type === "eda" && r.status === "COMPLETED" && r.dataset_version_id === dataset?.current_version_id);
    if (latest && !job.run) api.get<AnalysisRun>(`/analysis/${latest.id}`).then(job.setRun).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs.data, dataset?.current_version_id]);
  if (!dataset) return <NeedsData />;
  const result = job.run?.results?.[0]?.result;
  const explore = () => job.start(project.id, { analysis_type: "eda", dataset_id: dataset.id }).then(() => reload());
  return (
    <div className="stack">
      <PageHead title="Explore data" actions={<><DatasetPicker />{canWrite && <Button variant="primary" busy={job.busy} onClick={explore}>{result ? "Run again on the current version" : "Explore the dataset"}</Button>}</>}>
        An automatic overview of {dataset.name}: distributions, missing data, outliers and relationships. Use it to get to know the data and to choose analyses, not to draw conclusions.
      </PageHead>
      <StepCheckPanel step="exploration" />
      <ErrorNote message={job.error ?? (job.run?.status === "FAILED" ? job.run.error_message : null)} />
      {job.busy && <Loading label="Exploring the dataset" />}
      {result && job.run && (
        <>
          <section className="panel">
            <div className="row between"><h2>Highlights</h2><span className="trail"><Source kind="engine" /> dataset version {job.run.version_number}</span></div>
            <ul>{(result.highlights ?? []).map((h, i) => <li key={i}>{h}</li>)}</ul>
          </section>
          {(result.distributions ?? []).length > 0 && (
            <section className="panel">
              <DataTable table={{ title: "Distribution of numeric variables", columns: ["Variable", "Shape", "Skewness", "Kurtosis", "Normality test", "p", "Approximately normal"],
                rows: (result.distributions as any[]).map((d) => [d.variable, d.shape, d.skewness, d.kurtosis, d.normality_test, d.normality_p, d.normal === null ? "not assessed" : d.normal ? "Yes" : "No"]) }} />
            </section>
          )}
          {(result.outliers ?? []).length > 0 && (
            <section className="panel">
              <DataTable table={{ title: "Possible outliers (1.5 x IQR rule)", columns: ["Variable", "Count", "Percent", "Lower fence", "Upper fence", "Minimum", "Maximum"],
                rows: (result.outliers as any[]).map((o) => [o.variable, o.count, o.percent, o.lower_fence, o.upper_fence, o.min, o.max]),
                note: "An outlier is not automatically an error. Check each one against your records before changing anything." }} />
            </section>
          )}
          {(result.tables ?? []).map((t, i) => <section className="panel" key={i}><DataTable table={t} maxHeight={420} /></section>)}
          {Object.keys(result.categorical_summary ?? {}).length > 0 && (
            <section className="panel stack">
              <h2>Categorical variables</h2>
              <div className="grid cols-2">
                {Object.entries(result.categorical_summary as Record<string, any>).map(([name, freq]) => (
                  <DataTable key={name} table={{ title: name, columns: ["Value", "Count", "Percent"], rows: freq.levels.map((l: any) => [l.value, l.count, l.percent]),
                    note: `Valid n = ${freq.n}, missing = ${freq.n_missing}.` }} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
      {!result && !job.busy && <Empty title="Not explored yet">Run the exploration to see summaries of every variable.</Empty>}
    </div>
  );
}

// ------------------------------------------------------------ descriptive ----
export function Descriptive() {
  const { project, dataset, canWrite, reload } = useProject();
  const dictionary = useApi<{ variables: Variable[] }>(dataset ? `/datasets/${dataset.id}/dictionary` : null);
  const [selected, setSelected] = useState<string[]>([]);
  const [groupBy, setGroupBy] = useState("");
  const job = useJob();
  if (!dataset) return <NeedsData />;
  const variables = dictionary.data?.variables ?? [];
  const result = job.run?.results?.[0]?.result;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    job.start(project.id, { analysis_type: "descriptive", dataset_id: dataset.id, variables: { variables: selected.length ? selected : null, group_by: groupBy || null } }).then(() => reload());
  };
  return (
    <div className="stack">
      <PageHead title="Descriptive statistics" actions={<DatasetPicker />}>
        Counts, percentages, means, medians, spread and confidence intervals. Numeric and categorical variables are summarised differently.
      </PageHead>
      <ErrorNote message={dictionary.error ?? job.error ?? (job.run?.status === "FAILED" ? job.run.error_message : null)} />
      {canWrite && (
        <form className="panel stack" onSubmit={submit}>
          <div className="grid cols-2">
            <Field label="Variables" hint="Hold Ctrl (Cmd on Mac) to choose several. Leave empty to describe all of them.">
              <VariableMultiSelect variables={variables} value={selected} onChange={setSelected} />
            </Field>
            <Field label="Compare groups (optional)" hint="Adds a table of the numeric variables for each group.">
              <VariableSelect variables={variables} kind="categorical" value={groupBy} onChange={setGroupBy} />
            </Field>
          </div>
          <div><Button type="submit" variant="primary" busy={job.busy}>Calculate descriptive statistics</Button></div>
        </form>
      )}
      {result && job.run && (
        <section className="panel stack">
          <div className="row between"><h2>Results</h2><span className="trail"><Source kind="engine" /> dataset version {job.run.version_number}, n = {result.n}</span></div>
          {(result.tables ?? []).map((t, i) => <DataTable key={i} table={t} maxHeight={460} />)}
          {Object.entries((result.numeric ?? {}) as Record<string, any>).filter(([, d]) => d.mean !== undefined).map(([name, d]) => (
            <details key={name}>
              <summary>All statistics for {name}</summary>
              <DataTable table={{ title: "", columns: ["Statistic", "Value"], rows: [["Count", d.n], ["Missing", d.n_missing], ["Mean", d.mean], ["95% CI of the mean", `${fmtNumber(d.mean_ci_low)} to ${fmtNumber(d.mean_ci_high)}`],
                ["Median", d.median], ["Mode", d.mode], ["Standard deviation", d.std], ["Variance", d.variance], ["Minimum", d.min], ["Maximum", d.max], ["Range", d.range],
                ["First quartile", d.q1], ["Third quartile", d.q3], ["Interquartile range", d.iqr], ["Coefficient of variation", d.cv], ["Skewness", d.skewness], ["Kurtosis", d.kurtosis]] }} />
            </details>
          ))}
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------- statistical analysis ----
const OPTION_FIELDS: Record<string, { label: string; choices?: [string, string][]; type?: "number" | "text" | "check"; hint?: string }> = {
  alternative: { label: "Alternative hypothesis", choices: [["two-sided", "two-sided (any difference or relationship)"], ["greater", "one-sided: greater / positive"], ["less", "one-sided: less / negative"]],
    hint: "Choose one-sided only if your hypothesis stated the direction before you saw the data." },
  equal_var: { label: "Variances", choices: [["auto", "decide from Levene's test (recommended)"], ["true", "assume equal (Student)"], ["false", "do not assume equal (Welch)"]] },
  robust: { label: "Use robust (HC3) standard errors", type: "check" },
  event: { label: "Outcome category to model (the 'event')", type: "text", hint: "Leave empty to use the second category in alphabetical order." },
  n_components: { label: "Number of components (empty = eigenvalue > 1 rule)", type: "number" },
  n_factors: { label: "Number of factors (empty = eigenvalue > 1 rule)", type: "number" },
  rotation: { label: "Rotation", choices: [["varimax", "varimax"], ["none", "none"]] },
  n_clusters: { label: "Number of clusters (empty = choose by silhouette score)", type: "number" },
};

function RecommendationCard({ rec, explanation, onUse }: { rec: Recommendation; explanation: AIReply | null; onUse: (method: string, variables: Record<string, any>) => void }) {
  return (
    <section className="panel stack">
      <div className="row between">
        <h2 className="grow">Recommended analysis: {rec.primary.name}</h2>
        <Source kind="rule_engine" label="Rule engine, from your variable types and assumption checks" />
      </div>
      {!rec.primary.implemented && <Alert kind="warn">This is the appropriate method, but it is not implemented in this version. No results will be produced for it.</Alert>}
      <div>
        <h3>Why</h3>
        <ul>{rec.why.map((w, i) => <li key={i}>{w}</li>)}</ul>
      </div>
      {rec.assumption_checks.length > 0 && <div><h3>Assumptions checked on your data</h3><AssumptionList checks={rec.assumption_checks} /></div>}
      {rec.warnings.length > 0 && <Alert kind="warn"><ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{rec.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></Alert>}
      {rec.alternatives.length > 0 && (
        <div>
          <h3>Alternatives</h3>
          <ul>
            {rec.alternatives.map((a, i) => (
              <li key={i}>
                <strong>{a.name}</strong>: {a.reason}{" "}
                {a.implemented && a.method !== rec.primary.method && <Button small variant="quiet" onClick={() => onUse(a.method, rec.config.variables)}>Use this instead</Button>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {rec.level_notes.length > 0 && <div><h3>For {LEVEL_LABELS[rec.academic_level] ?? rec.academic_level} level work</h3><ul>{rec.level_notes.map((n, i) => <li key={i}>{n}</li>)}</ul></div>}
      {explanation && explanation.source === "llm" && <AIReplyView reply={explanation} />}
      <div className="row">
        {rec.primary.implemented && <Button variant="primary" onClick={() => onUse(rec.config.method, rec.config.variables)}>Use {rec.primary.name}</Button>}
        <span className="small muted">{rec.disclaimer}</span>
      </div>
    </section>
  );
}

export function StatisticalAnalysis({ embedded = false }: { embedded?: boolean }) {
  const { project, dataset, canWrite, reload } = useProject();
  const [params, setParams] = useSearchParams();
  const catalogue = useApi<{ methods: MethodInfo[] }>("/methods");
  const dictionary = useApi<{ variables: Variable[] }>(dataset ? `/datasets/${dataset.id}/dictionary` : null);
  const runs = useApi<{ analyses: AnalysisRun[] }>(`/projects/${project.id}/analysis`);
  const variables = dictionary.data?.variables ?? [];

  const [rqId, setRqId] = useState(params.get("rq") ?? "");
  const [hypothesisId, setHypothesisId] = useState(params.get("hypothesis") ?? "");
  // "help me choose"
  const [outcome, setOutcome] = useState("");
  const [predictors, setPredictors] = useState<string[]>([]);
  const [paired, setPaired] = useState(false);
  const [outcomeKind, setOutcomeKind] = useState("auto");
  const [rec, setRec] = useState<{ recommendation: Recommendation; explanation: AIReply | null } | null>(null);
  const [planNote, setPlanNote] = useState<string | null>(null);
  // the test itself
  const [method, setMethod] = useState("");
  const [roles, setRoles] = useState<Record<string, any>>({});
  const [options, setOptions] = useState<Record<string, any>>({});
  const [alpha, setAlpha] = useState("0.05");
  const [justification, setJustification] = useState("");
  const [open, setOpen] = useState<AnalysisRun | null>(null);
  const [explained, setExplained] = useState<Record<number, AIReply>>({});
  const [drafted, setDrafted] = useState<Record<number, Finding>>({});
  const [notice, setNotice] = useState(false);
  const recommend = useAction();
  const planAction = useAction();
  const runTest = useAction();
  const side = useAction();

  const info = useMemo(() => catalogue.data?.methods.find((m) => m.key === method) ?? null, [catalogue.data, method]);
  const grouped = useMemo(() => {
    const out: Record<string, MethodInfo[]> = {};
    (catalogue.data?.methods ?? []).forEach((m) => (out[m.category] = [...(out[m.category] ?? []), m]));
    return out;
  }, [catalogue.data]);

  // open a run named in the URL (?run=12)
  const runParam = params.get("run");
  useEffect(() => {
    if (runParam) api.get<AnalysisRun>(`/analysis/${runParam}`).then(setOpen).catch(() => undefined);
  }, [runParam]);
  // a hypothesis fixes alpha and the research question
  useEffect(() => {
    const h = project.hypotheses.find((x) => String(x.id) === hypothesisId);
    if (h) {
      setAlpha(String(h.alpha));
      if (h.research_question_id) setRqId(String(h.research_question_id));
    }
  }, [hypothesisId, project.hypotheses]);

  if (!dataset) return <NeedsData />;

  const askRecommendation = (event: FormEvent) => {
    event.preventDefault();
    recommend.run(() => api.post<{ recommendation: Recommendation; explanation: AIReply }>(`/projects/${project.id}/ai/recommend`, {
      dataset_id: dataset.id, research_question_id: rqId ? Number(rqId) : null, outcome: paired ? null : outcome || null,
      predictors: paired ? [] : predictors, paired, measures: paired ? predictors : [], outcome_kind: outcomeKind,
    })).then((result) => result && setRec(result));
  };
  const applyMethod = (key: string, vars: Record<string, any>) => {
    setMethod(key);
    setRoles(vars);
    setOptions({});
    if (rec) setJustification(rec.recommendation.why.join(" "));
    document.getElementById("run-test")?.scrollIntoView({ behavior: "smooth" });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const cleanOptions: Record<string, unknown> = { alpha: Number(alpha) };
    Object.entries(options).forEach(([key, value]) => {
      if (value === "" || value === undefined || value === null) return;
      const spec = OPTION_FIELDS[key];
      cleanOptions[key] = spec?.type === "number" ? Number(value) : key === "equal_var" && value !== "auto" ? value === "true" : value;
    });
    runTest.run(async () => {
      const created = await api.post<AnalysisRun>(`/projects/${project.id}/analysis`, {
        analysis_type: "inferential", dataset_id: dataset.id, method, variables: roles, params: cleanOptions,
        research_question_id: rqId ? Number(rqId) : null, hypothesis_id: hypothesisId ? Number(hypothesisId) : null, justification: justification || null,
      });
      setOpen(created);
      const finished = await waitForRun(created, setOpen);
      setOpen(finished);
      runs.reload();
      reload();
      setParams({ run: String(finished.id) }, { replace: true });
    });
  };
  const explain = (resultId: number) =>
    side.run(() => api.post<AIReply>(`/projects/${project.id}/ai/explain`, { analysis_result_id: resultId })).then((reply) => reply && setExplained({ ...explained, [resultId]: reply }));
  const draftFinding = (resultId: number) =>
    side.run(() => api.post<Finding>(`/projects/${project.id}/findings/from-result`, { analysis_result_id: resultId })).then((finding) => {
      if (finding) {
        setDrafted({ ...drafted, [resultId]: finding });
        reload();
      }
    });
  const reproduce = (run: AnalysisRun) =>
    side.run(async () => {
      const created = await api.post<AnalysisRun>(`/analysis/${run.id}/reproduce`);
      setOpen(created);
      await waitForRun(created);
      setOpen(await api.get<AnalysisRun>(`/analysis/${created.id}`));
      runs.reload();
    });
  const diagnostics = (run: AnalysisRun) => side.run(() => api.post(`/analysis/${run.id}/diagnostic-plot`)).then((ok) => ok && setNotice(true));
  // AI chooses the variables and test for the selected question/hypothesis and fills in the form (nothing is run)
  const choosePlan = () => {
    setPlanNote(null);
    planAction.run(() => api.post<AIPlan>(`/projects/${project.id}/ai/plan`, {
      dataset_id: dataset.id, research_question_id: rqId ? Number(rqId) : null, hypothesis_id: hypothesisId ? Number(hypothesisId) : null,
    })).then((plan) => {
      if (!plan) return;
      if (plan.status === "skipped") return setPlanNote(plan.reason ?? "This question cannot be analysed yet.");
      setOutcome(plan.outcome ?? "");
      setPredictors(plan.predictors ?? []);
      setPaired(false);
      setRec(plan.recommendation ? { recommendation: plan.recommendation, explanation: null } : null);
      setMethod(plan.method ?? "");
      setRoles(plan.variables ?? {});
      setOptions({});
      setJustification(plan.justification ?? "");
      if (plan.source !== "llm") setPlanNote(`The AI assistant did not choose this test, so the rule engine's choice is shown. ${plan.notice ?? ""}`.trim());
      document.getElementById("run-test")?.scrollIntoView({ behavior: "smooth" });
    });
  };

  return (
    <div className="stack">
      {!embedded && (
        <PageHead title="Run analysis" actions={<DatasetPicker />}>
          Choose a test yourself, or describe your variables and get a recommendation with the reasons for it. Analysing {dataset.name}, version {dataset.current_version_number}.
        </PageHead>
      )}
      <StepCheckPanel step="analysis" />
      <ErrorNote message={catalogue.error ?? dictionary.error} />

      {canWrite && (
        <>
          <section className="panel grid cols-2">
            <Field label="Research question this analysis answers">
              <select value={rqId} onChange={(e) => setRqId(e.target.value)}>
                <option value="">Not linked to a question</option>
                {project.research_questions.map((q) => <option key={q.id} value={q.id}>{q.code}: {q.text.slice(0, 70)}</option>)}
              </select>
            </Field>
            <Field label="Hypothesis being tested" hint="The decision on H0 is recorded on the hypothesis when the test finishes.">
              <select value={hypothesisId} onChange={(e) => setHypothesisId(e.target.value)}>
                <option value="">No hypothesis</option>
                {project.hypotheses.map((h) => <option key={h.id} value={h.id}>{h.code}: {h.alternative_text.slice(0, 70)}</option>)}
              </select>
            </Field>
          </section>

          <form className="panel stack" onSubmit={askRecommendation}>
            <h2>Help me choose a test</h2>
            <label className="check">
              <input type="checkbox" checked={paired} onChange={(e) => setPaired(e.target.checked)} />
              <span>The same participants were measured more than once (before/after, or repeated measurements in separate columns)</span>
            </label>
            <div className="grid cols-2">
              {!paired && (
                <Field label="Outcome (dependent variable)" hint="What you want to explain or compare.">
                  <VariableSelect variables={variables} value={outcome} onChange={setOutcome} />
                </Field>
              )}
              <Field label={paired ? "Measurement columns (2 or more)" : "Predictors or grouping variables (independent)"} hint="Hold Ctrl (Cmd on Mac) to choose several.">
                <VariableMultiSelect variables={variables} kind={paired ? "numeric" : "any"} value={predictors} onChange={setPredictors} />
              </Field>
              {!paired && (
                <Field label="Type of outcome" hint="Detected from the data dictionary unless you say otherwise.">
                  <select value={outcomeKind} onChange={(e) => setOutcomeKind(e.target.value)}>
                    <option value="auto">Detect automatically</option>
                    <option value="continuous">Continuous number</option>
                    <option value="ordinal">Ordinal (ordered ratings)</option>
                    <option value="binary">Two categories</option>
                    <option value="nominal">Several categories</option>
                    <option value="count">Count of events</option>
                    <option value="time_to_event">Time until an event</option>
                  </select>
                </Field>
              )}
            </div>
            <ErrorNote message={recommend.error ?? planAction.error} />
            {planNote && <Alert kind="warn">{planNote}</Alert>}
            <div className="row">
              <Button type="submit" busy={recommend.busy}>Recommend a method</Button>
              <Button type="button" variant="primary" busy={planAction.busy} onClick={choosePlan}>Choose the most suitable test with AI</Button>
            </div>
          </form>
          {rec && <RecommendationCard rec={rec.recommendation} explanation={rec.explanation} onUse={applyMethod} />}

          <form className="panel stack" id="run-test" onSubmit={submit}>
            <h2>Run a statistical test</h2>
            <Field label="Method">
              <select required value={method} onChange={(e) => { setMethod(e.target.value); setRoles({}); setOptions({}); }}>
                <option value="">Choose a method</option>
                {Object.entries(grouped).map(([category, methods]) => (
                  <optgroup key={category} label={category}>
                    {methods.map((m) => <option key={m.key} value={m.key} disabled={!m.implemented}>{m.name}{m.implemented ? "" : " (not implemented yet)"}</option>)}
                  </optgroup>
                ))}
              </select>
            </Field>
            {info && <p className="small muted">{info.description} Typically used from {LEVEL_LABELS[info.typical_level]} level.</p>}
            {info && (
              <div className="grid cols-2">
                {info.roles.map((role) => (
                  <Field key={role.name} label={role.label} hint={role.multiple ? `Choose at least ${role.min}. Hold Ctrl (Cmd on Mac) to choose several.` : undefined}>
                    {role.multiple ? (
                      <VariableMultiSelect variables={variables} kind={role.kind} value={roles[role.name] ?? []} onChange={(v) => setRoles({ ...roles, [role.name]: v })} />
                    ) : (
                      <VariableSelect variables={variables} kind={role.kind} value={roles[role.name] ?? ""} onChange={(v) => setRoles({ ...roles, [role.name]: v })} />
                    )}
                  </Field>
                ))}
                {info.options.map((key) => {
                  const spec = OPTION_FIELDS[key];
                  if (!spec) return null;
                  if (spec.type === "check") {
                    return <label className="check" key={key}><input type="checkbox" checked={!!options[key]} onChange={(e) => setOptions({ ...options, [key]: e.target.checked })} /><span>{spec.label}</span></label>;
                  }
                  return (
                    <Field key={key} label={spec.label} hint={spec.hint}>
                      {spec.choices ? (
                        <select value={options[key] ?? spec.choices[0][0]} onChange={(e) => setOptions({ ...options, [key]: e.target.value })}>
                          {spec.choices.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                      ) : <input type={spec.type === "number" ? "number" : "text"} min={1} value={options[key] ?? ""} onChange={(e) => setOptions({ ...options, [key]: e.target.value })} />}
                    </Field>
                  );
                })}
                <Field label="Significance level (alpha)" hint={hypothesisId ? "Taken from the hypothesis." : "Fix this before running the test."}>
                  <select value={alpha} disabled={!!hypothesisId} onChange={(e) => setAlpha(e.target.value)}>
                    <option value="0.05">0.05</option><option value="0.01">0.01</option><option value="0.1">0.10</option>
                  </select>
                </Field>
              </div>
            )}
            <Field label="Why this method? (optional)" hint="Goes into the methodology section of your report.">
              <textarea value={justification} onChange={(e) => setJustification(e.target.value)} />
            </Field>
            <ErrorNote message={runTest.error} />
            <div><Button type="submit" variant="primary" busy={runTest.busy} disabled={!method}>Run the test</Button></div>
          </form>
        </>
      )}

      {open && (
        <section className="stack" aria-live="polite">
          <div className="panel row between">
            <div className="grow">
              <h2>{open.name} <StatusBadge status={open.status} /></h2>
              <div className="small muted">
                Analysis #{open.id}, dataset version {open.version_number}, {fmtDate(open.created_at)}.
                {open.reproduced_from_id ? ` Reproduction of analysis #${open.reproduced_from_id}.` : ""}
                {open.filters.length > 0 ? ` Filters: ${JSON.stringify(open.filters)}.` : ""}
              </div>
            </div>
            {canWrite && open.status === "COMPLETED" && (
              <div className="row">
                <Button small busy={side.busy} onClick={() => reproduce(open)}>Reproduce</Button>
                {open.results?.some((r) => r.result?.diagnostics) && <Button small onClick={() => diagnostics(open)}>Draw diagnostic plots</Button>}
              </div>
            )}
          </div>
          {(open.status === "PENDING" || open.status === "PROCESSING") && <Loading label={`Running (${open.progress}%)`} />}
          {open.status === "FAILED" && <Alert kind="error"><strong>No result was produced.</strong> {open.error_message}</Alert>}
          {open.tests.filter((t) => t.status === "FAILED" && open.status !== "FAILED").map((t) => <Alert kind="error" key={t.id}>{t.method_name}: {t.error_message}</Alert>)}
          {open.reproduction_check && (
            <Alert kind={open.reproduction_check.identical ? "ok" : "warn"}>
              {open.reproduction_check.identical
                ? "Reproduced: the statistics and p-values are identical to the original analysis."
                : "The reproduction differs from the original. Compare the software versions recorded with each run."}
            </Alert>
          )}
          <ErrorNote message={side.error} />
          {notice && <Alert kind="ok">Diagnostic plots were added. <Link to="../charts">Open the Visualization studio</Link>.</Alert>}
          {(open.results ?? []).filter((r) => r.result).map((row) => (
            <div className="stack" key={row.id}>
              <ResultView result={row.result as EngineResult} datasetVersion={open.version_number}
                actions={row.result_type === "test" && (
                  <>
                    <Button small busy={side.busy} onClick={() => explain(row.id)}>Explain this result</Button>
                    {canWrite && !drafted[row.id] && <Button small variant="primary" busy={side.busy} onClick={() => draftFinding(row.id)}>Draft a finding</Button>}
                  </>
                )} />
              {explained[row.id] && <div className="panel"><h3>Explanation</h3><AIReplyView reply={explained[row.id]} /></div>}
              {drafted[row.id] && <Alert kind="ok">Finding drafted: "{drafted[row.id].title}". <Link to="../findings">Review and edit it</Link>.</Alert>}
            </div>
          ))}
        </section>
      )}

      <section className="panel">
        <h2>Analyses in this project</h2>
        {runs.loading && <Loading />}
        {runs.data && runs.data.analyses.length === 0 && <p className="muted">Nothing has been run yet.</p>}
        {runs.data && runs.data.analyses.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Analysis</th><th>Variables</th><th>Question</th><th>Dataset version</th><th>Date</th><th>Status</th></tr></thead>
              <tbody>
                {runs.data.analyses.map((r) => (
                  <tr key={r.id}>
                    <td><Button variant="quiet" small onClick={() => setParams({ run: String(r.id) })}>{r.name}</Button></td>
                    <td className="small">{variablesText(r.config.variables)}</td>
                    <td>{project.research_questions.find((q) => q.id === r.research_question_id)?.code ?? "–"}</td>
                    <td className="num">v{r.version_number}</td>
                    <td className="small">{fmtDate(r.created_at)}</td>
                    <td><StatusBadge status={r.status} />{r.result_summaries.some((s) => s.is_significant) ? <> <Badge tone="ok">significant</Badge></> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

// ------------------------------------------------------------------ power ----
interface PowerResult { summary: string; warnings: string[]; planning: string; required_n?: number; total_n?: number; n_unit: string; power?: number; achieved_power?: number;
  effect_size_name: string; benchmarks: Record<string, number>; power_curve: { n: number; power: number }[] }

export function PowerPlanner() {
  const designs = useApi<{ power_designs: { key: string; label: string; effect: string; benchmarks: Record<string, number> }[] }>("/methods");
  const [design, setDesign] = useState("t_test_independent");
  const [mode, setMode] = useState("required_n");
  const [effect, setEffect] = useState("0.5");
  const [n, setN] = useState("50");
  const [power, setPower] = useState("0.8");
  const [alpha, setAlpha] = useState("0.05");
  const [groups, setGroups] = useState("3");
  const [df, setDf] = useState("1");
  const [predictors, setPredictors] = useState("3");
  const [result, setResult] = useState<PowerResult | null>(null);
  const { busy, error, run } = useAction();
  const current = designs.data?.power_designs.find((d) => d.key === design);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const body: Record<string, unknown> = { design, mode, effect_size: Number(effect), alpha: Number(alpha) };
    if (mode === "required_n") body.power = Number(power); else body.n = Number(n);
    if (design === "anova") body.k_groups = Number(groups);
    if (design === "chi_square") body.df = Number(df);
    if (design === "regression") body.n_predictors = Number(predictors);
    run(() => api.post<PowerResult>("/power", body)).then((r) => r && setResult(r));
  };
  return (
    <main className="page stack" style={{ maxWidth: 900 }}>
      <PageHead title="Sample size and power">
        Plan how many participants you need before collecting data. The calculation uses the same noncentral distributions as G*Power.
      </PageHead>
      <form className="panel stack" onSubmit={submit}>
        <div className="grid cols-2">
          <Field label="Planned analysis">
            <select value={design} onChange={(e) => { setDesign(e.target.value); setResult(null); }}>
              {(designs.data?.power_designs ?? []).map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
            </select>
          </Field>
          <Field label="What do you want to know?">
            <select value={mode} onChange={(e) => { setMode(e.target.value); setResult(null); }}>
              <option value="required_n">Sample size needed (planning before the study)</option>
              <option value="power">Power of a given sample size for an assumed effect</option>
              <option value="post_hoc">Observed (post-hoc) power from a result I already have</option>
            </select>
          </Field>
          <Field label={`Effect size (${current?.effect ?? "effect size"})`}
            hint={current ? `Cohen's benchmarks: small ${current.benchmarks.small}, medium ${current.benchmarks.medium}, large ${current.benchmarks.large}. Prefer a value from earlier studies.` : undefined}>
            <input type="number" step="any" required value={effect} onChange={(e) => setEffect(e.target.value)} />
          </Field>
          {mode === "required_n" ? (
            <Field label="Desired power" hint="0.80 is the usual minimum."><input type="number" step="0.01" min="0.5" max="0.99" required value={power} onChange={(e) => setPower(e.target.value)} /></Field>
          ) : (
            <Field label={design === "t_test_independent" ? "Sample size per group" : design === "t_test_paired" ? "Number of pairs" : "Total sample size"}>
              <input type="number" min={2} required value={n} onChange={(e) => setN(e.target.value)} />
            </Field>
          )}
          <Field label="Significance level (alpha)"><select value={alpha} onChange={(e) => setAlpha(e.target.value)}><option>0.05</option><option>0.01</option><option>0.1</option></select></Field>
          {design === "anova" && <Field label="Number of groups"><input type="number" min={2} value={groups} onChange={(e) => setGroups(e.target.value)} /></Field>}
          {design === "chi_square" && <Field label="Degrees of freedom" hint="(rows - 1) x (columns - 1)"><input type="number" min={1} value={df} onChange={(e) => setDf(e.target.value)} /></Field>}
          {design === "regression" && <Field label="Number of predictors"><input type="number" min={1} value={predictors} onChange={(e) => setPredictors(e.target.value)} /></Field>}
        </div>
        {mode === "post_hoc" && <Alert kind="warn">Observed power is a re-expression of the p-value and cannot show whether a study was large enough. Report the confidence interval of the effect instead. It is offered only because some departments ask for it.</Alert>}
        <ErrorNote message={error} />
        <div><Button type="submit" variant="primary" busy={busy}>Calculate</Button></div>
      </form>
      {result && (
        <section className="panel stack">
          <div className="row between"><h2>{result.planning === "post_hoc" ? "Post-hoc (observed) power" : "Prospective planning"}</h2><Source kind="engine" /></div>
          <p style={{ fontSize: "1.05rem" }}>{result.summary}</p>
          {result.warnings.map((w, i) => <Alert kind="warn" key={i}>{w}</Alert>)}
          <DataTable table={{ title: "Power at different sample sizes", columns: [`Sample size (${result.n_unit})`, "Power"], rows: result.power_curve.map((p) => [p.n, p.power]) }} />
        </section>
      )}
    </main>
  );
}

