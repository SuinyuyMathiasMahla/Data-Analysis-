import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ClientInfoForm, ProjectForm } from "../pages/Projects";
import { isValidWhatsApp, whatsAppProblem } from "../utils/whatsapp";

function renderClientPage() {
  return render(
    <MemoryRouter initialEntries={["/projects/new/client"]}>
      <Routes>
        <Route path="/projects/new/client" element={<ClientInfoForm />} />
        <Route path="/projects/new/details" element={<ProjectForm />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function fillClient(number: string, email = "contact@mbah.example") {
  await userEvent.type(screen.getByLabelText(/Client's name/), "Mbah Consulting");
  await userEvent.type(screen.getByLabelText(/Client's e-mail/), email);
  await userEvent.type(screen.getByLabelText(/Client's WhatsApp number/), number);
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
}

describe("WhatsApp number rules", () => {
  it("rejects a local number with a leading 0 and says what to type instead", () => {
    expect(isValidWhatsApp("0677000000")).toBe(false);
    expect(whatsAppProblem("0677000000")).toContain("without the leading 0");
    expect(whatsAppProblem("call me")).toContain("country code");
    expect(whatsAppProblem("237 677 000 000")).toBeNull();
    expect(whatsAppProblem("")).toBeNull();
  });
});

describe("client details step", () => {
  it("shows the error on this page and does not continue when the number is not a number", async () => {
    renderClientPage();
    await fillClient("call me");
    expect(await screen.findByText(/Enter the WhatsApp number with the country code/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "The client's details" })).toBeTruthy();
    expect(screen.queryByLabelText("Project title")).toBeNull();
  });

  it("refuses a number with a leading 0 on this page", async () => {
    renderClientPage();
    await fillClient("0677 000 000");
    expect(await screen.findByText(/without the leading 0/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "The client's details" })).toBeTruthy();
  });

  it("refuses an invalid e-mail on this page", async () => {
    renderClientPage();
    await fillClient("237 677 000 000", "not-an-email");
    expect(await screen.findByText(/valid e-mail address/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "The client's details" })).toBeTruthy();
  });

  it("continues when both details are valid", async () => {
    renderClientPage();
    await fillClient("237 677 000 000");
    expect(await screen.findByRole("heading", { name: "Create a client's project" })).toBeTruthy();
  });
});
