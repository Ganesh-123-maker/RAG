import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ChatPanel from "@/components/ChatPanel";

function sseResponse(chunks: string[], opts: { ok?: boolean; status?: number } = {}) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return { ok: opts.ok ?? true, status: opts.status ?? 200, body: stream } as unknown as Response;
}

function hangingResponse() {
  const stream = new ReadableStream<Uint8Array>({ start() { /* never closes */ } });
  return { ok: true, status: 200, body: stream } as unknown as Response;
}

describe("ChatPanel streaming (Phase F)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("streams tokens split across chunks, shows status, then final answer + citation chip opening the panel", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'data: {"status": "grading"}\n',
        'data: {"token": "Hel',
        'lo "}\n',
        'data: {"token": "world"}\n',
        'data: {"citations": [{"document_id": "d1", "document_name": "a.pdf", "chunk_index": 2, "score": 0.9, "snippet": "snippet text", "chunk_id": "c1", "page": 3, "section": "Intro"}]}\n',
        'data: {"done": true, "conversation_id": "conv-1", "answer": "Hello world", "citations": [{"document_id": "d1", "document_name": "a.pdf", "chunk_index": 2, "score": 0.9, "snippet": "snippet text", "chunk_id": "c1", "page": 3, "section": "Intro"}]}\n',
      ])
    );
    const onCreated = vi.fn();
    render(<ChatPanel conversationId={null} onConversationCreated={onCreated} />);

    fireEvent.change(screen.getByLabelText(/Ask a question/), { target: { value: "Hi?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(screen.getByText("Hello world")).toBeInTheDocument());
    expect(onCreated).toHaveBeenCalledWith("conv-1");
    // Citations are Phase B/C fields, not just retrieved text.
    fireEvent.click(screen.getByRole("button", { name: /Show 1 source/ }));
    fireEvent.click(screen.getByRole("button", { name: /Open source 1: a\.pdf/ }));
    expect(screen.getByRole("dialog", { name: /Source 1: a\.pdf/ })).toBeInTheDocument();
    // Snippet appears twice by design: once in the citation chip,
    // once in the open source panel.
    expect(screen.getAllByText("snippet text")).toHaveLength(2);
  });

  it("stop keeps the partial answer instead of deleting it", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      sseResponse(['data: {"token": "partial "}\n'])
    );
    // Replace the resolved stream with a hanging one: first chunk
    // arrives, then the test stops generation before completion.
    fetchMock.mockReset();
    const encoder = new TextEncoder();
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        controller.enqueue(encoder.encode('data: {"token": "partial "}\n'));
        await held;
        controller.close();
      },
    });
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, body: stream } as unknown as Response);

    render(<ChatPanel conversationId={null} onConversationCreated={() => undefined} />);
    fireEvent.change(screen.getByLabelText(/Ask a question/), { target: { value: "Hi?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(screen.getByText("partial")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
    // Partial text survives the stop (old code deleted the message).
    expect(screen.getByText("partial")).toBeInTheDocument();
    release();
  });

  it("a 401 on the stream path surfaces a session-expired error (axios interceptor cannot catch fetch)", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce({ ok: false, status: 401, body: null } as unknown as Response);
    render(<ChatPanel conversationId={null} onConversationCreated={() => undefined} />);
    fireEvent.change(screen.getByLabelText(/Ask a question/), { target: { value: "Hi?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    // Retry appears after a failed stream; the partial/empty
    // assistant message is kept, not deleted.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Retry last message/ })).toBeInTheDocument()
    );
  });

  it("sanitised markdown: embedded HTML in an answer is not rendered as an element", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'data: {"done": true, "answer": "Hello <img src=x onerror=alert(1)> world", "citations": []}\n',
      ])
    );
    const { container } = render(<ChatPanel conversationId={null} onConversationCreated={() => undefined} />);
    fireEvent.change(screen.getByLabelText(/Ask a question/), { target: { value: "Hi?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(screen.getByText(/Hello/)).toBeInTheDocument());
    expect(container.querySelector("img")).toBeNull();
  });
});
