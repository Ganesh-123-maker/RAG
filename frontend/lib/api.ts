import axios, { type AxiosError } from "axios";

const BASE_URL = "";

// Phase F: a SINGLE axios instance for the whole app. Previously
// authApi() created a brand-new instance per call, so no interceptor
// could ever be shared. `authApi` is kept as an alias for the same
// instance so existing imports keep working.
//
// Auth is cookie-based (Phase E): the backend sets an httpOnly
// cookie on /auth/login and the browser sends it automatically on
// same-origin requests (withCredentials). JS never holds, reads,
// or writes a token — do not reintroduce js-cookie token handling.

export function getApiErrorMessage(err: unknown): string {
  const error = err as AxiosError<{ detail?: unknown }> | { response?: { data?: { detail?: unknown } } };
  const detail =
    (error as AxiosError<{ detail?: unknown }>)?.response?.data?.detail ??
    (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (err instanceof Error && err.message) return err.message;
  return "Something went wrong. Please try again.";
}

/** Pure redirect decision, unit-tested: a 401 on /login itself
 * must not redirect (that would loop); anywhere else it does. */
export function shouldRedirectOnUnauthorized(pathname: string): boolean {
  return pathname !== "/login";
}

/** Redirect to /login on a 401, unless already there. */
export function handleUnauthorized(): void {
  if (typeof window === "undefined") return;
  if (!shouldRedirectOnUnauthorized(window.location.pathname)) return;
  window.location.href = "/login";
}

export const api = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error?.response?.status === 401) {
      handleUnauthorized();
    }
    return Promise.reject(error);
  }
);

// Alias: same shared instance, not a fresh client per call.
export const authApi = () => api;

export const MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024;
export const ALLOWED_UPLOAD_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"] as const;

export interface Document {
  id: string;
  original_name: string;
  file_type: string;
  file_size_bytes: number;
  chunk_count: number;
  status: "queued" | "processing" | "ready" | "error";
  error_message: string | null;
  ingestion_progress?: number;
  ingestion_attempts?: number;
  created_at: string;
}

export interface Citation {
  document_id: string;
  document_name: string;
  chunk_index: number;
  score: number;
  snippet: string;
  chunk_id?: string;
  page?: number | null;
  section?: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  messages?: Message[];
}
