// Client for the auth-protected backend master-data API.
import { auth } from "./firebase";
import { API_BASE_URL } from "./api";

const MASTER_DATA_PREFIX = "/master-data";

export interface ProductRow {
  sku_code: string;
  internal_code?: string | null;
  supplier_id?: string | null;
  supplier_name?: string | null;
  description?: string | null;
  long_description?: string | null;
  product_type?: string | null;
  material?: string | null;
  category?: string | null;
  size?: string | null;
  qty_on_hand?: number | null;
  cost_price?: number | null;
  cost_currency?: string | null;
  cost_basis?: { source_currency?: string; source_amount?: number; fx_rate_cny_per_sgd?: number } | null;
  retail_price?: number | null;
  retail_price_note?: string | null;
  retail_price_set_at?: string | null;
  sale_ready?: boolean;
  block_sales?: boolean;
  needs_retail_price?: boolean;
  needs_review?: boolean;
  stocking_location?: string | null;
  nec_plu?: string | null;
  sourcing_strategy?: string | null;
  inventory_type?: string | null;
  image_urls?: string[];
  thumbnail_url?: string | null;
  variant_group_id?: string | null;
  variant_label?: string | null;
  variant_siblings?: ProductRow[];
}

export interface PosStatusEntry {
  in_plus: boolean;
  has_current_price: boolean;
  active_price_id?: string | null;
}

export interface PosStatusResponse {
  as_of: string;
  plus: Record<string, PosStatusEntry>;
}

export interface ExportLabelsRequest {
  skus: string[];
  output_name?: string;
  include_box?: boolean;
}

export interface LabelsExportResult extends ExportResult {
  missing_skus?: string[];
  skus_no_plu?: string[];
  plu_count?: number;
}

export interface ProductPatch {
  retail_price?: number;
  sale_ready?: boolean;
  block_sales?: boolean;
  description?: string;
  long_description?: string;
  qty_on_hand?: number;
  notes?: string;
  stocking_location?: string;
}

export interface Stats {
  total: number;
  sale_ready: number;
  needs_price_flag: number;
  needs_review_flag: number;
  sale_ready_missing_price: number;
  by_supplier: Record<string, number>;
}

export interface ExportResult {
  ok: boolean;
  exit_code: number;
  output_path?: string | null;
  download_url?: string | null;
  stdout: string;
  stderr: string;
}

export interface IngestPreviewItem {
  line_number?: number | null;
  supplier_item_code?: string | null;
  product_name_en?: string | null;
  material?: string | null;
  product_type?: string | null;
  size?: string | null;
  quantity?: number | null;
  unit_price_cny?: number | null;
  proposed_sku?: string | null;
  proposed_plu?: string | null;
  proposed_cost_sgd?: number | null;
  already_exists?: boolean;
  existing_sku?: string | null;
  skip_reason?: string | null;
}

export interface IngestPreview {
  upload_id: string;
  document_type?: string | null;
  document_number?: string | null;
  document_date?: string | null;
  supplier_name?: string | null;
  currency?: string | null;
  document_total?: number | null;
  items: IngestPreviewItem[];
  summary: {
    total_lines: number;
    new_skus: number;
    already_exists: number;
    skipped: number;
  };
}

export interface IngestCommitRequest {
  upload_id: string;
  items: IngestPreviewItem[];
  supplier_id?: string;
  supplier_name?: string;
  order_number?: string | null;
}

export interface IngestCommitResult {
  added: number;
  skipped: number;
  added_entries: ProductRow[];
  skipped_entries: { item: IngestPreviewItem; reason: string }[];
}

export interface PriceRecommendation {
  sku_code: string;
  recommended_retail_sgd: number;
  implied_margin_pct?: number | null;
  confidence: "low" | "medium" | "high";
  comparable_skus?: string[];
  rationale: string;
}

export interface PriceRecommendationsResponse {
  rules_inferred?: string[];
  recommendations: PriceRecommendation[];
  notes?: string | null;
  n_priced_examples?: number;
  n_targets?: number;
}

