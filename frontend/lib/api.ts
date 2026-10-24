import axios from "axios";
const BASE_URL = "";

export const api = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

// Phase E: no JS token handling. The backend sets an httpOnly
// cookie on /auth/login; the browser sends it automatically on
// same-origin requests (withCredentials), so JS never holds the
// token and cannot leak it via XSS. Bearer auth is still
// supported server-side for non-browser API clients.
export const authApi = () => {
  return axios.create({
    baseURL: BASE_URL,
    headers: { "Content-Type": "application/json" },
    withCredentials: true,
  });
};

export interface Document {
  id: string;
  original_name: string;
  file_type: string;
  file_size_bytes: number;
  chunk_count: number;
  status: "processing" | "ready" | "error";
  error_message: string | null;
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
