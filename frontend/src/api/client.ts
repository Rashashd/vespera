/**
 * Typed fetch wrapper.  Attaches Authorization: Bearer <token> on every request.
 * On a 401 response it broadcasts an AUTH_EXPIRED event so AuthContext can clear the session.
 */

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function getToken(): string | null {
  return localStorage.getItem("pantera_token");
}

export async function apiClient<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const resp = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (resp.status === 401) {
    window.dispatchEvent(new Event("AUTH_EXPIRED"));
    throw new ApiError(401, "Session expired");
  }

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = body?.detail ?? detail;
    } catch {}
    throw new ApiError(resp.status, detail);
  }

  if (resp.status === 204) {
    return undefined as T;
  }

  return resp.json() as Promise<T>;
}

// Convenience helpers
export const get = <T>(path: string) => apiClient<T>(path);
export const post = <T>(path: string, body?: unknown) =>
  apiClient<T>(path, {
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
export const patch = <T>(path: string, body?: unknown) =>
  apiClient<T>(path, {
    method: "PATCH",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
export const del = <T>(path: string) => apiClient<T>(path, { method: "DELETE" });
