import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import AppLayout from "../layouts/AppLayout";
import { Login } from "../pages/public/Auth";
import { api, ApiError, storeTokens } from "../services/api";
import { AuthProvider } from "../services/auth";

const USER = { id: 1, email: "ada@example.org", full_name: "Ada Lovelace", institution: null, department: null, academic_level: "masters", is_active: true,
  is_email_verified: true, roles: ["researcher"], permissions: ["project.manage_own", "ai.use"], last_login_at: null, created_at: null };
const TOKENS = { access_token: "access-1", refresh_token: "refresh-1", expires_in: 1800, token_type: "bearer", user: USER };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderApp(start: string) {
  return render(
    <MemoryRouter initialEntries={[start]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<AppLayout />}>
            <Route path="/dashboard" element={<h1>Dashboard page</h1>} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("authentication flow", () => {
  it("redirects a visitor without a session from a protected page to sign-in", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ error: { code: "unauthorized", message: "Sign in to continue." } }, 401));
    renderApp("/dashboard");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText("Dashboard page")).not.toBeInTheDocument();
  });

  it("signs in and opens the dashboard", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/login")) return json(TOKENS);
      if (url.includes("/notifications")) return json({ notifications: [], unread: 0 });
      return json({ error: { code: "not_found", message: "Not found." } }, 404);
    });
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("E-mail address"), "ada@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "Str0ngPassword!x");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Dashboard page")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    const login = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/auth/login"));
    expect(JSON.parse(String(login?.[1]?.body))).toEqual({ email: "ada@example.org", password: "Str0ngPassword!x" });
    expect(localStorage.getItem("arda.refresh_token")).toBe("refresh-1");
  });

  it("shows the server's message when the password is wrong", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ error: { code: "invalid_credentials", message: "The e-mail address or password is incorrect." } }, 401));
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("E-mail address"), "ada@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The e-mail address or password is incorrect.");
  });
});

describe("API client", () => {
  it("sends the access token and retries once after refreshing an expired session", async () => {
    storeTokens({ ...TOKENS, access_token: "expired" } as never);
    const seen: (string | null)[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) return json({ ...TOKENS, access_token: "fresh", refresh_token: "refresh-2" });
      const header = new Headers(init?.headers).get("Authorization");
      seen.push(header);
      return header === "Bearer fresh" ? json({ projects: [] }) : json({ error: { code: "token_invalid", message: "Expired." } }, 401);
    });
    await expect(api.get("/projects")).resolves.toEqual({ projects: [] });
    expect(seen).toEqual(["Bearer expired", "Bearer fresh"]);
    await waitFor(() => expect(localStorage.getItem("arda.refresh_token")).toBe("refresh-2"));
  });

  it("turns error responses into ApiError with the server's code and message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ error: { code: "analysis_error", message: "Choose two different variables.", details: null } }, 422));
    const error = (await api.post("/projects/1/analysis", {}).catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("analysis_error");
    expect(error.message).toBe("Choose two different variables.");
  });

  it("reports an unreachable server in plain language", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.get("/health")).rejects.toThrow(/could not be reached/);
  });
});
