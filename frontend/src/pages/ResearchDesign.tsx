import { useState } from "react";
import { HypothesisDrafts } from "../components/HypothesisDrafts";
import { StepCheckPanel } from "../components/StepCheck";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, confirmAction, Empty, ErrorNote, Field, Loading, PageHead } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { useProject } from "../layouts/ProjectLayout";
import { api } from "../services/api";
import type { Finding, Hypothesis, ResearchQuestion, Variable } from "../types";
import { fmtP, variablesText } from "../utils/format";

interface Evaluated extends ResearchQuestion {
  status: "not_analysed" | "analysed" | "answered";
  status_text: string;
  analyses: { analysis_run_id: number; method_name: string; variables: Record<string, unknown>; apa: string | null; p_value: number | null; significant: boolean | null; dataset_version: number | null }[];
  hypotheses: Hypothesis[];
  findings: Finding[];
}

const ROLES = ["dependent", "independent", "control", "moderator", "mediator", "other"];

export function ResearchQuestions() {
  const { project, reload, canWrite, dataset } = useProject();
  const list = useApi<{ research_questions: Evaluated[] }>(`/projects/${project.id}/research-questions`);
  const dictionary = useApi<{ variables: Variable[] }>(dataset ? `/datasets/${dataset.id}/dictionary` : null);
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [links, setLinks] = useState<Record<number, string>>({});
  const { busy, error, run } = useAction();
  const refresh = () => {
    list.reload();
    reload();
  };

  const add = (event: FormEvent) => {
    event.preventDefault();
    run(() => api.post(`/projects/${project.id}/research-questions`, { text })).then((ok) => {
      if (ok) {
        setText("");
        refresh();
      }
    });
  };
  const startEdit = (q: Evaluated) => {
    setEditing(q.id);
    setEditText(q.text);
    setLinks(Object.fromEntries(q.variables.map((v) => [v.variable_id, v.role])));
  };
  const save = (q: Evaluated) =>
    run(() => api.put(`/research-questions/${q.id}`, {
      text: editText,
      variables: Object.entries(links).filter(([, role]) => role).map(([id, role]) => ({ variable_id: Number(id), role })),
    })).then((ok) => {
      if (ok) {
        setEditing(null);
        refresh();
      }
    });
  const remove = (q: Evaluated) => {
    if (confirmAction(`Delete ${q.code}? Analyses and findings stay but lose their link to it.`)) run(() => api.del(`/research-questions/${q.id}`)).then(refresh);
  };
  const tone = { not_analysed: "", analysed: "warn", answered: "ok" } as const;
  const label = { not_analysed: "Not analysed yet", analysed: "Analysed, no finding recorded", answered: "Evidence recorded" };

  return (
    <div className="stack">
      <PageHead title="Research questions">
        Each analysis you run can be linked to a question, so you can always see which questions have evidence and where it came from.
      </PageHead>
      <StepCheckPanel step="research_questions" />
      <ErrorNote message={list.error ?? error} />
      {list.loading && <Loading />}
      {list.data && list.data.research_questions.length === 0 && (
        <Empty title="No research questions yet">Write the questions your study sets out to answer, one at a time. Example: "Is there a relationship between study hours and GPA?"</Empty>
      )}
      {list.data?.research_questions.map((q) => (
        <article className="panel stack" key={q.id} style={{ ["--gap" as string]: "0.7rem" }}>
          <div className="row between">
            <h2 className="grow">{q.code}</h2>
            <Badge tone={tone[q.status]}>{label[q.status]}</Badge>
          </div>
          {editing === q.id ? (
            <div className="stack">
              <Field label="Question"><textarea value={editText} onChange={(e) => setEditText(e.target.value)} /></Field>
              {dictionary.data && dictionary.data.variables.length > 0 ? (
                <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
                  <legend style={{ fontWeight: 500 }}>Variables that answer this question</legend>
                  <p className="small muted">Mark the outcome as dependent and the explanatory variables as independent. The method recommender uses these roles.</p>
                  <div className="grid cols-3">
                    {dictionary.data.variables.filter((v) => v.data_type !== "identifier" && v.data_type !== "text").map((v) => (
                      <label key={v.id} className="small">
                        {v.name}
                        <select value={links[v.id] ?? ""} onChange={(e) => setLinks({ ...links, [v.id]: e.target.value })}>
                          <option value="">not used</option>
                          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                        </select>
                      </label>
                    ))}
                  </div>
                </fieldset>
              ) : <p className="small muted">Upload a dataset to link variables to this question.</p>}
              <div className="row">
                <Button variant="primary" busy={busy} onClick={() => save(q)}>Save question</Button>
                <Button onClick={() => setEditing(null)}>Cancel</Button>
              </div>
            </div>
          ) : (
            <>
              <p style={{ fontSize: "1.05rem" }}>{q.text}</p>
              {q.variables.length > 0 && <p className="small"><strong>Variables:</strong> {q.variables.map((v) => `${v.name} (${v.role})`).join(", ")}</p>}
              {q.hypotheses.length > 0 && <p className="small"><strong>Hypotheses:</strong> {q.hypotheses.map((h) => h.code).join(", ")}</p>}
              {q.analyses.length > 0 && (
                <div>
                  <strong className="small">Analyses</strong>
                  <ul className="small" style={{ margin: "0.2rem 0 0", paddingLeft: "1.1rem" }}>
                    {q.analyses.map((a, i) => (
                      <li key={i}>
                        <Link to={`../analysis?run=${a.analysis_run_id}`}>{a.method_name}</Link> on {variablesText(a.variables)} (dataset version {a.dataset_version}):{" "}
                        {a.apa ?? `p = ${fmtP(a.p_value)}`}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {q.findings.map((f) => <p key={f.id} className="small"><strong>Finding:</strong> {f.statement}</p>)}
              <p className="small muted">{q.status_text}</p>
              {canWrite && (
                <div className="row">
                  <Link className="btn small" to={`../analysis?rq=${q.id}`}>Analyse this question</Link>
                  <Button small onClick={() => startEdit(q)}>Edit and link variables</Button>
                  <Button small variant="quiet" onClick={() => remove(q)}>Delete</Button>
                </div>
              )}
            </>
          )}
        </article>
      ))}
      {canWrite && (
        <form className="panel stack" onSubmit={add}>
          <h2>Add a research question</h2>
          <Field label="Question" hint="It is numbered automatically (RQ1, RQ2, ...).">
            <textarea required minLength={5} value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
          <div><Button type="submit" variant="primary" busy={busy}>Add question</Button></div>
        </form>
      )}
    </div>
  );
}

const DECISION: Record<string, [string, "ok" | "warn" | ""]> = {
  pending: ["Not tested yet", ""],
  reject_null: ["H0 rejected", "ok"],
  fail_to_reject_null: ["H0 not rejected", "warn"],
};
const BLANK = { null_text: "", alternative_text: "", research_question_id: "", direction: "non_directional", alpha: "0.05" };

export function Hypotheses() {
  const { project, reload, canWrite } = useProject();
  const [form, setForm] = useState(BLANK);
  const [editing, setEditing] = useState<number | null>(null);
  const { busy, error, run } = useAction();
  const set = (key: keyof typeof BLANK) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const questionCode = (id: number | null) => project.research_questions.find((q) => q.id === id)?.code;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const body = { null_text: form.null_text, alternative_text: form.alternative_text, direction: form.direction, alpha: Number(form.alpha),
      research_question_id: form.research_question_id ? Number(form.research_question_id) : null };
    run(() => (editing ? api.put(`/hypotheses/${editing}`, body) : api.post(`/projects/${project.id}/hypotheses`, body))).then((ok) => {
      if (ok) {
        setForm(BLANK);
        setEditing(null);
        reload();
      }
    });
  };
  const edit = (h: Hypothesis) => {
    setEditing(h.id);
    setForm({ null_text: h.null_text, alternative_text: h.alternative_text, research_question_id: h.research_question_id ? String(h.research_question_id) : "",
      direction: h.direction, alpha: String(h.alpha) });
  };

  return (
    <div className="stack">
      <PageHead title="Hypotheses">
        State the null hypothesis (H0, no effect) and the alternative (H1). When you link a statistical test to a hypothesis, the decision is recorded here automatically.
      </PageHead>
      <StepCheckPanel step="hypotheses" />
      {canWrite && (
        <HypothesisDrafts
          projectId={project.id}
          questions={project.research_questions.filter((q) => !project.hypotheses.some((h) => h.research_question_id === q.id))}
          onUse={(draft) => setForm({ ...form, ...draft })}
        />
      )}
      <ErrorNote message={error} />
      {project.hypotheses.length === 0 && <Empty title="No hypotheses yet">Not every study needs hypotheses: descriptive and exploratory studies often have only research questions.</Empty>}
      {project.hypotheses.map((h) => (
        <article className="panel stack" key={h.id} style={{ ["--gap" as string]: "0.5rem" }}>
          <div className="row between">
            <h2 className="grow">{h.code}{questionCode(h.research_question_id) ? <span className="muted small"> for {questionCode(h.research_question_id)}</span> : null}</h2>
            <Badge tone={DECISION[h.decision][1]}>{DECISION[h.decision][0]}</Badge>
          </div>
          <p><strong>H0:</strong> {h.null_text}</p>
          <p><strong>H1:</strong> {h.alternative_text}</p>
          <p className="small muted">
            {h.direction === "non_directional" ? "Non-directional (two-sided test)" : `Directional (${h.direction}); choose the matching one-sided alternative when you run the test`}. Significance level alpha = {h.alpha}.
            {h.decision === "fail_to_reject_null" ? " Not rejecting H0 does not prove H0 is true." : ""}
          </p>
          {canWrite && (
            <div className="row">
              <Link className="btn small" to={`../analysis?hypothesis=${h.id}${h.research_question_id ? `&rq=${h.research_question_id}` : ""}`}>Test this hypothesis</Link>
              <Button small onClick={() => edit(h)}>Edit</Button>
              <Button small variant="quiet" onClick={() => confirmAction(`Delete ${h.code}?`) && run(() => api.del(`/hypotheses/${h.id}`)).then(reload)}>Delete</Button>
            </div>
          )}
        </article>
      ))}
      {canWrite && (
        <form className="panel stack" onSubmit={submit}>
          <h2>{editing ? "Edit hypothesis" : "Add a hypothesis"}</h2>
          <Field label="Null hypothesis (H0)"><textarea required minLength={5} placeholder="There is no significant relationship between ..." value={form.null_text} onChange={set("null_text")} /></Field>
          <Field label="Alternative hypothesis (H1)"><textarea required minLength={5} placeholder="There is a significant relationship between ..." value={form.alternative_text} onChange={set("alternative_text")} /></Field>
          <div className="grid cols-3">
            <Field label="Research question">
              <select value={form.research_question_id} onChange={set("research_question_id")}>
                <option value="">Not linked</option>
                {project.research_questions.map((q) => <option key={q.id} value={q.id}>{q.code}: {q.text.slice(0, 60)}</option>)}
              </select>
            </Field>
            <Field label="Direction">
              <select value={form.direction} onChange={set("direction")}>
                <option value="non_directional">Non-directional (there is a difference or relationship)</option>
                <option value="greater">Directional: greater / positive</option>
                <option value="less">Directional: less / negative</option>
              </select>
            </Field>
            <Field label="Significance level (alpha)" hint="Decide this before looking at the results.">
              <select value={form.alpha} onChange={set("alpha")}>
                <option value="0.05">0.05</option>
                <option value="0.01">0.01</option>
                <option value="0.1">0.10</option>
              </select>
            </Field>
          </div>
          <div className="row">
            <Button type="submit" variant="primary" busy={busy}>{editing ? "Save hypothesis" : "Add hypothesis"}</Button>
            {editing && <Button onClick={() => { setEditing(null); setForm(BLANK); }}>Cancel</Button>}
          </div>
        </form>
      )}
    </div>
  );
}
