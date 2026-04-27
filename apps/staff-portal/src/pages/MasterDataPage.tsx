import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getMasterDataApiBase,
  setMasterDataApiBase,
  masterDataApi,
  type ExportResult,
  type IngestPreview,
  type ManualProductRequest,
  type PriceRecommendationsResponse,
  type ProductRow,
  type Stats,
  type VisualSearchResponse,
} from "../lib/master-data-api";

type SaveState = "idle" | "saving" | "saved" | "error";

interface RowState {
  product: ProductRow;
  draftPrice: string;
  draftNotes: string;
  saleReady: boolean;
  save: SaveState;
  error?: string;
  savedAt?: number;
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

export default function MasterDataPage() {
  const [apiBase, setApiBase] = useState<string>(() => getMasterDataApiBase());
  const [stats, setStats] = useState<Stats | null>(null);
  const [rows, setRows] = useState<RowState[]>([]);
  const [loading, setLoading] = useState(true);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [supplierFilter, setSupplierFilter] = useState<string>("all");
  const [needsPriceOnly, setNeedsPriceOnly] = useState(true);
  const [purchasedOnly, setPurchasedOnly] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [lastExport, setLastExport] = useState<ExportResult | null>(null);
  const [ingestState, setIngestState] = useState<
    | { kind: "idle" }
    | { kind: "uploading"; filename: string }
    | { kind: "preview"; preview: IngestPreview; selected: Set<string> }
    | { kind: "committing" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const [manualState, setManualState] = useState<
    | { kind: "idle" }
    | { kind: "open" }
    | { kind: "saving" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const [aiState, setAiState] = useState<
    | { kind: "idle" }
    | { kind: "loading" }
    | { kind: "preview"; response: PriceRecommendationsResponse; accepted: Set<string>; overrides: Record<string, string> }
    | { kind: "applying"; total: number; done: number }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const [visualState, setVisualState] = useState<
    | { kind: "idle" }
    | { kind: "uploading"; filename: string }
    | { kind: "results"; previewUrl: string; response: VisualSearchResponse }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const visualInputRef = useRef<HTMLInputElement | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setGlobalError(null);
    try {
      const [statsRes, productsRes] = await Promise.all([
        masterDataApi.stats(),
        masterDataApi.listProducts({
          launch_only: true,
          needs_price: needsPriceOnly,
          purchased_only: purchasedOnly,
        }),
      ]);
      setStats(statsRes);
      setRows(
        productsRes.products.map((p) => ({
          product: p,
          draftPrice: p.retail_price ? String(p.retail_price) : "",
          draftNotes: p.retail_price_note ?? "",
          saleReady: Boolean(p.sale_ready),
          save: "idle",
        })),
      );
    } catch (e) {
      setGlobalError(`Couldn't reach the master-data API at ${apiBase}. Is it running? (${(e as Error).message})`);
    } finally {
      setLoading(false);
    }
  }, [needsPriceOnly, purchasedOnly, apiBase]);

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

  const updateRow = (sku: string, fn: (r: RowState) => RowState) => {
    setRows((prev) => prev.map((r) => (r.product.sku_code === sku ? fn(r) : r)));
  };

  const saveRow = async (sku: string) => {
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
    if (e.key === "Enter") void saveRow(sku);
  };

  const handleApiBase = (next: string) => {
    setMasterDataApiBase(next);
    setApiBase(next);
  };

  const regenerate = async () => {
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

  const onPickInvoice = () => fileInputRef.current?.click();

  const onInvoiceFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
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

  const onPickVisualPhoto = () => visualInputRef.current?.click();

  const onVisualPhotoFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setVisualState({ kind: "uploading", filename: file.name });
    const previewUrl = URL.createObjectURL(file);
    try {
      const response = await masterDataApi.visualSearch(file, 8);
      setVisualState({ kind: "results", previewUrl, response });
    } catch (err) {
      URL.revokeObjectURL(previewUrl);
      setVisualState({ kind: "error", message: (err as Error).message });
    }
  };

  const closeVisual = () => {
    if (visualState.kind === "results") URL.revokeObjectURL(visualState.previewUrl);
    setVisualState({ kind: "idle" });
  };

  const submitManual = async (req: ManualProductRequest) => {
    setManualState({ kind: "saving" });
    try {
      const created = await masterDataApi.createManualProduct(req);
      setManualState({ kind: "idle" });
      await loadAll();
      alert(`Added ${created.sku_code} (PLU ${created.nec_plu}).`);
    } catch (err) {
      setManualState({ kind: "error", message: (err as Error).message });
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-yellow-300 bg-yellow-50 px-6 py-2 text-sm text-yellow-900">
        Local-only mode · master-data API at <code className="rounded bg-white px-1.5 py-0.5">{apiBase}</code> · auth bypassed for May 1 launch (move under auth gate in Track 2)
      </header>

      <div className="mx-auto max-w-[1400px] px-6 py-6">
        <div className="mb-4 flex items-baseline justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Master Data — Retail Pricing</h1>
            <p className="text-sm text-gray-500">Enter retail prices for SKUs heading to NEC POS. Edits save to <code className="rounded bg-gray-100 px-1">data/master_product_list.json</code>.</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff"
              onChange={onInvoiceFile}
              className="hidden"
            />
            <input
              ref={visualInputRef}
              type="file"
              accept="image/*"
              capture="environment"
              onChange={onVisualPhotoFile}
              className="hidden"
            />
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
              onClick={onPickVisualPhoto}
              disabled={visualState.kind === "uploading"}
              className="rounded-md border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-800 shadow-sm hover:bg-emerald-100 disabled:bg-gray-200"
              title="Snap or upload a photo of an item — Gemini matches it against the catalog"
            >
              {visualState.kind === "uploading"
                ? `Searching ${visualState.filename}…`
                : "Find by photo 📷"}
            </button>
            <button
              onClick={() => setManualState({ kind: "open" })}
              disabled={manualState.kind === "saving"}
              className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-800 shadow-sm hover:bg-gray-50 disabled:bg-gray-200"
              title="Add a one-off SKU that has no supplier order (e.g. Guardian artwork)"
            >
              {manualState.kind === "saving" ? "Saving…" : "Add manual SKU…"}
            </button>
            <button
              onClick={requestAiPrices}
              disabled={aiState.kind === "loading" || aiState.kind === "applying"}
              className="rounded-md border border-purple-300 bg-purple-50 px-4 py-2 text-sm font-semibold text-purple-800 shadow-sm hover:bg-purple-100 disabled:bg-gray-200"
              title="Ask DeepSeek to suggest retail prices for unpriced SKUs (uses cost + comparables + cold-start heuristics)"
            >
              {aiState.kind === "loading" ? "Thinking…" : "AI suggest prices ✨"}
            </button>
            <button
              onClick={regenerate}
              disabled={exporting}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:bg-gray-400"
            >
              {exporting ? "Generating…" : "Regenerate NEC Excel"}
            </button>
          </div>
        </div>

        {globalError && (
          <div className="mb-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
            <div className="font-semibold">{globalError}</div>
            <div className="mt-1 text-xs">
              Start it with <code className="rounded bg-white px-1">python tools/server/master_data_api.py</code>
            </div>
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
          <ApiBaseEditor current={apiBase} onChange={handleApiBase} />
        </div>

        {lastExport && (
          <div className={`mb-4 rounded-md border p-3 text-sm ${lastExport.ok ? "border-green-300 bg-green-50 text-green-900" : "border-red-300 bg-red-50 text-red-900"}`}>
            {lastExport.ok ? (
              <>
                <div className="font-semibold">Excel regenerated.</div>
                {lastExport.download_url && (
                  <a href={`${apiBase}${lastExport.download_url}`} className="underline" target="_blank" rel="noreferrer">
                    Download nec_jewel_master_data.xlsx
                  </a>
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
                <th className="sticky left-0 z-20 bg-gray-100 px-3 py-2">SKU</th>
                <th className="px-3 py-2">Barcode (PLU)</th>
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
                  <td colSpan={14} className="px-3 py-8 text-center text-gray-400">
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && filteredRows.length === 0 && !globalError && (
                <tr>
                  <td colSpan={14} className="px-3 py-8 text-center text-gray-400">
                    Nothing to show with these filters.
                  </td>
                </tr>
              )}
              {filteredRows.map((r) => {
                const p = r.product;
                const priceNum = Number.parseFloat(r.draftPrice);
                const margin = marginPct(p.cost_price, Number.isFinite(priceNum) ? priceNum : null);
                return (
                  <tr key={p.sku_code} className="hover:bg-blue-50/30">
                    <td className="sticky left-0 z-10 bg-white px-3 py-2 font-mono text-xs text-gray-700 hover:bg-blue-50/30">{p.sku_code}</td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-700">{p.nec_plu || "—"}</td>
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
                        onBlur={() => void saveRow(p.sku_code)}
                        onKeyDown={(e) => onPriceKey(p.sku_code, e)}
                        className="w-24 rounded border border-gray-300 px-2 py-1 text-right font-mono text-sm focus:border-blue-500 focus:outline-none"
                      />
                    </td>
                    <td className="px-3 py-2 text-right text-gray-600">{margin}</td>
                    <td className="px-3 py-2 text-right text-gray-600">{p.qty_on_hand ?? "—"}</td>
                    <td className="px-3 py-2">
                      <label className="inline-flex items-center gap-1 text-xs">
                        <input
                          type="checkbox"
                          checked={r.saleReady}
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
                        onBlur={() => void saveRow(p.sku_code)}
                        className="w-44 rounded border border-gray-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"
                      />
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.save === "saving" && <span className="text-gray-500">Saving…</span>}
                      {r.save === "saved" && <span className="text-green-600">Saved ✓</span>}
                      {r.save === "error" && <span className="text-red-600" title={r.error}>Error</span>}
                      {r.save === "idle" && p.retail_price && <span className="text-gray-400">—</span>}
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

      {ingestState.kind === "error" && (
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

      {ingestState.kind === "preview" && (
        <IngestPreviewModal
          preview={ingestState.preview}
          selected={ingestState.selected}
          onToggle={togglePreviewItem}
          onCancel={cancelPreview}
          onCommit={commitPreview}
        />
      )}
      {ingestState.kind === "committing" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40">
          <div className="rounded-md bg-white px-6 py-4 shadow-lg text-sm text-gray-700">
            Adding products to master JSON…
          </div>
        </div>
      )}

      {aiState.kind === "loading" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40">
          <div className="rounded-md bg-white px-6 py-4 shadow-lg text-sm text-gray-700">
            DeepSeek is reasoning over your catalog… (this can take 30–60s)
          </div>
        </div>
      )}

      {aiState.kind === "applying" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40">
          <div className="rounded-md bg-white px-6 py-4 shadow-lg text-sm text-gray-700">
            Applying retail prices… {aiState.done} / {aiState.total}
          </div>
        </div>
      )}

      {aiState.kind === "error" && (
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

      {aiState.kind === "preview" && (
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

      {(manualState.kind === "open" || manualState.kind === "saving") && (
        <ManualSkuModal
          saving={manualState.kind === "saving"}
          onCancel={() => setManualState({ kind: "idle" })}
          onSubmit={submitManual}
        />
      )}

      {visualState.kind === "uploading" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40">
          <div className="rounded-md bg-white px-6 py-4 shadow-lg text-sm text-gray-700">
            Gemini is matching your photo against the catalog… ({visualState.filename})
          </div>
        </div>
      )}

      {visualState.kind === "error" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4">
          <div className="max-w-md rounded-md bg-white p-4 shadow-lg">
            <div className="font-semibold text-red-700">Visual search failed</div>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs text-red-800">
              {visualState.message}
            </pre>
            <div className="mt-3 text-right">
              <button
                onClick={() => setVisualState({ kind: "idle" })}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {visualState.kind === "results" && (
        <VisualSearchModal
          previewUrl={visualState.previewUrl}
          response={visualState.response}
          onClose={closeVisual}
        />
      )}

      {manualState.kind === "error" && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4">
          <div className="max-w-md rounded-md bg-white p-4 shadow-lg">
            <div className="font-semibold text-red-700">Couldn't add manual SKU</div>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs text-red-800">
              {manualState.message}
            </pre>
            <div className="mt-3 text-right">
              <button
                onClick={() => setManualState({ kind: "idle" })}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ManualSkuModal({
  saving,
  onCancel,
  onSubmit,
}: {
  saving: boolean;
  onCancel: () => void;
  onSubmit: (req: ManualProductRequest) => void;
}) {
  const [description, setDescription] = useState("Guardian artwork piece");
  const [longDescription, setLongDescription] = useState("");
  const [productType, setProductType] = useState("Artwork");
  const [material, setMaterial] = useState("Mixed media");
  const [size, setSize] = useState("");
  const [qty, setQty] = useState("1");
  const [costPrice, setCostPrice] = useState("");
  const [retailPrice, setRetailPrice] = useState("");
  const [supplierName, setSupplierName] = useState("Internal / Manual");
  const [internalCode, setInternalCode] = useState("");
  const [notes, setNotes] = useState("");

  const canSubmit =
    description.trim().length > 0 &&
    productType.trim().length > 0 &&
    material.trim().length > 0;

  const handle = () => {
    const req: ManualProductRequest = {
      description: description.trim(),
      long_description: longDescription.trim() || undefined,
      product_type: productType.trim(),
      material: material.trim(),
      size: size.trim() || undefined,
      qty_on_hand: Number.parseFloat(qty) || 1,
      cost_price: costPrice ? Number.parseFloat(costPrice) : undefined,
      retail_price: retailPrice ? Number.parseFloat(retailPrice) : undefined,
      supplier_name: supplierName.trim() || undefined,
      internal_code: internalCode.trim() || undefined,
      notes: notes.trim() || undefined,
    };
    onSubmit(req);
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-2xl rounded-md bg-white shadow-xl">
        <header className="border-b border-gray-200 px-5 py-3">
          <div className="text-base font-semibold text-gray-900">Add manual SKU</div>
          <div className="text-xs text-gray-500">
            For one-off items with no supplier order (e.g. Guardian artwork). The mini-server
            will allocate a fresh SKU + barcode.
          </div>
        </header>
        <div className="grid grid-cols-1 gap-3 p-5 sm:grid-cols-2">
          <Field label="Description *" hint="Shown on the receipt and in the master list">
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </Field>
          <Field label="Long description" hint="Optional — used for online listings">
            <input
              type="text"
              value={longDescription}
              onChange={(e) => setLongDescription(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </Field>
          <Field label="Product type *" hint="e.g. Artwork, Bookend, Sphere">
            <input
              type="text"
              value={productType}
              onChange={(e) => setProductType(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </Field>
          <Field label="Material *" hint="e.g. Mixed media, Crystal, Bronze">
            <input
              type="text"
              value={material}
              onChange={(e) => setMaterial(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </Field>
          <Field label="Size">
            <input
              type="text"
              value={size}
              onChange={(e) => setSize(e.target.value)}
              placeholder="e.g. 30×40cm"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </Field>
          <Field label="Qty on hand">
            <input
              type="number"
              min="0"
              step="1"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </Field>
          <Field label="Cost SGD" hint="Leave blank for commissioned/internal pieces">
            <input
              type="number"
              min="0"
              step="0.01"
              value={costPrice}
              onChange={(e) => setCostPrice(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </Field>
          <Field label="Retail SGD" hint="Set now to mark sale-ready, or leave blank to fill in later">
            <input
              type="number"
              min="0"
              step="0.01"
              value={retailPrice}
              onChange={(e) => setRetailPrice(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </Field>
          <Field label="Supplier name">
            <input
              type="text"
              value={supplierName}
              onChange={(e) => setSupplierName(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </Field>
          <Field label="Internal code" hint="Optional — auto-generated if blank">
            <input
              type="text"
              value={internalCode}
              onChange={(e) => setInternalCode(e.target.value)}
              placeholder="e.g. GUARDIAN-001"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Notes">
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
              />
            </Field>
          </div>
        </div>
        <footer className="flex items-center justify-end gap-2 border-t border-gray-200 px-5 py-3">
          <button
            onClick={onCancel}
            disabled={saving}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:bg-gray-100"
          >
            Cancel
          </button>
          <button
            onClick={handle}
            disabled={!canSubmit || saving}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-gray-400"
          >
            {saving ? "Adding…" : "Add SKU"}
          </button>
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
    <label className="block">
      <span className="block text-xs font-semibold uppercase tracking-wide text-gray-600">
        {label}
      </span>
      {children}
      {hint && <span className="mt-0.5 block text-[11px] text-gray-500">{hint}</span>}
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
              {(preview.summary.images_extracted ?? 0) > 0 && (
                <>
                  {" · "}
                  <span title="Images extracted from the PDF / matched to line items">
                    {preview.summary.images_extracted} images extracted
                    {(preview.summary.items_with_image ?? 0) > 0
                      ? ` (${preview.summary.items_with_image} matched to lines)`
                      : ""}
                  </span>
                </>
              )}
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
                <th className="px-3 py-2">Image</th>
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
                const imageHref = masterDataApi.resolveAssetUrl(it.image_url);
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
                    <td className="px-3 py-2">
                      {imageHref ? (
                        <a href={imageHref} target="_blank" rel="noreferrer" title="Open full-size image">
                          <img
                            src={imageHref}
                            alt={it.product_name_en ?? code ?? "item"}
                            className="h-12 w-12 rounded border border-gray-200 object-cover"
                          />
                        </a>
                      ) : (
                        <div className="h-12 w-12 rounded border border-dashed border-gray-200 bg-gray-50" title="No image extracted for this line" />
                      )}
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
          {preview.page_images && preview.page_images.length > 0 && (
            <details className="border-t border-gray-200 bg-gray-50 px-5 py-3 text-xs">
              <summary className="cursor-pointer font-semibold text-gray-700">
                All extracted images ({preview.page_images.length}) — fallback if a line's thumbnail is wrong
              </summary>
              <div className="mt-3 grid grid-cols-6 gap-3 sm:grid-cols-8 md:grid-cols-10">
                {preview.page_images.map((img, i) => {
                  const href = masterDataApi.resolveAssetUrl(img.url);
                  if (!href) return null;
                  return (
                    <a
                      key={`${img.page_number}-${i}`}
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                      title={`Page ${img.page_number}`}
                      className="block"
                    >
                      <img
                        src={href}
                        alt={`Page ${img.page_number} image ${i + 1}`}
                        className="aspect-square w-full rounded border border-gray-200 object-cover"
                      />
                      <div className="mt-0.5 text-center text-[10px] text-gray-500">
                        p.{img.page_number}
                      </div>
                    </a>
                  );
                })}
              </div>
            </details>
          )}
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
                AI price recommendations ✨
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

function VisualSearchModal({
  previewUrl,
  response,
  onClose,
}: {
  previewUrl: string;
  response: VisualSearchResponse;
  onClose: () => void;
}) {
  const desc = response.descriptor as Record<string, unknown>;
  const tagList = Array.isArray(desc.style_tags) ? (desc.style_tags as string[]).join(", ") : "";
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-[90vh] w-full max-w-6xl flex-col rounded-md bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
          <div>
            <div className="text-base font-semibold text-gray-900">Find by photo 📷</div>
            <div className="text-xs text-gray-500">
              Top {response.matches.length} match{response.matches.length === 1 ? "" : "es"} from a catalog of {response.catalog_size}.
            </div>
          </div>
          <button onClick={onClose} className="text-sm text-gray-500 hover:underline">
            Close
          </button>
        </header>
        <div className="flex flex-1 gap-4 overflow-auto p-5">
          <aside className="w-60 shrink-0">
            <img
              src={previewUrl}
              alt="Uploaded item"
              className="aspect-square w-full rounded border border-gray-200 object-cover"
            />
            <div className="mt-3 space-y-1 text-xs text-gray-600">
              <div><span className="font-semibold">Shape:</span> {String(desc.object_shape ?? "—")}</div>
              <div><span className="font-semibold">Material:</span> {String(desc.material_type ?? "—")}</div>
              <div><span className="font-semibold">Colour:</span> {String(desc.dominant_colour ?? "—")}</div>
              {tagList && <div><span className="font-semibold">Tags:</span> {tagList}</div>}
              {desc.visual_description && (
                <p className="mt-2 italic text-gray-500">{String(desc.visual_description)}</p>
              )}
            </div>
          </aside>
          <div className="flex-1">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {response.matches.map((m) => {
                const href = masterDataApi.resolveAssetUrl(m.image_url);
                const sim = (m.similarity * 100).toFixed(1);
                const tone =
                  m.similarity >= 0.75
                    ? "border-green-300 bg-green-50"
                    : m.similarity >= 0.6
                    ? "border-yellow-300 bg-yellow-50"
                    : "border-gray-200 bg-white";
                return (
                  <div
                    key={`${m.code}-${m.rank}`}
                    className={`rounded border ${tone} p-2 text-xs shadow-sm`}
                  >
                    {href ? (
                      <a href={href} target="_blank" rel="noreferrer">
                        <img
                          src={href}
                          alt={m.code ?? "match"}
                          className="aspect-square w-full rounded object-cover"
                        />
                      </a>
                    ) : (
                      <div className="aspect-square w-full rounded border border-dashed border-gray-300 bg-gray-50" />
                    )}
                    <div className="mt-2 flex items-baseline justify-between">
                      <div className="font-mono text-[11px] font-semibold text-gray-700">{m.code}</div>
                      <div className="text-[11px] font-semibold text-gray-600">{sim}%</div>
                    </div>
                    {m.sku ? (
                      <div className="mt-1 space-y-0.5">
                        <div className="font-mono text-[11px] text-gray-700">{m.sku}</div>
                        {m.nec_plu && (
                          <div className="font-mono text-[11px] text-gray-500">PLU {m.nec_plu}</div>
                        )}
                        {m.description && (
                          <div className="line-clamp-2 text-[11px] text-gray-600" title={m.description}>
                            {m.description}
                          </div>
                        )}
                        <div className="flex gap-3 text-[11px] text-gray-500">
                          {m.retail_price != null && <span>S${m.retail_price.toFixed(2)}</span>}
                          {m.qty_on_hand != null && <span>qty {m.qty_on_hand}</span>}
                        </div>
                      </div>
                    ) : (
                      <div className="mt-1 text-[11px] italic text-gray-400">
                        No master-list entry yet
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {response.matches.length === 0 && (
              <div className="py-12 text-center text-sm text-gray-500">
                No catalog matches. Try a different photo or rebuild the catalog index.
              </div>
            )}
          </div>
        </div>
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

function ApiBaseEditor({ current, onChange }: { current: string; onChange: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(current);
  if (!editing) {
    return (
      <button
        onClick={() => {
          setDraft(current);
          setEditing(true);
        }}
        className="ml-auto rounded-md border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
        title="Configure the master-data API URL"
      >
        API: {current}
      </button>
    );
  }
  return (
    <div className="ml-auto flex items-center gap-2">
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="http://192.168.x.x:8765"
        className="w-64 rounded-md border border-gray-300 px-3 py-1.5 text-xs"
      />
      <button
        onClick={() => {
          onChange(draft);
          setEditing(false);
        }}
        className="rounded-md bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700"
      >
        Save
      </button>
      <button onClick={() => setEditing(false)} className="text-xs text-gray-500 hover:underline">
        Cancel
      </button>
    </div>
  );
}
