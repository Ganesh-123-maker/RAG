import { test, expect } from "@playwright/test";

/**
 * Signup -> upload -> ask -> cited answer.
 *
 * Run: E2E_RUN=1 npx playwright test   (browsers must be installed:
 * `npx playwright install chromium` — NOT run in this sandbox, see
 * docs/phase-f-report.md).
 *
 * No real OpenAI key is required in either mode: the chat stream
 * is always intercepted with a canned SSE answer. Auth/upload are
 * intercepted too when E2E_MOCK_API=1 (default); set
 * E2E_MOCK_API=0 to exercise a real backend from the docker stack
 * for signup/upload while still mocking only the LLM stream.
 */
const MOCK_API = process.env.E2E_MOCK_API !== "0";
const SSE =
  'data: {"status": "grading"}\n\n' +
  'data: {"token": "The handbook says "}\n\n' +
  'data: {"token": "safety first."}\n\n' +
  'data: {"done": true, "conversation_id": "conv-e2e", "answer": "The handbook says safety first.", "citations": [{"document_id": "doc-e2e", "document_name": "handbook.pdf", "chunk_index": 1, "score": 0.92, "snippet": "safety first", "chunk_id": "chunk-e2e", "page": 2, "section": "Safety"}]}\n\n';

test("signup -> upload -> ask -> cited answer", async ({ page }) => {
  if (MOCK_API) {
    await page.route("**/api/v1/auth/register", (route) => route.fulfill({ status: 201, json: { id: "u1", email: "e2e@example.com", full_name: "E2E User" } }));
    await page.route("**/api/v1/auth/login", (route) => route.fulfill({ status: 200, json: { access_token: "mock" } }));
    await page.route("**/api/v1/auth/me", (route) => route.fulfill({ status: 200, json: { id: "u1", email: "e2e@example.com", full_name: "E2E User" } }));
    await page.route("**/api/v1/documents/", (route) => route.fulfill({ status: 200, json: { documents: [], total: 0 } }));
    await page.route("**/api/v1/documents/upload", (route) =>
      route.fulfill({
        status: 201,
        json: { id: "doc-e2e", original_name: "handbook.pdf", file_type: "pdf", file_size_bytes: 123, chunk_count: 3, status: "ready", error_message: null, ingestion_progress: 100, created_at: new Date().toISOString() },
      })
    );
    await page.route("**/api/v1/chat/conversations", (route) => route.fulfill({ status: 200, json: { conversations: [] } }));
  }
  await page.route("**/api/v1/chat/stream", (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: SSE })
  );
  // The stream's done event sets conversationId=conv-e2e, which makes
  // ChatPanel fetch the conversation history. That GET is unmocked in
  // both modes (the mocked stream never persisted anything), so
  // without this route it hits the real backend, 401s, and the
  // refresh interceptor redirects to /login mid-test. Mock it with
  // the same user question + cited answer the stream produced.
  await page.route("**/api/v1/chat/conversations/conv-e2e", (route) =>
    route.fulfill({
      status: 200,
      json: {
        id: "conv-e2e",
        messages: [
          {
            id: "m1",
            role: "user",
            content: "What does the handbook say about safety?",
            citations: [],
          },
          {
            id: "m2",
            role: "assistant",
            content: "The handbook says safety first.",
            citations: [
              {
                document_id: "doc-e2e",
                document_name: "handbook.pdf",
                chunk_index: 1,
                score: 0.92,
                snippet: "safety first",
                chunk_id: "chunk-e2e",
                page: 2,
                section: "Safety",
              },
            ],
          },
        ],
      },
    })
  );

  await page.goto("/register");
  // Wait for hydration: in dev mode a submit click before React
  // hydrates performs a native form GET (URL ends with "?") and
  // never reaches the onSubmit handler.
  await page.waitForLoadState("networkidle");
  await page.fill("#register-name", "E2E User");
  await page.fill("#register-email", "e2e@example.com");
  await page.fill("#register-password", "password123");
  await page.click("#register-submit");
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });

  // Upload a small in-memory PDF-shaped file via the dropzone input.
  const buffer = Buffer.from("%PDF-1.4 fake content");
  await page.setInputFiles("#file-upload", { name: "handbook.pdf", mimeType: "application/pdf", buffer });
  await expect(page.getByText("handbook.pdf")).toBeVisible();

  await page.getByRole("button", { name: "New chat" }).click();
  await page.getByLabel(/Ask a question/).fill("What does the handbook say about safety?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("The handbook says safety first.")).toBeVisible();
  await page.getByRole("button", { name: /Show 1 source/ }).click();
  await page.getByRole("button", { name: /Open source 1: handbook\.pdf/ }).click();
  await expect(page.getByRole("dialog", { name: /Source 1: handbook\.pdf/ })).toBeVisible();
  // "safety first" also appears in the answer and the chip, so
  // scope this assertion to the open source panel.
  await expect(page.getByRole("dialog", { name: /Source 1: handbook\.pdf/ }).getByText("safety first")).toBeVisible();
});
