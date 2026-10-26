import { readApiError } from "./errors";
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
export const STATION_TOKEN_KEY = "tds-station-token";

export function stationAuthHeader(): Record<string, string> {
  const token = sessionStorage.getItem(STATION_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function isStationRequest(path: string): boolean {
  return /^\/api\/(cart(?:[/?]|$)|print(?:[?]|$)|station-auth\/me(?:[?]|$)|labels\/\d+\/preview(?:[?]|$))/.test(path);
}

export function requestAuthHeader(path: string): Record<string, string> {
  if (isStationRequest(path)) return stationAuthHeader();
  if (path.startsWith("/api/station-auth/")) return {};
  return adminAuthHeader();
}

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
  const authHeader = requestAuthHeader(path);
  const init: RequestInit = { method, headers: { ...authHeader } };
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
  if (res.status === 401 && authHeader.Authorization === requestAuthHeader(path).Authorization && !path.startsWith("/api/auth/") && !["/api/station-auth/login", "/api/station-auth/status"].includes(path)) {
    sessionStorage.removeItem(isStationRequest(path) ? STATION_TOKEN_KEY : TOKEN_KEY);
    if (isStationRequest(path) && typeof window !== "undefined" && ["/", "/kiosk"].includes(window.location.pathname)) {
      window.location.assign(`/login?redirect=${encodeURIComponent(window.location.pathname)}`);
    }
    if (!isStationRequest(path) && (
      typeof window !== "undefined" &&
      window.location.pathname.startsWith("/admin") &&
      !window.location.pathname.includes("/admin/login")
    )) {
      const redirect = encodeURIComponent(
        window.location.pathname + window.location.search,
      );
      window.location.assign(`/admin/login?redirect=${redirect}`);
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, await readApiError(res));
  }
  if (res.status === 204) return undefined as T;
  // Some endpoints (preview) return non-JSON; callers that need binary should
  // not use this helper.
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};
