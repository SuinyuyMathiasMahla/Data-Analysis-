import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { SendReportToClient } from "../components/ClientWhatsApp";
import { ClientInfoForm, ProjectForm, ProjectTypeChoice } from "../pages/Projects";
import { api } from "../services/api";
import { isValidWhatsApp, normaliseWhatsApp, whatsappChatUrl } from "../utils/whatsapp";

vi.mock("../services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/api")>();
  return { ...actual, api: { ...actual.api, post: vi.fn(), blob: vi.fn() } };
});

function renderFlow(path = "/projects/new") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects/new" element={<ProjectTypeChoice />} />
        <Route path="/projects/new/client" element={<ClientInfoForm />} />
        <Route path="/projects/new/details" element={<ProjectForm />} />
        <Route path="/projects/:projectId" element={<p>Project page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("creating a project", () => {
  it("takes a personal project straight to the project form, with no client section", async () => {
    renderFlow();
    await userEvent.click(screen.getByRole("link", { name: /Personal project/ }));
    expect(await screen.findByRole("heading", { name: "Create a research project" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "The client" })).toBeNull();
  });

  it("asks for the client's details first for a client's project, then hands them to the project form", async () => {
    renderFlow();
    await userEvent.click(screen.getByRole("link", { name: /Client's project/ }));
    await userEvent.type(await screen.findByLabelText(/Client's name/), "Mbah Consulting");
    await userEvent.type(screen.getByLabelText(/Client's e-mail/), "contact@mbah.example");
    await userEvent.type(screen.getByLabelText(/Client's WhatsApp number/), "237 677 000 000");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("heading", { name: "The client" })).toBeTruthy();
    expect((screen.getByLabelText(/Client's name/) as HTMLInputElement).value).toBe("Mbah Consulting");
    expect((screen.getByLabelText(/Client's WhatsApp number/) as HTMLInputElement).value).toBe("237 677 000 000");
    expect(screen.getByRole("link", { name: "Chat with Mbah Consulting on WhatsApp" }).getAttribute("href")).toBe("https://wa.me/237677000000");
  });

  it("sends the client's details with the new project", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ id: 9 });
    renderFlow("/projects/new/client");
    await userEvent.type(screen.getByLabelText(/Client's name/), "Mbah Consulting");
    await userEvent.type(screen.getByLabelText(/Client's e-mail/), "contact@mbah.example");
    await userEvent.type(screen.getByLabelText(/Client's WhatsApp number/), "+237 677-00-00-00");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.type(await screen.findByLabelText("Project title"), "Staff survey for Mbah Consulting");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/projects", expect.objectContaining({
      project_type: "client", client_name: "Mbah Consulting", client_email: "contact@mbah.example", client_whatsapp: "+237 677-00-00-00",
    })));
    expect(await screen.findByText("Project page")).toBeTruthy();
  });

  it("sends the personal project type and no client details", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ id: 3 });
    renderFlow("/projects/new/details?type=personal");
    await userEvent.type(await screen.findByLabelText("Project title"), "My thesis project");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/projects", expect.objectContaining({ project_type: "personal" })));
    const calls = vi.mocked(api.post).mock.calls;
    const body = calls[calls.length - 1][1] as Record<string, unknown>;
    expect(body).not.toHaveProperty("client_name");
  });

  it("sends a client's project back to the client page when the details were not handed over", async () => {
    renderFlow("/projects/new/details?type=client");
    expect(await screen.findByRole("heading", { name: "The client's details" })).toBeTruthy();
  });
});

describe("WhatsApp helpers", () => {
  it("keeps only the digits of a number and checks its length", () => {
    expect(normaliseWhatsApp("+237 677-00 (00) 00")).toBe("237677000000");
    expect(isValidWhatsApp("237 677 000 000")).toBe(true);
    expect(isValidWhatsApp("677")).toBe(false);
    expect(isValidWhatsApp("call me")).toBe(false);
  });

  it("builds a chat link with the message typed in", () => {
    expect(whatsappChatUrl("+237 677 000 000", "Hello & welcome")).toBe("https://wa.me/237677000000?text=Hello%20%26%20welcome");
  });
});

describe("SendReportToClient", () => {
  it("falls back to a download and a chat link where the device cannot share files", async () => {
    vi.mocked(api.blob).mockResolvedValueOnce(new Blob(["pdf"], { type: "application/pdf" }));
    globalThis.URL.createObjectURL = vi.fn(() => "blob:report");
    globalThis.URL.revokeObjectURL = vi.fn();
    render(<SendReportToClient clientName="Mbah Consulting" clientNumber="237677000000" projectTitle="Staff survey"
                               downloadUrl="/api/reports/4/download?version=1" filename="Staff survey_v1.pdf" />);
    await userEvent.click(screen.getByRole("button", { name: "Send to Mbah Consulting on WhatsApp" }));
    const chat = await screen.findByRole("link", { name: "Open the chat with Mbah Consulting" });
    expect(chat.getAttribute("href")).toBe(whatsappChatUrl("237677000000", 'Dear Mbah Consulting, please find attached the report for "Staff survey".'));
    expect(api.blob).toHaveBeenCalledWith("/reports/4/download?version=1");
  });
});
