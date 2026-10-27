import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { WhatsAppChatLink } from "../components/ClientWhatsApp";
import { Alert, Badge, Button, Empty, ErrorNote, Field, Loading, Meter, PageHead } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { Progress, Project, ProjectDetail } from "../types";
import { fmtDate, formatMoney, LEVEL_LABELS } from "../utils/format";
import { isValidWhatsApp, whatsAppProblem } from "../utils/whatsapp";

export function ProjectList() {
  const { data, loading, error } = useApi<{ projects: (Project & { progress: Progress })[] }>("/projects");
  return (
    <main className="page stack">
      <PageHead title="My projects" actions={<Link className="btn primary" to="/projects/new">New project</Link>} />
      <ErrorNote message={error} />
      {loading && <Loading />}
      {data && data.projects.length === 0 && (
        <Empty title="No projects yet" action={<Link className="btn primary" to="/projects/new">Create a project</Link>}>
          Create a project to define your research questions and upload data.
        </Empty>
      )}
      <div className="grid cols-2">
        {data?.projects.map((p) => (
          <article className="panel stack" key={p.id} style={{ ["--gap" as string]: "0.6rem" }}>
            <div className="row between">
              <h2 className="grow"><Link to={`/projects/${p.id}`}>{p.title}</Link></h2>
              <Badge tone={p.status === "completed" ? "ok" : p.status === "active" ? "info" : ""}>{p.status}</Badge>
            </div>
            <div className="small muted">
              {LEVEL_LABELS[p.academic_level]}{p.research_field ? `, ${p.research_field}` : ""}. Updated {fmtDate(p.updated_at, false)}.
              {p.project_type === "client" && p.client_name ? ` Client: ${p.client_name}.` : ""}
              {p.approximate_cost ? ` Approximate cost: ${formatMoney(p.approximate_cost, p.cost_currency ?? "USD")}.` : ""}
              {p.my_role && p.my_role !== "owner" ? ` You are ${p.my_role} (owner: ${p.owner_name}).` : ""}
            </div>
            <Meter percent={p.progress.percent} label={`Progress of ${p.title}`} />
          </article>
        ))}
      </div>
    </main>
  );
}

const CHOICE_STYLE = { color: "inherit", textDecoration: "none" };

/** First step of a new project: is it the researcher's own, or a client's? */
export function ProjectTypeChoice() {
  return (
    <main className="page medium">
      <PageHead title="What kind of project is this?">
        A personal project is your own research. For a client's project you first enter the client's details, and the report is then
        addressed to that client.
      </PageHead>
      <div className="grid cols-2">
        <Link className="panel stack" style={CHOICE_STYLE} to="/projects/new/details?type=personal">
          <h2>Personal project</h2>
          <p className="muted">Your own research, thesis or study. The report names you as the researcher.</p>
        </Link>
        <Link className="panel stack" style={CHOICE_STYLE} to="/projects/new/client">
          <h2>Client's project</h2>
          <p className="muted">
            Work for a client. The report names the client, and you can chat with them on WhatsApp and send them the report from here.
          </p>
        </Link>
      </div>
    </main>
  );
}

interface ClientForm {
  name: string;
  email: string;
  whatsapp: string;
}
const NO_CLIENT: ClientForm = { name: "", email: "", whatsapp: "" };

/** Client details for a client's project. The project form follows on the next page. */
export function ClientInfoForm() {
  const navigate = useNavigate();
  const [client, setClient] = useState<ClientForm>(NO_CLIENT);
  const [problem, setProblem] = useState<string | null>(null);
  const setField = (key: keyof ClientForm) => (e: { target: { value: string } }) => {
    setProblem(null);
    setClient({ ...client, [key]: e.target.value });
  };

  // checked here, so a wrong number or e-mail is corrected on this page rather than after the whole project form is filled in
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const nameProblem = client.name.trim().length < 2 ? "Enter the client's name." : null;
    const emailProblem = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(client.email.trim()) ? null : "Enter a valid e-mail address for the client.";
    const whatsappProblem = whatsAppProblem(client.whatsapp);
    const first = nameProblem ?? emailProblem ?? whatsappProblem;
    if (first) {
      setProblem(first);
      return;
    }
    navigate("/projects/new/details?type=client", { state: { client } });
  };

  return (
    <main className="page narrow">
      <PageHead title="The client's details">
        The report will name this client. You can message them on WhatsApp from the project, and send them the finished report there.
      </PageHead>
      <form className="panel stack" onSubmit={submit} noValidate>
        <Field label="Client's name" hint="This name is printed on the report.">
          <input type="text" required minLength={2} maxLength={200} value={client.name} onChange={setField("name")} />
        </Field>
        <Field label="Client's e-mail address">
          <input type="email" required maxLength={254} value={client.email} onChange={setField("email")} />
        </Field>
        <Field label="Client's WhatsApp number" hint="Country code first, without the + sign, then the number. For example 237 677 000 000.">
          <input type="tel" required value={client.whatsapp} onChange={setField("whatsapp")} aria-invalid={!!problem} />
        </Field>
        {problem && <Alert kind="error">{problem}</Alert>}
        {isValidWhatsApp(client.whatsapp) && (
          <div className="row">
            <span className="small muted">Check the number:</span>
            <WhatsAppChatLink name={client.name || "the client"} number={client.whatsapp} label="Open the WhatsApp chat" />
          </div>
        )}
        <div className="row">
          <Button type="submit" variant="primary">Continue</Button>
          <Link className="btn" to="/projects/new">Back</Link>
        </div>
      </form>
    </main>
  );
}

