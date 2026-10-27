import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useParams } from "react-router-dom";

import { ErrorNote, Loading, Meter } from "../components/ui";
import { useApi } from "../hooks/useApi";
import type { Dataset, ProjectDetail } from "../types";
import { LEVEL_LABELS } from "../utils/format";

interface ProjectState {
  project: ProjectDetail;
  reload: () => void;
  /** dataset the analysis pages work on */
  dataset: Dataset | null;
  selectDataset: (id: number) => void;
  canWrite: boolean;
  canReview: boolean;
}

const ProjectContext = createContext<ProjectState | null>(null);

export function useProject(): ProjectState {
  const context = useContext(ProjectContext);
  if (!context) throw new Error("useProject must be used inside a project page");
  return context;
}

// The guided workflow. `stage` links a page to the progress step reported by the API.
const STEPS: { to: string; label: string; stage: string }[] = [
  { to: "", label: "Project overview", stage: "project" },
  { to: "research-questions", label: "Research questions", stage: "research_questions" },
  { to: "hypotheses", label: "Hypotheses", stage: "hypotheses" },
  { to: "upload", label: "Upload dataset", stage: "dataset" },
  { to: "quality", label: "Check data quality", stage: "quality" },
  { to: "cleaning", label: "Clean data", stage: "cleaning" },
  { to: "explore", label: "Explore data", stage: "exploration" },
  { to: "analysis", label: "Run analysis", stage: "analysis" },
  { to: "findings", label: "Review findings", stage: "findings" },
  { to: "conclusions", label: "Conclusions and recommendations", stage: "conclusions" },
  { to: "visuals", label: "Charts worth drawing", stage: "charts" },
  { to: "report", label: "Generate report", stage: "report" },
];
const TOOLS: { to: string; label: string }[] = [
  { to: "preview", label: "Dataset preview" },
  { to: "dictionary", label: "Data dictionary" },
  { to: "descriptive", label: "Descriptive statistics" },
  { to: "charts", label: "Visualization studio" },
  { to: "assistant", label: "AI research assistant" },
  { to: "costs", label: "Project costs" },
  { to: "history", label: "Project history" },
];

export default function ProjectLayout() {
  const { projectId } = useParams();
  const { data: project, loading, error, reload } = useApi<ProjectDetail>(projectId ? `/projects/${projectId}` : null);
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const location = useLocation();

  useEffect(() => setDatasetId(null), [projectId]);
  // On narrow screens the workflow is a horizontal strip: keep the current step in view.
  useEffect(() => {
    document.querySelector<HTMLElement>(".rail a.active")?.scrollIntoView?.({ inline: "center", block: "nearest" });
  }, [location.pathname, project?.id]);

  const state = useMemo<ProjectState | null>(() => {
    if (!project) return null;
    const dataset = project.datasets.find((d) => d.id === datasetId) ?? project.datasets[project.datasets.length - 1] ?? null;
    return {
      project, reload, dataset, selectDataset: setDatasetId,
      canWrite: project.rights.includes("write"), canReview: project.rights.includes("review"),
    };
  }, [project, reload, datasetId]);

  if (loading && !project) return <main className="page"><Loading label="Opening project" /></main>;
  if (error || !state) return <main className="page"><ErrorNote message={error ?? "Project not found."} /></main>;

  const done = new Map(state.project.progress.steps.map((s) => [s.key, s.done]));
  return (
    <div className="workspace">
      <aside className="rail" aria-label="Project workflow">
        <div className="project-title">{state.project.title}</div>
        <div className="small muted">{LEVEL_LABELS[state.project.academic_level]} project</div>
        <div className="progress-wrap"><Meter percent={state.project.progress.percent} label="Workflow progress" /></div>
        <ol>
          {STEPS.map((step, index) => {
            const isDone = done.get(step.stage) === true;
            const isNext = state.project.progress.next_step === step.stage;
            return (
              <li key={step.to} className={isDone ? "done" : isNext ? "next" : undefined}>
                <NavLink to={step.to} end={step.to === ""}>
                  <span className="step-no" aria-hidden="true">{isDone ? "✓" : index + 1}</span>
                  <span>
                    {step.label}
                    <span className="sr-only">{isDone ? " (done)" : isNext ? " (next step)" : ""}</span>
                  </span>
                </NavLink>
              </li>
            );
          })}
        </ol>
        <div className="group-label">Tools</div>
        <ul>
          {TOOLS.map((tool) => (
            <li key={tool.to}>
              <NavLink to={tool.to}>{tool.label}</NavLink>
            </li>
          ))}
        </ul>
      </aside>
      <div className="content">
        {!state.canWrite && (
          <div className="alert info" style={{ marginBottom: "1rem" }}>
            You have read-only access to this project{state.canReview ? " and can comment on and review its stages (see Project history)." : "."}
          </div>
        )}
        <ProjectContext.Provider value={state}>
          <Outlet />
        </ProjectContext.Provider>
      </div>
    </div>
  );
}

/** Dataset picker shown on pages that work on a dataset. */
export function DatasetPicker() {
  const { project, dataset, selectDataset } = useProject();
  if (project.datasets.length <= 1 || !dataset) return null;
  return (
    <label className="row small">
      <span>Dataset</span>
      <select value={dataset.id} onChange={(e) => selectDataset(Number(e.target.value))} style={{ width: "auto" }}>
        {project.datasets.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </select>
    </label>
  );
}