export interface PublishPriceRequest {
  retail_price: number;
  store_code?: string;
  currency?: string;
  tax_code?: string;
  /**
   * Concurrency guard. Pass the price_id the row was loaded with (or "" if
   * the SKU had no active price). The server returns 409 if someone else
   * has published a different price since.
   */
  expected_active_price_id?: string;
}

export interface PublishPriceResult {
  ok: boolean;
  sku: string;
  plu_code: string;
  sku_id: string;
  plu_id: string;
  price_id: string;
  retail_price: number;
  currency?: string;
  tax_code?: string;
  valid_from: string;
  valid_to: string;
  superseded_price_ids: string[];
  store_id: string;
  product: ProductRow;
  audit?: { actor_email?: string | null; actor_user_id?: string | null };
}

/**
 * Hand-entered SKU — companion to invoice OCR ingest for one-off products.
 * If retail_price is supplied the server will create the SKU *and* publish
 * the price to Firestore in a single round-trip.
 *
 * NOTE: SKU code and NEC PLU are *intentionally* not on this interface.
 * They are always auto-allocated server-side from the shared identifier
 * sequence so SKU/PLU pairs cannot drift. Do not re-add overrides here.
 */
export interface CreateProductRequest {
  description: string;
  long_description?: string | null;
  product_type: string;
  material: string;
  size?: string | null;
  supplier_id?: string | null;
  supplier_name?: string | null;
  /** Supplier's own catalog code; links the row back to the supplier catalog. */
  supplier_item_code?: string | null;
  internal_code?: string | null;
  cost_price?: number | null;
  cost_currency?: string | null;
  qty_on_hand?: number | null;
  /** One of the values from `getSourcingOptions()`. */
  sourcing_strategy?: string;
  /** Auto-derived from sourcing_strategy when omitted. */
  inventory_type?: string | null;
  notes?: string | null;
  retail_price?: number | null;
  store_code?: string;
  currency?: string;
  tax_code?: string;
  image_urls?: string[];
  variant_of_sku?: string | null;
  variant_label?: string | null;
}

export interface CreateProductResult {
  ok: boolean;
  product: ProductRow;
  publish_result: PublishPriceResult | null;
}

export interface ProductImageUploadResult {
  url: string;
  thumbnail_url: string;
  product: ProductRow;
}

// ── Sourcing taxonomy + supplier catalog ───────────────────────────────────

export interface SourcingOption {
  value: string;
  label: string;
  description: string;
  requires_supplier: boolean;
  inventory_type: string;
}

export interface SourcingOptionsResponse {
  options: SourcingOption[];
}

export interface SupplierSummary {
  slug: string;
  supplier_id: string | null;
  supplier_name: string;
  product_count: number;
  has_catalog: boolean;
}

export interface SuppliersResponse {
  suppliers: SupplierSummary[];
}

export interface SupplierCatalogProduct {
  catalog_product_id?: string | null;
  primary_supplier_item_code?: string | null;
  supplier_item_codes?: string[];
  raw_model?: string | null;
  display_name?: string | null;
  size?: string | null;
  materials?: string | null;
  color?: string | null;
  price_options_cny?: number[];
  raw_price?: string | null;
  notes?: string | null;
}

export interface SupplierCatalogResponse {
  slug: string;
  supplier_id: string | null;
  supplier_name: string | null;
  count: number;
  products: SupplierCatalogProduct[];
}

export interface SupplierCatalogEntryAddRequest {
  supplier_item_code: string;
  display_name?: string | null;
  materials?: string | null;
  size?: string | null;
  color?: string | null;
  unit_price_cny?: number | null;
  notes?: string | null;
}

export interface AiDescribeRequest {
  product_type: string;
  material: string;
  size?: string | null;
  supplier_name?: string | null;
  supplier_item_code?: string | null;
  supplier_catalog_hint?: string | null;
  sourcing_strategy?: string | null;
}

