import { describe, it, expect } from "vitest";
import {
  createSseParser,
  applyStreamEvent,
  emptyStreamState,
  type StreamEvent,
} from "@/lib/stream";

describe("SSE parser (Phase F, backend stream contract)", () => {
  it("handles tokens split across fetch chunks and a partial final line on flush", () => {
    const events: StreamEvent[] = [];
    const parser = createSseParser((e) => events.push(e));
    parser.feed('data: {"status": "grading"}\n');
    parser.feed('data: {"token": "Hel');
    parser.feed('lo "}\n');
    parser.feed('data: {"token": "world"}'); // no newline yet: held
    expect(events.map((e) => e.type)).toEqual(["status", "token"]);
    parser.flush();
    expect(events.map((e) => e.type)).toEqual(["status", "token", "token"]);
    const state = events.reduce(applyStreamEvent, emptyStreamState());
    expect(state.content).toBe("Hello world");
    expect(state.status).toBe("grading");
  });

  it("drops malformed lines without killing the stream", () => {
    const events: StreamEvent[] = [];
    const parser = createSseParser((e) => events.push(e));
    parser.feed('data: not-json\ndata: {"token": "ok"}\nnot-a-data-line\n');
    expect(events).toEqual([{ type: "token", token: "ok" }]);
  });

  it("applies status/token/citations/done/error in order; done wins over streamed text", () => {
    let state = emptyStreamState();
    state = applyStreamEvent(state, { type: "status", status: "verifying" });
    state = applyStreamEvent(state, { type: "token", token: "draft " });
    state = applyStreamEvent(state, {
      type: "citations",
      citations: [{ document_id: "d1", document_name: "a.pdf", chunk_index: 2, score: 0.9, snippet: "s", chunk_id: "c1", page: 3, section: "Intro" }],
    });
    state = applyStreamEvent(state, { type: "error", error: "boom" });
    state = applyStreamEvent(state, { type: "done", answer: "final", citations: state.citations });
    expect(state.content).toBe("final");
    expect(state.citations[0].page).toBe(3);
    expect(state.citations[0].section).toBe("Intro");
    expect(state.done).toBe(true);
    expect(state.error).toBe("boom");
  });
});
