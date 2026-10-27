import { useState } from "react";
import { ProjectGaps } from "../components/AssistantDrafts";
import { WhatsAppChatLink } from "../components/ClientWhatsApp";
import { StepCheckPanel } from "../components/StepCheck";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Badge, Button, confirmAction, ErrorNote, Field, PageHead } from "../components/ui";
import { useAction } from "../hooks/useApi";
import { useProject } from "../layouts/ProjectLayout";
import { api } from "../services/api";
import { useAuth } from "../services/auth";
import { fmtDate, formatMoney, LEVEL_LABELS } from "../utils/format";
import { formatWhatsApp } from "../utils/whatsapp";

const NEXT: Record<string, [string, string]> = {
  research_questions: ["research-questions", "Define your research questions"],
  hypotheses: ["hypotheses", "Define your hypotheses"],
  dataset: ["upload", "Upload your dataset"],
  quality: ["quality", "Check data quality"],
  cleaning: ["cleaning", "Clean the data"],
  exploration: ["explore", "Explore the data"],
  analysis: ["analysis", "Run an analysis"],
  findings: ["findings", "Record your findings"],
  conclusions: ["conclusions", "Draft conclusions"],
  report: ["report", "Generate the report"],
};

export default function ProjectOverview() {
  const { project, reload, canWrite } = useProject();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("supervisor");
  const { busy, error, run } = useAction();
  const isOwner = user?.id === project.owner_id || !!user?.roles.includes("admin");
  const next = project.progress.next_step ? NEXT[project.progress.next_step] : null;

  const addMember = (event: FormEvent) => {
    event.preventDefault();
    run(() => api.post(`/projects/${project.id}/members`, { email, member_role: role })).then((ok) => {
      if (ok) {
        setEmail("");
        reload();
      }
    });
  };
  const remove = () => {
    if (!confirmAction(`Delete "${project.title}" with all its data, analyses and reports? This cannot be undone.`)) return;
    run(() => api.del(`/projects/${project.id}`)).then((ok) => ok && navigate("/projects"));
  };
  const facts: [string, string | number | null][] = [
    ["Academic level", LEVEL_LABELS[project.academic_level]], ["Research field", project.research_field], ["Institution", project.institution],
    ["Department", project.department], ["Methodology", project.research_methodology], ["Study design", project.study_design],
    ["Sampling technique", project.sampling_technique], ["Planned sample size", project.sample_size],
    ["Data collection", project.data_collection_method], ["Study population", project.study_population],
  ];
  return (
    <div className="stack">
      <PageHead title={project.title} actions={canWrite && <Link className="btn" to={`/projects/${project.id}/edit`}>Edit details</Link>}>
        Status: {project.status}. Created {fmtDate(project.created_at, false)}, last updated {fmtDate(project.updated_at)}.
      </PageHead>
      {canWrite && <ProjectGaps projectId={project.id} />}
      <StepCheckPanel step="project" />
      <ErrorNote message={error} />

      {next ? (
        <section className="panel row between">
          <div className="grow">
            <h2>Next step: {next[1]}</h2>
            <p className="muted" style={{ margin: 0 }}>{project.progress.percent}% of the workflow is complete. Steps can be done in any order, but this is the usual one.</p>
          </div>
          <Link className="btn primary" to={next[0]}>{next[1]}</Link>
        </section>
      ) : (
        <section className="panel"><h2>All workflow steps are complete</h2><p className="muted">You can still add analyses, refine findings and regenerate the report.</p></section>
      )}

      <section className="panel">
        <h2>Research design</h2>
        {project.research_problem && <p><strong>Research problem.</strong> {project.research_problem}</p>}
        {project.general_objective && <p><strong>General objective.</strong> {project.general_objective}</p>}
        {project.objectives.length > 0 && (
          <>
            <strong>Specific objectives</strong>
            <ol>{project.objectives.map((o) => <li key={o.id}>{o.text}</li>)}</ol>
          </>
        )}
        <dl className="grid cols-3" style={{ margin: "0.5rem 0 0" }}>
          {facts.filter(([, value]) => value !== null && value !== "").map(([label, value]) => (
            <div key={label}>
              <dt className="small muted">{label}</dt>
              <dd style={{ margin: 0 }}>{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="panel row between">
        <div className="grow">
          <h2>Approximate cost</h2>
          <p className="muted" style={{ margin: 0 }}>
            {project.approximate_cost ? formatMoney(project.approximate_cost, project.cost_currency ?? "USD") : "No costs entered yet."}
          </p>
        </div>
        <Link className="btn" to="costs">Project costs</Link>
      </section>

      {project.project_type === "client" && project.client_name && project.client_whatsapp && (
        <section className="panel stack">
          <h2>Client</h2>
          <dl className="grid cols-3" style={{ margin: 0 }}>
            <div><dt className="small muted">Name</dt><dd style={{ margin: 0 }}>{project.client_name}</dd></div>
            <div><dt className="small muted">E-mail</dt><dd style={{ margin: 0 }}><a href={`mailto:${project.client_email}`}>{project.client_email}</a></dd></div>
            <div><dt className="small muted">WhatsApp</dt><dd style={{ margin: 0 }}>{formatWhatsApp(project.client_whatsapp)}</dd></div>
          </dl>
          <div className="row">
            <WhatsAppChatLink name={project.client_name} number={project.client_whatsapp} />
            <Link className="btn" to="report">Report and sending</Link>
          </div>
        </section>
      )}

      <div className="grid cols-3">
        <div className="panel"><div className="small muted">Research questions</div><div style={{ fontSize: "1.5rem", fontFamily: "var(--serif)" }}>{project.research_questions.length}</div></div>
        <div className="panel"><div className="small muted">Hypotheses</div><div style={{ fontSize: "1.5rem", fontFamily: "var(--serif)" }}>{project.hypotheses.length}</div></div>
        <div className="panel"><div className="small muted">Datasets</div><div style={{ fontSize: "1.5rem", fontFamily: "var(--serif)" }}>{project.datasets.length}</div></div>
      </div>

      <section className="panel stack">
        <h2>Supervisor and collaborators</h2>
        <p className="muted small">Only people listed here can open this project. A supervisor can read everything, comment and approve stages; a collaborator can also edit; a viewer can only read.</p>
        {project.members.length === 0 ? <p className="muted">Nobody else has access.</p> : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {project.members.map((m) => (
              <li key={m.id} className="row between" style={{ padding: "0.35rem 0" }}>
                <span>{m.full_name} <span className="muted">({m.email})</span> <Badge>{m.member_role}</Badge></span>
                {isOwner && <Button small variant="quiet" onClick={() => run(() => api.del(`/projects/${project.id}/members/${m.id}`)).then(reload)}>Remove access</Button>}
              </li>
            ))}
          </ul>
        )}
        {isOwner && (
          <form className="row" onSubmit={addMember} style={{ alignItems: "flex-end" }}>
            <div className="grow"><Field label="E-mail address of a registered user"><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field></div>
            <Field label="Role">
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="supervisor">Supervisor</option>
                <option value="collaborator">Collaborator</option>
                <option value="viewer">Viewer</option>
              </select>
            </Field>
            <Button type="submit" busy={busy}>Give access</Button>
          </form>
        )}
      </section>

      {isOwner && (
        <section className="panel row between">
          <div className="grow"><h3>Delete this project</h3><p className="muted small" style={{ margin: 0 }}>Removes the project with its datasets, analyses and reports.</p></div>
          <Button variant="danger" onClick={remove}>Delete project</Button>
        </section>
      )}
    </div>
  );
}