export interface AiDescribeResponse {
  description: string;
  long_description: string;
  is_fallback: boolean;
  model?: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const user = auth.currentUser;
  if (!user) throw new Error("Not authenticated");
  const token = await user.getIdToken();
  const res = await fetch(`${API_BASE_URL}${MASTER_DATA_PREFIX}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

async function requestFile(path: string): Promise<Blob> {
  const user = auth.currentUser;
  if (!user) throw new Error("Not authenticated");
  const token = await user.getIdToken();
  const res = await fetch(`${API_BASE_URL}${MASTER_DATA_PREFIX}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.blob();
}

export const masterDataApi = {
  health: () => request<{ status: string; master_exists: boolean }>("/health"),
  stats: () => request<Stats>("/stats"),
  listProducts: (
    params: {
      launch_only?: boolean;
      needs_price?: boolean;
      supplier?: string;
      purchased_only?: boolean;
      sourcing_strategy?: string;
      group_variants?: boolean;
    } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.launch_only !== undefined) q.set("launch_only", String(params.launch_only));
    if (params.needs_price !== undefined) q.set("needs_price", String(params.needs_price));
    if (params.purchased_only !== undefined) q.set("purchased_only", String(params.purchased_only));
    if (params.supplier) q.set("supplier", params.supplier);
    if (params.sourcing_strategy) q.set("sourcing_strategy", params.sourcing_strategy);
    if (params.group_variants !== undefined) q.set("group_variants", String(params.group_variants));
    return request<{ count: number; products: ProductRow[] }>(`/products?${q.toString()}`);
  },
  patchProduct: (sku: string, patch: ProductPatch) =>
    request<ProductRow>(`/products/${encodeURIComponent(sku)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  exportNecJewel: () => request<ExportResult>(`/export/nec_jewel`, { method: "POST" }),
  exportLabels: (req: ExportLabelsRequest) =>
    request<LabelsExportResult>(`/export/labels`, {
      method: "POST",
      body: JSON.stringify(req),
    }),
  posStatus: () => request<PosStatusResponse>(`/pos-status`),
  downloadExport: (filename: string) => requestFile(`/exports/${encodeURIComponent(filename)}`),
  ingestInvoice: async (file: File): Promise<IngestPreview> => {
    const user = auth.currentUser;
    if (!user) throw new Error("Not authenticated");
    const token = await user.getIdToken();
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE_URL}${MASTER_DATA_PREFIX}/ingest/invoice`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    return res.json() as Promise<IngestPreview>;
  },
  commitInvoice: (req: IngestCommitRequest) =>
    request<IngestCommitResult>(`/ingest/invoice/commit`, {
      method: "POST",
      body: JSON.stringify(req),
    }),
  recommendPrices: (params: { target_skus?: string[]; max_targets?: number } = {}) =>
    request<PriceRecommendationsResponse>(`/ai/recommend_prices`, {
      method: "POST",
      body: JSON.stringify({
        target_skus: params.target_skus,
        max_targets: params.max_targets ?? 80,
      }),
    }),
  publishPrice: (sku: string, req: PublishPriceRequest) =>
    request<PublishPriceResult>(`/products/${encodeURIComponent(sku)}/publish_price`, {
      method: "POST",
      body: JSON.stringify(req),
    }),
  createProduct: (req: CreateProductRequest) =>
    request<CreateProductResult>(`/products`, {
      method: "POST",
      body: JSON.stringify(req),
    }),
  uploadProductImage: async (sku: string, file: File): Promise<ProductImageUploadResult> => {
    const user = auth.currentUser;
    if (!user) throw new Error("Not authenticated");
    const token = await user.getIdToken();
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(
      `${API_BASE_URL}${MASTER_DATA_PREFIX}/products/${encodeURIComponent(sku)}/images`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      },
    );
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    return res.json() as Promise<ProductImageUploadResult>;
  },
  getSourcingOptions: () => request<SourcingOptionsResponse>(`/sourcing-options`),
  listSuppliers: () => request<SuppliersResponse>(`/suppliers`),
  getSupplierCatalog: (slug: string, params: { query?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.query) q.set("query", params.query);
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<SupplierCatalogResponse>(
      `/suppliers/${encodeURIComponent(slug)}/catalog${qs ? `?${qs}` : ""}`,
    );
  },
  addSupplierCatalogEntry: (slug: string, req: SupplierCatalogEntryAddRequest) =>
    request<SupplierCatalogProduct>(
      `/suppliers/${encodeURIComponent(slug)}/catalog`,
      {
        method: "POST",
        body: JSON.stringify(req),
      },
    ),
  aiDescribeProduct: (req: AiDescribeRequest) =>
    request<AiDescribeResponse>(`/ai/describe_product`, {
      method: "POST",
      body: JSON.stringify(req),
    }),
  publishPricesBulk: (req: BulkPublishRequest) =>
    request<BulkPublishResponse>(`/products/publish_prices_bulk`, {
      method: "POST",
      body: JSON.stringify(req),
    }),
};

