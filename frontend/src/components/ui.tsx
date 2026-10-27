// Small in-house component set (no external UI dependency).
import type { ButtonHTMLAttributes, ReactNode } from "react";

import type { ResultTable } from "../types";
import { fmtNumber, fmtP } from "../utils/format";

const ICONS: Record<string, string> = {
  logo: "M4 19V9m6 10V5m6 14v-7m4 7H2",
  home: "M3 11.5 12 4l9 7.5M5 10v10h5v-6h4v6h5V10",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  calc: "M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm2 4h8M8 12h.01M12 12h.01M16 12h.01M8 16h.01M12 16h.01M16 16h.01",
  shield: "M12 3 4 6v6c0 4.5 3.4 7.8 8 9 4.6-1.2 8-4.5 8-9V6z",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14.5 3h-4l-.4 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z",
  logout: "M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4M16 8l4 4-4 4M20 12H9",
  menu: "M4 6h16M4 12h16M4 18h16",
  plus: "M12 5v14M5 12h14",
  check: "M5 12.5 10 17.5 19 7",
  data: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
  spark: "m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
  trace: "M6 6a2 2 0 1 0 0 .01M18 18a2 2 0 1 0 0 .01M8 6h5a4 4 0 0 1 0 8h-2a4 4 0 0 0 0 8",
  repeat: "M17 2l4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4M21 13v2a3 3 0 0 1-3 3H3",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  chart: "M4 20h16M7 16v-5M12 16V6M17 16v-8",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-13v4.5l3 1.5",
  report: "M8 3h8l4 4v14H8zM4 7v14h2M11 12h6M11 16h6",
};

export function Icon({ name }: { name: keyof typeof ICONS | string }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={ICONS[name] ?? ICONS.file} />
    </svg>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "default" | "quiet" | "danger"; small?: boolean; busy?: boolean };

export function Button({ variant = "default", small, busy, children, className, disabled, type, ...rest }: ButtonProps) {
  const classes = ["btn", variant !== "default" ? variant : "", small ? "small" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <button type={type ?? "button"} className={classes} disabled={disabled || busy} {...rest}>
      {busy && <span className="spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}

export function Alert({ kind = "info", children }: { kind?: "error" | "warn" | "ok" | "info"; children: ReactNode }) {
  return (
    <div className={`alert ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function ErrorNote({ message }: { message: string | null | undefined }) {
  return message ? <Alert kind="error">{message}</Alert> : null;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p className="muted" role="status">
      <span className="spinner" aria-hidden="true" /> {label}…
    </p>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="panel empty">
      <div className="empty-art"><Icon name="folder" /></div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function PageHead({ title, children, actions }: { title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head row between">
      <div className="grow">
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

/** Provenance mark: who produced a number or a piece of text. */
export function Source({ kind, label }: { kind: "engine" | "ai" | "human" | "rule_engine" | "llm" | "manual" | "auto"; label?: string }) {
  const map: Record<string, [string, string]> = {
    engine: ["engine", "Computed by the statistical engine"],
    rule_engine: ["engine", "Rule engine (not a language model)"],
    auto: ["engine", "Detected automatically"],
    ai: ["ai", "AI-assisted draft"],
    llm: ["ai", "AI interpretation"],
    human: ["human", "Written by you"],
    manual: ["human", "Written by you"],
  };
  const [cls, text] = map[kind] ?? ["neutral", kind];
  return <span className={`mark ${cls}`}>{label ?? text}</span>;
}

export function Badge({ tone = "", children }: { tone?: "ok" | "warn" | "danger" | "info" | ""; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const tone = status === "COMPLETED" ? "ok" : status === "FAILED" ? "danger" : "info";
  const label = { PENDING: "Queued", PROCESSING: "Running", COMPLETED: "Completed", FAILED: "Failed" }[status] ?? status;
  return <Badge tone={tone}>{label}</Badge>;
}

function cell(value: unknown, column: string): string {
  if (typeof value === "number" && /^(p|adjusted p|p-value|p \(.*\))$/i.test(column.trim())) return fmtP(value);
  return fmtNumber(value);
}

/** Generic table for engine output: numbers right-aligned with tabular figures. */
export function DataTable({ table, maxHeight }: { table: ResultTable; maxHeight?: number }) {
  return (
    <div>
      <div className="table-wrap" style={maxHeight ? { maxHeight, overflowY: "auto" } : undefined}>
        <table className="data">
          {table.title && <caption>{table.title}</caption>}
          <thead>
            <tr>
              {table.columns.map((column, i) => (
                <th key={i} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, r) => (
              <tr key={r}>
                {table.columns.map((column, c) => {
                  const value = row[c];
                  const numeric = typeof value === "number";
                  return (
                    <td key={c} className={numeric ? "num" : value === null || value === undefined ? "missing" : undefined}>
                      {cell(value, column)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.note && <p className="table-note">Note. {table.note}</p>}
    </div>
  );
}

export function Meter({ percent, label }: { percent: number; label: string }) {
  return (
    <div>
      <div className="meter" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={label}>
        <span style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
      </div>
      <span className="small muted">{percent}% complete</span>
    </div>
  );
}

export function confirmAction(message: string): boolean {
  return window.confirm(message);
}
