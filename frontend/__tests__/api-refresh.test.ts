import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { api } from "@/lib/api";

/**
 * Tests the 401 -> refresh -> retry interceptor on the shared `api`
 * instance, using a stub adapter (no new test dependency): the
 * adapter decides the response per URL, so the interceptor, the
 * single shared refresh promise, and the one-retry guard all run
 * for real.
 */

function okResponse(config: InternalAxiosRequestConfig, data: unknown): AxiosResponse {
  return {
    data,
    status: 200,
    statusText: "OK",
    headers: {},
    config,
  };
}

function unauthorizedResponse(config: InternalAxiosRequestConfig): AxiosResponse {
  return {
    data: { detail: "Could not validate credentials" },
    status: 401,
    statusText: "Unauthorized",
    headers: {},
    config,
  };
}

describe("api 401 interceptor refresh-and-retry", () => {
  let refreshCalls = 0;
  let protectedCalls = 0;
  let refreshShouldSucceed = true;
  let protected401s = 1;
  let originalAdapter: unknown;

  beforeEach(() => {
    refreshCalls = 0;
    protectedCalls = 0;
    refreshShouldSucceed = true;
    protected401s = 1;
    originalAdapter = api.defaults.adapter;
    api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      if (config.url?.includes("/auth/refresh")) {
        refreshCalls += 1;
        if (!refreshShouldSucceed) {
          // Axios rejects on non-2xx only via validateStatus; the
          // adapter must throw for the interceptor to see an error.
          const err = new Error("Request failed with status code 401") as Error & {
            response: AxiosResponse;
            config: InternalAxiosRequestConfig;
            isAxiosError: boolean;
          };
          err.response = unauthorizedResponse(config);
          err.config = config;
          err.isAxiosError = true;
          throw err;
        }
        return okResponse(config, { access_token: "new-access", token_type: "bearer" });
      }
      if (config.url === "/protected") {
        protectedCalls += 1;
        if (protectedCalls <= protected401s) {
          const err = new Error("Request failed with status code 401") as Error & {
            response: AxiosResponse;
            config: InternalAxiosRequestConfig;
            isAxiosError: boolean;
          };
          err.response = unauthorizedResponse(config);
          err.config = config;
          err.isAxiosError = true;
          throw err;
        }
        return okResponse(config, { ok: true });
      }
      return okResponse(config, {});
    };
  });

  afterEach(() => {
    api.defaults.adapter = originalAdapter as typeof api.defaults.adapter;
    vi.restoreAllMocks();
  });

  it("refreshes once and retries the original request after a 401", async () => {
    const response = await api.get("/protected");
    expect(response.status).toBe(200);
    expect(response.data).toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
    expect(protectedCalls).toBe(2);
  });

  it("shares a single in-flight refresh across concurrent 401s", async () => {
    // Both concurrent calls 401 on their first attempt; both must
    // wait on the same refresh call, then both retry successfully.
    protected401s = 2;
    const results = await Promise.allSettled([api.get("/protected"), api.get("/protected")]);
    expect(refreshCalls).toBe(1);
    expect(results[0].status).toBe("fulfilled");
    expect(results[1].status).toBe("fulfilled");
    expect(protectedCalls).toBe(4);
  });

  it("rejects (and does not retry forever) when refresh fails", async () => {
    refreshShouldSucceed = false;
    await expect(api.get("/protected")).rejects.toThrow();
    expect(refreshCalls).toBe(1);
    // Original attempt + no successful retry: the second protected
    // call never happened because refresh failed.
    expect(protectedCalls).toBe(1);
  });

  it("does not trigger refresh for a 401 from the refresh endpoint itself", async () => {
    refreshShouldSucceed = false;
    await expect(api.post("/api/v1/auth/refresh")).rejects.toThrow();
    expect(refreshCalls).toBe(1);
  });
});
