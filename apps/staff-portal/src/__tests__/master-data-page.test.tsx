import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import MasterDataPage from "../pages/MasterDataPage";
import { masterDataApi } from "../lib/master-data-api";
import { useAuth } from "../contexts/AuthContext";
import { auth } from "../lib/firebase";

vi.mock("../contexts/AuthContext", () => ({ useAuth: vi.fn() }));

vi.mock("../lib/firebase", () => ({
  auth: { currentUser: { getIdToken: vi.fn() } },
}));

vi.mock("../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  API_BASE_URL: "http://localhost:8000/api",
}));

vi.mock("../lib/master-data-api", () => ({
  masterDataApi: {
    health: vi.fn(),
    stats: vi.fn(),
    listProducts: vi.fn(),
    patchProduct: vi.fn(),
    exportNecJewel: vi.fn(),
    exportLabels: vi.fn(),
    posStatus: vi.fn(),
    downloadExport: vi.fn(),
    ingestInvoice: vi.fn(),
    commitInvoice: vi.fn(),
    recommendPrices: vi.fn(),
    publishPrice: vi.fn(),
    createProduct: vi.fn(),
    uploadProductImage: vi.fn(),
    getSourcingOptions: vi.fn(),
    listSuppliers: vi.fn(),
    getSupplierCatalog: vi.fn(),
    addSupplierCatalogEntry: vi.fn(),
    aiDescribeProduct: vi.fn(),
    publishPricesBulk: vi.fn(),
  },
}));

const mockedUseAuth = vi.mocked(useAuth);
const mockedApi = masterDataApi as unknown as Record<string, Mock>;
const mockedAuth = auth as unknown as { currentUser: { getIdToken: Mock } };

beforeEach(() => {
  mockedUseAuth.mockReturnValue({
    isOwner: true,
    user: { email: "craig@victoriaenso.com" },
  } as never);
  mockedApi.stats.mockResolvedValue({
    total: 1,
    sale_ready: 1,
    needs_price_flag: 0,
    needs_review_flag: 0,
    sale_ready_missing_price: 0,
    by_supplier: {},
  });
  mockedApi.listProducts.mockResolvedValue({
    count: 1,
    products: [
      {
        sku_code: "SKU-1",
        description: "Test product",
        retail_price: 9.99,
        sale_ready: true,
      },
    ],
  });
  mockedApi.posStatus.mockResolvedValue({ as_of: "2026-04-29", plus: {} });
  mockedApi.getSourcingOptions.mockResolvedValue({ options: [] });
  mockedApi.listSuppliers.mockResolvedValue({ suppliers: [] });
  mockedAuth.currentUser.getIdToken.mockResolvedValue("test-token");
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function makeFakeWindow() {
  return {
    document: { open: vi.fn(), write: vi.fn(), close: vi.fn() },
    close: vi.fn(),
  } as unknown as Window;
}

describe("MasterDataPage Print POS Labels", () => {
  it("opens the print window synchronously, before any network call", async () => {
    const fakeWin = makeFakeWindow();
    const openSpy = vi.spyOn(window, "open").mockReturnValue(fakeWin);

    // Pending fetch — we resolve it after the synchronous assertions so we can
    // pin down that window.open ran first. This is the core invariant that
    // keeps Safari/Firefox from blocking the popup.
    let resolveFetch: (val: Response) => void = () => {};
    const fetchPromise = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });
    const fetchSpy = vi.fn().mockReturnValue(fetchPromise);
    vi.stubGlobal("fetch", fetchSpy);

    render(<MasterDataPage />);
    const btn = await screen.findByRole("button", { name: /Print POS Labels/i });

    fireEvent.click(btn);

    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith("", "_blank");
    expect(fetchSpy).not.toHaveBeenCalled();
    const writeMock = (fakeWin.document.write as unknown) as Mock;
    expect(writeMock.mock.calls[0][0]).toMatch(/Generating labels/);

    resolveFetch({
      ok: true,
      text: () => Promise.resolve("<html>labels</html>"),
    } as unknown as Response);

    // Once the labels HTML is back, the placeholder is replaced and the tab
    // is left open for printing — close() is reserved for the failure path.
    await vi.waitFor(() =>
      expect(writeMock.mock.calls.some((c) => c[0] === "<html>labels</html>")).toBe(true),
    );
    expect((fakeWin.close as unknown as Mock)).not.toHaveBeenCalled();
  });

  it("closes the placeholder tab when the labels fetch fails", async () => {
    const fakeWin = makeFakeWindow();
    vi.spyOn(window, "open").mockReturnValue(fakeWin);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, text: () => Promise.resolve("nope") }),
    );
    vi.spyOn(window, "alert").mockImplementation(() => undefined);

    render(<MasterDataPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Print POS Labels/i }));

    await vi.waitFor(() =>
      expect((fakeWin.close as unknown as Mock)).toHaveBeenCalledTimes(1),
    );
  });
});
