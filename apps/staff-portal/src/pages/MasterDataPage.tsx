import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  masterDataApi,
  type CreateProductRequest,
  type ExportResult,
  type IngestPreview,
  type LabelsExportResult,
  type PosStatusResponse,
  type PriceRecommendationsResponse,
  type ProductRow,
  type Stats,
} from "../lib/master-data-api";
import { auth } from "../lib/firebase";
import { useAuth } from "../contexts/AuthContext";

type SaveState = "idle" | "saving" | "saved" | "error";
type PublishState = "idle" | "publishing" | "published" | "error";

interface RowState {
  product: ProductRow;
  draftPrice: string;
  draftNotes: string;
  saleReady: boolean;
  save: SaveState;
  error?: string;
  savedAt?: number;
  publish: PublishState;
  publishError?: string;
  publishedAt?: number;
}

const SUPPLIER_LABELS: Record<string, string> = {
  "CN-001": "Hengwei Craft",
  "(none)": "Internal / Other",
};

function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(2);
}

function marginPct(cost: number | null | undefined, retail: number | null | undefined): string {
  if (!cost || !retail || cost <= 0) return "—";
  return `${(((retail - cost) / retail) * 100).toFixed(0)}%`;
}

function suggestedRetail(cost: number | null | undefined): string {
  if (!cost) return "";
  return (Math.round(cost * 3 / 5) * 5).toFixed(0);
}

// Mirrors the backend allowlist (settings.MASTER_DATA_PUBLISHER_EMAILS in
// backend/app/config.py). UI-only convenience: the server is the source of
// truth — non-allowlisted owners get a 403 from /publish_price even if they
// somehow manage to call it. Override locally with VITE_MASTER_DATA_PUBLISHERS
// (comma-separated emails).
const PUBLISHER_ALLOWLIST: ReadonlySet<string> = new Set(
  (import.meta.env.VITE_MASTER_DATA_PUBLISHERS || "craig@victoriaenso.com,irina@victoriaenso.com")
    .split(",")
    .map((s: string) => s.trim().toLowerCase())
    .filter(Boolean),
);

