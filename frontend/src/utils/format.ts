// Display formatting shared across pages. Numbers are only formatted here -
// never recomputed - so what is shown always traces back to the engine output.

export function fmtNumber(value: unknown, digits = 3): string {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value !== "number") return String(value);
  if (!Number.isFinite(value)) return "–";
  if (Number.isInteger(value) && Math.abs(value) < 1e9) return String(value);
  if (value !== 0 && Math.abs(value) < 0.001) return value > 0 ? "< 0.001" : value.toExponential(2);
  return value.toFixed(digits);
}

/** APA style: p < .001 below that, otherwise three decimals without the leading zero. */
export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "–";
  if (p < 0.001) return "< .001";
  return p.toFixed(3).replace(/^0/, "");
}

export function fmtPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "–";
  return `${value.toFixed(digits)}%`;
}

export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "–";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "–";
  return withTime
    ? date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : date.toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const LEVEL_LABELS: Record<string, string> = { undergraduate: "Undergraduate", masters: "Master's", phd: "PhD" };

export function variablesText(variables: Record<string, unknown> | null | undefined): string {
  if (!variables) return "";
  return Object.entries(variables)
    .filter(([, v]) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0))
    .map(([role, v]) => `${role}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
    .join("; ");
}

/** "dataset.cleaned" -> "Dataset cleaned" */
export function actionLabel(action: string): string {
  const text = action.replace(/[._]/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong. Please try again.";
}

/** "USD 1,250.00" style amount for display. */
export function formatMoney(amount: number, currency: string): string {
  return `${currency} ${amount.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
