import { renderHook, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { useNecErrors } from "../state/useNecErrors";
import { cagExportApi } from "../lib/master-data-api";

vi.mock("../lib/master-data-api", () => ({
  cagExportApi: { errors: vi.fn() },
}));

const mockedErrors = cagExportApi.errors as unknown as Mock;

beforeEach(() => {
  window.localStorage.clear();
  mockedErrors.mockReset();
});

// Flushes the dynamic ``await import(...)`` inside loadCagExportApi plus the
// mocked promise from cagExportApi.errors so the hook's catch / setState
// settle before assertions.
async function flushHook() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
  });
}

describe("useNecErrors — 503 not-configured handling", () => {
  it("latches notConfigured=true and clears state when /errors returns 503", async () => {
    // cagRequest's contract: thrown Error message starts with `API 503:`.
    mockedErrors.mockRejectedValue(
      new Error("API 503: CAG SFTP is not configured."),
    );

    const { result } = renderHook(() => useNecErrors(true));
    await flushHook();

    expect(mockedErrors).toHaveBeenCalledTimes(1);
    expect(result.current.notConfigured).toBe(true);
    expect(result.current.errors).toEqual([]);
    expect(result.current.fetchError).toBeNull();
  });

  it("stops polling once notConfigured latches (no further fetches across the 60s tick)", async () => {
    mockedErrors.mockRejectedValue(
      new Error("API 503: CAG SFTP is not configured."),
    );

    const { result } = renderHook(() => useNecErrors(true));
    await flushHook();
    expect(result.current.notConfigured).toBe(true);
    expect(mockedErrors).toHaveBeenCalledTimes(1);

    // The polling effect should have torn its interval down. Switch to fake
    // timers now (after the latch is observed under real timers) and advance
    // well past the 60s poll cadence to prove no further fetches land.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      await act(async () => {
        vi.advanceTimersByTime(180_000);
      });
      expect(mockedErrors).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("non-503 errors still surface as fetchError and leave notConfigured false", async () => {
    mockedErrors.mockRejectedValue(new Error("API 500: boom"));

    const { result } = renderHook(() => useNecErrors(true));
    await flushHook();

    expect(result.current.fetchError).toBe("API 500: boom");
    expect(result.current.notConfigured).toBe(false);
  });

  it("disabled hook never calls the endpoint and stays in default state", async () => {
    const { result } = renderHook(() => useNecErrors(false));
    await flushHook();

    expect(mockedErrors).not.toHaveBeenCalled();
    expect(result.current.notConfigured).toBe(false);
    expect(result.current.fetchError).toBeNull();
  });
});
