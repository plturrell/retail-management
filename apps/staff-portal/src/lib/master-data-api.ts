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
    } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.launch_only !== undefined) q.set("launch_only", String(params.launch_only));
    if (params.needs_price !== undefined) q.set("needs_price", String(params.needs_price));
    if (params.purchased_only !== undefined) q.set("purchased_only", String(params.purchased_only));
    if (params.supplier) q.set("supplier", params.supplier);
    return request<{ count: number; products: ProductRow[] }>(`/products?${q.toString()}`);
  },
  patchProduct: (sku: string, patch: ProductPatch) =>
    request<ProductRow>(`/products/${encodeURIComponent(sku)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  exportNecJewel: () => request<ExportResult>(`/export/nec_jewel`, { method: "POST" }),
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
};