// ── Bulk publish (multi-SKU) ────────────────────────────────────────────────

export interface BulkPublishItem {
  sku: string;
  retail_price: number;
  store_code?: string;
  currency?: string;
  tax_code?: string;
  expected_active_price_id?: string;
}

export interface BulkPublishRequest {
  items: BulkPublishItem[];
}

export interface BulkPublishItemError {
  status_code: number;
  code?: string;
  message?: string;
  expected?: string | null;
  actual?: string | null;
}

export interface BulkPublishItemResult {
  sku: string;
  ok: boolean;
  price_id?: string | null;
  superseded_price_ids: string[];
  error?: BulkPublishItemError | null;
}

export interface BulkPublishResponse {
  ok: boolean;
  succeeded: number;
  failed: number;
  results: BulkPublishItemResult[];
}

// ── CAG export endpoints ────────────────────────────────────────────────────

export interface CagPushResponse {
  files_uploaded: string[];
  bytes_uploaded: number;
  counts: Record<string, number>;
  started_at: string;
  finished_at: string | null;
  errors: string[];
}

export interface CagErrorEntry {
  status: string;
  line: number;
  message: string;
  source_file: string | null;
}

const CAG_EXPORT_PREFIX = "/cag/export";

async function cagRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const user = auth.currentUser;
  if (!user) throw new Error("Not authenticated");
  const token = await user.getIdToken();
  const res = await fetch(`${API_BASE_URL}${CAG_EXPORT_PREFIX}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

async function cagRequestFile(path: string): Promise<{ blob: Blob; filename: string }> {
  const user = auth.currentUser;
  if (!user) throw new Error("Not authenticated");
  const token = await user.getIdToken();
  const res = await fetch(`${API_BASE_URL}${CAG_EXPORT_PREFIX}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  const cd = res.headers.get("Content-Disposition") || "";
  const match = cd.match(/filename="?([^";]+)"?/i);
  return { blob: await res.blob(), filename: match?.[1] || "cag_bundle.zip" };
}

export const cagExportApi = {
  txt: (params: { tenant_code?: string; nec_store_id?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.tenant_code) q.set("tenant_code", params.tenant_code);
    if (params.nec_store_id) q.set("nec_store_id", params.nec_store_id);
    const qs = q.toString();
    return cagRequestFile(`/txt${qs ? `?${qs}` : ""}`);
  },
  push: (params: { tenant_code?: string; nec_store_id?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.tenant_code) q.set("tenant_code", params.tenant_code);
    if (params.nec_store_id) q.set("nec_store_id", params.nec_store_id);
    const qs = q.toString();
    return cagRequest<CagPushResponse>(`/push${qs ? `?${qs}` : ""}`, { method: "POST" });
  },
  // On-demand mirror of POST /push/scheduled — same default-resolution and
  // telemetry path, but owner-authenticated for ad-hoc verification from the
  // Settings page.
  testScheduledPush: (
    body: { tenant_code?: string; nec_store_id?: string; taxable?: boolean } = {},
  ) =>
    cagRequest<CagPushResponse>("/push/test", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  errors: (limit = 50) =>
    cagRequest<CagErrorEntry[]>(`/errors?limit=${encodeURIComponent(String(limit))}`),
};
