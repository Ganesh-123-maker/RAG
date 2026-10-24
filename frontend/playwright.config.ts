import { defineConfig } from "@playwright/test";

/**
 * Phase F E2E. Gated: it only runs when E2E_RUN=1, so a plain
 * `npm test` / CI without the docker stack never fails on it.
 *
 * Modes (no real OpenAI key is ever required):
 * - E2E_MOCK_API=1 (default when E2E_RUN=1): every /api/v1 call
 *   is intercepted in the spec, so only the frontend dev server
 *   (PLAYWRIGHT_BASE_URL, default http://localhost:3000) is needed.
 * - E2E_MOCK_API=0: signup/upload hit a real backend (docker
 *   stack), but /api/v1/chat/stream is still intercepted with a
 *   canned SSE answer, so the LLM is mocked and no key is needed.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
  },
  reporter: "list",
});
