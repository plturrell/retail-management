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
 */
export interface CreateProductRequest {
  description: string;
  long_description?: string | null;
  product_type: string;
  material: string;
  size?: string | null;
  supplier_id?: string;
  supplier_name?: string | null;
  internal_code?: string | null;
  cost_price?: number | null;
  cost_currency?: string | null;
  qty_on_hand?: number | null;
  sku_code?: string | null;
  nec_plu?: string | null;
  sourcing_strategy?: string;
  inventory_type?: string;
  notes?: string | null;
  retail_price?: number | null;
  store_code?: string;
  currency?: string;
  tax_code?: string;
}

export interface CreateProductResult {
  ok: boolean;
  product: ProductRow;
  publish_result: PublishPriceResult | null;
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
    } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.launch_only !== undefined) q.set("launch_only", String(params.launch_only));
    if (params.needs_price !== undefined) q.set("needs_price", String(params.needs_price));
    if (params.purchased_only !== undefined) q.set("purchased_only", String(params.purchased_only));
    if (params.supplier) q.set("supplier", params.supplier);
    if (params.sourcing_strategy) q.set("sourcing_strategy", params.sourcing_strategy);
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
};
