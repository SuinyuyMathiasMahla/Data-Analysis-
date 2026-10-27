import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StepCheckPanel } from "../components/StepCheck";
import { api } from "../services/api";

vi.mock("../layouts/ProjectLayout", () => ({
  useProject: () => ({ project: { id: 7 }, dataset: { id: 3 }, canWrite: true }),
}));
vi.mock("../services/api", () => ({
  api: { get: vi.fn(), post: vi.fn(() => Promise.resolve({ logged: true })) },
}));

const check = {
  step: "quality",
  passed: false,
  blocking: [{ code: "impossible_value", severity: "blocking", message: "'bmi' has 1 value outside the plausible range.", fix: "Suggested fix: Remove invalid values." }],
  warnings: [{ code: "duplicate_rows", severity: "warning", message: "3 row(s) are exact duplicates.", fix: "Suggested fix: Remove duplicate rows." }],
};

describe("StepCheckPanel", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue(check);
    vi.mocked(api.post).mockClear();
  });

  it("shows what blocks the step, with its fix, and says moving on is blocked", async () => {
    render(<StepCheckPanel step="quality" />);
    expect(await screen.findByText(/Moving on is blocked/)).toBeTruthy();
    expect(screen.getByText(/outside the plausible range/)).toBeTruthy();
    expect(screen.getByText(/Remove invalid values/)).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("/projects/7/steps/quality/check?dataset_id=3");
  });

  it("logs the user's acceptance of a warning as a decision", async () => {
    render(<StepCheckPanel step="quality" />);
    await userEvent.click(await screen.findByRole("button", { name: "Accept" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/projects/7/assistant/decisions",
        expect.objectContaining({ step: "quality", kind: "decision", decision: "accepted" })));
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });
});
