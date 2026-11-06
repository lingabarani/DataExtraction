/**
 * DataExtraction — Unified API Client
 * Enterprise HTTP client with JWT authentication, error handling,
 * and memory-safe streaming file downloads.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001/api";

const TOKEN_KEY = "dataextraction_token";
const USER_KEY = "dataextraction_user";
const LEGACY_TOKEN_KEYS = ["oneextraction_token", "prospex_token"];
const LEGACY_USER_KEYS = ["oneextraction_user", "prospex_user"];

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  let token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    for (const legacyKey of LEGACY_TOKEN_KEYS) {
      const legacyToken = localStorage.getItem(legacyKey);
      if (legacyToken) {
        localStorage.setItem(TOKEN_KEY, legacyToken);
        localStorage.removeItem(legacyKey);
        token = legacyToken;
        break;
      }
    }
  }
  return token;
}

export function clearAuth(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  LEGACY_TOKEN_KEYS.forEach((k) => localStorage.removeItem(k));
  LEGACY_USER_KEYS.forEach((k) => localStorage.removeItem(k));
}

export function setAuth(token: string, user: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  LEGACY_TOKEN_KEYS.forEach((k) => localStorage.removeItem(k));
  LEGACY_USER_KEYS.forEach((k) => localStorage.removeItem(k));
}

export interface ApiRequestOptions extends RequestInit {
  timeoutMs?: number;
}

async function request<T>(path: string, options?: ApiRequestOptions): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options?.headers as Record<string, string>),
  };

  const timeoutMs = options?.timeoutMs ?? 2500;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
      signal: options?.signal || controller.signal,
    });
    clearTimeout(timeoutId);

    if (res.status === 401) {
      clearAuth();
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
      throw new Error("Unauthorized. Please log in again.");
    }

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      let message = `Request failed with status ${res.status}`;
      if (typeof error.detail === "string") {
        message = error.detail;
      } else if (Array.isArray(error.detail)) {
        message = error.detail
          .map((d: any) => d.msg || d.message || (typeof d === "string" ? d : JSON.stringify(d)))
          .join("; ");
      } else if (error.detail && typeof error.detail === "object") {
        message = error.detail.message || error.detail.msg || JSON.stringify(error.detail);
      } else if (error.message) {
        message = error.message;
      }
      throw new Error(message);
    }

    return res.json();
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error(`API request to ${path} timed out after ${timeoutMs}ms`);
    }
    throw err;
  }
}

export const api = {
  get: <T>(path: string, options?: ApiRequestOptions) =>
    request<T>(path, { method: "GET", ...options }),

  post: <T>(path: string, body: unknown, options?: ApiRequestOptions) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body), ...options }),

  put: <T>(path: string, body: unknown, options?: ApiRequestOptions) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body), ...options }),

  patch: <T>(path: string, body: unknown, options?: ApiRequestOptions) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body), ...options }),

  delete: <T>(path: string, options?: ApiRequestOptions) =>
    request<T>(path, { method: "DELETE", ...options }),

  /**
   * Fetches a file stream with authentication headers and initiates safe browser download.
   */
  async download(path: string, filename: string): Promise<void> {
    const token = getToken();
    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

    const res = await fetch(`${API_URL}${path}`, { headers });

    if (res.status === 401) {
      clearAuth();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
      return;
    }

    if (!res.ok) {
      throw new Error(`Download failed with status: HTTP ${res.status}`);
    }

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    // Defer revocation so browser completes save dialog
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 1500);
  },

  /**
   * Subscribes to a real-time Server-Sent Events (SSE) telemetry stream.
   * Eliminates client polling thrashing and returns an unsubscribe cleanup function.
   */
  subscribeToStream(
    path: string,
    onMessage: (event: { type: string; data: any }) => void,
    onError?: (error: any) => void
  ): () => void {
    if (typeof window === "undefined") {
      return () => {};
    }
    const token = getToken();
    const delimiter = path.includes("?") ? "&" : "?";
    const url = `${API_URL}${path}${token ? `${delimiter}token=${encodeURIComponent(token)}` : ""}`;
    const eventSource = new EventSource(url);

    eventSource.addEventListener("telemetry", (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data);
        onMessage({ type: "telemetry", data: parsed });
      } catch {
        onMessage({ type: "telemetry", data: event.data });
      }
    });

    eventSource.addEventListener("done", (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data);
        onMessage({ type: "done", data: parsed });
      } catch {
        onMessage({ type: "done", data: event.data });
      }
      eventSource.close();
    });

    eventSource.onerror = (err) => {
      if (onError) onError(err);
    };

    return () => {
      eventSource.close();
    };
  },
};
