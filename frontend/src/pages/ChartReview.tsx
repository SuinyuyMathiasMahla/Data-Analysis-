import { Link } from "react-router-dom";

import { StepCheckPanel } from "../components/StepCheck";
import { ChartIdeas } from "../components/ChartDrawer";
import { Empty, ErrorNote, Loading, PageHead } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { DatasetPicker, useProject } from "../layouts/ProjectLayout";
import type { ChartIdea } from "../types";

/** Workflow step after conclusions and recommendations: the charts the exploration suggests, drawn inline. */
export function ChartReview() {
  const { project, dataset } = useProject();
  const suggested = useApi<{ run_id: number | null; charts: ChartIdea[] }>(
    dataset ? `/projects/${project.id}/charts/suggested?dataset_id=${dataset.id}` : null,
  );
  if (!dataset) {
    return <Empty title="Upload a dataset first" action={<Link className="btn primary" to="../upload">Upload a dataset</Link>}>Charts are drawn from the dataset.</Empty>;
  }
  return (
    <div className="stack">
      <PageHead title="Charts worth drawing" actions={<DatasetPicker />}>
        Charts suggested by the exploration of {dataset.name}. Draw any of them to see the pattern in the data. The panel lets you change the chart type and the variables.
      </PageHead>
      <StepCheckPanel step="charts" />
      <ErrorNote message={suggested.error} />
      {suggested.loading && <Loading />}
      {suggested.data && suggested.data.charts.length === 0 && (
        <Empty title="No charts suggested yet" action={<Link className="btn primary" to="../explore">Go to Explore data</Link>}>
          Explore the data first. The charts it suggests appear here.
        </Empty>
      )}
      {suggested.data && <ChartIdeas ideas={suggested.data.charts} heading="Suggested from the exploration" />}
    </div>
  );
}
