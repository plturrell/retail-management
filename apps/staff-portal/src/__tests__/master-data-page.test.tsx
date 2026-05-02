import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import MasterDataPage from "../pages/MasterDataPage";
import AddItemPage from "../pages/AddItemPage";
import { masterDataApi } from "../lib/master-data-api";
import { useAuth } from "../contexts/AuthContext";
import { auth } from "../lib/firebase";

// Test harness mirroring App.tsx's two routes so the "+ Create inventory"
// button (which now navigates to /master-data/add) can land on AddItemPage
// the same way it does in production.
function renderWithRouter() {
  return render(
    <MemoryRouter initialEntries={["/master-data"]}>
      <Routes>
        <Route path="/master-data" element={<MasterDataPage />} />
        <Route path="/master-data/add" element={<AddItemPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

vi.mock("../contexts/AuthContext", () => ({ useAuth: vi.fn() }));

vi.mock("../lib/firebase", () => ({
  auth: { currentUser: { getIdToken: vi.fn() } },
}));

vi.mock("../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  API_BASE_URL: "http://localhost:8000/api",
}));

vi.mock("../lib/master-data-api", () => ({
  newIdempotencyKey: vi.fn(() => "test-idempotency-key"),
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
    checkSimilarProducts: vi.fn(),
    previewCodes: vi.fn(),
    publishPricesBulk: vi.fn(),
    archiveProduct: vi.fn(),
    restoreProduct: vi.fn(),
  },
}));

const mockedUseAuth = vi.mocked(useAuth);
const mockedApi = masterDataApi as unknown as Record<string, Mock>;
const mockedAuth = auth as unknown as { currentUser: { getIdToken: Mock } };

beforeEach(() => {
  window.localStorage.clear();
  mockedUseAuth.mockReturnValue({
    isOwner: true,
    user: { email: "turrell.craig.1971@gmail.com" },
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
        retail_price: null,
        sale_ready: true,
      },
    ],
  });
  mockedApi.posStatus.mockResolvedValue({ as_of: "2026-04-29", plus: {} });
  mockedApi.getSourcingOptions.mockResolvedValue({ options: [] });
  mockedApi.listSuppliers.mockResolvedValue({ suppliers: [] });
  mockedApi.checkSimilarProducts.mockResolvedValue({ matches: [], ai_used: false });
  mockedApi.previewCodes.mockResolvedValue({
    sku_code: "VEMINLAPI0000001",
    nec_plu: "2000000000011",
    sequence: 1,
    sequence_source: "auto",
    collision: null,
  });
  mockedAuth.currentUser.getIdToken.mockResolvedValue("test-token");
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
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

    renderWithRouter();
    fireEvent.click(await screen.findByText("Tools"));
    const btn = await screen.findByRole("button", { name: /Print POS labels/i });

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

    renderWithRouter();
    fireEvent.click(await screen.findByText("Tools"));
    fireEvent.click(await screen.findByRole("button", { name: /Print POS labels/i }));

    await vi.waitFor(() =>
      expect((fakeWin.close as unknown as Mock)).toHaveBeenCalledTimes(1),
    );
  });
});

