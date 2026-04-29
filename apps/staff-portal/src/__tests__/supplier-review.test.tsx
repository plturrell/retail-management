import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SupplierReviewPage from "../pages/SupplierReviewPage";

const bundlePayload = {
  supplier: {
    id: "CN-001",
    name: "Hengwei Craft",
    name_local: "衡威工艺",
  },
  import_readiness: {
    supplier_record_ready: true,
    order_line_items_extracted: true,
    product_candidates_ready: true,
    catalog_products_ready: true,
    purchase_orders_ready: false,
    blocking_reason: "The scanned line items are structured, but they are not yet matched to real RetailSG SKU ids.",
  },
};

const catalogPayload = {
  supplier_id: "CN-001",
  supplier_name: "Hengwei Craft",
  products: [
    {
      catalog_product_id: "catalog-item-1",
      catalog_file: "catalog.xlsx",
      sheet_name: "摆件",
      source_block_row: 10,
      source_value_column: "B",
      raw_model: "A339A",
      supplier_item_codes: ["A339A"],
      primary_supplier_item_code: "A339A",
      display_name: "decoration",
      size: "8*8*10",
      materials: "Copper, Natural mineral stone",
      color: null,
      price_label: "special",
      price_options_cny: [120],
      raw_price: "120",
    },
  ],
};

const order364Payload = {
  order_number: "364-365",
  order_date: "2026-03-26",
  currency: "CNY",
  source_document_total_amount: 11046,
  document_payment_status: "cash_paid",
  item_reconciliation_status: "needs_follow_up",
  financial_reconciliation_status: "paid",
  payment_breakdown: [{ method: "cash", currency: "CNY", amount: 11046 }],
  line_items: [
    {
      source_line_number: 1,
      supplier_item_code: "A339A",
      quantity: 5,
      unit_cost_cny: 120,
      line_total_cny: 600,
      size: "8*8*10",
      material_description: "Copper, Natural mineral stone",
    },
  ],
};

const order369Payload = {
  order_number: "369",
  order_date: "2026-03-30",
  currency: "CNY",
  source_document_total_amount: 34125,
  document_payment_status: "unpaid",
  item_reconciliation_status: "catalog_matched",
  financial_reconciliation_status: "disputed",
  financial_reconciliation_issue: "scan_conflicts_with_reported_reference",
  reported_external_reference: {
    reference_number: "149",
    reported_total_amount_cny: 34123,
  },
  charges: [{ description: "Cost of wooden frame", currency: "CNY", amount: 1300 }],
  line_items: [
    {
      source_line_number: 1,
      supplier_item_code: "A008",
      quantity: 2,
      unit_cost_cny: 240,
      line_total_cny: 480,
      size: "38*11*49",
      material_description: "Copper, green fluorite",
    },
  ],
};

const candidatePayload = {
  supplier_id: "CN-001",
  supplier_name: "Hengwei Craft",
  products: [
    {
      supplier_item_code: "A339A",
      supplier_name: "Hengwei Craft",
      supplier_id: "CN-001",
      inventory_type: "purchased",
      sourcing_strategy: "supplier_premade",
      default_unit_cost_cny: 120,
      material_descriptions: ["Copper, Natural mineral stone"],
      observed_sizes: ["8*8*10"],
      source_orders: ["364-365"],
      source_line_numbers: ["364-365:1"],
      notes: [],
      catalog_match_count: 1,
      catalog_matches: [
        {
          catalog_product_id: "catalog-item-1",
          catalog_file: "catalog.xlsx",
          sheet_name: "摆件",
          display_name: "decoration",
          size: "8*8*10",
          materials: "Copper, Natural mineral stone",
          price_label: "special",
          price_options_cny: [120],
          raw_model: "A339A",
        },
      ],
      import_status: "catalog_matched",
    },
  ],
  uncoded_order_lines: [],
};

describe("SupplierReviewPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("supplier_bundle.json")) {
          return new Response(JSON.stringify(bundlePayload), { status: 200 });
        }
        if (url.includes("catalog_products.json")) {
          return new Response(JSON.stringify(catalogPayload), { status: 200 });
        }
        if (url.includes("product_candidates.json")) {
          return new Response(JSON.stringify(candidatePayload), { status: 200 });
        }
        if (url.includes("364-365.json")) {
          return new Response(JSON.stringify(order364Payload), { status: 200 });
        }
        if (url.includes("369.json")) {
          return new Response(JSON.stringify(order369Payload), { status: 200 });
        }
        return new Response("not found", { status: 404 });
      }),
    );
  });

  it("renders the invoice review workspace with invoice, extracted data, and crop gallery", async () => {
    render(<SupplierReviewPage />);

    await waitFor(() => expect(screen.getByText("Hengwei Craft · 衡威工艺")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Catalog matches")).toBeInTheDocument());

    expect(screen.getByText("Source Invoice")).toBeInTheDocument();
    expect(screen.getByText("OCR / structured review")).toBeInTheDocument();
    expect(screen.getByText("Line image crops")).toBeInTheDocument();
    expect(screen.getByText(/Saved locally in this browser/i)).toBeInTheDocument();
    expect(screen.getAllByText("A339A").length).toBeGreaterThan(0);
    expect(screen.getByText("Product candidate ready")).toBeInTheDocument();
  });

  it("shows the reconciliation warning when switching to the conflicting source document", async () => {
    render(<SupplierReviewPage />);

    await waitFor(() => expect(screen.getAllByText("Order 369").length).toBeGreaterThan(0));
    screen.getAllByRole("button", { name: /Order 369/i })[0].click();

    await waitFor(() =>
      expect(screen.getByText(/This order has a source-document conflict/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/order 149/i)).toBeInTheDocument();
  });

  it("persists line review decisions in local storage", async () => {
    window.localStorage.clear();
    render(<SupplierReviewPage />);

    await waitFor(() => expect(screen.getAllByText("Catalog matches").length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByRole("button", { name: /Mark line verified/i })[0]);

    await waitFor(() => {
      const saved = window.localStorage.getItem("supplier-review:CN-001");
      expect(saved).toContain("\"status\":\"verified\"");
    });
  });
});
