import { useEffect, useRef, useState } from "react";
import { StepCheckPanel } from "../components/StepCheck";
import type { FormEvent } from "react";
import { Link, NavLink } from "react-router-dom";

import { Alert, Badge, Button, confirmAction, Empty, ErrorNote, Field, Loading, PageHead, Source } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { useProject } from "../layouts/ProjectLayout";
import { api } from "../services/api";
import type { Finding, Limitation, TextItem } from "../types";
import { ChartIdeas } from "../components/ChartDrawer";

const CONFIDENCE: Record<string, "ok" | "warn" | "danger"> = { high: "ok", moderate: "warn", low: "danger" };
/** Runs the automatic findings / conclusions / recommendations step once per visit. Safe to repeat: the server only adds what is missing. */
function useAutomaticEvidence(onDone: () => void) {
  const { project, canWrite, reload } = useProject();
  const action = useAction();
  const triggered = useRef(false);
  const go = (regenerate: boolean) =>
    action.run(() => api.post(`/projects/${project.id}/evidence/auto`, { regenerate })).then(() => { onDone(); reload(); });
  useEffect(() => {
    if (triggered.current || !canWrite) return;
    triggered.current = true;
    go(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canWrite]);
  return { busy: action.busy, error: action.error, go };
}

function Breakdown({ finding }: { finding: Finding }) {
  const b = finding.breakdown;
  if (!b) return <p>{finding.statement}</p>;
  return (
    <div className="stack" style={{ ["--gap" as string]: "0.45rem" }}>
      <div><h3>What was tested</h3><p>{b.what_was_tested}</p></div>
      <div><h3>What we found</h3><p>{b.what_we_found}</p></div>
      <div><h3>What it means</h3><p>{b.what_it_means}</p></div>
      <div><h3>How sure we are</h3><p>{b.how_sure}</p></div>
      {finding.statistical_evidence && (
        <details>
          <summary className="small">Technical details (the numbers behind this finding)</summary>
          <p className="apa">{finding.statistical_evidence}</p>
        </details>
      )}
    </div>
  );
}

const BLANK = { title: "", statement: "", statistical_evidence: "", interpretation: "", confidence_level: "moderate", limitations_note: "", research_question_id: "", hypothesis_id: "" };

// ---------------------------------------------------------------- findings ----
export function Findings() {
  const { project, canWrite, reload } = useProject();
  const list = useApi<{ findings: Finding[] }>(`/projects/${project.id}/findings`);
  const [form, setForm] = useState(BLANK);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const { busy, error, run } = useAction();
  const auto = useAutomaticEvidence(() => list.reload());
  const set = (key: keyof typeof BLANK) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const code = (items: { id: number; code: string }[], id: number | null) => items.find((x) => x.id === id)?.code;

  const open = (f: Finding) => {
    setEditing(f.id);
    setForm({ title: f.title, statement: f.statement, statistical_evidence: f.statistical_evidence ?? "", interpretation: f.interpretation ?? "", confidence_level: f.confidence_level,
      limitations_note: f.limitations_note ?? "", research_question_id: f.research_question_id ? String(f.research_question_id) : "", hypothesis_id: f.hypothesis_id ? String(f.hypothesis_id) : "" });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const body = { ...form, statistical_evidence: form.statistical_evidence || null, interpretation: form.interpretation || null, limitations_note: form.limitations_note || null,
      research_question_id: form.research_question_id ? Number(form.research_question_id) : null, hypothesis_id: form.hypothesis_id ? Number(form.hypothesis_id) : null };
    run(() => (editing === "new" ? api.post(`/projects/${project.id}/findings`, body) : api.put(`/findings/${editing}`, body))).then((ok) => {
      if (ok) {
        setEditing(null);
        setForm(BLANK);
        list.reload();
        reload();
      }
    });
  };
  const remove = (f: Finding) => confirmAction("Delete this finding? Conclusions that cite it will lose the link.") && run(() => api.del(`/findings/${f.id}`)).then(() => { list.reload(); reload(); });

  const editor = (
    <form className="panel stack" onSubmit={submit}>
      <h2>{editing === "new" ? "Write a finding" : "Edit finding"}</h2>
      <Field label="Title"><input type="text" required minLength={3} value={form.title} onChange={set("title")} /></Field>
      <Field label="Finding" hint="State what was found, in your own words. Keep the numbers exactly as the engine reported them."><textarea required minLength={5} value={form.statement} onChange={set("statement")} /></Field>
      <Field label="Statistical evidence"><textarea value={form.statistical_evidence} onChange={set("statistical_evidence")} /></Field>
      <Field label="Interpretation"><textarea value={form.interpretation} onChange={set("interpretation")} /></Field>
      <div className="grid cols-3">
        <Field label="Research question">
          <select value={form.research_question_id} onChange={set("research_question_id")}><option value="">Not linked</option>{project.research_questions.map((q) => <option key={q.id} value={q.id}>{q.code}</option>)}</select>
        </Field>
        <Field label="Hypothesis">
          <select value={form.hypothesis_id} onChange={set("hypothesis_id")}><option value="">Not linked</option>{project.hypotheses.map((h) => <option key={h.id} value={h.id}>{h.code}</option>)}</select>
        </Field>
        <Field label="Strength of the evidence">
          <select value={form.confidence_level} onChange={set("confidence_level")}><option value="high">High</option><option value="moderate">Moderate</option><option value="low">Low</option></select>
        </Field>
      </div>
      <Field label="Limitations of this finding"><textarea value={form.limitations_note} onChange={set("limitations_note")} /></Field>
      <div className="row"><Button type="submit" variant="primary" busy={busy}>Save finding</Button><Button onClick={() => { setEditing(null); setForm(BLANK); }}>Cancel</Button></div>
    </form>
  );

  return (
    <div className="stack">
      <PageHead title="Findings" actions={canWrite && editing === null && <Button onClick={() => { setEditing("new"); setForm(BLANK); }}>Write a finding manually</Button>}>
        Each finding states, in plain language, what an analysis showed. Findings are written automatically from the completed analyses,
        and each one links back to its statistical evidence. Edit any finding in your own words.
      </PageHead>
      <StepCheckPanel step="findings" />
      <ErrorNote message={list.error ?? error ?? auto.error} />
      {list.loading && <Loading />}
      {auto.busy && <Loading label="Writing the findings in plain language" />}
      {editing !== null && editor}
      {list.data && list.data.findings.length === 0 && editing === null && (
        <Empty title="No findings yet" action={<Link className="btn primary" to="../analysis">Go to Run analysis</Link>}>
          Findings appear here once the analyses on Run analysis have finished.
        </Empty>
      )}
      {list.data?.findings.map((f, i) => (
        <article className="panel stack" key={f.id} style={{ ["--gap" as string]: "0.55rem" }}>
          <div className="row between">
            <h2 className="grow">Finding {i + 1}: {f.title}</h2>
            <Badge tone={CONFIDENCE[f.confidence_level]}>{f.confidence_level} strength of evidence</Badge>
          </div>
          <div className="trail">
            <Source kind={f.source} label={f.source === "ai" ? "Written by the AI assistant from the analysis" : "Drafted from the engine result"} />
            {f.is_edited && <Source kind="human" label="Edited by you" />}
            {code(project.research_questions, f.research_question_id) && <span>answers {code(project.research_questions, f.research_question_id)}</span>}
            {code(project.hypotheses, f.hypothesis_id) && <span>tests {code(project.hypotheses, f.hypothesis_id)}</span>}
            {f.analysis_run_id ? <Link to={`../analysis?run=${f.analysis_run_id}`}>View the supporting analysis</Link> : <span className="muted">no linked analysis</span>}
          </div>
          {f.breakdown ? <Breakdown finding={f} /> : (
            <>
              <p>{f.statement}</p>
              {f.statistical_evidence && <p className="apa">{f.statistical_evidence}</p>}
              {f.interpretation && f.interpretation !== f.statement && <p className="small"><strong>Interpretation.</strong> {f.interpretation}</p>}
            </>
          )}
          {f.limitations_note && <p className="small" style={{ color: "var(--warn)" }}><strong>Limitations.</strong> {f.limitations_note}</p>}
          <ChartIdeas ideas={f.charts ?? []} heading="Charts to draw for this finding" />
          {canWrite && <div className="row"><Button small onClick={() => open(f)}>Edit</Button><Button small variant="quiet" onClick={() => remove(f)}>Delete</Button></div>}
        </article>
      ))}
    </div>
  );
}

// ---------------------------------------- conclusions and recommendations ----
function Tabs() {
  return (
    <nav className="row" aria-label="Section">
      <NavLink className="btn small" to="../conclusions">Conclusions and limitations</NavLink>
      <NavLink className="btn small" to="../recommendations">Recommendations</NavLink>
    </nav>
  );
}

function TextItems({ kind }: { kind: "conclusions" | "recommendations" }) {
  const { project, canWrite, reload } = useProject();
  const singular = kind === "conclusions" ? "conclusion" : "recommendation";
  const list = useApi<Record<string, TextItem[]>>(`/projects/${project.id}/${kind}`);
  const findings = useApi<{ findings: Finding[] }>(`/projects/${project.id}/findings`);
  const [text, setText] = useState("");
  const [linked, setLinked] = useState<number[]>([]);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const { busy, error, run } = useAction();
  const auto = useAutomaticEvidence(() => refresh());
  const items = list.data?.[kind] ?? [];
  const all = findings.data?.findings ?? [];
  const number = (id: number) => all.findIndex((f) => f.id === id) + 1;
  const refresh = () => { list.reload(); reload(); };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const body = { text, finding_ids: linked };
    run(() => (editing === "new" ? api.post(`/projects/${project.id}/${kind}`, body) : api.put(`/${kind}/${editing}`, body))).then((ok) => {
      if (ok) {
        setEditing(null);
        setText("");
        setLinked([]);
        refresh();
      }
    });
  };
  const toggle = (id: number) => setLinked(linked.includes(id) ? linked.filter((x) => x !== id) : [...linked, id]);

  return (
    <section className="stack">
      <ErrorNote message={list.error ?? error} />
      {all.length === 0 ? (
        <Empty title="Record findings first" action={<Link className="btn primary" to="../findings">Go to Findings</Link>}>
          {kind === "conclusions" ? "Conclusions are built only from findings, so that each one rests on statistical evidence." : "Recommendations must be connected to findings, not written in general terms."}
        </Empty>
      ) : (
        canWrite && (
          <div className="panel row between">
            <p className="grow muted small" style={{ margin: 0 }}>
              Written automatically from your {all.length} finding(s). Edit any item in your own words. Regenerating rewrites the automatic items and keeps the ones you wrote.
            </p>
            <Button busy={busy || auto.busy} onClick={() => auto.go(true)}>Regenerate automatically</Button>
            <Button onClick={() => { setEditing("new"); setText(""); setLinked([]); }}>Write one</Button>
          </div>
        )
      )}
      {auto.busy && <Loading label={kind === "conclusions" ? "Writing the conclusions" : "Writing the recommendations"} />}
      {editing !== null && (
        <form className="panel stack" onSubmit={submit}>
          <h2>{editing === "new" ? `Write a ${singular}` : `Edit ${singular}`}</h2>
          <Field label="Text"><textarea required minLength={5} style={{ minHeight: "8rem" }} value={text} onChange={(e) => setText(e.target.value)} /></Field>
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend style={{ fontWeight: 500 }}>Findings this {singular} is based on</legend>
            {all.map((f, i) => (
              <label className="check" key={f.id}><input type="checkbox" checked={linked.includes(f.id)} onChange={() => toggle(f.id)} /><span>Finding {i + 1}: {f.title}</span></label>
            ))}
          </fieldset>
          {linked.length === 0 && <Alert kind="warn">A {singular} with no finding behind it has no evidence trail. Link at least one finding.</Alert>}
          <div className="row"><Button type="submit" variant="primary" busy={busy}>Save {singular}</Button><Button onClick={() => setEditing(null)}>Cancel</Button></div>
        </form>
      )}
      {items.map((item, i) => (
        <article className="panel stack" key={item.id} style={{ ["--gap" as string]: "0.5rem" }}>
          <div className="trail">
            <strong>{singular.charAt(0).toUpperCase() + singular.slice(1)} {i + 1}</strong>
            <Source kind={item.source} label={item.source === "ai" ? "Written by the AI assistant from your findings" : item.source === "engine" ? "Automatic draft from findings" : undefined} />
            {item.finding_ids.length > 0
              ? <span>based on {item.finding_ids.map((id) => `Finding ${number(id)}`).join(", ")}</span>
              : <Badge tone="warn">no finding linked</Badge>}
          </div>
          <div className="plain-text">{item.text}</div>
          {canWrite && (
            <div className="row">
              <Button small onClick={() => { setEditing(item.id); setText(item.text); setLinked(item.finding_ids); }}>Edit</Button>
              <Button small variant="quiet" onClick={() => confirmAction(`Delete this ${singular}?`) && run(() => api.del(`/${kind}/${item.id}`)).then(refresh)}>Delete</Button>
            </div>
          )}
        </article>
      ))}
    </section>
  );
}

