import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChartTitleDraft, ProjectGaps } from "../components/AssistantDrafts";
import { api } from "../services/api";

vi.mock("../services/api", () => ({ api: { post: vi.fn() } }));

describe("assistant drafts", () => {
  it("asks for what the project overview still lacks", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ questions: ["Who are the participants?", "Has ethics approval been granted?"], note: "Answer these." });
    render(<ProjectGaps projectId={7} />);
    await userEvent.click(screen.getByRole("button", { name: "Ask the assistant" }));
    expect(await screen.findByText("Who are the participants?")).toBeTruthy();
    expect(api.post).toHaveBeenCalledWith("/projects/7/assistant/draft", { kind: "project_gaps" });
  });

  it("offers a chart title and axis labels only when the user chooses them", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ draft: { title: "GPA by study time", x_label: "Study time", y_label: "GPA (points)" }, questions: [] });
    const onUse = vi.fn();
    render(<ChartTitleDraft projectId={7} chartType="scatter" x="study_time" y="gpa" onUse={onUse} />);
    await userEvent.click(screen.getByRole("button", { name: "Draft a title from the variables" }));
    expect(await screen.findByText(/GPA by study time/)).toBeTruthy();
    expect(onUse).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Use this title and labels" }));
    expect(onUse).toHaveBeenCalledWith({ title: "GPA by study time", xLabel: "Study time", yLabel: "GPA (points)" });
  });
});
