/**
 * Tiny typed fetch wrapper. Used by stores and components.
 *
 * Once ``npm run gen:api`` is run against a live backend the project can
 * migrate to ``openapi-fetch`` for end-to-end typing — for now we use the
 * hand-written DTOs in ``./types.ts``.
 */

/**
 * Base URL for the FastAPI server. Empty string → same-origin (works in dev
 * via Vite proxy and in prod when the SPA is served behind a reverse proxy
 * that forwards ``/api``). Set ``VITE_API_BASE_URL`` at build time when the
 * SPA is on a different host than the API, e.g. ``http://10.0.0.5:8000``.
 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

const TOKEN_KEY = "tds-admin-token";

/** Bearer token for admin-only routes (multipart / image fetch). */
export function adminAuthHeader(): Record<string, string> {
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Resolve a relative API path against ``API_BASE`` — for callers that
 * need to drive ``fetch`` directly (e.g. multipart uploads). */
export const apiUrl = (path: string): string => API_BASE + path;

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = { method, headers: { ...adminAuthHeader() } };
  if (body !== undefined) {
    if (body instanceof FormData) {
      init.body = body;
    } else {
      (init.headers as Record<string, string>)["Content-Type"] =
        "application/json";
      init.body = JSON.stringify(body);
    }
  }
  const res = await fetch(API_BASE + path, init);
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    sessionStorage.removeItem(TOKEN_KEY);
    if (
      typeof window !== "undefined" &&
      window.location.pathname.startsWith("/admin") &&
      !window.location.pathname.includes("/admin/login")
    ) {
      const redirect = encodeURIComponent(
        window.location.pathname + window.location.search,
      );
      window.location.assign(`/admin/login?redirect=${redirect}`);
    }
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail ?? data);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  // Some endpoints (preview) return non-JSON; callers that need binary should
  // not use this helper.
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};