const EMPTY = {
  title: "", academic_level: "undergraduate", research_field: "", institution: "", department: "", research_problem: "", general_objective: "",
  objectives: "", study_population: "", sample_size: "", sampling_technique: "", research_methodology: "Quantitative", study_design: "",
  data_collection_method: "", status: "draft",
};
type FormState = typeof EMPTY;

const DESIGNS = ["Cross-sectional survey", "Longitudinal study", "Experimental (randomised)", "Quasi-experimental", "Correlational", "Case-control",
  "Cohort study", "Secondary data analysis"];
const SAMPLING = ["Simple random sampling", "Stratified random sampling", "Cluster sampling", "Systematic sampling", "Convenience sampling",
  "Purposive sampling", "Snowball sampling", "Census (whole population)"];

function toForm(project: ProjectDetail): FormState {
  const text = (v: unknown) => (v === null || v === undefined ? "" : String(v));
  return {
    title: project.title, academic_level: project.academic_level, research_field: text(project.research_field), institution: text(project.institution),
    department: text(project.department), research_problem: text(project.research_problem), general_objective: text(project.general_objective),
    objectives: project.objectives.map((o) => o.text).join("\n"), study_population: text(project.study_population),
    sample_size: text(project.sample_size), sampling_technique: text(project.sampling_technique),
    research_methodology: text(project.research_methodology), study_design: text(project.study_design),
    data_collection_method: text(project.data_collection_method), status: project.status,
  };
}

function toClient(project: ProjectDetail): ClientForm {
  return { name: project.client_name ?? "", email: project.client_email ?? "", whatsapp: project.client_whatsapp ?? "" };
}

/**
 * Create a project, or edit one when rendered at /projects/:projectId/edit.
 * A new project arrives here as ?type=personal, or as ?type=client with the client's details handed over from the client page.
 */
