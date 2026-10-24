import { describe, it, expect } from "vitest";
import { getApiErrorMessage, shouldRedirectOnUnauthorized, api } from "@/lib/api";

describe("api client (Phase F)", () => {
  it("prefers the backend safe detail message, never a stack trace", () => {
    expect(getApiErrorMessage({ response: { data: { detail: "Document not found" } } })).toBe(
      "Document not found"
    );
    expect(getApiErrorMessage(new Error("network down"))).toBe("network down");
    expect(getApiErrorMessage({})).toBe("Something went wrong. Please try again.");
    expect(getApiErrorMessage({ response: { data: { detail: { nested: true } } } })).toBe(
      "Something went wrong. Please try again."
    );
  });

  it("redirects on 401 everywhere except /login itself", () => {
    expect(shouldRedirectOnUnauthorized("/dashboard")).toBe(true);
    expect(shouldRedirectOnUnauthorized("/login")).toBe(false);
  });

  it("has a shared response interceptor (single instance, not per-call clients)", () => {
    // axios stores interceptors as handlers; a 401 interceptor must
    // be registered on the shared instance for the redirect to work.
    const handlers = (api.interceptors.response as unknown as { handlers: unknown[] }).handlers;
    expect(handlers.length).toBeGreaterThan(0);
  });
});
