import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import CitationPanel from "@/components/CitationPanel";

describe("CitationPanel", () => {
  it("shows document, page, section, chunk id, score, and snippet; close calls onClose", () => {
    const onClose = vi.fn();
    render(
      <CitationPanel
        index={0}
        onClose={onClose}
        citation={{
          document_id: "d1",
          document_name: "handbook.pdf",
          chunk_index: 4,
          score: 0.87,
          snippet: "The quick brown fox.",
          chunk_id: "chunk-abc",
          page: 12,
          section: "Safety",
        }}
      />
    );
    expect(screen.getByRole("dialog", { name: /Source 1: handbook\.pdf/ })).toBeInTheDocument();
    expect(screen.getByText(/Page 12/)).toBeInTheDocument();
    expect(screen.getByText("Safety")).toBeInTheDocument();
    expect(screen.getByText(/chunk-abc/)).toBeInTheDocument();
    expect(screen.getByText("87% match")).toBeInTheDocument();
    expect(screen.getByText("The quick brown fox.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close source panel" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("labels missing page/section as not recorded instead of blank", () => {
    render(
      <CitationPanel
        index={1}
        onClose={() => undefined}
        citation={{ document_id: "d2", document_name: "notes.txt", chunk_index: 0, score: 0.5, snippet: "x" }}
      />
    );
    expect(screen.getAllByText("Not recorded")).toHaveLength(2);
  });
});