describe("MasterDataPage create inventory taxonomy", () => {
  it("submits Minerals category with a primary material and repeatable other materials", async () => {
    vi.spyOn(window, "alert").mockImplementation(() => undefined);
    mockedApi.getSourcingOptions.mockResolvedValue({
      options: [
        {
          value: "manufactured_in_house",
          label: "Manufactured by Victoria Enso",
          description: "Built in our workshop from raw materials we hold.",
          requires_supplier: false,
          inventory_type: "finished",
        },
      ],
    });
    mockedApi.createProduct.mockResolvedValue({
      ok: true,
      product: {
        sku_code: "VEMINLAPI0000001",
        description: "Lapis specimen",
        category: "Minerals",
        product_type: "Mineral Specimen",
        material: "Lapis Lazuli",
        additional_materials: ["Copper", "Marble"],
      },
      publish_result: null,
    });

    renderWithRouter();
    // Clicking "+ Create inventory" navigates to /master-data/add, which
    // mounts AddItemPage and the same shared form the modal used to host.
    fireEvent.click(await screen.findByRole("button", { name: /Create inventory/i }));

    await screen.findByText("SKU and PLU are allocated automatically.");
    await screen.findByText("Manufactured by Victoria Enso");
    fireEvent.change(screen.getByLabelText(/Category/i), { target: { value: "minerals" } });
    expect(screen.getByLabelText(/Product type/i)).toHaveValue("Mineral Specimen");

    fireEvent.change(screen.getByLabelText(/Primary material/i), { target: { value: "Lapis Lazuli" } });
    fireEvent.change(screen.getByLabelText(/Other materials/i), { target: { value: "Copper" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.change(screen.getByLabelText(/Other materials/i), { target: { value: "Marble" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.change(screen.getByLabelText(/Short description/i), { target: { value: "Lapis specimen" } });

    const submitButton = screen.getByRole("button", { name: "Add inventory" }) as HTMLButtonElement;
    await vi.waitFor(() => expect(submitButton.disabled).toBe(false));
    fireEvent.click(submitButton);

    await vi.waitFor(() => expect(mockedApi.createProduct).toHaveBeenCalledTimes(1));
    const [req] = mockedApi.createProduct.mock.calls[0];
    expect(req).toEqual(expect.objectContaining({
      category: "Minerals",
      product_type: "Mineral Specimen",
      material: "Lapis Lazuli",
      additional_materials: ["Copper", "Marble"],
    }));
    expect(req).not.toHaveProperty("material_category");
    expect(req).not.toHaveProperty("material_subcategory");
  });
});

describe("MasterDataPage archive controls", () => {
  it("loads archived rows through the owner Archived queue", async () => {
    mockedApi.stats.mockResolvedValue({
      total: 1,
      sale_ready: 1,
      needs_price_flag: 0,
      needs_review_flag: 0,
      sale_ready_missing_price: 0,
      archived: 1,
      by_supplier: {},
    });
    const activeProduct = {
      sku_code: "SKU-1",
      description: "Active product",
      retail_price: null,
      sale_ready: true,
    };
    const archivedProduct = {
      sku_code: "SKU-ARCHIVED",
      description: "Archived product",
      retail_price: null,
      sale_ready: false,
      status: "archived",
      archived_at: "2026-05-01T10:00:00Z",
    };
    mockedApi.listProducts.mockImplementation((params) => {
      if (params?.launch_only && params?.include_archived) {
        return Promise.resolve({ count: 1, products: [archivedProduct] });
      }
      if (params?.launch_only === false) {
        return Promise.resolve({ count: 2, products: [activeProduct, archivedProduct] });
      }
      return Promise.resolve({ count: 1, products: [activeProduct] });
    });

    renderWithRouter();

    fireEvent.click(await screen.findByRole("button", { name: /Archived/i }));

    await vi.waitFor(() => {
      expect(
        mockedApi.listProducts.mock.calls.some(([params]) =>
          Boolean(params?.launch_only && params?.include_archived),
        ),
      ).toBe(true);
    });
    expect(await screen.findByText("Archived product")).toBeInTheDocument();
    expect(screen.getAllByText("Archived").length).toBeGreaterThan(0);
  });

  it("keeps archive as a deliberate item-detail action", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockedApi.archiveProduct.mockResolvedValue({
      ok: true,
      product: {
        sku_code: "SKU-1",
        description: "Test product",
        retail_price: null,
        sale_ready: false,
        status: "archived",
        archived_at: "2026-05-01T10:00:00Z",
      },
    });

    renderWithRouter();

    fireEvent.click(await screen.findByRole("button", { name: "Details" }));
    fireEvent.click(await screen.findByRole("button", { name: "Archive item" }));

    await vi.waitFor(() =>
      expect(mockedApi.archiveProduct).toHaveBeenCalledWith("SKU-1", {
        reason: "Archived from Master Data",
      }),
    );
  });

  it("surfaces database sync failures in item details", async () => {
    mockedApi.listProducts.mockResolvedValue({
      count: 1,
      products: [
        {
          sku_code: "SKU-1",
          description: "Test product",
          retail_price: null,
          sale_ready: true,
          database_sync: { ok: false, error: "Firestore unavailable" },
        },
      ],
    });

    renderWithRouter();

    fireEvent.click(await screen.findByRole("button", { name: "Details" }));

    expect(await screen.findByText("Database sync pending")).toBeInTheDocument();
  });
});

describe("AddItemPage page-mode 'More' disclosures", () => {
  it("tucks rarely-touched fields behind <details> in page mode", async () => {
    mockedApi.getSourcingOptions.mockResolvedValue({
      options: [
        {
          value: "manufactured_in_house",
          label: "Manufactured by Victoria Enso",
          description: "Built in our workshop from raw materials we hold.",
          requires_supplier: false,
          inventory_type: "finished",
        },
      ],
    });

    renderWithRouter();
    fireEvent.click(await screen.findByRole("button", { name: /Create inventory/i }));
    await screen.findByText("SKU and PLU are allocated automatically.");

    // Three page-mode disclosures render as <summary> elements inside closed
    // <details>; each summary is the only visible affordance until expanded.
    const moreFields = await screen.findByText("More fields");
    expect(moreFields.tagName).toBe("SUMMARY");
    const moreDetails = moreFields.closest("details") as HTMLDetailsElement;
    expect(moreDetails).not.toBeNull();
    expect(moreDetails.open).toBe(false);

    const addLongDesc = screen.getByText("Add long description");
    expect(addLongDesc.tagName).toBe("SUMMARY");
    expect((addLongDesc.closest("details") as HTMLDetailsElement).open).toBe(false);

    const overrideSeq = screen.getByText(/Override sequence/i);
    expect(overrideSeq.tagName).toBe("SUMMARY");
    expect((overrideSeq.closest("details") as HTMLDetailsElement).open).toBe(false);

    // The wrapped fields live INSIDE the "More fields" <details>, not in the
    // structured grid: the Notes input is a descendant of the disclosure.
    const notesInput = screen.getByLabelText(/^Notes$/);
    expect(moreDetails.contains(notesInput)).toBe(true);
  });
});
