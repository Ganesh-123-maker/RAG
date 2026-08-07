import axios from "axios";
import Cookies from "js-cookie";

const BASE_URL = "";

export const api = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
});

export const authApi = () => {
  const token = Cookies.get("access_token");
  return axios.create({
    baseURL: BASE_URL,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
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
