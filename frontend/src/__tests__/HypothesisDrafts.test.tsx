import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { HypothesisDrafts } from "../components/HypothesisDrafts";
import { api } from "../services/api";

vi.mock("../services/api", () => ({ api: { post: vi.fn() } }));

const questions = [{ id: 4, code: "RQ1", text: "Is study time related to GPA?" }];

describe("HypothesisDrafts", () => {
  it("fills the form only when the user chooses the draft", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      draft: { null_text: "There is no association between study time and GPA.", alternative_text: "There is an association between study time and GPA." },
      questions: [],
    });
    const onUse = vi.fn();
    render(<HypothesisDrafts projectId={7} questions={questions} onUse={onUse} />);
    await userEvent.click(screen.getByRole("button", { name: "Draft H0 and H1" }));
    expect(await screen.findByText(/There is an association/)).toBeTruthy();
    expect(onUse).not.toHaveBeenCalled();                       // a draft alone changes nothing
    await userEvent.click(screen.getByRole("button", { name: "Use this draft in the form" }));
    await waitFor(() => expect(onUse).toHaveBeenCalledWith(expect.objectContaining({ research_question_id: "4" })));
  });

  it("asks the user for what it cannot infer instead of guessing", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ draft: null, questions: ["Which variable is the outcome this question is about?"] });
    render(<HypothesisDrafts projectId={7} questions={questions} onUse={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Draft H0 and H1" }));
    expect(await screen.findByText(/Which variable is the outcome/)).toBeTruthy();
  });
});
