import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import ProjectCosts from "../pages/ProjectCosts";
import { api } from "../services/api";

vi.mock("../layouts/ProjectLayout", () => ({
  useProject: () => ({ project: { id: 4 }, canWrite: true }),
}));
vi.mock("../services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/api")>();
  return { ...actual, api: { ...actual.api, get: vi.fn(), put: vi.fn() } };
});

describe("ProjectCosts", () => {
  it("adds up the lines into the approximate total and saves them", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ currency: "USD", items: [{ description: "Printing", category: "Printing and binding", amount: 40 }], total: 40 });
    vi.mocked(api.put).mockImplementationOnce(async (_path, body) => ({ ...(body as object), total: 0 }) as never);
    render(<MemoryRouter initialEntries={["/projects/4/costs"]}><Routes><Route path="/projects/4/costs" element={<ProjectCosts />} /></Routes></MemoryRouter>);

    expect(await screen.findByText("Approximate total: USD 40.00")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Add a cost" }));
    await userEvent.type(screen.getByLabelText("Cost 2 description"), "Transport");
    await userEvent.clear(screen.getByLabelText("Cost 2 amount"));
    await userEvent.type(screen.getByLabelText("Cost 2 amount"), "12.5");
    expect(screen.getByText("Approximate total: USD 52.50")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Save costs" }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/projects/4/costs", {
      currency: "USD",
      items: [{ description: "Printing", category: "Printing and binding", amount: 40 }, { description: "Transport", category: "Other", amount: 12.5 }],
    }));
  });
});
