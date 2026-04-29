import { startTransition, useDeferredValue, useEffect, useState } from "react";
import {
  type CropRegion,
  hengweiInvoiceAssets,
  hengweiReviewAssetUrls,
} from "../lib/supplier-review-assets";
import {
  defaultLineReview,
  defaultOrderReview,
  loadWorkspaceState,
  persistWorkspaceState,
  type ReviewFinancialStatus,
  type ReviewItemStatus,
  type ReviewLineState,
  type ReviewLineStatus,
  type ReviewOrderState,
  type SupplierReviewWorkspaceState,
} from "../lib/supplier-review-state";

type Charge = {
  description: string;
  currency: string;
  amount: number;
};

type PaymentLine = {
  method: string;
  currency: string;
  amount: number;
  reported_fx_rate_cny_per_sgd?: number;
  derived_sgd_equivalent?: number;
  bank_name?: string;
  bank_location?: string;
  account_number?: string;
  swift_code?: string;
};

type OrderLineItem = {
  source_line_number: number;
  line_position?: string;
  supplier_item_code?: string | null;
  display_name?: string;
  unit_cost_cny?: number;
  quantity?: number;
  line_total_cny?: number;
  size?: string;
  material_description?: string;
  note?: string;
};

type OrderRecord = {
  order_number: string;
  order_date: string;
  currency: string;
  source_document_total_amount: number;
  document_payment_status: string;
  reported_operational_status?: string;
  item_reconciliation_status?: ReviewItemStatus;
  item_reconciliation_notes?: string[];
  financial_reconciliation_status?: ReviewFinancialStatus;
  financial_reconciliation_issue?: string;
  financial_reconciliation_notes?: string[];
  payment_breakdown?: PaymentLine[];
  charges?: Charge[];
  line_items: OrderLineItem[];
  reported_external_reference?: {
    reference_number: string;
    reported_total_amount_cny: number;
    reported_payment_breakdown?: PaymentLine[];
  };
  inventory_movement?: {
    current_location: string;
    current_location_role?: string[];
    current_state?: string;
    planned_destination?: string;
    planned_reason?: string;
    planned_destination_open_date?: string;
  };
  verification?: {
    source_of_truth?: string[];
    normalization_notes?: string[];
  };
};

type SupplierBundle = {
  supplier: {
    id: string;
    name: string;
    name_local?: string;
    country?: string;
    cities?: string[];
    category?: string;
    brand?: string;
  };
  import_readiness: {
    supplier_record_ready: boolean;
    order_line_items_extracted: boolean;
    product_candidates_ready: boolean;
    catalog_products_ready?: boolean;
    purchase_orders_ready: boolean;
    blocking_reason?: string;
  };
};

type CatalogProduct = {
  catalog_product_id: string;
  catalog_file: string;
  sheet_name: string;
  source_block_row: number;
  source_value_column: string;
  raw_model: string;
  supplier_item_codes: string[];
  primary_supplier_item_code: string;
  display_name?: string | null;
  size?: string | null;
  materials?: string | null;
  color?: string | null;
  price_label?: string | null;
  price_options_cny: number[];
  raw_price?: string | null;
};

type CatalogProductBundle = {
  supplier_id: string;
  supplier_name: string;
  products: CatalogProduct[];
  summary?: {
    catalog_product_count: number;
    distinct_supplier_codes: number;
    duplicate_code_count: number;
  };
};

type CandidateCatalogMatch = {
  catalog_product_id: string;
  catalog_file: string;
  sheet_name: string;
  display_name?: string | null;
  size?: string | null;
  materials?: string | null;
  price_label?: string | null;
  price_options_cny?: number[];
  raw_model?: string | null;
};

type ProductCandidate = {
  supplier_item_code: string;
  supplier_name: string;
  supplier_id: string;
  inventory_type: string;
  sourcing_strategy: string;
  default_unit_cost_cny: number | null;
  material_descriptions: string[];
  observed_sizes: string[];
  source_orders: string[];
  source_line_numbers: string[];
  notes: string[];
  catalog_match_count?: number;
  catalog_matches?: CandidateCatalogMatch[];
  import_status?: string;
};

type ProductCandidateBundle = {
  supplier_id: string;
  supplier_name: string;
  catalog_products_file?: string;
  matched_catalog_products?: number;
  unmatched_supplier_codes?: string[];
  products: ProductCandidate[];
  uncoded_order_lines: Array<{
    order_number: string;
    source_line_number: number;
    display_name?: string;
    line_total_cny?: number;
  }>;
};

type LoadedReviewData = {
  bundle: SupplierBundle;
  catalogProducts: CatalogProductBundle;
  orders: Record<string, OrderRecord>;
  productCandidates: ProductCandidateBundle;
};

