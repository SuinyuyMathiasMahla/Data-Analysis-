import { useEffect, useState } from "react";

import { api, relative } from "../services/api";
import type { AIReply, Variable } from "../types";
import { Alert, Source } from "./ui";

/** <img> for a protected image: fetched with the Authorization header. */
export function AuthImage({ path, alt, version }: { path: string; alt: string; version?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);
    api
      .blob(relative(path))
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path, version]);
  if (failed) return <p className="muted">The chart could not be loaded.</p>;
  if (!url) return <p className="muted">Loading chart…</p>;
  return <img src={url} alt={alt} />;
}

const NUMERIC = ["numeric", "integer"];

export function variableFits(variable: Variable, kind: "numeric" | "categorical" | "any"): boolean {
  if (variable.data_type === "identifier" || variable.data_type === "text") return false;
  if (kind === "numeric") return NUMERIC.includes(variable.data_type);
  if (kind === "categorical") return !NUMERIC.includes(variable.data_type) || (variable.n_unique ?? 99) <= 12;
  return true;
}

function optionLabel(v: Variable): string {
  return `${v.name}${v.label ? ` – ${v.label}` : ""} (${v.data_type}, ${v.measurement_level})`;
}

export function VariableSelect({
  variables, kind = "any", value, onChange, id, allowEmpty = true,
}: {
  variables: Variable[]; kind?: "numeric" | "categorical" | "any"; value: string; onChange: (value: string) => void; id?: string; allowEmpty?: boolean;
}) {
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      {allowEmpty && <option value="">Choose a variable</option>}
      {variables.filter((v) => variableFits(v, kind)).map((v) => (
        <option key={v.name} value={v.name}>
          {optionLabel(v)}
        </option>
      ))}
    </select>
  );
}

export function VariableMultiSelect({
  variables, kind = "any", value, onChange, id,
}: {
  variables: Variable[]; kind?: "numeric" | "categorical" | "any"; value: string[]; onChange: (value: string[]) => void; id?: string;
}) {
  return (
    <select id={id} multiple value={value} onChange={(e) => onChange(Array.from(e.target.selectedOptions).map((o) => o.value))}>
      {variables.filter((v) => variableFits(v, kind)).map((v) => (
        <option key={v.name} value={v.name}>
          {optionLabel(v)}
        </option>
      ))}
    </select>
  );
}

/** An AI (or rule-engine) reply with its provenance and integrity notice. */
export function AIReplyView({ reply }: { reply: AIReply }) {
  return (
    <div className="stack" style={{ ["--gap" as string]: "0.6rem" }}>
      <div className="row">
        <Source kind={reply.source} />
        {reply.source === "llm" && reply.provider && (
          <span className="small muted">
            {reply.provider} {reply.model}
          </span>
        )}
        {reply.grounding && reply.source === "llm" && reply.grounding.grounded && (
          <span className="small muted">{reply.grounding.checked} number(s) matched to engine results</span>
        )}
      </div>
      {reply.notice && <Alert kind={reply.grounding && !reply.grounding.grounded ? "error" : "info"}>{reply.notice}</Alert>}
      <div className="bubble assistant">{reply.content}</div>
      {reply.source === "llm" && (
        <p className="table-note">
          An AI interpretation can be wrong. Check it against the result tables; you remain responsible for the final academic interpretation.
        </p>
      )}
    </div>
  );
}
