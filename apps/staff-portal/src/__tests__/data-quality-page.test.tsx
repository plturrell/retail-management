import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import DataQualityPage from "../pages/DataQualityPage";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  API_BASE_URL: "http://localhost:8000/api",
}));

const mockedApi = api as unknown as { get: Mock; post: Mock; put: Mock; patch: Mock; delete: Mock };

const baseQualityResponse = {
  generated_at: "2026-04-29T00:00:00Z",
  total_products: 0,
  quality_summary: {
    total_errors: 0,
    total_warnings: 0,
    products_with_issues: 0,
    products_clean: 0,
  },
  reference: {
    product_types: [],
    inventory_categories: [],
    stocking_statuses: [],
    stocking_locations: [],
    inventory_types: [],
    sourcing_strategies: [],
  },
  products: [],
};

beforeEach(() => {
  mockedApi.get.mockImplementation((path: string) => {
    if (path === "/data-quality/products") return Promise.resolve({ ...baseQualityResponse });
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("DataQualityPage saveMsg banner", () => {
  it("renders an error banner in red when PLU preview fails", async () => {
    mockedApi.get.mockImplementation((path: string) => {
      if (path === "/data-quality/products") return Promise.resolve({ ...baseQualityResponse });
      if (path === "/data-quality/plus/bulk-preview")
        return Promise.reject(new Error("backend exploded"));
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });

    render(<DataQualityPage />);
    const fixBtn = await screen.findByRole("button", { name: /Fix PLUs/i });
    fireEvent.click(fixBtn);

    const banner = await screen.findByText(/PLU preview failed: backend exploded/i);
    expect(banner.className).toMatch(/text-red-700/);
    expect(banner.className).toMatch(/bg-red-50/);
    expect(banner.className).not.toMatch(/text-green-700/);
  });

  it("renders a success banner in green when PLU bulk-apply succeeds", async () => {
    const plan = {
      applied: false,
      summary: { total: 2, missing: 1, invalid: 1, misaligned: 0 },
      plan: [
        {
          sku_id: "p1",
          sku_code: "SKU-1",
          description: "Item 1",
          old_plu: null,
          new_plu: "1234567890128",
          reason: "missing",
        },
        {
          sku_id: "p2",
          sku_code: "SKU-2",
          description: "Item 2",
          old_plu: "x",
          new_plu: "1234567890135",
          reason: "invalid",
        },
      ],
      plan_total: 2,
    };
    const appliedPlan = { ...plan, applied: true };

    mockedApi.get.mockImplementation((path: string) => {
      if (path === "/data-quality/products") return Promise.resolve({ ...baseQualityResponse });
      if (path === "/data-quality/plus/bulk-preview") return Promise.resolve(plan);
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });
    mockedApi.post.mockResolvedValue(appliedPlan);

    render(<DataQualityPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Fix PLUs/i }));

    const applyBtn = await screen.findByRole("button", { name: /Apply \(2\)/i });
    fireEvent.click(applyBtn);

    await waitFor(() =>
      expect(mockedApi.post).toHaveBeenCalledWith("/data-quality/plus/bulk-apply", {}),
    );

    const banner = await screen.findByText(/PLU bulk-assign applied — 2 row\(s\) updated\./i);
    expect(banner.className).toMatch(/text-green-700/);
    expect(banner.className).toMatch(/bg-green-50/);
    expect(banner.className).not.toMatch(/text-red-700/);
  });

  it("clears the banner on a fresh preview attempt before showing the new state", async () => {
    // First click fails (red banner). Second click succeeds (no banner — only
    // applyPluPlan emits the success banner). This pins down the setSaveMsg(null)
    // reset path on previewPluPlan so a stale red banner doesn't leak through.
    let attempts = 0;
    mockedApi.get.mockImplementation((path: string) => {
      if (path === "/data-quality/products") return Promise.resolve({ ...baseQualityResponse });
      if (path === "/data-quality/plus/bulk-preview") {
        attempts += 1;
        if (attempts === 1) return Promise.reject(new Error("first try"));
        return Promise.resolve({
          applied: false,
          summary: { total: 0 },
          plan: [],
          plan_total: 0,
        });
      }
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });

    render(<DataQualityPage />);
    const fixBtn = await screen.findByRole("button", { name: /Fix PLUs/i });

    fireEvent.click(fixBtn);
    await screen.findByText(/PLU preview failed: first try/i);

    fireEvent.click(fixBtn);
    await waitFor(() =>
      expect(screen.queryByText(/PLU preview failed: first try/i)).toBeNull(),
    );
  });
});
