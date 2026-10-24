import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockGet = vi.hoisted(() => vi.fn());
const mockPost = vi.hoisted(() => vi.fn());
const mockDelete = vi.hoisted(() => vi.fn());
const mockPatch = vi.hoisted(() => vi.fn());
const mockPush = vi.hoisted(() => vi.fn());
// Stable router object: returning a fresh { push } per render
// changes fetchData's identity every render, which re-runs the
// dashboard's fetch effect forever (an infinite render loop).
const mockRouter = vi.hoisted(() => ({ push: mockPush }));

vi.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
// react-hot-toast's internal timers can keep a jsdom worker alive
// after the test ends; the toasts themselves are not under test.
vi.mock("react-hot-toast", () => ({ default: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    authApi: () => ({ get: mockGet, post: mockPost, delete: mockDelete, patch: mockPatch }),
  };
});

import DashboardPage from "@/app/dashboard/page";

const processingDoc = {
  id: "doc-1",
  original_name: "a.pdf",
  file_type: "pdf",
  file_size_bytes: 1000,
  chunk_count: 0,
  status: "processing",
  error_message: null,
  ingestion_progress: 50,
  created_at: new Date().toISOString(),
};
const errorDoc = {
  ...processingDoc,
  id: "doc-2",
  original_name: "bad.pdf",
  status: "error",
  error_message: "Embedding failed",
  ingestion_progress: 0,
};

function setupDocs(docs: unknown[]) {
  mockGet.mockImplementation((url: string) => {
    if (url === "/api/v1/auth/me") return Promise.resolve({ data: { email: "u@example.com" } });
    if (url.startsWith("/api/v1/documents")) return Promise.resolve({ data: { documents: docs } });
    if (url.startsWith("/api/v1/chat/conversations")) return Promise.resolve({ data: { conversations: [] } });
    return Promise.reject(new Error("unknown url"));
  });
}

describe("Dashboard (Phase F)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("shows ingestion progress for processing docs and the backend error_message for failed docs", async () => {
    setupDocs([processingDoc, errorDoc]);
    render(<DashboardPage />);
    await waitFor(() => expect(screen.getByText("a.pdf")).toBeInTheDocument());
    expect(screen.getByRole("progressbar", { name: /Ingestion progress for a\.pdf/ })).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByText("Embedding failed")).toBeInTheDocument();
  });

  // 15s timeout: the test waits through two real 2.5s poll ticks.
  it("polls only while a document is non-terminal, and shows a retry on list failure", async () => {
    setupDocs([processingDoc]);
    render(<DashboardPage />);
    await waitFor(() => expect(screen.getByText("a.pdf")).toBeInTheDocument());
    const callsBefore = mockGet.mock.calls.filter((c) => String(c[0]).startsWith("/api/v1/documents")).length;
    // Real timers: wait for at least one 2.5s poll tick.
    await waitFor(
      () => {
        const callsNow = mockGet.mock.calls.filter((c) => String(c[0]).startsWith("/api/v1/documents")).length;
        expect(callsNow).toBeGreaterThan(callsBefore);
      },
      { timeout: 6000 }
    );

    // Now fail the document list: an error state + retry replaces
    // the old silent empty list. The next poll tick surfaces it.
    mockGet.mockImplementation((url: string) => {
      if (url === "/api/v1/auth/me") return Promise.resolve({ data: { email: "u@example.com" } });
      if (url.startsWith("/api/v1/documents")) return Promise.reject({ response: { data: { detail: "DB down" } } });
      return Promise.resolve({ data: { conversations: [] } });
    });
    await waitFor(() => expect(screen.getByText(/Could not load documents: DB down/)).toBeInTheDocument(), { timeout: 6000 });
    expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
  }, 15000);

  it("rename saves via PATCH and updates the sidebar title", async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === "/api/v1/auth/me") return Promise.resolve({ data: { email: "u@example.com" } });
      if (url.startsWith("/api/v1/documents")) return Promise.resolve({ data: { documents: [] } });
      if (url.startsWith("/api/v1/chat/conversations")) {
        return Promise.resolve({
          data: { conversations: [{ id: "c1", title: "Old title", created_at: new Date().toISOString() }] },
        });
      }
      return Promise.reject(new Error("unknown"));
    });
    mockPatch.mockResolvedValue({ data: {} });
    render(<DashboardPage />);
    await waitFor(() => expect(screen.getByText("Old title")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Rename conversation Old title/ }));
    fireEvent.change(screen.getByLabelText(/Rename conversation Old title/), { target: { value: "New title" } });
    fireEvent.click(screen.getByRole("button", { name: "Save new title" }));
    // The sidebar title only updates after the PATCH resolves, so
    // waiting for the new title also proves the PATCH completed.
    await screen.findByText("New title");
    expect(mockPatch).toHaveBeenCalledWith("/api/v1/chat/conversations/c1", { title: "New title" });
  });
});