function formatMoney(amount: number | undefined, currency: string) {
  if (amount === undefined) return "n/a";
  return new Intl.NumberFormat("en-SG", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

function lineKey(orderNumber: string, line: OrderLineItem) {
  return `${orderNumber}:${line.source_line_number}${line.line_position ? `:${line.line_position}` : ""}`;
}

function lineReviewTone(status: ReviewLineStatus) {
  switch (status) {
    case "verified":
      return "bg-emerald-100 text-emerald-700";
    case "needs_follow_up":
      return "bg-amber-100 text-amber-700";
    default:
      return "bg-slate-100 text-slate-600";
  }
}

function lineReviewLabel(status: ReviewLineStatus) {
  switch (status) {
    case "verified":
      return "Verified";
    case "needs_follow_up":
      return "Needs follow-up";
    default:
      return "Unreviewed";
  }
}

function itemReviewTone(status: ReviewItemStatus) {
  switch (status) {
    case "catalog_matched":
    case "sku_mapped":
      return "bg-emerald-100 text-emerald-700";
    case "needs_follow_up":
      return "bg-amber-100 text-amber-700";
    default:
      return "bg-slate-100 text-slate-600";
  }
}

function itemReviewLabel(status: ReviewItemStatus) {
  switch (status) {
    case "catalog_matched":
      return "Catalog matched";
    case "sku_mapped":
      return "SKU mapped";
    case "needs_follow_up":
      return "Needs follow-up";
    default:
      return "Unreviewed";
  }
}

function financialReviewTone(status: ReviewFinancialStatus) {
  switch (status) {
    case "paid":
      return "bg-emerald-100 text-emerald-700";
    case "partially_paid":
    case "disputed":
      return "bg-amber-100 text-amber-700";
    case "unpaid":
      return "bg-rose-100 text-rose-700";
    default:
      return "bg-slate-100 text-slate-600";
  }
}

function financialReviewLabel(status: ReviewFinancialStatus) {
  switch (status) {
    case "unpaid":
      return "Unpaid";
    case "partially_paid":
      return "Partially paid";
    case "paid":
      return "Paid";
    case "disputed":
      return "Disputed";
    default:
      return "Unreviewed";
  }
}

function InvoiceCropPreview({
  src,
  originalWidth,
  originalHeight,
  crop,
  previewWidth,
  alt,
}: {
  src: string;
  originalWidth: number;
  originalHeight: number;
  crop: CropRegion;
  previewWidth: number;
  alt: string;
}) {
  const scale = previewWidth / crop.width;
  const previewHeight = crop.height * scale;

  return (
    <div
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
      style={{ width: previewWidth, height: previewHeight }}
      aria-label={alt}
      title={alt}
    >
      <img
        src={src}
        alt={alt}
        draggable={false}
        className="max-w-none select-none"
        style={{
          width: originalWidth * scale,
          height: originalHeight * scale,
          marginLeft: -crop.x * scale,
          marginTop: -crop.y * scale,
        }}
      />
    </div>
  );
}

function MetricCard({
  label,
  value,
  tone = "slate",
}: {
  label: string;
  value: string;
  tone?: "slate" | "amber" | "emerald";
}) {
  const toneClass =
    tone === "amber"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : tone === "emerald"
        ? "border-emerald-200 bg-emerald-50 text-emerald-900"
        : "border-slate-200 bg-white text-slate-900";

  return (
    <div className={`rounded-2xl border p-4 shadow-sm ${toneClass}`}>
      <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">{label}</div>
      <div className="mt-2 text-xl font-semibold">{value}</div>
    </div>
  );
}

export default function SupplierReviewPage() {
  const [data, setData] = useState<LoadedReviewData | null>(null);
  const [reviewState, setReviewState] = useState<SupplierReviewWorkspaceState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedOrderNumber, setSelectedOrderNumber] = useState<string>("364-365");
  const [selectedLineKey, setSelectedLineKey] = useState<string | null>(null);
  const [lineSearch, setLineSearch] = useState("");
  const [jsonMode, setJsonMode] = useState<"structured" | "raw">("structured");
  const deferredLineSearch = useDeferredValue(lineSearch.trim().toLowerCase());

  useEffect(() => {
    let cancelled = false;

    async function loadReviewData() {
      try {
        setLoading(true);
        setError(null);

        const [bundleRes, catalogRes, candidatesRes, order364Res, order369Res] = await Promise.all([
          fetch(hengweiReviewAssetUrls.bundle),
          fetch(hengweiReviewAssetUrls.catalogProducts),
          fetch(hengweiReviewAssetUrls.productCandidates),
          fetch(hengweiReviewAssetUrls.orders["364-365"]),
          fetch(hengweiReviewAssetUrls.orders["369"]),
        ]);

        if (!bundleRes.ok || !catalogRes.ok || !candidatesRes.ok || !order364Res.ok || !order369Res.ok) {
          throw new Error("Unable to load the local supplier review assets.");
        }

        const [bundle, catalogProducts, productCandidates, order364365, order369] = await Promise.all([
          bundleRes.json() as Promise<SupplierBundle>,
          catalogRes.json() as Promise<CatalogProductBundle>,
          candidatesRes.json() as Promise<ProductCandidateBundle>,
          order364Res.json() as Promise<OrderRecord>,
          order369Res.json() as Promise<OrderRecord>,
        ]);

        if (cancelled) return;

        setData({
          bundle,
          catalogProducts,
          productCandidates,
          orders: {
            "364-365": order364365,
            "369": order369,
          },
        });
        setReviewState(loadWorkspaceState(bundle.supplier.id));
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "Unable to load the supplier review.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadReviewData();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!reviewState) return;
    persistWorkspaceState(reviewState);
  }, [reviewState]);

  const currentOrder = data?.orders[selectedOrderNumber] ?? null;
  const currentInvoice = currentOrder ? hengweiInvoiceAssets[currentOrder.order_number] : null;

  const filteredLineItems =
    currentOrder?.line_items.filter((line) => {
      if (!deferredLineSearch) return true;
      const haystack = [
        line.supplier_item_code,
        line.display_name,
        line.material_description,
        line.size,
        line.note,
        String(line.source_line_number),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(deferredLineSearch);
    }) ?? [];

  useEffect(() => {
    if (!currentOrder) return;
    if (!filteredLineItems.length) {
      if (selectedLineKey !== null) setSelectedLineKey(null);
      return;
    }
    const stillVisible = filteredLineItems.some((line) => lineKey(currentOrder.order_number, line) === selectedLineKey);
    if (!stillVisible) {
      setSelectedLineKey(lineKey(currentOrder.order_number, filteredLineItems[0]));
    }
  }, [currentOrder, filteredLineItems, selectedLineKey]);

  const selectedLine =
    currentOrder && selectedLineKey
      ? filteredLineItems.find((line) => lineKey(currentOrder.order_number, line) === selectedLineKey) ?? null
      : null;

  const selectedRegion =
    currentOrder && selectedLine && currentInvoice
      ? currentInvoice.lineRegions[lineKey(currentOrder.order_number, selectedLine)] ?? null
      : null;

  const orderCandidates =
    data?.productCandidates.products.filter((product) => product.source_orders.includes(selectedOrderNumber)) ?? [];

  const uncodedLines =
    data?.productCandidates.uncoded_order_lines.filter((item) => item.order_number === selectedOrderNumber) ?? [];

  const currentOrderReview = reviewState?.orders[selectedOrderNumber] ?? defaultOrderReview();
  const selectedLineReview =
    selectedLineKey && currentOrderReview.lines[selectedLineKey]
      ? currentOrderReview.lines[selectedLineKey]
      : defaultLineReview();

  const selectedLineCatalogMatches =
    selectedLine?.supplier_item_code
      ? data?.catalogProducts.products.filter((product) =>
          product.supplier_item_codes.includes(selectedLine.supplier_item_code ?? ""),
        ) ?? []
      : [];

  const selectedCandidate =
    selectedLine?.supplier_item_code
      ? orderCandidates.find((candidate) => candidate.supplier_item_code === selectedLine.supplier_item_code) ?? null
      : null;

  const reviewedLineCount = currentOrder
    ? currentOrder.line_items.filter((line) => {
        const review = currentOrderReview.lines[lineKey(currentOrder.order_number, line)];
        return review?.status && review.status !== "unreviewed";
      }).length
    : 0;

  const flaggedLineCount = currentOrder
    ? currentOrder.line_items.filter((line) => {
        const review = currentOrderReview.lines[lineKey(currentOrder.order_number, line)];
        return review?.status === "needs_follow_up";
      }).length
    : 0;

  if (loading) {
    return (
      <div className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-500">Supplier Review</div>
        <p className="mt-3 text-slate-600">Loading Hengwei invoice review workspace…</p>
      </div>
    );
  }

  if (error || !data || !currentOrder || !currentInvoice || !reviewState) {
    return (
      <div className="rounded-3xl border border-rose-200 bg-rose-50 p-8 shadow-sm">
        <div className="text-sm font-semibold uppercase tracking-[0.24em] text-rose-700">Supplier Review</div>
        <p className="mt-3 text-rose-700">{error ?? "Unable to load the supplier review workspace."}</p>
      </div>
    );
  }

  const loadedData = data;
  const workspace = reviewState;
  const sourceItemStatus = currentOrder.item_reconciliation_status ?? "unreviewed";
  const sourceFinancialStatus = currentOrder.financial_reconciliation_status ?? "unreviewed";
  const financialIssue = currentOrder.financial_reconciliation_issue;

  const totalLineValue = currentOrder.line_items.reduce((sum, line) => sum + (line.line_total_cny ?? 0), 0);
  const totalCharges = currentOrder.charges?.reduce((sum, charge) => sum + charge.amount, 0) ?? 0;
  const highlightedTop = selectedRegion ? `${(selectedRegion.y / currentInvoice.height) * 100}%` : undefined;
  const highlightedLeft = selectedRegion ? `${(selectedRegion.x / currentInvoice.width) * 100}%` : undefined;
  const highlightedWidth = selectedRegion ? `${(selectedRegion.width / currentInvoice.width) * 100}%` : undefined;
  const highlightedHeight = selectedRegion ? `${(selectedRegion.height / currentInvoice.height) * 100}%` : undefined;

  function touchWorkspace(nextOrders: Record<string, ReviewOrderState>) {
    setReviewState({
      ...workspace,
      orders: nextOrders,
      savedAt: new Date().toISOString(),
    });
  }

  function updateOrderReview(patch: Partial<ReviewOrderState>) {
    const nextOrderReview: ReviewOrderState = {
      ...currentOrderReview,
      ...patch,
    };
    touchWorkspace({
      ...workspace.orders,
      [selectedOrderNumber]: nextOrderReview,
    });
  }

  function updateLineReview(patch: Partial<ReviewLineState>) {
    if (!selectedLineKey) return;
    const nextLineReview: ReviewLineState = {
      ...selectedLineReview,
      ...patch,
      updatedAt: new Date().toISOString(),
    };
    touchWorkspace({
      ...workspace.orders,
      [selectedOrderNumber]: {
        ...currentOrderReview,
        lines: {
          ...currentOrderReview.lines,
          [selectedLineKey]: nextLineReview,
        },
      },
    });
  }

  function exportReviewPacket() {
    const payload = {
      supplier: loadedData.bundle.supplier,
      saved_at: workspace.savedAt,
      orders: workspace.orders,
    };
    const json = JSON.stringify(payload, null, 2);

    if (typeof window === "undefined" || typeof document === "undefined") return;
    if (typeof URL.createObjectURL !== "function") return;

    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `hengwei-review-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">Supplier OCR Review</div>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
              {data.bundle.supplier.name}
              {data.bundle.supplier.name_local ? ` · ${data.bundle.supplier.name_local}` : ""}
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              Review the source invoice, the extracted structured data, the supplier catalog matches, and the per-line
              image crops in one place before we map supplier codes to live RetailSG SKUs.
            </p>
            <div className="mt-3 text-xs text-slate-500">
              Saved locally in this browser
              {reviewState.savedAt ? ` · last update ${new Date(reviewState.savedAt).toLocaleString("en-SG")}` : ""}
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <MetricCard label="Catalog Products" value={String(data.catalogProducts.products.length)} tone="emerald" />
            <MetricCard label="Reviewed Lines" value={String(reviewedLineCount)} />
            <MetricCard label="Needs Follow-up" value={String(flaggedLineCount)} tone="amber" />
          </div>
        </div>
      </section>

      <section className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-sm font-semibold text-slate-900">Invoice Set</div>
            <div className="mt-1 text-sm text-slate-500">
              {data.bundle.import_readiness.purchase_orders_ready
                ? "Ready to import into RetailSG."
                : data.bundle.import_readiness.blocking_reason}
            </div>
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-600">
                Catalog extraction {data.bundle.import_readiness.catalog_products_ready ? "ready" : "pending"}
              </span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-600">
                Product candidates {data.bundle.import_readiness.product_candidates_ready ? "ready" : "pending"}
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={exportReviewPacket}
              className="rounded-full border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:border-slate-300 hover:bg-slate-50"
            >
              Export review JSON
            </button>
            {Object.values(data.orders)
              .sort((left, right) => right.order_date.localeCompare(left.order_date))
              .map((order) => {
                const active = selectedOrderNumber === order.order_number;
                const orderItemStatus = order.item_reconciliation_status ?? "unreviewed";
                const orderFinancialStatus = order.financial_reconciliation_status ?? "unreviewed";
                return (
                  <button
                    key={order.order_number}
                    type="button"
                    onClick={() =>
                      startTransition(() => {
                        setSelectedOrderNumber(order.order_number);
                        setSelectedLineKey(null);
                        setLineSearch("");
                        setJsonMode("structured");
                      })
                    }
                    className={`rounded-2xl border px-4 py-3 text-left transition ${
                      active
                        ? "border-blue-500 bg-blue-50 text-blue-900 shadow-sm"
                        : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50"
                    }`}
                  >
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
                        Order {order.order_number}
                      </div>
                      <div className="mt-1 text-sm font-semibold">{order.order_date}</div>
                      <div className="mt-1 text-sm">
                        {formatMoney(order.source_document_total_amount, order.currency)}
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${itemReviewTone(orderItemStatus)}`}>
                          Item: {itemReviewLabel(orderItemStatus)}
                        </span>
                        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${financialReviewTone(orderFinancialStatus)}`}>
                          Finance: {financialReviewLabel(orderFinancialStatus)}
                        </span>
                      </div>
                    </div>
                  </button>
                );
              })}
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.95fr)_minmax(360px,0.95fr)]">
        <article className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Source Invoice</div>
              <h2 className="mt-2 text-xl font-semibold text-slate-900">Order {currentOrder.order_number}</h2>
            </div>
            <a
              href={currentInvoice.src}
              target="_blank"
              rel="noreferrer"
              className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:border-slate-300 hover:bg-slate-50"
            >
              Open original
            </a>
          </div>

          <div className="relative mt-5 overflow-auto rounded-3xl border border-slate-200 bg-slate-100">
            <img
              src={currentInvoice.src}
              alt={`Supplier invoice ${currentOrder.order_number}`}
              className="block w-full min-w-[420px] bg-white"
            />
            {selectedRegion && (
              <div
                className="pointer-events-none absolute rounded-xl border-2 border-blue-500 bg-blue-400/10 shadow-[0_0_0_9999px_rgba(15,23,42,0.28)]"
                style={{
                  top: highlightedTop,
                  left: highlightedLeft,
                  width: highlightedWidth,
                  height: highlightedHeight,
                }}
              />
            )}
          </div>

          <div className="mt-4 text-sm text-slate-500">
            {selectedLine
              ? `Highlighted crop for line ${selectedLine.source_line_number}${selectedLine.line_position ? selectedLine.line_position.toUpperCase() : ""}.`
              : "Select a line item to highlight its source image region."}
          </div>
        </article>

        <article className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Extracted Data</div>
              <h2 className="mt-2 text-xl font-semibold text-slate-900">OCR / structured review</h2>
            </div>
            <div className="inline-flex rounded-full border border-slate-200 bg-slate-50 p-1 text-xs font-semibold">
              <button
                type="button"
                className={`rounded-full px-3 py-1.5 ${jsonMode === "structured" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}
                onClick={() => setJsonMode("structured")}
              >
                Structured
              </button>
              <button
                type="button"
                className={`rounded-full px-3 py-1.5 ${jsonMode === "raw" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}
                onClick={() => setJsonMode("raw")}
              >
                Raw JSON
              </button>
            </div>
          </div>

          {financialIssue && (
            <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              <div className="font-semibold">Financial reconciliation flag</div>
              <div className="mt-1">
                This order has a source-document conflict. The scan shows order {currentOrder.order_number}, while an
                earlier reported reference points to order {currentOrder.reported_external_reference?.reference_number}.
              </div>
            </div>
          )}

          {jsonMode === "structured" ? (
            <div className="mt-5 space-y-5">
              <div className="grid gap-3 sm:grid-cols-2">
                <MetricCard label="Scan Total" value={formatMoney(currentOrder.source_document_total_amount, currentOrder.currency)} />
                <MetricCard label="Line Count" value={String(currentOrder.line_items.length)} />
                <MetricCard label="Line Value" value={formatMoney(totalLineValue, currentOrder.currency)} />
                <MetricCard label="Charges" value={formatMoney(totalCharges, currentOrder.currency)} />
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex flex-col gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">Split reconciliation workspace</div>
                    <div className="mt-1 text-xs text-slate-500">
                      Keep item matching and receipt confidence separate from payment settlement and banking disputes.
                    </div>
                  </div>
                  <div className="grid gap-4 xl:grid-cols-2">
                    <div className="rounded-2xl border border-white/80 bg-white p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-900">Item reconciliation</div>
                          <div className="mt-1 text-xs text-slate-500">
                            Source status: {itemReviewLabel(sourceItemStatus)}
                          </div>
                        </div>
                        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${itemReviewTone(currentOrderReview.itemStatus)}`}>
                          {itemReviewLabel(currentOrderReview.itemStatus)}
                        </span>
                      </div>
                      {!!currentOrder.item_reconciliation_notes?.length && (
                        <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                          {currentOrder.item_reconciliation_notes.join(" ")}
                        </div>
                      )}
                      <div className="mt-4 space-y-3">
                        <select
                          value={currentOrderReview.itemStatus}
                          onChange={(event) =>
                            updateOrderReview({
                              itemStatus: event.target.value as ReviewItemStatus,
                              itemReviewedAt: new Date().toISOString(),
                            })
                          }
                          className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                        >
                          <option value="unreviewed">Unreviewed</option>
                          <option value="catalog_matched">Catalog matched</option>
                          <option value="sku_mapped">SKU mapped</option>
                          <option value="needs_follow_up">Needs follow-up</option>
                        </select>
                        <textarea
                          value={currentOrderReview.itemNote}
                          onChange={(event) =>
                            updateOrderReview({
                              itemNote: event.target.value,
                              itemReviewedAt: new Date().toISOString(),
                            })
                          }
                          rows={3}
                          placeholder="Add notes about unmatched lines, SKU mapping, or receipt-level uncertainty"
                          className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                        />
                      </div>
                    </div>

                    <div className="rounded-2xl border border-white/80 bg-white p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-900">Financial reconciliation</div>
                          <div className="mt-1 text-xs text-slate-500">
                            Source status: {financialReviewLabel(sourceFinancialStatus)}
                          </div>
                        </div>
                        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${financialReviewTone(currentOrderReview.financialStatus)}`}>
                          {financialReviewLabel(currentOrderReview.financialStatus)}
                        </span>
                      </div>
                      {!!currentOrder.financial_reconciliation_notes?.length && (
                        <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                          {currentOrder.financial_reconciliation_notes.join(" ")}
                        </div>
                      )}
                      <div className="mt-4 space-y-3">
                        <select
                          value={currentOrderReview.financialStatus}
                          onChange={(event) =>
                            updateOrderReview({
                              financialStatus: event.target.value as ReviewFinancialStatus,
                              financialReviewedAt: new Date().toISOString(),
                            })
                          }
                          className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                        >
                          <option value="unreviewed">Unreviewed</option>
                          <option value="unpaid">Unpaid</option>
                          <option value="partially_paid">Partially paid</option>
                          <option value="paid">Paid</option>
                          <option value="disputed">Disputed</option>
                        </select>
                        <textarea
                          value={currentOrderReview.financialNote}
                          onChange={(event) =>
                            updateOrderReview({
                              financialNote: event.target.value,
                              financialReviewedAt: new Date().toISOString(),
                            })
                          }
                          rows={3}
                          placeholder="Add payment evidence reminders, bank matching notes, or FX discrepancy details"
                          className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {!!currentOrder.payment_breakdown?.length && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">Payment notes</h3>
                  <div className="mt-3 space-y-2">
                    {currentOrder.payment_breakdown.map((payment, index) => (
                      <div key={`${payment.method}-${index}`} className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                        <div className="font-medium capitalize">{payment.method.split("_").join(" ")}</div>
                        <div className="mt-1">
                          {formatMoney(payment.amount, payment.currency)}
                          {payment.reported_fx_rate_cny_per_sgd
                            ? ` at ${payment.reported_fx_rate_cny_per_sgd} CNY/SGD`
                            : ""}
                        </div>
                        {payment.bank_name && (
                          <div className="mt-1 text-xs text-slate-500">
                            {payment.bank_name}, {payment.bank_location} · {payment.account_number} · {payment.swift_code}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {!!currentOrder.inventory_movement && (
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                  <div className="font-semibold text-slate-900">Movement plan</div>
                  <div className="mt-2">
                    {currentOrder.inventory_movement.current_location} · {currentOrder.inventory_movement.current_state}
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    Planned destination: {currentOrder.inventory_movement.planned_destination} ·{" "}
                    {currentOrder.inventory_movement.planned_destination_open_date}
                  </div>
                </div>
              )}

              <div>
                <label htmlFor="line-search" className="text-sm font-semibold text-slate-900">
                  Filter extracted lines
                </label>
                <input
                  id="line-search"
                  value={lineSearch}
                  onChange={(event) => setLineSearch(event.target.value)}
                  placeholder="Search by supplier code, material, size, or note"
                  className="mt-2 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                />
              </div>

              <div className="max-h-[640px] overflow-auto rounded-3xl border border-slate-200">
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-[0.18em] text-slate-500">
                    <tr>
                      <th className="px-4 py-3">Line</th>
                      <th className="px-4 py-3">Code</th>
                      <th className="px-4 py-3">Catalog</th>
                      <th className="px-4 py-3">Review</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {filteredLineItems.map((line) => {
                      const key = lineKey(currentOrder.order_number, line);
                      const isSelected = key === selectedLineKey;
                      const review = currentOrderReview.lines[key] ?? defaultLineReview();
                      const catalogMatchCount = line.supplier_item_code
                        ? data.catalogProducts.products.filter((product) =>
                            product.supplier_item_codes.includes(line.supplier_item_code ?? ""),
                          ).length
                        : 0;
                      return (
                        <tr
                          key={key}
                          className={`cursor-pointer transition ${isSelected ? "bg-blue-50" : "hover:bg-slate-50"}`}
                          onClick={() => setSelectedLineKey(key)}
                        >
                          <td className="px-4 py-3 font-medium text-slate-700">
                            {line.source_line_number}
                            {line.line_position ? line.line_position.toUpperCase() : ""}
                          </td>
                          <td className="px-4 py-3">
                            <div className="font-medium text-slate-900">{line.supplier_item_code ?? line.display_name ?? "Uncoded item"}</div>
                            <div className="mt-1 text-xs text-slate-500">{line.material_description ?? "No material description"}</div>
                          </td>
                          <td className="px-4 py-3 text-slate-600">
                            {catalogMatchCount ? `${catalogMatchCount} match${catalogMatchCount > 1 ? "es" : ""}` : "No match"}
                          </td>
                          <td className="px-4 py-3">
                            <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${lineReviewTone(review.status)}`}>
                              {lineReviewLabel(review.status)}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <pre className="mt-5 max-h-[820px] overflow-auto rounded-3xl border border-slate-200 bg-slate-950 p-4 text-xs leading-6 text-slate-100">
              {JSON.stringify(currentOrder, null, 2)}
            </pre>
          )}
        </article>

        <article className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Extracted Images</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">Line image crops</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              These previews are pulled from the invoice image so you can compare the picture cell against the extracted
              data, the supplier catalog, and your review decision without leaving the page.
            </p>
          </div>

          {selectedLine && selectedRegion && (
            <div className="mt-5 space-y-4 rounded-3xl border border-blue-200 bg-blue-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">Selected line</div>
              <div className="flex flex-col items-start gap-4">
                <InvoiceCropPreview
                  src={currentInvoice.src}
                  originalWidth={currentInvoice.width}
                  originalHeight={currentInvoice.height}
                  crop={selectedRegion}
                  previewWidth={260}
                  alt={`Extracted image for ${selectedLine.supplier_item_code ?? selectedLine.display_name ?? `line ${selectedLine.source_line_number}`}`}
                />
                <div className="space-y-1 text-sm text-slate-700">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="font-semibold text-slate-900">
                      {selectedLine.supplier_item_code ?? selectedLine.display_name ?? `Line ${selectedLine.source_line_number}`}
                    </div>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${lineReviewTone(selectedLineReview.status)}`}>
                      {lineReviewLabel(selectedLineReview.status)}
                    </span>
                  </div>
                  <div>{selectedLine.material_description ?? "No material description"}</div>
                  <div className="text-slate-500">
                    Qty {selectedLine.quantity ?? "n/a"} · {formatMoney(selectedLine.unit_cost_cny, currentOrder.currency)} each
                  </div>
                </div>
              </div>

              <div className="rounded-3xl border border-white/70 bg-white/80 p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">Manager review workspace</div>
                    <div className="mt-1 text-xs text-slate-500">
                      Save your line-by-line verification notes while you compare the scan and catalog.
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => updateLineReview({ status: "verified" })}
                      className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100"
                    >
                      Mark line verified
                    </button>
                    <button
                      type="button"
                      onClick={() => updateLineReview({ status: "needs_follow_up" })}
                      className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100"
                    >
                      Flag follow-up
                    </button>
                  </div>
                </div>

                <div className="mt-4 space-y-3">
                  <select
                    value={selectedLineReview.status}
                    onChange={(event) => updateLineReview({ status: event.target.value as ReviewLineStatus })}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                  >
                    <option value="unreviewed">Unreviewed</option>
                    <option value="verified">Verified</option>
                    <option value="needs_follow_up">Needs follow-up</option>
                  </select>

                  <input
                    value={selectedLineReview.targetSkuId}
                    onChange={(event) => updateLineReview({ targetSkuId: event.target.value })}
                    placeholder="Optional target RetailSG SKU id"
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                  />

                  <select
                    value={selectedLineReview.matchedCatalogProductId ?? ""}
                    onChange={(event) =>
                      updateLineReview({
                        matchedCatalogProductId: event.target.value ? event.target.value : null,
                      })
                    }
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                  >
                    <option value="">No catalog match selected</option>
                    {selectedLineCatalogMatches.map((product) => (
                      <option key={product.catalog_product_id} value={product.catalog_product_id}>
                        {product.primary_supplier_item_code} · {product.sheet_name} · {product.display_name || "Unnamed catalog item"}
                      </option>
                    ))}
                  </select>

                  <textarea
                    value={selectedLineReview.note}
                    onChange={(event) => updateLineReview({ note: event.target.value })}
                    rows={4}
                    placeholder="Add notes about discrepancies, missing catalog context, or what should happen next"
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                  />
                </div>
              </div>

              <div className="rounded-3xl border border-white/70 bg-white/80 p-4">
                <div className="text-sm font-semibold text-slate-900">Catalog matches</div>
                <div className="mt-1 text-xs text-slate-500">
                  {selectedLineCatalogMatches.length
                    ? "Exact supplier-code matches from the structured Hengwei catalogs."
                    : "No exact catalog match for this supplier code yet."}
                </div>
                {selectedLineCatalogMatches.length ? (
                  <div className="mt-4 space-y-3">
                    {selectedLineCatalogMatches.map((product) => {
                      const selected = selectedLineReview.matchedCatalogProductId === product.catalog_product_id;
                      return (
                        <button
                          key={product.catalog_product_id}
                          type="button"
                          onClick={() => updateLineReview({ matchedCatalogProductId: product.catalog_product_id })}
                          className={`w-full rounded-2xl border p-4 text-left transition ${
                            selected
                              ? "border-blue-500 bg-blue-50"
                              : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-slate-900">
                                {product.primary_supplier_item_code} · {product.display_name || "Unnamed catalog item"}
                              </div>
                              <div className="mt-1 text-xs text-slate-500">
                                {product.sheet_name} · {product.catalog_file}
                              </div>
                            </div>
                            {product.price_options_cny.length > 0 && (
                              <div className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600">
                                {product.price_label === "special" ? "Special" : "Unit"}{" "}
                                {product.price_options_cny.map((value) => formatMoney(value, "CNY")).join(" / ")}
                              </div>
                            )}
                          </div>
                          <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
                            <div>Materials: {product.materials || "n/a"}</div>
                            <div>Size: {product.size || "n/a"}</div>
                            <div>Color: {product.color || "n/a"}</div>
                            <div>Raw model: {product.raw_model}</div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </div>

              {selectedCandidate && (
                <div className="rounded-3xl border border-white/70 bg-white/80 p-4">
                  <div className="text-sm font-semibold text-slate-900">Candidate staging record</div>
                  <div className="mt-3 text-sm text-slate-600">
                    {selectedCandidate.supplier_item_code} · {selectedCandidate.inventory_type} · {selectedCandidate.sourcing_strategy}
                  </div>
                  <div className="mt-2 text-xs text-slate-500">
                    Catalog matches in staging: {selectedCandidate.catalog_match_count ?? 0}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {filteredLineItems.map((line) => {
              const key = lineKey(currentOrder.order_number, line);
              const crop = currentInvoice.lineRegions[key];
              const candidate = line.supplier_item_code
                ? orderCandidates.find((item) => item.supplier_item_code === line.supplier_item_code)
                : null;
              const review = currentOrderReview.lines[key] ?? defaultLineReview();
              const catalogMatchCount = line.supplier_item_code
                ? data.catalogProducts.products.filter((product) =>
                    product.supplier_item_codes.includes(line.supplier_item_code ?? ""),
                  ).length
                : 0;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setSelectedLineKey(key)}
                  className={`rounded-3xl border p-3 text-left transition ${
                    key === selectedLineKey
                      ? "border-blue-500 bg-blue-50 shadow-sm"
                      : "border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-white"
                  }`}
                >
                  {crop ? (
                    <div className="flex justify-center">
                      <InvoiceCropPreview
                        src={currentInvoice.src}
                        originalWidth={currentInvoice.width}
                        originalHeight={currentInvoice.height}
                        crop={crop}
                        previewWidth={160}
                        alt={`Crop for ${line.supplier_item_code ?? line.display_name ?? `line ${line.source_line_number}`}`}
                      />
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-xs text-slate-400">
                      Crop preview unavailable
                    </div>
                  )}
                  <div className="mt-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-sm font-semibold text-slate-900">
                        {line.supplier_item_code ?? line.display_name ?? `Line ${line.source_line_number}`}
                      </div>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${lineReviewTone(review.status)}`}>
                        {lineReviewLabel(review.status)}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      Line {line.source_line_number}
                      {line.line_position ? line.line_position.toUpperCase() : ""} · {line.size ?? "No size"}
                    </div>
                    <div className="mt-2 text-xs text-slate-600">{line.material_description ?? "No material description"}</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {candidate && (
                        <div className="rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-emerald-700">
                          Product candidate ready
                        </div>
                      )}
                      <div className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-600">
                        {catalogMatchCount} catalog match{catalogMatchCount === 1 ? "" : "es"}
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {!!uncodedLines.length && (
            <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              <div className="font-semibold">Uncoded lines still need manual mapping</div>
              <div className="mt-2 space-y-1">
                {uncodedLines.map((line) => (
                  <div key={`${line.order_number}-${line.source_line_number}`}>
                    Order {line.order_number} · line {line.source_line_number} · {line.display_name ?? "Unnamed line"}
                  </div>
                ))}
              </div>
            </div>
          )}
        </article>
      </section>
    </div>
  );
}