const STATUS_LABEL: Record<string, string> = { active: "Applies", acknowledged: "Acknowledged and addressed", not_applicable: "Does not apply" };

function Limitations() {
  const { project, canWrite } = useProject();
  const list = useApi<{ limitations: Limitation[] }>(`/projects/${project.id}/limitations`);
  const [text, setText] = useState("");
  const { busy, error, run } = useAction();
  const detect = () => run(() => api.post<{ limitations: Limitation[] }>(`/projects/${project.id}/limitations/detect`)).then((r) => r && list.setData(r));
  const add = (event: FormEvent) => {
    event.preventDefault();
    run(() => api.post(`/projects/${project.id}/limitations`, { description: text })).then((ok) => { if (ok) { setText(""); list.reload(); } });
  };
  const setStatus = (item: Limitation, status: string) => {
    let note: string | null = null;
    if (status !== "active") {
      note = window.prompt(status === "acknowledged" ? "How is this limitation addressed or discussed in your work?" : "Why does this limitation not apply to your study?", item.status_note ?? "");
      if (!note) return;
    }
    run(() => api.put(`/limitations/${item.id}/status`, { status, status_note: note })).then(list.reload);
  };
  return (
    <section className="panel stack">
      <div className="row between">
        <div className="grow">
          <h2>Limitations</h2>
          <p className="muted small" style={{ margin: 0 }}>Detected from your study design, data quality and assumption checks. An automatically detected limitation cannot be deleted: you can only record, with a reason, that it is addressed or does not apply. Both appear in the report.</p>
        </div>
        {canWrite && <Button busy={busy} onClick={detect}>Detect limitations</Button>}
      </div>
      <ErrorNote message={list.error ?? error} />
      {list.data && list.data.limitations.length === 0 && <p className="muted">None recorded yet.</p>}
      <ul className="checks">
        {list.data?.limitations.map((item) => (
          <li key={item.id}>
            <div><Source kind={item.source} label={item.source === "auto" ? "Detected" : "Yours"} /></div>
            <div>
              {item.description}
              <div className="small muted">{STATUS_LABEL[item.status]}{item.status_note ? `: ${item.status_note}` : ""}</div>
              {canWrite && (
                <div className="row">
                  <select aria-label="Status" value={item.status} style={{ width: "auto" }} onChange={(e) => setStatus(item, e.target.value)}>
                    {Object.entries(STATUS_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                  {item.source === "manual" && <Button small variant="quiet" onClick={() => run(() => api.del(`/limitations/${item.id}`)).then(list.reload)}>Delete</Button>}
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
      {canWrite && (
        <form className="row" onSubmit={add} style={{ alignItems: "flex-end" }}>
          <label className="grow field"><span className="label">Add a limitation of your own</span><input type="text" required minLength={5} value={text} onChange={(e) => setText(e.target.value)} /></label>
          <Button type="submit" busy={busy}>Add limitation</Button>
        </form>
      )}
    </section>
  );
}

export function Conclusions() {
  return (
    <div className="stack">
      <PageHead title="Conclusions">Each conclusion should follow from one or more findings, which in turn rest on a statistical result and a dataset version.</PageHead>
      <StepCheckPanel step="conclusions" />
      <Tabs />
      <TextItems kind="conclusions" />
      <Limitations />
    </div>
  );
}

export function Recommendations() {
  return (
    <div className="stack">
      <PageHead title="Recommendations">Say who should do what, based on which finding. The automatic drafts are deliberately cautious and need your knowledge of the context.</PageHead>
      <Tabs />
      <TextItems kind="recommendations" />
    </div>
  );
}
