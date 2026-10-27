// Fetch-based API client.
//
// Session handling: the short-lived access token is kept in memory only. The
// refresh token is kept in localStorage so a page reload does not sign the
// user out; it is rotated on every use and revoked on sign-out (the server
// detects re-use of an old token and closes every session).
import type { Tokens } from "../types";

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000/api";
const REFRESH_KEY = "arda.refresh_token";

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let accessToken: string | null = null;
let refreshing: Promise<Tokens | null> | null = null;
let onSessionEnd: (() => void) | null = null;

export function setSessionEndHandler(handler: (() => void) | null): void {
  onSessionEnd = handler;
}

export function storeTokens(tokens: Tokens | null): void {
  accessToken = tokens ? tokens.access_token : null;
  try {
    if (tokens) localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
    else localStorage.removeItem(REFRESH_KEY);
  } catch {
    /* storage unavailable (private mode): the session lasts until reload */
  }
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

async function toError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    if (body && body.error) return new ApiError(response.status, body.error.code, body.error.message, body.error.details);
  } catch {
    /* not JSON */
  }
  return new ApiError(response.status, "http_error", `The server answered with an error (${response.status}).`);
}

/** Exchange the stored refresh token for a new session. Concurrent callers share one request. */
export function refreshSession(): Promise<Tokens | null> {
  if (refreshing) return refreshing;
  const token = getRefreshToken();
  if (!token) return Promise.resolve(null);
  refreshing = fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: token }),
  })
    .then(async (response) => {
      if (!response.ok) {
        storeTokens(null);
        return null;
      }
      const tokens = (await response.json()) as Tokens;
      storeTokens(tokens);
      return tokens;
    })
    .catch(() => null)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function send(path: string, init: RequestInit, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "network_error", "The server could not be reached. Check that the backend is running and try again.");
  }
  if (response.status === 401 && retry && !path.startsWith("/auth/")) {
    const tokens = await refreshSession();
    if (tokens) return send(path, init, false);
    if (onSessionEnd) onSessionEnd();
  }
  if (!response.ok) throw await toError(response);
  return response;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return body === undefined
    ? { method }
    : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const api = {
  get: async <T>(path: string): Promise<T> => (await send(path, { method: "GET" })).json(),
  post: async <T>(path: string, body?: unknown): Promise<T> => (await send(path, jsonInit("POST", body ?? {}))).json(),
  put: async <T>(path: string, body?: unknown): Promise<T> => (await send(path, jsonInit("PUT", body ?? {}))).json(),
  del: async <T>(path: string): Promise<T> => (await send(path, { method: "DELETE" })).json(),
  upload: async <T>(path: string, form: FormData): Promise<T> => (await send(path, { method: "POST", body: form })).json(),
  blob: async (path: string): Promise<Blob> => (await send(path, { method: "GET" })).blob(),
  postBlob: async (path: string, body?: unknown): Promise<Blob> => (await send(path, jsonInit("POST", body ?? {}))).blob(),
};

/** `/api/...` paths returned by the backend (image_url, download_url) -> path relative to API_URL. */
export function relative(path: string): string {
  return path.startsWith("/api/") ? path.slice(4) : path;
}

/** Download a protected file (the Authorization header cannot be sent by a plain link). */
export async function download(path: string, filename: string): Promise<void> {
  const blob = await api.blob(relative(path));
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
