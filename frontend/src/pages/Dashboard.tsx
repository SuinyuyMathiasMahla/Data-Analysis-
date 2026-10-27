import { Link } from "react-router-dom";

import { Badge, Empty, ErrorNote, Icon, Loading, Meter, PageHead, StatusBadge } from "../components/ui";
import { useApi } from "../hooks/useApi";
import type { Dataset, Progress, Project } from "../types";
import { fmtDate, LEVEL_LABELS } from "../utils/format";

interface DashboardData {
  counts: Record<string, number>;
  projects: (Project & { progress: Progress })[];
  active_project: (Project & { progress: Progress }) | null;
  recent_datasets: (Dataset & { project_title: string })[];
  recent_analyses: { id: number; name: string; status: string; project_id: number; project_title: string; created_at: string }[];
  data_quality_warnings: { project_id: number; project_title: string; dataset_name: string; score: number; high_severity_issues: number; top_issue: string | null }[];
  ai_recommendations: { id: number; project_id: number; project_title: string; rationale: string; recommendation: { primary: { name: string } } }[];
}

export default function Dashboard() {
  const { data, loading, error } = useApi<DashboardData>("/dashboard");
  if (loading) return <main className="page"><Loading /></main>;
  if (error || !data) return <main className="page"><ErrorNote message={error} /></main>;
  const active = data.active_project;
  const tiles: [string, number, string][] = [
    ["Projects", data.counts.projects, "folder"], ["Active", data.counts.active_projects, "clock"], ["Completed", data.counts.completed_projects, "check"],
    ["Datasets", data.counts.datasets, "data"], ["Analyses", data.counts.analyses, "chart"], ["Reports", data.counts.reports, "report"],
  ];
  return (
    <main className="page stack">
      <PageHead title="My research dashboard" actions={<Link className="btn primary" to="/projects/new"><Icon name="plus" /> New project</Link>} />
      {data.counts.projects === 0 ? (
        <Empty title="Start your first research project" action={<Link className="btn primary" to="/projects/new">Create a project</Link>}>
          A project holds your research questions, data, analyses and report. Creating one takes about two minutes.
        </Empty>
      ) : (
        <>
          <dl className="grid cols-4" style={{ margin: 0 }}>
            {tiles.map(([label, value, icon]) => (
              <div className="panel stat-card" key={label}>
                <span className="stat-icon"><Icon name={icon} /></span>
                <div>
                  <dt>{label}</dt>
                  <dd className="num-plain">{value}</dd>
                </div>
              </div>
            ))}
          </dl>

          {active && (
            <section className="panel hero-card stack">
              <div className="row between">
                <div>
                  <span className="small muted">Active project</span>
                  <h2><Link to={`/projects/${active.id}`}>{active.title}</Link></h2>
                </div>
                <Badge tone="info">{LEVEL_LABELS[active.academic_level]}</Badge>
              </div>
              <Meter percent={active.progress.percent} label="Project progress" />
              <div className="row chips" style={{ gap: "0.4rem 0.5rem" }}>
                {active.progress.steps.map((s) => (
                  <span key={s.key} className={s.done ? "" : "muted"}>{s.done ? "✓" : "○"} {s.label}</span>
                ))}
              </div>
            </section>
          )}

          <div className="grid cols-2">
            <section className="panel">
              <h2>Data quality warnings</h2>
              {data.data_quality_warnings.length === 0 ? <p className="muted">No datasets need attention.</p> : (
                <ul className="list-clean">
                  {data.data_quality_warnings.map((w, i) => (
                    <li key={i}>
                      <Link to={`/projects/${w.project_id}/quality`}>{w.dataset_name}</Link> <Badge tone="warn">{w.score}%</Badge>
                      <div className="small muted">{w.top_issue ?? `${w.high_severity_issues} serious issue(s)`}</div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section className="panel">
              <h2>Method recommendations</h2>
              {data.ai_recommendations.length === 0 ? <p className="muted">Ask for a recommendation on the Run analysis page.</p> : (
                <ul className="list-clean">
                  {data.ai_recommendations.map((r) => (
                    <li key={r.id}>
                      <Link to={`/projects/${r.project_id}/analysis`}>{r.recommendation.primary.name}</Link>
                      <div className="small muted">{r.project_title}</div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section className="panel">
              <h2>Recent analyses</h2>
              {data.recent_analyses.length === 0 ? <p className="muted">No analyses yet.</p> : (
                <ul className="list-clean">
                  {data.recent_analyses.map((a) => (
                    <li key={a.id} className="row between">
                      <span className="grow"><Link to={`/projects/${a.project_id}/analysis?run=${a.id}`}>{a.name}</Link>
                        <span className="small muted"> {fmtDate(a.created_at)}</span></span>
                      <StatusBadge status={a.status} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section className="panel">
              <h2>Recent datasets</h2>
              {data.recent_datasets.length === 0 ? <p className="muted">No datasets yet.</p> : (
                <ul className="list-clean">
                  {data.recent_datasets.map((d) => (
                    <li key={d.id}>
                      <Link to={`/projects/${d.project_id}/preview`}>{d.name}</Link>
                      <span className="small muted"> {d.row_count} rows, {d.column_count} variables</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </main>
  );
}
