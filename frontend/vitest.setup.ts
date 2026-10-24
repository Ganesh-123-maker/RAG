import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmount after every test so dashboard polling intervals and
// chat streams from one test cannot leak into the next.
afterEach(() => {
  cleanup();
});

// jsdom has no crypto.randomUUID in older Node; the app uses it
// for local message ids. Polyfill only if missing.
if (typeof globalThis.crypto === "undefined") {
  (globalThis as Record<string, unknown>).crypto = {
    randomUUID: () => `test-${Math.random().toString(36).slice(2)}`,
  };
}
