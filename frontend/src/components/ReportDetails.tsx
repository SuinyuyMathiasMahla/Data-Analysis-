import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAction, useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { ReportDetails as Details } from "../types";
import { Alert, Button, ErrorNote, Field, Loading } from "./ui";

interface Form {
  background: string;
  references: string;
  ethics_committee: string;
  ethics_reference: string;
  consent_method: string;
}

function toForm(details: Details): Form {
  return {
    background: details.background ?? "",
    references: details.references.join("\n"),
    ethics_committee: details.ethics_committee ?? "",
    ethics_reference: details.ethics_reference ?? "",
    consent_method: details.consent_method ?? "",
  };
}

/** What the report cannot work out by itself: the literature review, the references and the ethics approval. */
export function ReportDetailsForm({ projectId, canWrite }: { projectId: number; canWrite: boolean }) {
  const saved = useApi<Details>(`/projects/${projectId}/report-details`);
  const [form, setForm] = useState<Form | null>(null);
  const [done, setDone] = useState(false);
  const { busy, error, run } = useAction();

  useEffect(() => {
    if (saved.data) setForm(toForm(saved.data));
  }, [saved.data]);

  const set = (key: keyof Form) => (e: { target: { value: string } }) => {
    setDone(false);
    setForm((current) => (current ? { ...current, [key]: e.target.value } : current));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    const body = {
      background: form.background.trim() || null,
      references: form.references.split("\n").map((line) => line.trim()).filter(Boolean),
      ethics_committee: form.ethics_committee.trim() || null,
      ethics_reference: form.ethics_reference.trim() || null,
      consent_method: form.consent_method.trim() || null,
    };
    run(async () => {
      const updated = await api.put<Details>(`/projects/${projectId}/report-details`, body);
      setForm(toForm(updated));
      setDone(true);
    });
  };

  if (saved.loading || !form) return saved.error ? <ErrorNote message={saved.error} /> : <Loading label="Loading report details" />;
  return (
    <form className="panel stack" onSubmit={submit} aria-label="Report details">
      <h2 style={{ margin: 0 }}>Report details</h2>
      <p className="small muted">
        These parts of the report come from you, not from the data: the background and literature review, the references, and the
        ethics approval. They are printed in the report exactly as entered.
      </p>
      <ErrorNote message={error} />
      <Field label="Background and literature review" hint="Write in plain English what earlier research found and how this study builds on it. Separate paragraphs with a blank line.">
        <textarea rows={8} value={form.background} onChange={set("background")} disabled={!canWrite} aria-label="Background and literature review" />
      </Field>
      <Field label="References" hint="One source per line, in APA 7th edition format. Cite every study the background and discussion mention.">
        <textarea rows={6} value={form.references} onChange={set("references")} disabled={!canWrite} aria-label="References" />
      </Field>
      <div className="grid cols-2">
        <Field label="Ethics committee"><input type="text" value={form.ethics_committee} onChange={set("ethics_committee")} disabled={!canWrite} /></Field>
        <Field label="Approval reference and date"><input type="text" value={form.ethics_reference} onChange={set("ethics_reference")} disabled={!canWrite} /></Field>
      </div>
      <Field label="Consent method"><input type="text" placeholder="For example: written informed consent" value={form.consent_method} onChange={set("consent_method")} disabled={!canWrite} /></Field>
      {done && <Alert kind="ok">The report details are saved. They will appear in the next report you generate.</Alert>}
      {canWrite && <div><Button type="submit" variant="primary" busy={busy}>Save report details</Button></div>}
    </form>
  );
}
