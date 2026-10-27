import type { ReactNode } from "react";

import type { AssumptionCheck, EngineResult } from "../types";
import { fmtNumber, fmtP, variablesText } from "../utils/format";
import { Alert, Badge, DataTable, Source } from "./ui";

function checkLabel(check: AssumptionCheck): ReactNode {
  if (check.satisfied === true) return <Badge tone="ok">Met</Badge>;
  if (check.satisfied === false) return <Badge tone="danger">Not met</Badge>;
  return <Badge tone="warn">You judge</Badge>;
}

export function AssumptionList({ checks }: { checks: AssumptionCheck[] }) {
  if (!checks.length) return null;
  return (
    <ul className="checks">
      {checks.map((check, i) => (
        <li key={i}>
          <div>{checkLabel(check)}</div>
          <div>
            <strong>{check.name}</strong>
            {check.test && <span className="muted"> ({check.test})</span>}
            <div className="small">{check.note}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * Renders one result of the statistical engine. Everything shown here comes
 * straight from the engine output; this component formats but never computes.
 */
export function ResultView({ result, actions, datasetVersion }: { result: EngineResult; actions?: ReactNode; datasetVersion?: number | null }) {
  const hasTest = result.p_value !== null && result.p_value !== undefined;
  const failed = (result.assumptions ?? []).filter((a) => a.satisfied === false).length;
  return (
    <article className="panel stack" aria-label={result.method_name}>
      <header className="row between">
        <div className="grow">
          <h2>{result.method_name}</h2>
          <div className="trail" style={{ marginTop: "0.35rem" }}>
            <Source kind="engine" />
            {datasetVersion !== null && datasetVersion !== undefined && <span>Dataset version {datasetVersion}</span>}
            <span>n = {result.n}</span>
            {variablesText(result.variables) && <span>{variablesText(result.variables)}</span>}
          </div>
        </div>
        {actions && <div className="row">{actions}</div>}
      </header>

      {result.apa && <div className="apa">{result.apa}</div>}

      {hasTest && (
        <dl className="stat-line">
          {result.statistic && result.statistic.value !== null && (
            <div>
              <dt>{result.statistic.name}</dt>
              <dd>{fmtNumber(result.statistic.value)}</dd>
            </div>
          )}
          {result.df !== null && result.df !== undefined && (
            <div>
              <dt>df</dt>
              <dd>{typeof result.df === "number" ? fmtNumber(result.df, 2) : result.df}</dd>
            </div>
          )}
          <div>
            <dt>p-value</dt>
            <dd className={result.significant ? "sig" : undefined}>{fmtP(result.p_value)}</dd>
          </div>
          <div>
            <dt>Decision at alpha = {result.alpha ?? 0.05}</dt>
            <dd style={{ fontSize: "1.05rem" }}>{result.decision === "reject_null" ? "Reject H0" : "Fail to reject H0"}</dd>
          </div>
        </dl>
      )}

      {result.summary && (
        <section>
          <h3>What this means</h3>
          <p>{result.summary}</p>
        </section>
      )}

      {(result.warnings ?? []).length > 0 && (
        <Alert kind="warn">
          <strong>Read before you rely on this result</strong>
          <ul style={{ margin: "0.3rem 0 0", paddingLeft: "1.1rem" }}>
            {(result.warnings ?? []).map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Alert>
      )}

      {(result.effect_sizes ?? []).length > 0 && (
        <section>
          <h3>Effect size</h3>
          <DataTable
            table={{
              title: "",
              columns: ["Measure", "Value", "95% CI low", "95% CI high", "Magnitude"],
              rows: (result.effect_sizes ?? []).map((e) => [e.name, e.value, e.ci_low, e.ci_high, e.magnitude ?? ""]),
            }}
          />
          {(result.effect_sizes ?? [])
            .filter((e) => e.note)
            .map((e, i) => (
              <p key={i} className="table-note">
                {e.note}
              </p>
            ))}
        </section>
      )}

      {(result.estimates ?? []).length > 0 && (
        <section>
          <h3>Estimates and confidence intervals</h3>
          <DataTable
            table={{
              title: "",
              columns: ["Estimate", "Value", "95% CI low", "95% CI high"],
              rows: (result.estimates ?? []).map((e) => [e.name, e.value, e.ci_low, e.ci_high]),
            }}
          />
        </section>
      )}

      {(result.assumptions ?? []).length > 0 && (
        <section>
          <h3>
            Assumption checks{" "}
            {failed > 0 ? <Badge tone="danger">{failed} not met</Badge> : <Badge tone="ok">none failed</Badge>}
          </h3>
          <AssumptionList checks={result.assumptions ?? []} />
        </section>
      )}

      {(result.tables ?? []).map((table, i) => (
        <DataTable key={i} table={table} maxHeight={420} />
      ))}

      {result.software && (
        <p className="table-note">
          Software:{" "}
          {Object.entries(result.software)
            .map(([name, version]) => `${name} ${version}`)
            .join(", ")}
        </p>
      )}
    </article>
  );
}
