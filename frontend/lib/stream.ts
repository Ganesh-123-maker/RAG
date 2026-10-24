import type { Citation } from "@/lib/api";

/** Structured SSE events emitted by POST /api/v1/chat/stream
 * (backend/app/routers/chat.py: status / token / citations /
 * done / error). This parser is pure and framework-free so it can
 * be unit-tested without a DOM or a network. */

export type StreamEvent =
  | { type: "status"; status: string }
  | { type: "token"; token: string }
  | { type: "citations"; citations: Citation[] }
  | { type: "done"; conversation_id?: string; answer?: string; citations?: Citation[] }
  | { type: "error"; error: string };

export interface StreamState {
  content: string;
  citations: Citation[];
  status: string;
  done: boolean;
  error: string | null;
}

export const emptyStreamState = (): StreamState => ({
  content: "",
  citations: [],
  status: "",
  done: false,
  error: null,
});

/** Pure reducer: apply one parsed event to the accumulated state.
 * Malformed/unknown events are ignored by the parser, never here. */
export function applyStreamEvent(state: StreamState, event: StreamEvent): StreamState {
  switch (event.type) {
    case "status":
      return { ...state, status: event.status };
    case "token":
      return { ...state, content: state.content + event.token };
    case "citations":
      return { ...state, citations: event.citations };
    case "done":
      return {
        ...state,
        content: event.answer ?? state.content,
        citations: event.citations ?? state.citations,
        status: "",
        done: true,
      };
    case "error":
      return { ...state, error: event.error };
  }
}

function parseDataLine(line: string): StreamEvent | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("data: ")) return null;
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(trimmed.slice(6)) as Record<string, unknown>;
  } catch {
    // Malformed line: drop it silently (matches prior behaviour
    // and keeps a single bad chunk from killing the stream).
    return null;
  }
  if (typeof data.status === "string" && !data.done) {
    return { type: "status", status: data.status };
  }
  if (typeof data.token === "string") {
    return { type: "token", token: data.token };
  }
  if (Array.isArray(data.citations) && !data.done) {
    return { type: "citations", citations: data.citations as Citation[] };
  }
  if (typeof data.error === "string") {
    return { type: "error", error: data.error };
  }
  if (data.done) {
    return {
      type: "done",
      conversation_id: typeof data.conversation_id === "string" ? data.conversation_id : undefined,
      answer: typeof data.answer === "string" ? data.answer : undefined,
      citations: Array.isArray(data.citations) ? (data.citations as Citation[]) : undefined,
    };
  }
  return null;
}

/** Incremental SSE parser: feed() accepts arbitrary byte-chunk
 * boundaries; a trailing partial line is held until flush(). */
export function createSseParser(onEvent: (event: StreamEvent) => void) {
  let buffer = "";
  return {
    feed(text: string): void {
      buffer += text;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const event = parseDataLine(line);
        if (event) onEvent(event);
      }
    },
    flush(): void {
      if (!buffer.trim()) return;
      const event = parseDataLine(buffer);
      buffer = "";
      if (event) onEvent(event);
    },
  };
}
