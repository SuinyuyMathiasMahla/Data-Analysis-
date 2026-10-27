import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AutoClean } from "../components/AutoClean";
import { api } from "../services/api";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));

const dataset = { id: 3, current_version_id: 9 } as never;

const decision = {
  decision_id: 41, kind: "missing_value", column: "bmi", action: "delete_records", reason: "Only a few records lack a BMI.",
  source: "ai_assistant", missing_pct: 7.5, affects_results: true, undone: false,
};

describe("AutoClean", () => {
  it("cleans in one click, shows the score change, and explains the AI decision", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(api.get).mockResolvedValue({ decisions: [] });
    vi.mocked(api.post).mockResolvedValueOnce({
      score_before: 62.5, score_after: 100, rows_before: 61, rows_after: 57, applied: [], decisions: [decision], alerts: [decision],
    });
    const onDone = vi.fn();
    render(<AutoClean dataset={dataset} onDone={onDone} />);
    await userEvent.click(screen.getByRole("button", { name: "Clean data" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/datasets/3/auto-clean"));
    expect(await screen.findByText(/62\.5 → 100\.0/)).toBeTruthy();
    expect(screen.getAllByText(/Only a few records lack a BMI/).length).toBeGreaterThan(0);
    expect(onDone).toHaveBeenCalled();
  });

  it("lets the user undo a flagged decision", async () => {
    vi.mocked(api.get).mockResolvedValue({ decisions: [decision] });
    vi.mocked(api.post).mockResolvedValueOnce({});
    render(<AutoClean dataset={dataset} onDone={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/datasets/3/auto-decisions/41/undo"));
  });

  it("does nothing when the user cancels", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.mocked(api.post).mockClear();
    vi.mocked(api.get).mockResolvedValue({ decisions: [] });
    render(<AutoClean dataset={dataset} onDone={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Clean data" }));
    expect(api.post).not.toHaveBeenCalled();
  });
});
