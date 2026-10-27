import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReportDetailsForm } from "../components/ReportDetails";
import { api } from "../services/api";

vi.mock("../services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/api")>();
  return { ...actual, api: { ...actual.api, get: vi.fn(), put: vi.fn() } };
});

describe("ReportDetailsForm", () => {
  it("shows the saved details and sends the references one per line without blank entries", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      background: "Earlier work found a link.", references: ["Smith, J. (2020). Sleep and grades."],
      ethics_committee: null, ethics_reference: null, consent_method: null,
    });
    vi.mocked(api.put).mockImplementationOnce(async (_path, body) => body as never);
    render(<ReportDetailsForm projectId={4} canWrite />);

    const references = await screen.findByLabelText("References") as HTMLTextAreaElement;
    expect(references.value).toBe("Smith, J. (2020). Sleep and grades.");
    await userEvent.type(references, "{enter}Lee, K. (2021). Study time.{enter}  ");
    await userEvent.click(screen.getByRole("button", { name: "Save report details" }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/projects/4/report-details", expect.objectContaining({
      background: "Earlier work found a link.",
      references: ["Smith, J. (2020). Sleep and grades.", "Lee, K. (2021). Study time."],
    })));
  });

  it("is read-only for people who cannot write to the project", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ background: null, references: [], ethics_committee: null, ethics_reference: null, consent_method: null });
    render(<ReportDetailsForm projectId={4} canWrite={false} />);
    expect(await screen.findByLabelText("Background and literature review")).toHaveProperty("disabled", true);
    expect(screen.queryByRole("button", { name: "Save report details" })).toBeNull();
  });
});