export function ProjectForm() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const existing = useApi<ProjectDetail>(projectId ? `/projects/${projectId}` : null);
  const handedOver = (location.state as { client?: ClientForm } | null)?.client;
  const type = projectId ? existing.data?.project_type : params.get("type");
  const [form, setForm] = useState<FormState>(EMPTY);
  const [client, setClient] = useState<ClientForm>(handedOver ?? NO_CLIENT);
  const { busy, error, run } = useAction();
  useEffect(() => {
    if (existing.data) {
      setForm(toForm(existing.data));
      setClient(toClient(existing.data));
    }
  }, [existing.data]);
  // a problem with the form is shown at the top of the page, so bring the reader there
  useEffect(() => {
    if (error || existing.error) window.scrollTo({ top: 0, behavior: "smooth" });
  }, [error, existing.error]);
  const set = (key: keyof FormState) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const setClientField = (key: keyof ClientForm) => (e: { target: { value: string } }) => setClient({ ...client, [key]: e.target.value });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const body: Record<string, unknown> = {};
    (Object.keys(form) as (keyof FormState)[]).forEach((key) => {
      if (key === "objectives") body.objectives = form.objectives.split("\n").map((s) => s.trim()).filter(Boolean);
      else if (key === "sample_size") body.sample_size = form.sample_size ? Math.round(Number(form.sample_size)) : null;
      else body[key] = form[key] === "" ? null : form[key];
    });
    if (!projectId) body.project_type = type;
    if (type === "client") Object.assign(body, { client_name: client.name, client_email: client.email, client_whatsapp: client.whatsapp });
    run(async () => {
      const saved = projectId ? await api.put<Project>(`/projects/${projectId}`, body) : await api.post<Project>("/projects", body);
      navigate(`/projects/${saved.id}`);
    });
  };

  if (!projectId && type !== "personal" && type !== "client") return <Navigate to="/projects/new" replace />;
  if (!projectId && type === "client" && !handedOver) return <Navigate to="/projects/new/client" replace />;
  if (projectId && existing.loading) return <main className="page"><Loading /></main>;
  return (
    <main className="page medium">
      <PageHead title={projectId ? "Edit project details" : type === "client" ? "Create a client's project" : "Create a research project"}>
        Only the title and level are required now. The rest can be filled in later, and it is used in your report's methodology section
        and to detect limitations of the study.
      </PageHead>
      <form className="stack" onSubmit={submit}>
        <ErrorNote message={existing.error ?? error} />
        {type === "client" && (
          <section className="panel stack">
            <h2>The client</h2>
            <p className="small muted">The report is addressed to this client. You can chat with them on WhatsApp from the project and send them the report.</p>
            <div className="grid cols-2">
              <Field label="Client's name">
                <input type="text" required minLength={2} maxLength={200} value={client.name} onChange={setClientField("name")} />
              </Field>
              <Field label="Client's e-mail address">
                <input type="email" required maxLength={254} value={client.email} onChange={setClientField("email")} />
              </Field>
            </div>
            <Field label="Client's WhatsApp number" hint="Country code first, without the + sign. For example 237 677 000 000.">
              <div className="row">
                <input className="grow" type="tel" required value={client.whatsapp} onChange={setClientField("whatsapp")} />
                {isValidWhatsApp(client.whatsapp) && <WhatsAppChatLink name={client.name || "the client"} number={client.whatsapp} />}
              </div>
            </Field>
          </section>
        )}
        <section className="panel stack">
          <h2>The study</h2>
          <Field label="Project title">
            <input type="text" required minLength={3} maxLength={300} value={form.title} onChange={set("title")} />
          </Field>
          <div className="grid cols-2">
            <Field label="Academic level" hint="Sets how much depth the method guidance goes into. It never forces an advanced method.">
              <select value={form.academic_level} onChange={set("academic_level")}>
                <option value="undergraduate">Undergraduate / Bachelor's</option>
                <option value="masters">Master's</option>
                <option value="phd">PhD / Doctoral</option>
              </select>
            </Field>
            <Field label="Research field or discipline">
              <input type="text" maxLength={150} placeholder="e.g. Education, Public Health, Economics" value={form.research_field} onChange={set("research_field")} />
            </Field>
            <Field label="Institution"><input type="text" maxLength={200} value={form.institution} onChange={set("institution")} /></Field>
            <Field label="Department"><input type="text" maxLength={200} value={form.department} onChange={set("department")} /></Field>
          </div>
          <Field label="Research problem"><textarea maxLength={10000} value={form.research_problem} onChange={set("research_problem")} /></Field>
          <Field label="General objective"><textarea maxLength={5000} value={form.general_objective} onChange={set("general_objective")} /></Field>
          <Field label="Specific objectives" hint="One per line.">
            <textarea value={form.objectives} onChange={set("objectives")} />
          </Field>
        </section>
        <section className="panel stack">
          <h2>Methodology</h2>
          <div className="grid cols-2">
            <Field label="Research methodology">
              <select value={form.research_methodology} onChange={set("research_methodology")}>
                <option>Quantitative</option>
                <option>Mixed methods</option>
                <option>Qualitative</option>
              </select>
            </Field>
            <Field label="Study design">
              <input type="text" maxLength={150} list="designs" value={form.study_design} onChange={set("study_design")} />
              <datalist id="designs">{DESIGNS.map((d) => <option key={d} value={d} />)}</datalist>
            </Field>
            <Field label="Sampling technique">
              <input type="text" maxLength={150} list="sampling" value={form.sampling_technique} onChange={set("sampling_technique")} />
              <datalist id="sampling">{SAMPLING.map((d) => <option key={d} value={d} />)}</datalist>
            </Field>
            <Field label="Planned sample size">
              <input type="number" min={1} max={100000000} step={1} value={form.sample_size} onChange={set("sample_size")} />
            </Field>
          </div>
          <Field label="Study population"><textarea maxLength={5000} value={form.study_population} onChange={set("study_population")} /></Field>
          <Field label="Data collection method">
            <input type="text" maxLength={255} placeholder="e.g. Self-administered questionnaire" value={form.data_collection_method} onChange={set("data_collection_method")} />
          </Field>
          {form.research_methodology === "Qualitative" && (
            <p className="small muted">
              This version analyses quantitative data. Interview transcripts, coding and thematic analysis are not supported yet, and
              statistical tests are not a substitute for them.
            </p>
          )}
          {projectId && (
            <Field label="Project status">
              <select value={form.status} onChange={set("status")}>
                <option value="draft">Draft</option>
                <option value="active">Active</option>
                <option value="completed">Completed</option>
                <option value="archived">Archived</option>
              </select>
            </Field>
          )}
        </section>
        <div className="row">
          <Button type="submit" variant="primary" busy={busy}>{projectId ? "Save changes" : "Create project"}</Button>
          <Link className="btn" to={projectId ? `/projects/${projectId}` : "/projects"}>Cancel</Link>
        </div>
      </form>
    </main>
  );
}
