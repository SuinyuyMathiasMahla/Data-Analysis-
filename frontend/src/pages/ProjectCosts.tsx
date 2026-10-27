import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Alert, Button, ErrorNote, Field, Loading, PageHead } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { useProject } from "../layouts/ProjectLayout";
import { api } from "../services/api";
import type { ProjectCosts as Costs } from "../types";
import { formatMoney } from "../utils/format";

export const COST_CATEGORIES = ["Data collection", "Materials and supplies", "Travel", "Software and online services",
  "Printing and binding", "Participant incentives", "Other"];

interface Row {
  description: string;
  category: string;
  amount: string;
}

/** Approximate costs of the project, entered by the researcher. The total is worked out from the lines. */
export default function ProjectCosts() {
  const { project, canWrite } = useProject();
  const costs = useApi<Costs>(`/projects/${project.id}/costs`);
  const [currency, setCurrency] = useState("USD");
  const [rows, setRows] = useState<Row[]>([]);
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();

  useEffect(() => {
    if (!costs.data) return;
    setCurrency(costs.data.currency);
    setRows(costs.data.items.map((item) => ({ description: item.description, category: item.category, amount: String(item.amount) })));
  }, [costs.data]);

  const update = (index: number, key: keyof Row, value: string) => {
    setSaved(false);
    setRows((current) => current.map((row, i) => (i === index ? { ...row, [key]: value } : row)));
  };
  // an amount must be a finite number of 0 or more; rows that are not are left out of the total and block saving
  const amountOk = (value: string) => value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) >= 0;
  const badRows = rows.filter((row) => !amountOk(row.amount)).length;
  const total = rows.reduce((sum, row) => (amountOk(row.amount) ? sum + Number(row.amount) : sum), 0);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(async () => {
      const body = {
        currency: currency.trim() || "USD",
        items: rows.map((row) => ({ description: row.description.trim(), category: row.category, amount: Number(row.amount) })),
      };
      const updated = await api.put<Costs>(`/projects/${project.id}/costs`, body);
      costs.setData(updated);
      setSaved(true);
    });
  };

  if (costs.loading) return <main className="page"><Loading /></main>;
  return (
    <div className="stack">
      <PageHead title="Project costs">
        An approximate budget for this project: what data collection, materials, travel and printing are expected to cost. The total is
        added up from the lines below. Enter amounts in one currency. These are estimates, not payments made through the platform.
      </PageHead>
      <ErrorNote message={costs.error ?? error} />
      <form className="panel stack" onSubmit={submit} aria-label="Project costs">
        <Field label="Currency" hint="For example USD, EUR or XAF.">
          <input type="text" maxLength={10} value={currency} onChange={(e) => { setSaved(false); setCurrency(e.target.value); }} disabled={!canWrite} />
        </Field>
        {rows.length === 0 && <p className="muted">No costs have been entered yet.</p>}
        {rows.map((row, index) => (
          <div className="grid cols-3" key={index} style={{ alignItems: "end" }}>
            <Field label="What it is for">
              <input type="text" value={row.description} onChange={(e) => update(index, "description", e.target.value)} disabled={!canWrite} aria-label={`Cost ${index + 1} description`} />
            </Field>
            <Field label="Category">
              <select value={row.category} onChange={(e) => update(index, "category", e.target.value)} disabled={!canWrite} aria-label={`Cost ${index + 1} category`}>
                {COST_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <div className="row" style={{ alignItems: "flex-end" }}>
              <Field label="Amount" hint={amountOk(row.amount) ? undefined : "Enter an amount of 0 or more."}>
                <input type="number" min={0} step="0.01" value={row.amount} onChange={(e) => update(index, "amount", e.target.value)} disabled={!canWrite}
                  aria-label={`Cost ${index + 1} amount`} aria-invalid={!amountOk(row.amount)} />
              </Field>
              {canWrite && <Button small variant="quiet" onClick={() => { setSaved(false); setRows(rows.filter((_, i) => i !== index)); }}>Remove</Button>}
            </div>
          </div>
        ))}
        {canWrite && (
          <div className="row">
            <Button small onClick={() => { setSaved(false); setRows([...rows, { description: "", category: "Other", amount: "0" }]); }}>Add a cost</Button>
          </div>
        )}
        <p><strong>Approximate total: {formatMoney(total, currency)}</strong></p>
        {badRows > 0 && <Alert kind="error">{badRows === 1 ? "One amount is not valid" : `${badRows} amounts are not valid`}. Fix them before saving.</Alert>}
        {saved && <Alert kind="ok">The costs are saved.</Alert>}
        {canWrite && <div><Button type="submit" variant="primary" busy={busy} disabled={badRows > 0}>Save costs</Button></div>}
      </form>
    </div>
  );
}
