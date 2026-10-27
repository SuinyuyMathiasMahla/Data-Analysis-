import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ClientPackageForm } from "../components/ClientPackage";
import { ApiError, api } from "../services/api";

vi.mock("../services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/api")>();
  return { ...actual, api: { ...actual.api, postBlob: vi.fn() } };
});

describe("ClientPackageForm", () => {
  it("lists the blocking issues the server refuses the package for", async () => {
    vi.mocked(api.postBlob).mockRejectedValueOnce(new ApiError(422, "readiness_failed", "1 item(s) must be resolved before the client package can be generated.", {
      issues: [{ code: "missing_references", where: "references", message: "The report names statistical methods but no reference list was supplied.",
                 action: "Add the references.", diagnosis: "Paste the references.", fixed_by: "you" }],
      assistant_actions: [],
    }));
    render(<ClientPackageForm projectId={7} datasetId={3} projectTitle="Walking study" />);
    await userEvent.click(screen.getByRole("button", { name: "Build client package" }));
    const list = await screen.findByRole("list", { name: "Items to fix" });
    expect(list.textContent).toContain("no reference list was supplied");
    expect(list.textContent).toContain("Paste the references.");
  });

  it("sends the chosen audience, length and references", async () => {
    vi.mocked(api.postBlob).mockResolvedValueOnce(new Blob(["zip"]));
    globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
    globalThis.URL.revokeObjectURL = vi.fn();
    render(<ClientPackageForm projectId={7} datasetId={3} projectTitle="Walking study" />);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Audience/ }), "executive");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Length/ }), "one_page");
    await userEvent.type(screen.getByLabelText("References"), "Bull, F. C. (2020). WHO guidelines.");
    await userEvent.click(screen.getByRole("button", { name: "Build client package" }));
    await waitFor(() => expect(api.postBlob).toHaveBeenCalledWith("/projects/7/client-package", expect.objectContaining({
      audience: "executive", length: "one_page", deliverables: ["summary"], references: ["Bull, F. C. (2020). WHO guidelines."], dataset_id: 3,
    })));
  });
});
