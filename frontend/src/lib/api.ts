/**
 * DataExtraction — Unified API Client
 * Enterprise HTTP client with JWT authentication, error handling,
 * and memory-safe streaming file downloads.
 */

function resolveApiUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";
  const trimmed = raw.trim().replace(/\/+$/, "");
  return trimmed.endsWith("/api") ? trimmed : `${trimmed}/api`;
}

const API_URL = resolveApiUrl();

const TOKEN_KEY = "dataextraction_token";
const USER_KEY = "dataextraction_user";
const LEGACY_TOKEN_KEYS = ["oneextraction_token", "prospex_token"];
const LEGACY_USER_KEYS = ["oneextraction_user", "prospex_user"];
const LEGACY_PLACEHOLDER_TOKEN = "dataextraction-admin-session-active";

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
  if (token === LEGACY_PLACEHOLDER_TOKEN) {
    localStorage.removeItem(TOKEN_KEY);
    return null;
  }
  return token;
}

/** Appends the auth token as ?token= (EventSource cannot send an Authorization header). */
export function withAuthToken(url: string): string {
  const token = getToken();
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
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

  const timeoutMs = options?.timeoutMs ?? 15000;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const url = /^https?:\/\//i.test(path) ? path : `${API_URL}${path}`;
    const res = await fetch(url, {
      ...options,
      headers,
      signal: options?.signal || controller.signal,
    });
    clearTimeout(timeoutId);

    if (res.status === 401) {
      clearAuth();
      throw new Error("Unauthorized. Access denied (HTTP 401).");
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
      throw new Error("Unauthorized. Download access denied (HTTP 401).");
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

  discovery: {
    initSearch: (query: string, filters: DiscoverySearchOptions = {}, budgetSeconds = 45.0) => {
      const baseUrl = API_URL.replace(/\/api$/, "");
      return request<{ search_id: string; query: string; stream_url: string }>(
        `${baseUrl}/api/v1/discovery/search`,
        {
          method: "POST",
          body: JSON.stringify({ query, filters, budget_seconds: budgetSeconds }),
        }
      );
    },
    getSearchResult: (searchId: string) => {
      const baseUrl = API_URL.replace(/\/api$/, "");
      return request<{ search_id: string; status: string; answer?: DiscoveryAnswer }>(
        `${baseUrl}/api/v1/discovery/search/${encodeURIComponent(searchId)}`
      );
    },
    getSourcesStatus: () => {
      const baseUrl = API_URL.replace(/\/api$/, "");
      return request<Array<{ source: string; status: string; type: string }>>(
        `${baseUrl}/api/v1/discovery/sources/status`
      );
    },
    getStreamUrl: (searchId: string) => {
      const baseUrl = API_URL.replace(/\/api$/, "");
      return withAuthToken(`${baseUrl}/api/v1/discovery/search/${encodeURIComponent(searchId)}/stream`);
    },
    getOrganization: (orgId: string) => {
      const baseUrl = API_URL.replace(/\/api$/, "");
      return request<DiscoveryOrganization>(`${baseUrl}/api/v1/discovery/organizations/${encodeURIComponent(orgId)}`);
    },
    exportUrl: (searchId: string, format: "csv" | "jsonl") => {
      const baseUrl = API_URL.replace(/\/api$/, "");
      return `${baseUrl}/api/v1/discovery/search/${encodeURIComponent(searchId)}/export?format=${format}`;
    },
  },
};

export interface DiscoveryCard {
  org_id: string;
  name: string;
  category?: string;
  address: Record<string, any>;
  phone?: string;
  phones: string[];
  website?: string;
  hours: Array<Record<string, any>>;
  social: Record<string, string>;
  source_links: Array<{ source: string; url: string }>;
  rating?: number;
  review_count?: number;
  services: string[];
  cms_star_rating?: number;
  cms_ownership?: string;
  nc_license_number?: string;
  nc_license_status?: string;
  named_people: Array<{
    name: string;
    title?: string;
    role_type?: string;
    emails: Array<{ value: string; label: string; confidence: number }>;
    phones: string[];
    profile_urls: string[];
  }>;
  emails: Array<{ value: string; label: string; confidence: number }>;
  sources: string[];
  citation_ids: number[];
}

export interface DiscoveryCitation {
  id: number;
  source: string;
  url?: string;
  entity_name: string;
  fact_description: string;
}

export interface DiscoverySourceStatus {
  source: string;
  status: "ok" | "empty" | "blocked" | "error" | "unavailable" | "timeout" | "running";
  count: number;
  elapsed_ms: number;
  message?: string;
}

export interface DiscoveryAnswer {
  query: string;
  total_organizations: number;
  total_people: number;
  summary_markdown: string;
  source_breakdown: Record<string, number>;
  shown_organizations: number;
  needs_location: boolean;
  message?: string | null;
  geography: Record<string, any>;
  cards: DiscoveryCard[];
  citations: DiscoveryCitation[];
  source_statuses: DiscoverySourceStatus[];
  elapsed_ms: number;
}
/** Merged cards received so far while a search is still running (ids are not final; no citations yet). */
export interface DiscoverySnapshot {
  total_organizations: number;
  total_people: number;
  cards: DiscoveryCard[];
  elapsed_ms: number;
  sources_done: number;
  preliminary: boolean;
}

export interface DiscoverySearchOptions {
  /** 1-1000 */
  max_results?: number;
  /** "internet" skips the saved database; "all" also includes previously saved results */
  sources?: "all" | "internet";
  /** false = fast search without reading company websites */
  crawl_websites?: boolean;
  include_unverified?: boolean;
}
export interface DiscoveryFact {
  field: string;
  value: any;
  source: string;
  source_url?: string | null;
  confidence: number;
  retrieved_at?: string | null;
}
export interface DiscoveryOrganization {
  id: string;
  name: string;
  category?: string;
  subcategories: string[];
  address: Record<string, any>;
  coordinates: { lat?: number; lng?: number };
  phones: Array<{ number: string; source_url?: string }>;
  emails: Array<{ value: string; label: string; source_url?: string }>;
  website?: string;
  hours: Array<Record<string, any>>;
  rating?: number;
  review_count?: number;
  services: string[];
  regulatory: Record<string, any>;
  social: Record<string, string>;
  people: Array<{ id: string; name: string; title?: string; role_type?: string; verified: boolean; provenance: string;
    emails: Array<{ value: string; label: string }>; profile_urls: string[] }>;
  facts: DiscoveryFact[];
  first_seen?: string;
  last_seen?: string;
}

// ── B2B AI Chatbot Interfaces & API Methods ─────────────────────────────────

export interface ChatSession {
  id: string;
  user_id: string;
  title: string;
  context: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface ChatCompany {
  company_id: string;
  company_name: string;
  canonical_name?: string;
  industry?: string;
  website?: string;
  domain?: string;
  phone?: string;
  phones?: Array<{ number: string; type?: string }>;
  email?: string;
  emails?: Array<{ value: string; label?: string }>;
  address_street?: string;
  address_city?: string;
  address_state?: string;
  address_postal_code?: string;
  address_country?: string;
  executive?: string;
  rating?: number;
  review_count?: number;
  services?: string[];
  lead_score?: number;
  email_status?: string;
  origin?: string;
  pending_review?: boolean;
  website_pending_review?: boolean;
  phone_pending_review?: boolean;
  email_pending_review?: boolean;
  executive_pending_review?: boolean;
  phone_conflict?: { database: string; discovered: string };
  email_conflict?: { database: string; discovered: string };
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  structured_plan?: Record<string, any>;
  completeness_report?: Record<string, any>;
  results_summary?: Record<string, any>;
  companies?: ChatCompany[];
  created_at: string;
}

export const chatApi = {
  createSession: (title?: string) =>
    api.post<ChatSession>("/v1/chat/sessions", { title: title || "New Conversation" }),

  listSessions: (limit: number = 50) =>
    api.get<ChatSession[]>(`/v1/chat/sessions?limit=${limit}`),

  getSession: (id: string) =>
    api.get<ChatSession>(`/v1/chat/sessions/${id}`),

  deleteSession: (id: string) =>
    api.delete<void>(`/v1/chat/sessions/${id}`),

  getHistory: (sessionId: string) =>
    api.get<ChatMessage[]>(`/v1/chat/sessions/${sessionId}/history`),

  sendMessage: (sessionId: string, content: string) =>
    api.post<any>(`/v1/chat/sessions/${sessionId}/messages`, { content }),

  cancelExecution: (sessionId: string) =>
    api.post<any>(`/v1/chat/sessions/${sessionId}/cancel`, {}),

  getStreamUrl: (sessionId: string, prompt: string) => {
    const rawUrl = `${API_URL}/v1/chat/sessions/${sessionId}/stream?prompt=${encodeURIComponent(prompt)}`;
    return withAuthToken(rawUrl);
  },
};