export default function MasterDataPage() {
  const { isOwner, user } = useAuth();
  const canPublishPrice =
    isOwner &&
    Boolean(user?.email) &&
    PUBLISHER_ALLOWLIST.has((user!.email as string).toLowerCase());
  const [stats, setStats] = useState<Stats | null>(null);
  const [rows, setRows] = useState<RowState[]>([]);
  const [loading, setLoading] = useState(true);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [supplierFilter, setSupplierFilter] = useState<string>("all");
  const [sourcingFilter, setSourcingFilter] = useState<string>("all");
  const [needsPriceOnly, setNeedsPriceOnly] = useState(true);
  const [purchasedOnly, setPurchasedOnly] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [lastExport, setLastExport] = useState<ExportResult | null>(null);
  const [posStatus, setPosStatus] = useState<PosStatusResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [labelsExporting, setLabelsExporting] = useState(false);
  const [lastLabelsExport, setLastLabelsExport] = useState<LabelsExportResult | null>(null);
  const [ingestState, setIngestState] = useState<
    | { kind: "idle" }
    | { kind: "uploading"; filename: string }
    | { kind: "preview"; preview: IngestPreview; selected: Set<string> }
    | { kind: "committing" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const [aiState, setAiState] = useState<
    | { kind: "idle" }
    | { kind: "loading" }
    | { kind: "preview"; response: PriceRecommendationsResponse; accepted: Set<string>; overrides: Record<string, string> }
    | { kind: "applying"; total: number; done: number }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const [createState, setCreateState] = useState<
    | { kind: "idle" }
    | { kind: "open" }
    | { kind: "submitting" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setGlobalError(null);
    try {
      const [statsRes, productsRes, posRes] = await Promise.all([
        masterDataApi.stats(),
        masterDataApi.listProducts({
          launch_only: true,
          needs_price: needsPriceOnly,
          purchased_only: purchasedOnly,
          sourcing_strategy: sourcingFilter !== "all" ? sourcingFilter : undefined,
        }),
        masterDataApi.posStatus().catch(() => null),
      ]);
      setStats(statsRes);
      setPosStatus(posRes);
      setRows(
        productsRes.products.map((p) => ({
          product: p,
          draftPrice: p.retail_price ? String(p.retail_price) : "",
          draftNotes: p.retail_price_note ?? "",
          saleReady: Boolean(p.sale_ready),
          save: "idle",
          publish: "idle",
        })),
      );
      setSelected((prev) => {
        const visible = new Set(productsRes.products.map((p) => p.sku_code));
        const next = new Set<string>();
        for (const sku of prev) if (visible.has(sku)) next.add(sku);
        return next;
      });
    } catch (e) {
      setGlobalError(`Couldn't reach the backend master-data API. (${(e as Error).message})`);
    } finally {
      setLoading(false);
    }
  }, [needsPriceOnly, purchasedOnly, sourcingFilter]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (supplierFilter !== "all") {
        const sup = r.product.supplier_id || "(none)";
        if (sup !== supplierFilter) return false;
      }
      if (q) {
        const haystack = [
          r.product.sku_code,
          r.product.internal_code,
          r.product.description,
          r.product.material,
          r.product.product_type,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [rows, search, supplierFilter]);

  const supplierOptions = useMemo(() => {
    const codes = Array.from(new Set(rows.map((r) => r.product.supplier_id || "(none)"))).sort();
    return codes;
  }, [rows]);

  const sourcingOptions = useMemo(() => {
    const codes = Array.from(
      new Set(rows.map((r) => r.product.sourcing_strategy || "(unset)")),
    ).sort();
    return codes;
  }, [rows]);

  const posLookup = useCallback(
    (plu: string | null | undefined): "live" | "no-price" | "missing" => {
      if (!plu || !posStatus) return "missing";
      const entry = posStatus.plus[String(plu)];
      if (!entry) return "missing";
      return entry.has_current_price ? "live" : "no-price";
    },
    [posStatus],
  );

  const updateRow = (sku: string, fn: (r: RowState) => RowState) => {
    setRows((prev) => prev.map((r) => (r.product.sku_code === sku ? fn(r) : r)));
  };

  const saveRow = async (sku: string) => {
    if (!isOwner) return;
    const row = rows.find((r) => r.product.sku_code === sku);
    if (!row) return;
    const priceNum = Number.parseFloat(row.draftPrice);
    if (Number.isNaN(priceNum) || priceNum <= 0) {
      updateRow(sku, (r) => ({ ...r, save: "error", error: "Enter a positive price" }));
      return;
    }
    updateRow(sku, (r) => ({ ...r, save: "saving", error: undefined }));
    try {
      const updated = await masterDataApi.patchProduct(sku, {
        retail_price: priceNum,
        sale_ready: row.saleReady,
        notes: row.draftNotes || undefined,
      });
      updateRow(sku, (r) => ({
        ...r,
        product: updated,
        save: "saved",
        savedAt: Date.now(),
        error: undefined,
      }));
    } catch (e) {
      updateRow(sku, (r) => ({ ...r, save: "error", error: (e as Error).message }));
    }
  };

  const onPriceKey = (sku: string, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (isOwner && e.key === "Enter") void saveRow(sku);
  };

  const publishRow = async (sku: string) => {
    if (!canPublishPrice) return;
    const row = rows.find((r) => r.product.sku_code === sku);
    if (!row) return;
    const priceNum = Number.parseFloat(row.draftPrice);
    if (Number.isNaN(priceNum) || priceNum <= 0) {
      updateRow(sku, (r) => ({ ...r, publish: "error", publishError: "Enter a price first" }));
      return;
    }
    if (!row.product.nec_plu) {
      updateRow(sku, (r) => ({ ...r, publish: "error", publishError: "SKU has no PLU" }));
      return;
    }
    updateRow(sku, (r) => ({ ...r, publish: "publishing", publishError: undefined }));
    // Optimistic-lock: tell the server which price doc was active when the
    // user loaded the row. Server returns 409 if someone else has published
    // in the meantime — at which point we refresh and let the user retry.
    const plu = row.product.nec_plu ? String(row.product.nec_plu) : null;
    const expected = plu ? posStatus?.plus[plu]?.active_price_id ?? "" : "";
    try {
      const result = await masterDataApi.publishPrice(sku, {
        retail_price: priceNum,
        expected_active_price_id: expected,
      });
      updateRow(sku, (r) => ({
        ...r,
        product: result.product,
        publish: "published",
        publishedAt: Date.now(),
        publishError: undefined,
      }));
      const refreshed = await masterDataApi.posStatus().catch(() => null);
      if (refreshed) setPosStatus(refreshed);
    } catch (e) {
      const msg = (e as Error).message;
      const friendly = msg.includes("409")
        ? "Another publish landed first — refresh and retry."
        : msg;
      updateRow(sku, (r) => ({ ...r, publish: "error", publishError: friendly }));
      // On conflict, refresh POS status so the next attempt has the new id.
      if (msg.includes("409")) {
        const refreshed = await masterDataApi.posStatus().catch(() => null);
        if (refreshed) setPosStatus(refreshed);
      }
    }
  };

  const regenerate = async () => {
    if (!isOwner) return;
    setExporting(true);
    setLastExport(null);
    try {
      const res = await masterDataApi.exportNecJewel();
      setLastExport(res);
    } catch (e) {
      setLastExport({ ok: false, exit_code: -1, stdout: "", stderr: (e as Error).message });
    } finally {
      setExporting(false);
    }
  };

  const downloadExport = async () => {
    if (!lastExport?.download_url) return;
    const filename = lastExport.download_url.split("/").pop() || "nec_jewel_master_data.xlsx";
    const blob = await masterDataApi.downloadExport(filename);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  const onPickInvoice = () => fileInputRef.current?.click();

  const onInvoiceFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!isOwner) return;
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setIngestState({ kind: "uploading", filename: file.name });
    try {
      const preview = await masterDataApi.ingestInvoice(file);
      const selected = new Set(
        preview.items
          .filter((it) => it.proposed_sku && !it.already_exists && !it.skip_reason)
          .map((it) => String(it.supplier_item_code)),
      );
      setIngestState({ kind: "preview", preview, selected });
    } catch (err) {
      setIngestState({ kind: "error", message: (err as Error).message });
    }
  };

  const togglePreviewItem = (code: string) => {
    setIngestState((s) => {
      if (s.kind !== "preview") return s;
      const next = new Set(s.selected);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return { ...s, selected: next };
    });
  };

  const commitPreview = async () => {
    if (!isOwner) return;
    if (ingestState.kind !== "preview") return;
    const { preview, selected } = ingestState;
    const itemsToCommit = preview.items.filter(
      (it) => it.supplier_item_code && selected.has(String(it.supplier_item_code)),
    );
    if (itemsToCommit.length === 0) return;
    setIngestState({ kind: "committing" });
    try {
      const result = await masterDataApi.commitInvoice({
        upload_id: preview.upload_id,
        items: itemsToCommit,
        order_number: preview.document_number ?? null,
      });
      setIngestState({ kind: "idle" });
      await loadAll();
      alert(`Added ${result.added} new SKUs. Skipped ${result.skipped}.`);
    } catch (err) {
      setIngestState({ kind: "error", message: (err as Error).message });
    }
  };

  const cancelPreview = () => setIngestState({ kind: "idle" });

  const requestAiPrices = async () => {
    if (!isOwner) return;
    setAiState({ kind: "loading" });
    try {
      const targetSkus = filteredRows
        .filter((r) => !r.product.retail_price)
        .map((r) => r.product.sku_code);
      const response = await masterDataApi.recommendPrices({
        target_skus: targetSkus.length > 0 ? targetSkus : undefined,
      });
      const accepted = new Set(
        response.recommendations
          .filter((r) => r.confidence === "high" || r.confidence === "medium")
          .map((r) => r.sku_code),
      );
      const overrides: Record<string, string> = {};
      for (const r of response.recommendations) {
        overrides[r.sku_code] = r.recommended_retail_sgd.toFixed(2);
      }
      setAiState({ kind: "preview", response, accepted, overrides });
    } catch (err) {
      setAiState({ kind: "error", message: (err as Error).message });
    }
  };

  const toggleAiAcceptance = (sku: string) => {
    setAiState((s) => {
      if (s.kind !== "preview") return s;
      const next = new Set(s.accepted);
      if (next.has(sku)) next.delete(sku);
      else next.add(sku);
      return { ...s, accepted: next };
    });
  };

  const updateAiOverride = (sku: string, value: string) => {
    setAiState((s) => {
      if (s.kind !== "preview") return s;
      return { ...s, overrides: { ...s.overrides, [sku]: value } };
    });
  };

  const applyAiPrices = async () => {
    if (!isOwner) return;
    if (aiState.kind !== "preview") return;
    const { response, accepted, overrides } = aiState;
    const toApply = response.recommendations
      .filter((r) => accepted.has(r.sku_code))
      .map((r) => {
        const raw = overrides[r.sku_code] ?? String(r.recommended_retail_sgd);
        const num = Number.parseFloat(raw);
        return { sku: r.sku_code, price: num };
      })
      .filter((x) => Number.isFinite(x.price) && x.price > 0);
    if (toApply.length === 0) {
      setAiState({ kind: "idle" });
      return;
    }
    setAiState({ kind: "applying", total: toApply.length, done: 0 });
    let done = 0;
    let failed = 0;
    for (const { sku, price } of toApply) {
      try {
        await masterDataApi.patchProduct(sku, { retail_price: price });
      } catch {
        failed += 1;
      }
      done += 1;
      setAiState({ kind: "applying", total: toApply.length, done });
    }
    setAiState({ kind: "idle" });
    await loadAll();
    if (failed > 0) {
      alert(`Applied ${done - failed} prices. ${failed} failed (check the API logs).`);
    } else {
      alert(`Applied ${done} retail prices.`);
    }
  };

  const cancelAi = () => setAiState({ kind: "idle" });

  const submitCreate = async (req: CreateProductRequest) => {
    if (!isOwner) return;
    setCreateState({ kind: "submitting" });
    try {
      const result = await masterDataApi.createProduct(req);
      setCreateState({ kind: "idle" });
      await loadAll();
      const newSku = result.product.sku_code;
      const published = result.publish_result?.ok;
      alert(
        published
          ? `Added ${newSku} and published S$${result.publish_result?.retail_price.toFixed(2)} to POS.`
          : `Added ${newSku}. Set a price and click Publish to POS to make it sellable.`,
      );
    } catch (err) {
      setCreateState({ kind: "error", message: (err as Error).message });
    }
  };

  const toggleSelected = (sku: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(sku)) next.delete(sku);
      else next.add(sku);
      return next;
    });
  };

  const allVisibleSelected =
    filteredRows.length > 0 && filteredRows.every((r) => selected.has(r.product.sku_code));

  const toggleAllVisible = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) {
        for (const r of filteredRows) next.delete(r.product.sku_code);
      } else {
        for (const r of filteredRows) next.add(r.product.sku_code);
      }
      return next;
    });
  };

  const clearSelection = () => setSelected(new Set());

  const exportLabelsForSelected = async (includeBox: boolean) => {
    if (!isOwner) return;
    const skus = Array.from(selected);
    if (skus.length === 0) return;
    setLabelsExporting(true);
    setLastLabelsExport(null);
    try {
      const suffix = includeBox ? "item_box" : "item";
      const res = await masterDataApi.exportLabels({
        skus,
        include_box: includeBox,
        output_name: `ptouch_${suffix}_${skus.length}.xlsx`,
      });
      setLastLabelsExport(res);
      if (res.ok && res.download_url) {
        const filename = res.download_url.split("/").pop() || "ptouch_labels.xlsx";
        const blob = await masterDataApi.downloadExport(filename);
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        link.click();
        URL.revokeObjectURL(url);
      }
    } catch (e) {
      setLastLabelsExport({
        ok: false,
        exit_code: -1,
        stdout: "",
        stderr: (e as Error).message,
      });
    } finally {
      setLabelsExporting(false);
    }
  };

  const printPosLabels = async () => {
    if (!isOwner) return;
    const toPrint = filteredRows.filter((r) => r.saleReady);
    if (toPrint.length === 0) {
      alert("No sale-ready items found in the current view to print.");
      return;
    }
    const params = new URLSearchParams();
    toPrint.forEach((r) => {
      params.append("skus", r.product.sku_code);
      params.append("prices", r.draftPrice ? `S$${r.draftPrice}` : "");
      params.append("names", r.product.description || "");
    });
    
    try {
      const user = auth.currentUser;
      if (!user) return;
      const token = await user.getIdToken();
      const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api";
      const res = await fetch(`${BASE_URL}/pos-labelling/print?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error("Failed to load labels");
      const html = await res.text();
      
      const printWin = window.open("", "_blank");
      if (printWin) {
        printWin.document.open();
        printWin.document.write(html);
        printWin.document.close();
      }
    } catch (err) {
      alert("Error generating labels: " + (err as Error).message);
    }
  };

  return (
    <div>
      <div className="mx-auto max-w-[1400px]">
        <div className="mb-4 flex items-baseline justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Master Data — Retail Pricing</h1>
            <p className="text-sm text-gray-500">
              {isOwner
                ? "Enter retail prices for SKUs heading to NEC POS. Edits sync through the authenticated backend and are available to all UIs."
                : "Review POS-ready catalogue, price gaps, and SKU readiness. Owner access is required to change prices, ingest invoices, or export files."}
            </p>
          </div>
          {isOwner && (
            <div className="flex items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff"
                onChange={onInvoiceFile}
                className="hidden"
              />
              <button
                onClick={() => setCreateState({ kind: "open" })}
                className="rounded-md border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-800 shadow-sm hover:bg-emerald-100"
                title="Hand-enter a one-off product without a supplier invoice"
              >
                + Add SKU manually
              </button>
              <button
                onClick={onPickInvoice}
                disabled={ingestState.kind === "uploading" || ingestState.kind === "committing"}
                className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-800 shadow-sm hover:bg-gray-50 disabled:bg-gray-200"
                title="Upload a supplier PDF/image — DeepSeek OCR extracts line items"
              >
                {ingestState.kind === "uploading"
                  ? `OCR'ing ${ingestState.filename}…`
                  : "Process invoice…"}
              </button>
              <button
                onClick={requestAiPrices}
                disabled={aiState.kind === "loading" || aiState.kind === "applying"}
                className="rounded-md border border-purple-300 bg-purple-50 px-4 py-2 text-sm font-semibold text-purple-800 shadow-sm hover:bg-purple-100 disabled:bg-gray-200"
                title="Ask DeepSeek to suggest retail prices for unpriced SKUs (uses cost + comparables + cold-start heuristics)"
              >
                {aiState.kind === "loading" ? "Thinking…" : "AI suggest prices"}
              </button>
              <button
                onClick={regenerate}
                disabled={exporting}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:bg-gray-400"
              >
                {exporting ? "Generating…" : "Regenerate NEC Excel"}
              </button>
              <button
                onClick={printPosLabels}
                className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-800 shadow-sm hover:bg-gray-50"
                title="Print barcode labels for sale-ready SKUs currently visible in the grid"
              >
                Print POS Labels
              </button>
            </div>
          )}
        </div>

        {globalError && (
          <div className="mb-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
            <div className="font-semibold">{globalError}</div>
          </div>
        )}

        {stats && (
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Total products" value={stats.total} />
            <Stat label="Sale ready" value={stats.sale_ready} accent={stats.sale_ready > 0 ? "good" : undefined} />
            <Stat label="Sale-ready missing price" value={stats.sale_ready_missing_price} accent={stats.sale_ready_missing_price > 0 ? "warn" : "good"} />
            <Stat label="New SKUs awaiting price" value={stats.needs_price_flag} accent={stats.needs_price_flag > 0 ? "warn" : "good"} />
          </div>
        )}

        <div className="mb-3 flex flex-wrap items-center gap-3 rounded-md bg-white p-3 shadow-sm">
          <input
            type="text"
            placeholder="Search SKU, internal code, description…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
          <select
            value={supplierFilter}
            onChange={(e) => setSupplierFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          >
            <option value="all">All suppliers</option>
            {supplierOptions.map((s) => (
              <option key={s} value={s}>
                {SUPPLIER_LABELS[s] || s}
              </option>
            ))}
          </select>
          <select
            value={sourcingFilter}
            onChange={(e) => setSourcingFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
            title="Filter by sourcing strategy (supplier-purchased vs in-house manufactured)"
          >
            <option value="all">All sourcing</option>
            <option value="supplier_premade">Supplier (pre-made)</option>
            <option value="manufactured">Manufactured (in-house)</option>
            {sourcingOptions
              .filter((s) => s !== "supplier_premade" && !s.startsWith("manufactured") && s !== "(unset)")
              .map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
          </select>
          <label className="flex items-center gap-1.5 text-sm text-gray-700" title="Show only SKUs from real POs / invoices (skip catalog-only rows)">
            <input
              type="checkbox"
              checked={purchasedOnly}
              onChange={(e) => setPurchasedOnly(e.target.checked)}
            />
            Purchased only
          </label>
          <label className="flex items-center gap-1.5 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={needsPriceOnly}
              onChange={(e) => setNeedsPriceOnly(e.target.checked)}
            />
            Needs price only
          </label>
          <button
            onClick={() => void loadAll()}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            Refresh
          </button>
        </div>

        {lastExport && (
          <div className={`mb-4 rounded-md border p-3 text-sm ${lastExport.ok ? "border-green-300 bg-green-50 text-green-900" : "border-red-300 bg-red-50 text-red-900"}`}>
            {lastExport.ok ? (
              <>
                <div className="font-semibold">Excel regenerated.</div>
                {lastExport.download_url && (
                  <button onClick={() => void downloadExport()} className="underline">
                    Download nec_jewel_master_data.xlsx
                  </button>
                )}
                <details className="mt-2 text-xs">
                  <summary className="cursor-pointer">Export log</summary>
                  <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-white p-2 text-[11px]">{lastExport.stdout}</pre>
                </details>
              </>
            ) : (
              <>
                <div className="font-semibold">Export failed (exit {lastExport.exit_code})</div>
                <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-[11px]">{lastExport.stderr || lastExport.stdout}</pre>
              </>
            )}
          </div>
        )}

        <div className="overflow-auto rounded-md border border-gray-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-gray-100 text-left text-xs uppercase tracking-wide text-gray-600">
              <tr>
                <th className="px-2 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select all visible"
                    checked={allVisibleSelected}
                    onChange={toggleAllVisible}
                    disabled={!isOwner || filteredRows.length === 0}
                  />
                </th>
                <th className="sticky left-0 z-20 bg-gray-100 px-3 py-2">SKU</th>
                <th className="px-3 py-2">Barcode (PLU)</th>
                <th className="px-3 py-2">Live POS</th>
                <th className="px-3 py-2">Sourcing</th>
                <th className="px-3 py-2">Internal</th>
                <th className="px-3 py-2">Description</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Material</th>
                <th className="px-3 py-2">Size</th>
                <th className="px-3 py-2 text-right">Cost SGD</th>
                <th className="px-3 py-2 text-right">Retail SGD</th>
                <th className="px-3 py-2 text-right">Margin</th>
                <th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2">Sale ready</th>
                <th className="px-3 py-2">Notes</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading && (
                <tr>
                  <td colSpan={17} className="px-3 py-8 text-center text-gray-400">
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && filteredRows.length === 0 && !globalError && (
                <tr>
                  <td colSpan={17} className="px-3 py-8 text-center text-gray-400">
                    Nothing to show with these filters.
                  </td>
                </tr>
              )}
              {filteredRows.map((r) => {
                const p = r.product;
                const priceNum = Number.parseFloat(r.draftPrice);
                const margin = marginPct(p.cost_price, Number.isFinite(priceNum) ? priceNum : null);
                const posState = posLookup(p.nec_plu);
                const isSelected = selected.has(p.sku_code);
                return (
                  <tr key={p.sku_code} className={isSelected ? "bg-blue-50/40" : "hover:bg-blue-50/30"}>
                    <td className="px-2 py-2">
                      <input
                        type="checkbox"
                        aria-label={`Select ${p.sku_code}`}
                        checked={isSelected}
                        onChange={() => toggleSelected(p.sku_code)}
                        disabled={!isOwner}
                      />
                    </td>
                    <td className={`sticky left-0 z-10 px-3 py-2 font-mono text-xs text-gray-700 ${isSelected ? "bg-blue-50" : "bg-white hover:bg-blue-50/30"}`}>{p.sku_code}</td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-700">{p.nec_plu || "—"}</td>
                    <td className="px-3 py-2 text-xs">
                      {posState === "live" && <span className="rounded bg-green-100 px-1.5 py-0.5 text-green-800">Live</span>}
                      {posState === "no-price" && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-800" title="In Firestore plus collection but no current price doc">No price</span>}
                      {posState === "missing" && <span className="text-gray-400">—</span>}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600">
                      {p.sourcing_strategy === "supplier_premade"
                        ? "Supplier"
                        : p.sourcing_strategy?.startsWith("manufactured")
                          ? "Manufactured"
                          : (p.sourcing_strategy || "—")}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-500">{p.internal_code || "—"}</td>
                    <td className="px-3 py-2 max-w-md truncate text-gray-700" title={p.description ?? ""}>
                      {p.description}
                    </td>
                    <td className="px-3 py-2 text-gray-600">{p.product_type}</td>
                    <td className="px-3 py-2 text-gray-600">{p.material}</td>
                    <td className="px-3 py-2 text-gray-500">{p.size}</td>
                    <td className="px-3 py-2 text-right text-gray-700">S${fmtMoney(p.cost_price)}</td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={r.draftPrice}
                        placeholder={suggestedRetail(p.cost_price)}
                        onChange={(e) => updateRow(p.sku_code, (rs) => ({ ...rs, draftPrice: e.target.value, save: "idle" }))}
                        onBlur={() => isOwner && void saveRow(p.sku_code)}
                        onKeyDown={(e) => onPriceKey(p.sku_code, e)}
                        disabled={!isOwner}
                        className="w-24 rounded border border-gray-300 px-2 py-1 text-right font-mono text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-500"
                      />
                    </td>
                    <td className="px-3 py-2 text-right text-gray-600">{margin}</td>
                    <td className="px-3 py-2 text-right text-gray-600">{p.qty_on_hand ?? "—"}</td>
                    <td className="px-3 py-2">
                      <label className="inline-flex items-center gap-1 text-xs">
                        <input
                          type="checkbox"
                          checked={r.saleReady}
                          disabled={!isOwner}
                          onChange={(e) =>
                            updateRow(p.sku_code, (rs) => ({ ...rs, saleReady: e.target.checked, save: "idle" }))
                          }
                        />
                        <span>{r.saleReady ? "Yes" : "No"}</span>
                      </label>
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="text"
                        value={r.draftNotes}
                        onChange={(e) => updateRow(p.sku_code, (rs) => ({ ...rs, draftNotes: e.target.value, save: "idle" }))}
                        onBlur={() => isOwner && void saveRow(p.sku_code)}
                        disabled={!isOwner}
                        className="w-44 rounded border border-gray-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-500"
                      />
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <div className="flex flex-col gap-1">
                        <div>
                          {r.save === "saving" && <span className="text-gray-500">Saving…</span>}
                          {r.save === "saved" && <span className="text-green-600">Saved ✓</span>}
                          {r.save === "error" && <span className="text-red-600" title={r.error}>Error</span>}
                          {r.save === "idle" && p.retail_price && <span className="text-gray-400">—</span>}
                        </div>
                        {canPublishPrice && p.nec_plu && (
                          <button
                            onClick={() => void publishRow(p.sku_code)}
                            disabled={
                              r.publish === "publishing" ||
                              !Number.isFinite(priceNum) ||
                              priceNum <= 0
                            }
                            className={
                              posState === "live"
                                ? "rounded border border-gray-300 px-2 py-0.5 text-[11px] font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400"
                                : "rounded bg-amber-500 px-2 py-0.5 text-[11px] font-semibold text-white hover:bg-amber-600 disabled:cursor-not-allowed disabled:bg-gray-300"
                            }
                            title={
                              posState === "live"
                                ? "Replace the current Firestore price with the value in the input"
                                : "Create a Firestore prices/{id} doc so the POS can ring up this barcode"
                            }
                          >
                            {r.publish === "publishing"
                              ? "Publishing…"
                              : posState === "live"
                                ? "Update POS"
                                : "Publish to POS"}
                          </button>
                        )}
                        {!canPublishPrice && isOwner && p.nec_plu && (
                          <span
                            className="text-[11px] text-gray-400"
                            title="Restricted to the named owner accounts (Craig, Irina)."
                          >
                            Owner-restricted
                          </span>
                        )}
                        {r.publish === "published" && (
                          <span className="text-green-600">Live ✓</span>
                        )}
                        {r.publish === "error" && (
                          <span className="text-red-600" title={r.publishError}>
                            {r.publishError ? r.publishError.slice(0, 40) : "Publish failed"}
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-xs text-gray-500">
          Tip: Tab between price cells to enter a column at a time. Edits autosave on blur or Enter. The placeholder
          retail price is a 60% target margin (cost ÷ 0.4 rounded to S$5) — overwrite as needed.
        </p>
      </div>

      {isOwner && selected.size > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-gray-200 bg-white shadow-[0_-4px_12px_rgba(0,0,0,0.08)]">
          <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-3 px-4 py-3">
            <div className="text-sm text-gray-700">
              <span className="font-semibold">{selected.size}</span> selected
              {lastLabelsExport && !lastLabelsExport.ok && (
                <span className="ml-3 text-red-700">
                  Export failed: {lastLabelsExport.stderr || `exit ${lastLabelsExport.exit_code}`}
                </span>
              )}
              {lastLabelsExport && lastLabelsExport.ok && (
                <span className="ml-3 text-green-700">
                  Generated {lastLabelsExport.plu_count ?? 0} labels.
                  {lastLabelsExport.skus_no_plu && lastLabelsExport.skus_no_plu.length > 0 && (
                    <span className="ml-2 text-amber-700">
                      ({lastLabelsExport.skus_no_plu.length} skipped — no PLU)
                    </span>
                  )}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={clearSelection}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
              >
                Clear
              </button>
              <button
                onClick={() => void exportLabelsForSelected(false)}
                disabled={labelsExporting}
                className="rounded-md border border-blue-300 bg-white px-4 py-1.5 text-sm font-semibold text-blue-800 shadow-sm hover:bg-blue-50 disabled:bg-gray-200"
                title="Generate ItemLabels only (description + price + barcode for each unit)"
              >
                {labelsExporting ? "Generating…" : "Item labels only"}
              </button>
              <button
                onClick={() => void exportLabelsForSelected(true)}
                disabled={labelsExporting}
                className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:bg-gray-400"
                title="Generate ItemLabels + BoxLabels (also includes box/drawer tags with qty and location)"
              >
                {labelsExporting ? "Generating…" : "Item + Box labels"}
              </button>
            </div>
          </div>
        </div>
      )}

      {isOwner && ingestState.kind === "error" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4">
          <div className="max-w-md rounded-md bg-white p-4 shadow-lg">
            <div className="font-semibold text-red-700">Invoice ingest failed</div>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs text-red-800">
              {ingestState.message}
            </pre>
            <div className="mt-3 text-right">
              <button
                onClick={() => setIngestState({ kind: "idle" })}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {isOwner && ingestState.kind === "preview" && (
        <IngestPreviewModal
          preview={ingestState.preview}
          selected={ingestState.selected}
          onToggle={togglePreviewItem}
          onCancel={cancelPreview}
          onCommit={commitPreview}
        />
      )}
      {isOwner && ingestState.kind === "committing" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40">
          <div className="rounded-md bg-white px-6 py-4 shadow-lg text-sm text-gray-700">
            Adding products to master JSON…
          </div>
        </div>
      )}

      {isOwner && aiState.kind === "loading" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40">
          <div className="rounded-md bg-white px-6 py-4 shadow-lg text-sm text-gray-700">
            DeepSeek is reasoning over your catalog… (this can take 30–60s)
          </div>
        </div>
      )}

      {isOwner && aiState.kind === "applying" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40">
          <div className="rounded-md bg-white px-6 py-4 shadow-lg text-sm text-gray-700">
            Applying retail prices… {aiState.done} / {aiState.total}
          </div>
        </div>
      )}

      {isOwner && aiState.kind === "error" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4">
          <div className="max-w-md rounded-md bg-white p-4 shadow-lg">
            <div className="font-semibold text-red-700">AI price recommendation failed</div>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs text-red-800">
              {aiState.message}
            </pre>
            <div className="mt-3 text-right">
              <button
                onClick={cancelAi}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {isOwner && aiState.kind === "preview" && (
        <PriceRecommendationsModal
          response={aiState.response}
          accepted={aiState.accepted}
          overrides={aiState.overrides}
          rowsBySku={Object.fromEntries(rows.map((r) => [r.product.sku_code, r.product]))}
          onToggle={toggleAiAcceptance}
          onOverride={updateAiOverride}
          onCancel={cancelAi}
          onApply={applyAiPrices}
        />
      )}

      {isOwner && (createState.kind === "open" || createState.kind === "submitting" || createState.kind === "error") && (
        <CreateProductModal
          submitting={createState.kind === "submitting"}
          errorMessage={createState.kind === "error" ? createState.message : null}
          onCancel={() => setCreateState({ kind: "idle" })}
          onSubmit={submitCreate}
        />
      )}
    </div>
  );
}

const PRODUCT_TYPE_OPTIONS = [
  "Bookend",
  "Napkin Holder",
  "Decorative Object",
  "Sculpture",
  "Figurine",
  "Vase",
  "Bowl",
  "Tray",
  "Box",
  "Bracelet",
  "Necklace",
  "Ring",
  "Pendant",
  "Earring",
  "Charm",
];

const MATERIAL_OPTIONS = [
  "Crystal",
  "Malachite",
  "Fluorite",
  "Marble",
  "Gypsum",
  "Mineral Stone",
  "Mixed Materials",
];

function CreateProductModal({
  submitting,
  errorMessage,
  onCancel,
  onSubmit,
}: {
  submitting: boolean;
  errorMessage: string | null;
  onCancel: () => void;
  onSubmit: (req: CreateProductRequest) => void;
}) {
  const [form, setForm] = useState({
    description: "",
    product_type: PRODUCT_TYPE_OPTIONS[0],
    material: MATERIAL_OPTIONS[0],
    size: "",
    supplier_id: "CN-001",
    supplier_name: "Hengwei Craft",
    internal_code: "",
    cost_price: "",
    qty_on_hand: "",
    notes: "",
    retail_price: "",
    publish_now: false,
  });
  const [localError, setLocalError] = useState<string | null>(null);

  const update = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const submit = () => {
    setLocalError(null);
    if (!form.description.trim()) {
      setLocalError("Description is required.");
      return;
    }
    const cost = form.cost_price.trim() ? Number.parseFloat(form.cost_price) : null;
    if (cost !== null && (!Number.isFinite(cost) || cost < 0)) {
      setLocalError("Cost price must be a non-negative number.");
      return;
    }
    const qty = form.qty_on_hand.trim() ? Number.parseInt(form.qty_on_hand, 10) : null;
    if (qty !== null && (!Number.isFinite(qty) || qty < 0)) {
      setLocalError("Quantity must be a non-negative integer.");
      return;
    }
    const retail = form.publish_now && form.retail_price.trim()
      ? Number.parseFloat(form.retail_price)
      : null;
    if (form.publish_now) {
      if (retail === null || !Number.isFinite(retail) || retail <= 0) {
        setLocalError("Enter a positive retail price to publish to POS.");
        return;
      }
    }

    const req: CreateProductRequest = {
      description: form.description.trim(),
      product_type: form.product_type,
      material: form.material,
      size: form.size.trim() || null,
      supplier_id: form.supplier_id.trim() || "CN-001",
      supplier_name: form.supplier_name.trim() || null,
      internal_code: form.internal_code.trim() || null,
      cost_price: cost,
      cost_currency: cost !== null ? "SGD" : null,
      qty_on_hand: qty,
      notes: form.notes.trim() || null,
      retail_price: retail,
    };
    onSubmit(req);
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-md bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
          <div>
            <div className="text-base font-semibold text-gray-900">Add SKU manually</div>
            <div className="text-xs text-gray-500">
              Hand-entered products. SKU code and barcode (PLU) are auto-allocated. Optionally set a
              retail price to publish to POS in one step.
            </div>
          </div>
          <button onClick={onCancel} className="text-sm text-gray-500 hover:underline" disabled={submitting}>
            Cancel
          </button>
        </header>
        <div className="flex-1 overflow-auto px-5 py-4 text-sm">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Description *" hint="Short label shown on labels and the POS screen.">
              <input
                type="text"
                value={form.description}
                onChange={(e) => update("description", e.target.value)}
                maxLength={120}
                disabled={submitting}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              />
            </Field>
            <Field label="Product type *">
              <select
                value={form.product_type}
                onChange={(e) => update("product_type", e.target.value)}
                disabled={submitting}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              >
                {PRODUCT_TYPE_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </Field>
            <Field label="Material *">
              <select
                value={form.material}
                onChange={(e) => update("material", e.target.value)}
                disabled={submitting}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              >
                {MATERIAL_OPTIONS.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </Field>
            <Field label="Size" hint="e.g. 10x10x30 cm">
              <input
                type="text"
                value={form.size}
                onChange={(e) => update("size", e.target.value)}
                disabled={submitting}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              />
            </Field>
            <Field label="Supplier ID">
              <input
                type="text"
                value={form.supplier_id}
                onChange={(e) => update("supplier_id", e.target.value)}
                disabled={submitting}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm font-mono focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              />
            </Field>
            <Field label="Supplier name">
              <input
                type="text"
                value={form.supplier_name}
                onChange={(e) => update("supplier_name", e.target.value)}
                disabled={submitting}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              />
            </Field>
            <Field label="Supplier item code" hint="Optional. Their SKU on the invoice/box.">
              <input
                type="text"
                value={form.internal_code}
                onChange={(e) => update("internal_code", e.target.value)}
                disabled={submitting}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm font-mono focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              />
            </Field>
            <Field label="Qty on hand">
              <input
                type="number"
                min={0}
                step={1}
                value={form.qty_on_hand}
                onChange={(e) => update("qty_on_hand", e.target.value)}
                disabled={submitting}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              />
            </Field>
            <Field label="Cost price (SGD)">
              <input
                type="number"
                min={0}
                step="0.01"
                value={form.cost_price}
                onChange={(e) => update("cost_price", e.target.value)}
                disabled={submitting}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              />
            </Field>
            <Field label="Notes">
              <input
                type="text"
                value={form.notes}
                onChange={(e) => update("notes", e.target.value)}
                disabled={submitting}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              />
            </Field>
          </div>

          <div className="mt-5 rounded-md border border-amber-200 bg-amber-50 p-3">
            <label className="flex items-center gap-2 text-sm font-semibold text-amber-900">
              <input
                type="checkbox"
                checked={form.publish_now}
                onChange={(e) => update("publish_now", e.target.checked)}
                disabled={submitting}
              />
              Publish a retail price to POS in the same step
            </label>
            {form.publish_now && (
              <div className="mt-2 flex items-center gap-2 text-sm">
                <span className="text-gray-700">Retail (S$, GST-inclusive):</span>
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  value={form.retail_price}
                  onChange={(e) => update("retail_price", e.target.value)}
                  disabled={submitting}
                  className="w-28 rounded border border-amber-300 px-2 py-1 text-sm focus:border-amber-500 focus:outline-none disabled:bg-gray-100"
                />
                <span className="text-xs text-gray-500">
                  Creates a Firestore prices/&#123;id&#125; doc valid from today.
                </span>
              </div>
            )}
          </div>

          {(localError || errorMessage) && (
            <div className="mt-4 rounded-md border border-red-300 bg-red-50 p-2 text-sm text-red-800">
              {localError || errorMessage}
            </div>
          )}
        </div>
        <footer className="flex items-center justify-between border-t border-gray-200 px-5 py-3">
          <div className="text-xs text-gray-500">
            SKU code &amp; barcode (PLU) are auto-allocated to keep them aligned.
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onCancel}
              disabled={submitting}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              onClick={submit}
              disabled={submitting || !form.description.trim()}
              className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:bg-gray-400"
            >
              {submitting ? "Adding…" : form.publish_now ? "Add & publish to POS" : "Add SKU"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm text-gray-700">
      <span className="font-semibold">{label}</span>
      {children}
      {hint && <span className="text-xs text-gray-500">{hint}</span>}
    </label>
  );
}

function IngestPreviewModal({
  preview,
  selected,
  onToggle,
  onCancel,
  onCommit,
}: {
  preview: IngestPreview;
  selected: Set<string>;
  onToggle: (code: string) => void;
  onCancel: () => void;
  onCommit: () => void;
}) {
  const selectableCount = preview.items.filter(
    (it) => it.proposed_sku && !it.already_exists && !it.skip_reason && it.supplier_item_code,
  ).length;
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-[90vh] w-full max-w-6xl flex-col rounded-md bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
          <div>
            <div className="text-base font-semibold text-gray-900">
              OCR preview — {preview.document_type || "document"}
              {preview.document_number ? ` · ${preview.document_number}` : ""}
            </div>
            <div className="text-xs text-gray-500">
              {preview.supplier_name || "supplier unknown"}
              {preview.document_date ? ` · ${preview.document_date}` : ""}
              {preview.currency && preview.document_total
                ? ` · ${preview.currency} ${preview.document_total.toLocaleString()}`
                : ""}
              {" · "}
              <span>
                {preview.summary.new_skus} new · {preview.summary.already_exists} already in master ·{" "}
                {preview.summary.skipped} skipped
              </span>
            </div>
          </div>
          <button onClick={onCancel} className="text-sm text-gray-500 hover:underline">
            Cancel
          </button>
        </header>
        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-100 text-left text-xs uppercase tracking-wide text-gray-600">
              <tr>
                <th className="px-3 py-2"></th>
                <th className="px-3 py-2">Code</th>
                <th className="px-3 py-2">Description</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Material</th>
                <th className="px-3 py-2">Size</th>
                <th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2 text-right">¥/unit</th>
                <th className="px-3 py-2 text-right">S$/unit</th>
                <th className="px-3 py-2">Proposed SKU</th>
                <th className="px-3 py-2">Barcode (PLU)</th>
                <th className="px-3 py-2">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {preview.items.map((it, idx) => {
                const code = it.supplier_item_code ? String(it.supplier_item_code) : null;
                const isNew = !!(it.proposed_sku && !it.already_exists && !it.skip_reason && code);
                const isChecked = code ? selected.has(code) : false;
                return (
                  <tr
                    key={`${idx}-${code ?? "noco"}`}
                    className={
                      it.already_exists
                        ? "bg-gray-50 text-gray-500"
                        : it.skip_reason
                        ? "bg-amber-50/50 text-amber-900"
                        : ""
                    }
                  >
                    <td className="px-3 py-2">
                      {isNew && code ? (
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => onToggle(code)}
                        />
                      ) : null}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{code || "—"}</td>
                    <td className="px-3 py-2 max-w-sm truncate" title={it.product_name_en ?? ""}>
                      {it.product_name_en}
                    </td>
                    <td className="px-3 py-2 text-xs">{it.product_type || "—"}</td>
                    <td className="px-3 py-2 text-xs">{it.material || "—"}</td>
                    <td className="px-3 py-2 text-xs">{it.size || "—"}</td>
                    <td className="px-3 py-2 text-right">{it.quantity ?? "—"}</td>
                    <td className="px-3 py-2 text-right">{it.unit_price_cny ?? "—"}</td>
                    <td className="px-3 py-2 text-right">
                      {it.proposed_cost_sgd != null ? it.proposed_cost_sgd.toFixed(2) : "—"}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{it.proposed_sku || "—"}</td>
                    <td className="px-3 py-2 font-mono text-xs">{it.proposed_plu || "—"}</td>
                    <td className="px-3 py-2 text-xs">
                      {it.already_exists ? (
                        <span className="text-gray-500">exists ({it.existing_sku})</span>
                      ) : it.skip_reason ? (
                        <span className="text-amber-700">{it.skip_reason}</span>
                      ) : (
                        <span className="text-green-700">new</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <footer className="flex items-center justify-between border-t border-gray-200 px-5 py-3">
          <div className="text-xs text-gray-500">
            {selected.size} of {selectableCount} new SKUs selected. Existing SKUs and skipped lines won't be touched.
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onCancel}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={onCommit}
              disabled={selected.size === 0}
              className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-gray-400"
            >
              Add {selected.size} SKU{selected.size === 1 ? "" : "s"} to master
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function PriceRecommendationsModal({
  response,
  accepted,
  overrides,
  rowsBySku,
  onToggle,
  onOverride,
  onCancel,
  onApply,
}: {
  response: PriceRecommendationsResponse;
  accepted: Set<string>;
  overrides: Record<string, string>;
  rowsBySku: Record<string, ProductRow>;
  onToggle: (sku: string) => void;
  onOverride: (sku: string, value: string) => void;
  onCancel: () => void;
  onApply: () => void;
}) {
  const sorted = useMemo(() => {
    const order: Record<string, number> = { high: 0, medium: 1, low: 2 };
    return [...response.recommendations].sort(
      (a, b) => (order[a.confidence] ?? 9) - (order[b.confidence] ?? 9),
    );
  }, [response.recommendations]);

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-[90vh] w-full max-w-7xl flex-col rounded-md bg-white shadow-xl">
        <header className="border-b border-gray-200 px-5 py-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-base font-semibold text-gray-900">
            AI price recommendations
              </div>
              <div className="text-xs text-gray-500">
                {response.recommendations.length} suggestion
                {response.recommendations.length === 1 ? "" : "s"} · trained on{" "}
                {response.n_priced_examples ?? 0} priced example
                {(response.n_priced_examples ?? 0) === 1 ? "" : "s"}
                {response.notes ? ` · ${response.notes}` : ""}
              </div>
            </div>
            <button onClick={onCancel} className="text-sm text-gray-500 hover:underline">
              Cancel
            </button>
          </div>
          {response.rules_inferred && response.rules_inferred.length > 0 && (
            <details className="mt-2 text-xs text-gray-600">
              <summary className="cursor-pointer text-gray-700">
                Rules the model inferred ({response.rules_inferred.length})
              </summary>
              <ul className="mt-1 list-disc space-y-0.5 pl-5">
                {response.rules_inferred.map((rule, i) => (
                  <li key={i}>{rule}</li>
                ))}
              </ul>
            </details>
          )}
        </header>
        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-100 text-left text-xs uppercase tracking-wide text-gray-600">
              <tr>
                <th className="px-3 py-2"></th>
                <th className="px-3 py-2">SKU</th>
                <th className="px-3 py-2">Description</th>
                <th className="px-3 py-2 text-right">Cost</th>
                <th className="px-3 py-2 text-right">Suggested S$</th>
                <th className="px-3 py-2 text-right">Margin</th>
                <th className="px-3 py-2">Confidence</th>
                <th className="px-3 py-2">Rationale</th>
                <th className="px-3 py-2">Comparables</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sorted.map((rec) => {
                const row = rowsBySku[rec.sku_code];
                const cost = row?.cost_price ?? null;
                const override = overrides[rec.sku_code] ?? rec.recommended_retail_sgd.toFixed(2);
                const overrideNum = Number.parseFloat(override);
                const margin = marginPct(cost, Number.isFinite(overrideNum) ? overrideNum : null);
                const isChecked = accepted.has(rec.sku_code);
                const confTone =
                  rec.confidence === "high"
                    ? "bg-green-100 text-green-800"
                    : rec.confidence === "medium"
                    ? "bg-yellow-100 text-yellow-800"
                    : "bg-gray-100 text-gray-700";
                return (
                  <tr key={rec.sku_code} className={isChecked ? "bg-purple-50/40" : ""}>
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => onToggle(rec.sku_code)}
                      />
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-700">{rec.sku_code}</td>
                    <td
                      className="px-3 py-2 max-w-xs truncate text-gray-700"
                      title={row?.description ?? ""}
                    >
                      {row?.description ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-700">
                      S${fmtMoney(cost)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={override}
                        onChange={(e) => onOverride(rec.sku_code, e.target.value)}
                        className="w-24 rounded border border-gray-300 px-2 py-1 text-right font-mono text-sm focus:border-blue-500 focus:outline-none"
                      />
                    </td>
                    <td className="px-3 py-2 text-right text-gray-600">{margin}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${confTone}`}>
                        {rec.confidence}
                      </span>
                    </td>
                    <td
                      className="px-3 py-2 max-w-md text-xs text-gray-600"
                      title={rec.rationale}
                    >
                      {rec.rationale}
                    </td>
                    <td className="px-3 py-2 font-mono text-[11px] text-gray-500">
                      {rec.comparable_skus && rec.comparable_skus.length > 0
                        ? rec.comparable_skus.slice(0, 3).join(", ")
                        : "—"}
                    </td>
                  </tr>
                );
              })}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-gray-500">
                    No recommendations returned. Try adding a few priced SKUs first so the model
                    has comparables.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex items-center justify-between border-t border-gray-200 px-5 py-3">
          <div className="text-xs text-gray-500">
            {accepted.size} of {sorted.length} selected. High & medium confidence are pre-checked.
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onCancel}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={onApply}
              disabled={accepted.size === 0}
              className="rounded-md bg-purple-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-purple-700 disabled:bg-gray-400"
            >
              Apply {accepted.size} retail price{accepted.size === 1 ? "" : "s"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: "good" | "warn" }) {
  const tone =
    accent === "good"
      ? "text-green-700"
      : accent === "warn"
      ? "text-amber-700"
      : "text-gray-900";
  return (
    <div className="rounded-md border border-gray-200 bg-white p-3 shadow-sm">
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`mt-0.5 text-2xl font-bold ${tone}`}>{value}</div>
    </div>
  );
}
