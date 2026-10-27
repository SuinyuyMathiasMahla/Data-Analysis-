import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ProjectCosts from "../pages/ProjectCosts";
import { api } from "../services/api";

vi.mock("../layouts/ProjectLayout", () => ({ useProject: () => ({ project: { id: 4 }, canWrite: true }) }));
vi.mock("../services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/api")>();
  return { ...actual, api: { ...actual.api, get: vi.fn(), put: vi.fn() } };
});

describe("cost amounts", () => {
  it("shows an error for a missing amount, blocks saving, and leaves that row out of the total", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ currency: "USD", items: [
      { description: "Printing", category: "Printing and binding", amount: 40 },
      { description: "Transport", category: "Travel", amount: 12 }], total: 52 });
    render(<ProjectCosts />);
    expect(await screen.findByText("Approximate total: USD 52.00")).toBeTruthy();

    await userEvent.clear(screen.getByLabelText("Cost 2 amount"));
    expect(screen.getByText("Enter an amount of 0 or more.")).toBeTruthy();
    expect(screen.getByText("One amount is not valid. Fix them before saving.")).toBeTruthy();
    expect(screen.getByText("Approximate total: USD 40.00")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save costs" }) as HTMLButtonElement).disabled).toBe(true);

    await userEvent.type(screen.getByLabelText("Cost 2 amount"), "15");
    expect(screen.queryByText("Enter an amount of 0 or more.")).toBeNull();
    expect((screen.getByRole("button", { name: "Save costs" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("refuses a negative amount", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ currency: "USD", items: [{ description: "Paper", category: "Other", amount: 5 }], total: 5 });
    render(<ProjectCosts />);
    await screen.findByText("Approximate total: USD 5.00");
    await userEvent.clear(screen.getByLabelText("Cost 1 amount"));
    await userEvent.type(screen.getByLabelText("Cost 1 amount"), "-3");
    expect(screen.getByText("Enter an amount of 0 or more.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save costs" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
