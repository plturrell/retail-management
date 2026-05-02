import { Fragment, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  masterDataApi,
  type ExportResult,
  type IngestPreview,
  type LabelsExportResult,
  type PosStatusResponse,
  type PriceRecommendationsResponse,
  type ProductRow,
  type Stats,
  newIdempotencyKey,
} from "../lib/master-data-api";
import { auth } from "../lib/firebase";
import { useAuth } from "../contexts/AuthContext";
import { Icon } from "../components/Icon";
import {
  CANONICAL_LOCATION_OPTIONS,
  type CanonicalLocationValue,
  type RecentCreate,
  STORE_LOCATION_VALUES,
  encodeStockingLocation,
  formatMaterialSummary,
  formatStockingLocation,
  loadRecentCreates,
  masterDataAssetUrl,
  normaliseCode,
  normaliseIdentity,
  parseStockingLocation,
  relativeTime,
  saveRecentCreates,
  withTimeout,
} from "../lib/master-data-helpers";

type SaveState = "idle" | "saving" | "saved" | "error";
type PublishState = "idle" | "publishing" | "published" | "error";
type OwnerView = "needs_pricing" | "new_skus" | "ready_publish" | "all" | "archived";
type MasterDataTool = "pricing" | "vault" | "pos_readiness";
type InventoryBucket = "store" | "warehouse" | "on_order" | "supplier_catalog";
type InventoryFilter = InventoryBucket | "all";

const EmbeddedVaultPage = lazy(() => import("./VaultPage"));
const EmbeddedPosReadinessPage = lazy(() => import("./PosReadinessPage"));

const MASTER_DATA_TOOLS: Array<{
  id: MasterDataTool;
  label: string;
  detail: string;
  icon: "package" | "archive" | "check-circle";
}> = [
  {
    id: "pricing",
    label: "Pricing",
    detail: "Create, price, publish",
    icon: "package",
  },
  {
    id: "vault",
    label: "Staging Vault",
    detail: "Review OCR documents",
    icon: "archive",
  },
  {
    id: "pos_readiness",
    label: "POS Readiness",
    detail: "Pre-flight checklist",
    icon: "check-circle",
  },
];

interface RowState {
  product: ProductRow;
  draftDescription: string;
  draftPrice: string;
  draftNotes: string;
  draftQty: string;
  draftLocation: string;
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
  (import.meta.env.VITE_MASTER_DATA_PUBLISHERS || "turrell.craig.1971@gmail.com,irina@victoriaenso.com")
    .split(",")
    .map((s: string) => s.trim().toLowerCase())
    .filter(Boolean),
);

export default function MasterDataPage() {
  const { isOwner, user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const canPublishPrice =
    isOwner &&
    Boolean(user?.email) &&
    PUBLISHER_ALLOWLIST.has((user!.email as string).toLowerCase());
  const [stats, setStats] = useState<Stats | null>(null);
  const [rows, setRows] = useState<RowState[]>([]);
  const [allProducts, setAllProducts] = useState<ProductRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [globalError, setGlobalError] = useState<string | null>(null);
  // Honour ``?focus=SKU`` from inbound deep-links (e.g. AddItemPage redirects
  // back here after a successful create) so the operator lands directly on
  // the row they just touched. The query param is consumed once and then
  // cleared so refresh/back doesn't re-snap the search to a stale SKU.
  const [search, setSearch] = useState(() => searchParams.get("focus") || "");
  const [supplierFilter, setSupplierFilter] = useState<string>("all");
  const [sourcingFilter, setSourcingFilter] = useState<string>("all");
  const [locationFilter, setLocationFilter] = useState<CanonicalLocationValue[]>([]);
  const [inventoryFilter, setInventoryFilter] = useState<InventoryFilter>("all");
  const [activeTool, setActiveTool] = useState<MasterDataTool>("pricing");
  const [ownerView, setOwnerView] = useState<OwnerView>("needs_pricing");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [advancedFiltersOpen, setAdvancedFiltersOpen] = useState(false);
  const [needsPriceOnly, setNeedsPriceOnly] = useState(true);
  const [purchasedOnly, setPurchasedOnly] = useState(true);
  const [recentCreates, setRecentCreates] = useState<RecentCreate[]>(() => loadRecentCreates());
  const [ownerToolsOpen, setOwnerToolsOpen] = useState(false);
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
  const [expandedVariants, setExpandedVariants] = useState<Set<string>>(new Set());
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadAll = useCallback(async (overrides: Partial<{
    needsPriceOnly: boolean;
    purchasedOnly: boolean;
    sourcingFilter: string;
    includeArchived: boolean;
  }> = {}) => {
    const effectiveNeedsPriceOnly = overrides.needsPriceOnly ?? needsPriceOnly;
    const effectivePurchasedOnly = overrides.purchasedOnly ?? purchasedOnly;
    const effectiveSourcingFilter = overrides.sourcingFilter ?? sourcingFilter;
    const effectiveIncludeArchived = overrides.includeArchived ?? includeArchived;
    setLoading(true);
    setGlobalError(null);
    try {
      const [statsRes, productsRes, allProductsRes, posRes] = await Promise.all([
        withTimeout(masterDataApi.stats(), 10_000, "Master data stats"),
        withTimeout(
          masterDataApi.listProducts({
            launch_only: true,
            needs_price: effectiveNeedsPriceOnly,
            purchased_only: effectivePurchasedOnly,
            sourcing_strategy: effectiveSourcingFilter !== "all" ? effectiveSourcingFilter : undefined,
            group_variants: true,
            include_archived: effectiveIncludeArchived,
          }),
          12_000,
          "Visible inventory",
        ),
        withTimeout(
          masterDataApi.listProducts({
            launch_only: false,
            needs_price: false,
            purchased_only: false,
            group_variants: false,
            include_archived: true,
          }),
          15_000,
          "Full inventory index",
        ),
        masterDataApi.posStatus().catch(() => null),
      ]);
      setStats(statsRes);
      setAllProducts(allProductsRes.products);
      setPosStatus(posRes);
      setRows(
        productsRes.products.map((p) => ({
          product: p,
          draftDescription: p.description ?? "",
          draftPrice: p.retail_price ? String(p.retail_price) : "",
          draftNotes: p.retail_price_note ?? "",
          draftQty: p.qty_on_hand === null || p.qty_on_hand === undefined ? "" : String(p.qty_on_hand),
          draftLocation: encodeStockingLocation(parseStockingLocation(p.stocking_location)),
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
  }, [needsPriceOnly, purchasedOnly, sourcingFilter, includeArchived]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  // Drop ``?focus=`` from the URL once seeded — the search box owns the value
  // from here on, so we don't want a manual page refresh to re-snap it.
  useEffect(() => {
    if (!searchParams.get("focus")) return;
    const next = new URLSearchParams(searchParams);
    next.delete("focus");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (supplierFilter !== "all") {
        const sup = r.product.supplier_id || "(none)";
        if (sup !== supplierFilter) return false;
      }
      if (locationFilter.length > 0) {
        const productLocations = parseStockingLocation(r.product.stocking_location);
        if (!productLocations.some((loc) => locationFilter.includes(loc))) return false;
      }
      if (inventoryFilter !== "all" && !inventoryBucketsForProduct(r.product).includes(inventoryFilter)) {
        return false;
      }
      if (ownerView === "archived") {
        if (!isArchivedProduct(r.product)) return false;
      } else if (isArchivedProduct(r.product)) {
        return false;
      }
      if (ownerView === "needs_pricing" && r.draftPrice.trim()) return false;
      if (
        ownerView === "new_skus" &&
        !r.product.needs_retail_price &&
        (r.product.retail_price || r.product.retail_price_set_at)
      ) return false;
      if (ownerView === "ready_publish" && (!r.saleReady || !r.draftPrice.trim())) return false;
      if (q) {
        const haystack = [
          r.product.sku_code,
          r.product.nec_plu,
          r.product.plu_code,
          r.product.internal_code,
          r.product.supplier_item_code,
          r.product.description,
          r.product.material,
          r.product.material_category,
          r.product.material_subcategory,
          ...(r.product.additional_materials || []),
          r.product.product_type,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [rows, search, supplierFilter, locationFilter, inventoryFilter, ownerView]);
  const visibleMissingPrices = useMemo(
    () => filteredRows.filter((r) => !r.draftPrice.trim()).length,
    [filteredRows],
  );
  const visibleReadyToPublish = useMemo(
    () => filteredRows.filter((r) => r.saleReady && r.draftPrice.trim()).length,
    [filteredRows],
  );
  const advancedFilterCount =
    (supplierFilter !== "all" ? 1 : 0) +
    (sourcingFilter !== "all" ? 1 : 0) +
    (inventoryFilter !== "all" ? 1 : 0) +
    locationFilter.length +
    (purchasedOnly ? 1 : 0) +
    (includeArchived ? 1 : 0);

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

  const dataIntegrity = useMemo(() => buildDataIntegrity(allProducts), [allProducts]);
  const inventorySummary = useMemo(() => buildInventorySummary(allProducts), [allProducts]);

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
      setAllProducts((prev) => prev.map((p) => (p.sku_code === sku ? updated : p)));
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

  const saveRowDetails = async (sku: string) => {
    if (!isOwner) return;
    const row = rows.find((r) => r.product.sku_code === sku);
    if (!row) return;
    const description = row.draftDescription.trim();
    if (!description) {
      updateRow(sku, (r) => ({ ...r, save: "error", error: "Item name is required" }));
      return;
    }
    const duplicate = dataIntegrity.nameKeyToProducts
      .get(normaliseIdentity(description))
      ?.find((p) => p.sku_code !== sku);
    if (duplicate) {
      updateRow(sku, (r) => ({
        ...r,
        save: "error",
        error: `Name already exists on ${duplicate.sku_code}`,
      }));
      return;
    }
    const qtyText = row.draftQty.trim();
    const qty = qtyText ? Number.parseFloat(qtyText) : null;
    if (qty !== null && (!Number.isFinite(qty) || qty < 0)) {
      updateRow(sku, (r) => ({ ...r, save: "error", error: "Quantity must be zero or more" }));
      return;
    }
    updateRow(sku, (r) => ({ ...r, save: "saving", error: undefined }));
    try {
      const updated = await masterDataApi.patchProduct(sku, {
        description,
        qty_on_hand: qty,
        stocking_location: row.draftLocation,
        notes: row.draftNotes,
      });
      setAllProducts((prev) => prev.map((p) => (p.sku_code === sku ? updated : p)));
      updateRow(sku, (r) => ({
        ...r,
        product: updated,
        draftDescription: updated.description ?? "",
        draftNotes: updated.retail_price_note ?? "",
        draftQty: updated.qty_on_hand === null || updated.qty_on_hand === undefined ? "" : String(updated.qty_on_hand),
        draftLocation: encodeStockingLocation(parseStockingLocation(updated.stocking_location)),
        save: "saved",
        savedAt: Date.now(),
        error: undefined,
      }));
    } catch (e) {
      updateRow(sku, (r) => ({ ...r, save: "error", error: (e as Error).message }));
    }
  };

  const archiveRow = async (sku: string) => {
    if (!isOwner) return;
    const row = rows.find((r) => r.product.sku_code === sku);
    if (!row) return;
    const name = row.product.description || sku;
    const confirmed = window.confirm(
      `Archive ${name}? The SKU and barcode stay reserved, but the item will be blocked from sales and hidden from normal inventory views.`,
    );
    if (!confirmed) return;
    updateRow(sku, (r) => ({ ...r, save: "saving", error: undefined }));
    try {
      const updated = await masterDataApi.archiveProduct(sku, {
        reason: "Archived from Master Data",
      });
      setAllProducts((prev) => prev.map((p) => (p.sku_code === sku ? updated : p)));
      if (ownerView === "archived") {
        updateRow(sku, (r) => ({
          ...r,
          product: updated,
          saleReady: Boolean(updated.sale_ready),
          save: "saved",
          savedAt: Date.now(),
        }));
      } else {
        setRows((prev) => prev.filter((r) => r.product.sku_code !== sku));
      }
    } catch (e) {
      updateRow(sku, (r) => ({ ...r, save: "error", error: (e as Error).message }));
    }
  };

  const restoreRow = async (sku: string) => {
    if (!isOwner) return;
    updateRow(sku, (r) => ({ ...r, save: "saving", error: undefined }));
    try {
      const updated = await masterDataApi.restoreProduct(sku);
      setAllProducts((prev) => prev.map((p) => (p.sku_code === sku ? updated : p)));
      if (ownerView === "archived") {
        setRows((prev) => prev.filter((r) => r.product.sku_code !== sku));
      } else {
        updateRow(sku, (r) => ({
          ...r,
          product: updated,
          draftDescription: updated.description ?? "",
          draftNotes: updated.retail_price_note ?? "",
          draftQty: updated.qty_on_hand === null || updated.qty_on_hand === undefined ? "" : String(updated.qty_on_hand),
          draftLocation: encodeStockingLocation(parseStockingLocation(updated.stocking_location)),
          saleReady: Boolean(updated.sale_ready),
          save: "saved",
          savedAt: Date.now(),
        }));
      }
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
      const result = await masterDataApi.commitInvoice(
        {
          upload_id: preview.upload_id,
          items: itemsToCommit,
          order_number: preview.document_number ?? null,
        },
        { idempotencyKey: newIdempotencyKey() },
      );
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

  const revealSku = (sku: string) => {
    setSearch(sku);
    setSupplierFilter("all");
    setSourcingFilter("all");
    setPurchasedOnly(false);
    setNeedsPriceOnly(false);
    void loadAll({ needsPriceOnly: false, purchasedOnly: false, sourcingFilter: "all" });
  };

  const clearRecentCreates = () => {
    setRecentCreates([]);
    saveRecentCreates([]);
  };

  const toggleLocationFilter = (value: CanonicalLocationValue) => {
    setLocationFilter((prev) => (
      prev.includes(value)
        ? prev.filter((item) => item !== value)
        : [...prev, value]
    ));
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

    // Open the print window synchronously, inside the click gesture, so Safari
    // and Firefox don't treat it as a popup. Fill it once the labels HTML is
    // back; close it on failure so the user doesn't end up with a blank tab.
    const printWin = window.open("", "_blank");
    if (printWin) {
      printWin.document.open();
      printWin.document.write(
        '<!doctype html><title>Generating labels…</title>' +
          '<body style="font-family:sans-serif;padding:2rem;color:#555">Generating labels…</body>',
      );
      printWin.document.close();
    }

    try {
      const user = auth.currentUser;
      if (!user) {
        printWin?.close();
        return;
      }
      const token = await user.getIdToken();
      const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api";
      const res = await fetch(`${BASE_URL}/pos-labelling/print?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error("Failed to load labels");
      const html = await res.text();

      if (printWin) {
        printWin.document.open();
        printWin.document.write(html);
        printWin.document.close();
      }
    } catch (err) {
      printWin?.close();
      alert("Error generating labels: " + (err as Error).message);
    }
  };

  const selectOwnerView = (view: OwnerView) => {
    setOwnerView(view);
    setInventoryFilter("all");
    setIncludeArchived(view === "archived");
    if (view === "archived") {
      setNeedsPriceOnly(false);
      setPurchasedOnly(false);
      setSourcingFilter("all");
      void loadAll({
        needsPriceOnly: false,
        purchasedOnly: false,
        sourcingFilter: "all",
        includeArchived: true,
      });
      return;
    }
    if (view === "all") {
      setNeedsPriceOnly(false);
      setPurchasedOnly(false);
      setSourcingFilter("all");
      void loadAll({
        needsPriceOnly: false,
        purchasedOnly: false,
        sourcingFilter: "all",
        includeArchived: false,
      });
      return;
    }
    if (view === "ready_publish") {
      setNeedsPriceOnly(false);
      void loadAll({ needsPriceOnly: false, includeArchived: false });
      return;
    }
    setNeedsPriceOnly(true);
    setPurchasedOnly(true);
    void loadAll({ needsPriceOnly: true, includeArchived: false });
  };

  const reviewPriceQueue = () => selectOwnerView("needs_pricing");
  const showFullInventory = () => selectOwnerView("all");

  const selectInventoryBucket = (bucket: InventoryFilter) => {
    setInventoryFilter(bucket);
    setOwnerView("all");
    setNeedsPriceOnly(false);
    setPurchasedOnly(false);
    setSourcingFilter("all");
    setIncludeArchived(false);
    void loadAll({
      needsPriceOnly: false,
      purchasedOnly: false,
      sourcingFilter: "all",
      includeArchived: false,
    });
  };

  return (
    <div>
      <div className="mx-auto max-w-[1400px]">
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <h1 className="text-[28px] font-semibold leading-tight text-slate-950 md:text-3xl">Master Data</h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-500">
              {isOwner
                ? "Price gaps, new SKUs, and POS publishing in one place."
                : "Review POS-ready catalogue, price gaps, and SKU readiness."}
            </p>
          </div>
          {isOwner && (
            <div className="flex items-center gap-2 md:justify-end">
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff"
                onChange={onInvoiceFile}
                className="hidden"
              />
              <button
                onClick={() => {
                  setOwnerToolsOpen(false);
                  navigate("/master-data/add");
                }}
                className="inline-flex min-h-10 flex-1 items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 sm:flex-none"
                title="Create a new inventory item — supplier or in-house — with optional inline price"
              >
                <Icon name="plus" className="h-4 w-4" />
                Create inventory
              </button>
              <details
                open={ownerToolsOpen}
                onToggle={(event) => setOwnerToolsOpen(event.currentTarget.open)}
                className="group relative"
              >
                <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 rounded-lg border border-slate-200 bg-white/90 px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 [&::-webkit-details-marker]:hidden">
                  <Icon name="menu" className="h-4 w-4" />
                  Tools
                </summary>
                <div className="absolute right-0 z-20 mt-2 w-64 rounded-lg border border-slate-200 bg-white p-1.5 shadow-xl">
                  <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Create
                  </div>
                  <button
                    onClick={() => {
                      setOwnerToolsOpen(false);
                      navigate("/master-data/add?variant=1");
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-50"
                    title="Create a new SKU as a variant of an existing product family"
                  >
                    <Icon name="plus" className="h-4 w-4 text-teal-700" />
                    Add variant
                  </button>
                  <button
                    onClick={() => {
                      setOwnerToolsOpen(false);
                      onPickInvoice();
                    }}
                    disabled={ingestState.kind === "uploading" || ingestState.kind === "committing"}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:text-slate-400"
                    title="Upload a supplier PDF/image — DeepSeek OCR extracts line items"
                  >
                    <Icon name="document" className="h-4 w-4 text-slate-500" />
                    {ingestState.kind === "uploading"
                      ? `OCR'ing ${ingestState.filename}…`
                      : "Process invoice"}
                  </button>
                  <div className="my-1 border-t border-slate-100" />
                  <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Review
                  </div>
                  <button
                    onClick={() => {
                      setOwnerToolsOpen(false);
                      setActiveTool("vault");
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-50"
                    title="Review OCR documents waiting in the staging vault"
                  >
                    <Icon name="archive" className="h-4 w-4 text-slate-500" />
                    Review staging vault
                  </button>
                  <button
                    onClick={() => {
                      setOwnerToolsOpen(false);
                      setActiveTool("pos_readiness");
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-50"
                    title="Check whether master data is ready for POS export"
                  >
                    <Icon name="check-circle" className="h-4 w-4 text-emerald-700" />
                    Check POS readiness
                  </button>
                  <div className="my-1 border-t border-slate-100" />
                  <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Assist
                  </div>
                  <button
                    onClick={() => {
                      setOwnerToolsOpen(false);
                      setActiveTool("pricing");
                      void requestAiPrices();
                    }}
                    disabled={aiState.kind === "loading" || aiState.kind === "applying"}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:text-slate-400"
                    title="Ask DeepSeek to suggest retail prices for unpriced SKUs"
                  >
                    <Icon name="spark" className="h-4 w-4 text-purple-700" />
                    {aiState.kind === "loading" ? "Thinking…" : "AI suggest prices"}
                  </button>
                  <div className="my-1 border-t border-slate-100" />
                  <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Export & print
                  </div>
                  <button
                    onClick={() => {
                      setOwnerToolsOpen(false);
                      void regenerate();
                    }}
                    disabled={exporting}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:text-slate-400"
                  >
                    <Icon name="document-text" className="h-4 w-4 text-blue-700" />
                    {exporting ? "Generating…" : "Regenerate NEC Excel"}
                  </button>
                  <button
                    onClick={() => {
                      setOwnerToolsOpen(false);
                      setActiveTool("pricing");
                      void printPosLabels();
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-50"
                    title="Print barcode labels for sale-ready SKUs currently visible in the grid"
                  >
                    <Icon name="package" className="h-4 w-4 text-slate-500" />
                    Print POS labels
                  </button>
                </div>
              </details>
            </div>
          )}
        </div>

        <div className="mb-4 grid gap-2 rounded-xl border border-slate-200 bg-white/82 p-1.5 shadow-sm sm:grid-cols-3">
          {MASTER_DATA_TOOLS.map((tool) => {
            const active = activeTool === tool.id;
            return (
              <button
                key={tool.id}
                type="button"
                onClick={() => setActiveTool(tool.id)}
                className={`flex min-h-14 items-center gap-3 rounded-lg px-3 py-2 text-left transition ${
                  active
                    ? "bg-slate-950 text-white shadow-sm"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-950"
                }`}
              >
                <Icon name={tool.icon} className="h-4 w-4 shrink-0" />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold">{tool.label}</span>
                  <span className={`block truncate text-[11px] ${active ? "text-white/64" : "text-slate-400"}`}>
                    {tool.detail}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        {activeTool === "pricing" ? (
          <>
        {globalError && (
          <div className="mb-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
            <div className="font-semibold">{globalError}</div>
          </div>
        )}

        <section className="mb-4 rounded-xl border border-slate-200 bg-white/88 p-3 shadow-sm">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Owner command centre</div>
              {stats ? (
                <div className="mt-1 text-sm text-slate-600">
                  Total {stats.total} · Sale ready {stats.sale_ready} · Visible {filteredRows.length}
                </div>
              ) : (
                <div className="mt-2 h-3 w-44 animate-pulse rounded bg-slate-100" />
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5 xl:min-w-[880px]">
              {stats ? (
                <>
                  <AttentionMetric
                    label="Needs pricing"
                    value={stats.sale_ready_missing_price}
                    detail={`${visibleMissingPrices} visible`}
                    tone={stats.sale_ready_missing_price > 0 ? "warn" : "good"}
                    active={ownerView === "needs_pricing"}
                    onClick={reviewPriceQueue}
                  />
                  <AttentionMetric
                    label="New SKUs"
                    value={stats.needs_price_flag}
                    detail="Awaiting retail"
                    tone={stats.needs_price_flag > 0 ? "warn" : "good"}
                    active={ownerView === "new_skus"}
                    onClick={() => selectOwnerView("new_skus")}
                  />
                  <AttentionMetric
                    label="Ready"
                    value={visibleReadyToPublish}
                    detail="Publishable"
                    tone={visibleReadyToPublish > 0 ? "good" : undefined}
                    active={ownerView === "ready_publish"}
                    onClick={() => selectOwnerView("ready_publish")}
                  />
                  <AttentionMetric
                    label="All"
                    value={stats.total}
                    detail="Inventory"
                    active={ownerView === "all"}
                    onClick={showFullInventory}
                  />
                  <AttentionMetric
                    label="Archived"
                    value={stats.archived ?? 0}
                    detail="Hidden safely"
                    active={ownerView === "archived"}
                    onClick={() => selectOwnerView("archived")}
                  />
                </>
              ) : (
                <>
                  <div className="h-[74px] animate-pulse rounded-md border border-slate-200 bg-slate-50" />
                  <div className="h-[74px] animate-pulse rounded-md border border-slate-200 bg-slate-50" />
                  <div className="h-[74px] animate-pulse rounded-md border border-slate-200 bg-slate-50" />
                  <div className="h-[74px] animate-pulse rounded-md border border-slate-200 bg-slate-50" />
                  <div className="h-[74px] animate-pulse rounded-md border border-slate-200 bg-slate-50" />
                </>
              )}
            </div>
          </div>

          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="grid flex-1 grid-cols-2 gap-2 lg:grid-cols-4">
              <AttentionMetric
                label="In store"
                value={inventorySummary.store}
                detail="Jewel, Isetan, Taka, Online"
                active={inventoryFilter === "store"}
                onClick={() => selectInventoryBucket("store")}
              />
              <AttentionMetric
                label="Warehouse"
                value={inventorySummary.warehouse}
                detail="Breeze stock"
                active={inventoryFilter === "warehouse"}
                onClick={() => selectInventoryBucket("warehouse")}
              />
              <AttentionMetric
                label="On order"
                value={inventorySummary.on_order}
                detail="Incoming stock"
                tone={inventorySummary.on_order > 0 ? "warn" : undefined}
                active={inventoryFilter === "on_order"}
                onClick={() => selectInventoryBucket("on_order")}
              />
              <AttentionMetric
                label="Catalog only"
                value={inventorySummary.supplier_catalog}
                detail="Supplier linked"
                active={inventoryFilter === "supplier_catalog"}
                onClick={() => selectInventoryBucket("supplier_catalog")}
              />
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-xs text-slate-600">
            <span className="font-semibold text-slate-800">Data guardrails</span>
            <IntegrityPill
              label="Names"
              value={dataIntegrity.duplicateNameGroups}
              noun="duplicate group"
            />
            <IntegrityPill
              label="Barcodes"
              value={dataIntegrity.duplicateBarcodeGroups}
              noun="duplicate group"
            />
            <IntegrityPill
              label="SKUs"
              value={dataIntegrity.duplicateSkuGroups}
              noun="duplicate group"
            />
            {inventoryFilter !== "all" && (
              <button
                type="button"
                onClick={() => selectInventoryBucket("all")}
                className="ml-auto rounded-md border border-slate-200 bg-white px-2 py-1 font-semibold text-slate-700 hover:bg-slate-50"
              >
                Clear inventory view
              </button>
            )}
          </div>

          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              type="text"
              placeholder="Search SKU or description…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="min-h-10 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-slate-400"
            />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setAdvancedFiltersOpen((open) => !open)}
                className="inline-flex min-h-10 flex-1 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 sm:flex-none"
              >
                <Icon name="search" className="h-4 w-4" />
                Filters
                {advancedFilterCount > 0 && (
                  <span className="rounded-full bg-slate-900 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                    {advancedFilterCount}
                  </span>
                )}
              </button>
              <button
                onClick={() => void loadAll()}
                className="inline-flex min-h-10 items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
              >
                Refresh
              </button>
            </div>
          </div>

          {advancedFiltersOpen && (
            <div className="mt-3 grid gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3 md:grid-cols-[minmax(160px,1fr)_minmax(180px,1fr)_2fr]">
              <select
                value={supplierFilter}
                onChange={(e) => setSupplierFilter(e.target.value)}
                className="min-h-10 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800"
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
                className="min-h-10 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800"
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
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Locations</span>
                {CANONICAL_LOCATION_OPTIONS.map((loc) => (
                  <label key={loc.value} className="flex items-center gap-1 text-xs text-slate-700">
                    <input
                      type="checkbox"
                      checked={locationFilter.includes(loc.value)}
                      onChange={() => toggleLocationFilter(loc.value)}
                    />
                    {loc.label}
                  </label>
                ))}
                {locationFilter.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setLocationFilter([])}
                    className="text-xs font-semibold text-blue-700 hover:underline"
                  >
                    Clear
                  </button>
                )}
              </div>
              <label className="flex items-center gap-1.5 text-sm text-slate-700" title="Show only SKUs from real POs / invoices (skip catalog-only rows)">
                <input
                  type="checkbox"
                  checked={purchasedOnly}
                  onChange={(e) => setPurchasedOnly(e.target.checked)}
                />
                Purchased only
              </label>
              <label className="flex items-center gap-1.5 text-sm text-slate-700" title="Show archived rows so they can be restored">
                <input
                  type="checkbox"
                  checked={includeArchived}
                  onChange={(e) => {
                    const checked = e.target.checked;
                    setIncludeArchived(checked);
                    if (checked) {
                      setOwnerView("all");
                      setNeedsPriceOnly(false);
                      setPurchasedOnly(false);
                      void loadAll({ needsPriceOnly: false, purchasedOnly: false, includeArchived: true });
                    } else {
                      setOwnerView("needs_pricing");
                      void loadAll({ includeArchived: false });
                    }
                  }}
                />
                Include archived
              </label>
              <label className="flex items-center gap-1.5 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={needsPriceOnly}
                  onChange={(e) => setNeedsPriceOnly(e.target.checked)}
                />
                Needs price only
              </label>
            </div>
          )}
        </section>

        {recentCreates.length > 0 && (
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-950">
            <span className="font-semibold">Recently added</span>
            {recentCreates.map((item) => (
              <button
                key={item.sku_code}
                type="button"
                onClick={() => revealSku(item.sku_code)}
                className="rounded-full border border-emerald-300 bg-white px-3 py-1 text-xs font-semibold text-emerald-800 shadow-sm hover:bg-emerald-100"
                title={[item.description, item.material, item.product_type].filter(Boolean).join(" · ")}
              >
                {item.sku_code}
              </button>
            ))}
            <button
              type="button"
              onClick={clearRecentCreates}
              className="ml-auto text-xs font-medium text-emerald-700 hover:underline"
            >
              Clear
            </button>
          </div>
        )}

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

        <div className="overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full min-w-[920px] text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-3">
                  <input
                    type="checkbox"
                    aria-label="Select all visible"
                    checked={allVisibleSelected}
                    onChange={toggleAllVisible}
                    disabled={!isOwner || filteredRows.length === 0}
                  />
                </th>
                <th className="sticky left-0 z-20 bg-slate-50 px-3 py-3">Item</th>
                <th className="px-3 py-3">Inventory</th>
                <th className="px-3 py-3 text-right">Cost</th>
                <th className="px-3 py-3 text-right">Retail</th>
                <th className="px-3 py-3 text-right">Margin</th>
                <th className="px-3 py-3">Ready</th>
                <th className="px-3 py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-slate-400">
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && filteredRows.length === 0 && !globalError && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-slate-400">
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
                const imageSrc = masterDataAssetUrl(p.thumbnail_url || p.image_urls?.[0]);
                const siblings = p.variant_siblings || [];
                const isExpanded = expandedVariants.has(p.sku_code);
                const isRowExpanded = expandedRows.has(p.sku_code);
                const rowWarnings = dataIntegrity.skuWarnings.get(p.sku_code) || [];
                const skuParts = parseSkuAnatomy(p.sku_code);
                const archived = isArchivedProduct(p);
                return (
                  <Fragment key={p.sku_code}>
                  <tr className={archived ? "bg-slate-100/80 text-slate-500" : isSelected ? "bg-blue-50/40" : "hover:bg-slate-50"}>
                    <td className="px-3 py-3 align-top">
                      <input
                        type="checkbox"
                        aria-label={`Select ${p.sku_code}`}
                        checked={isSelected}
                        onChange={() => toggleSelected(p.sku_code)}
                        disabled={!isOwner || archived}
                      />
                    </td>
                    <td className={`sticky left-0 z-10 px-3 py-3 ${archived ? "bg-slate-100" : isSelected ? "bg-blue-50" : "bg-white"}`}>
                      <div className="flex min-w-[310px] items-start gap-3">
                        {imageSrc ? (
                          <button type="button" onClick={() => setLightboxImage(imageSrc)} className="mt-0.5 block shrink-0">
                            <img src={imageSrc} loading="lazy" alt="" className="h-11 w-11 rounded-md object-cover shadow-sm" />
                          </button>
                        ) : (
                          <div className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-slate-100 text-xs text-slate-300">—</div>
                        )}
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-slate-900" title={p.description ?? ""}>
                            {archived && <span className="mr-2 rounded bg-slate-200 px-1.5 py-0.5 text-[11px] text-slate-700">Archived</span>}
                            {p.variant_label && <span className="mr-2 rounded bg-teal-50 px-1.5 py-0.5 text-[11px] text-teal-800">{p.variant_label}</span>}
                            {p.description || p.sku_code}
                          </div>
                          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                            <span>{p.product_type || "—"}</span>
                            <span>·</span>
                            <span title={formatMaterialSummary(p)}>{formatMaterialSummary(p) || "—"}</span>
                            {p.size && (
                              <>
                                <span>·</span>
                                <span>{p.size}</span>
                              </>
                            )}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-1.5">
                            <button
                              type="button"
                              onClick={() =>
                                setExpandedRows((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(p.sku_code)) next.delete(p.sku_code);
                                  else next.add(p.sku_code);
                                  return next;
                                })
                              }
                              className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-600 hover:bg-slate-50"
                            >
                              {isRowExpanded ? "Hide details" : "Details"}
                            </button>
                            {siblings.length > 0 && (
                              <button
                                type="button"
                                onClick={() =>
                                  setExpandedVariants((prev) => {
                                    const next = new Set(prev);
                                    if (next.has(p.sku_code)) next.delete(p.sku_code);
                                    else next.add(p.sku_code);
                                    return next;
                                  })
                                }
                                className="rounded-full border border-teal-200 bg-teal-50 px-2 py-0.5 text-[11px] font-semibold text-teal-800 hover:bg-teal-100"
                                title="Show variant SKUs"
                              >
                                {isExpanded ? "Hide" : "Show"} {siblings.length + 1} variants
                              </button>
                            )}
                            {rowWarnings.map((warning) => (
                              <span
                                key={warning}
                                className="rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[11px] font-semibold text-red-700"
                              >
                                {warning}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3 text-sm text-slate-600">
                      <div className="font-medium text-slate-700">{inventoryStateLabel(p)}</div>
                      <div className="mt-0.5 text-xs text-slate-500">{formatStockingLocation(p.stocking_location)}</div>
                    </td>
                    <td className="px-3 py-3 text-right font-medium text-slate-700">S${fmtMoney(p.cost_price)}</td>
                    <td className="px-3 py-3 text-right">
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={r.draftPrice}
                        placeholder={suggestedRetail(p.cost_price)}
                        onChange={(e) => updateRow(p.sku_code, (rs) => ({ ...rs, draftPrice: e.target.value, save: "idle" }))}
                        onBlur={() => isOwner && void saveRow(p.sku_code)}
                        onKeyDown={(e) => onPriceKey(p.sku_code, e)}
                        disabled={!isOwner || archived}
                        className="w-24 rounded-lg border border-slate-200 px-2 py-1.5 text-right font-mono text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-500"
                      />
                    </td>
                    <td className="px-3 py-3 text-right font-medium text-slate-700">{margin}</td>
                    <td className="px-3 py-3">
                      <label className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={r.saleReady}
                          disabled={!isOwner || archived}
                          onChange={(e) =>
                            updateRow(p.sku_code, (rs) => ({ ...rs, saleReady: e.target.checked, save: "idle" }))
                          }
                        />
                        <span>{r.saleReady ? "Yes" : "No"}</span>
                      </label>
                    </td>
                    <td className="px-3 py-3 text-xs">
                      <div className="flex min-w-[118px] flex-col items-start gap-1.5">
                        <div>
                          {r.save === "saving" && <span className="text-slate-500">Saving…</span>}
                          {r.save === "saved" && <span className="text-green-600">Saved ✓</span>}
                          {r.save === "error" && <span className="text-red-600" title={r.error}>Error</span>}
                          {r.save === "idle" && p.retail_price && <span className="text-slate-400">—</span>}
                        </div>
                        {canPublishPrice && p.nec_plu && !archived && (
                          <button
                            onClick={() => void publishRow(p.sku_code)}
                            disabled={
                              r.publish === "publishing" ||
                              !Number.isFinite(priceNum) ||
                              priceNum <= 0
                            }
                            className={
                              posState === "live"
                                ? "rounded-md border border-slate-300 px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
                                : "rounded-md bg-amber-500 px-2 py-1 text-[11px] font-semibold text-white hover:bg-amber-600 disabled:cursor-not-allowed disabled:bg-slate-300"
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
                        {!canPublishPrice && isOwner && p.nec_plu && !archived && (
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
                  {isRowExpanded && (
                    <tr className="bg-slate-50/70">
                      <td colSpan={8} className="px-4 py-3">
                        <div className="grid gap-3 text-xs text-slate-600 lg:grid-cols-[1.3fr_1fr_1.2fr_1fr]">
                          <div>
                            <div className="font-semibold uppercase text-slate-400">Item name</div>
                            <input
                              type="text"
                              value={r.draftDescription}
                              onChange={(e) => updateRow(p.sku_code, (rs) => ({ ...rs, draftDescription: e.target.value, save: "idle" }))}
                              disabled={!isOwner || archived}
                              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500"
                            />
                            <div className="mt-1 text-[11px] text-slate-400">
                              Names must be unique across the master catalogue.
                            </div>
                          </div>
                          <div>
                            <div className="font-semibold uppercase text-slate-400">Barcode</div>
                            <div className="mt-1 rounded-lg border border-slate-200 bg-white px-2 py-1.5">
                              <div className="font-mono text-base font-semibold text-slate-900">{p.nec_plu || p.plu_code || "—"}</div>
                              <div className="mt-0.5 text-[11px] text-slate-500">EAN-8 PLU, unique at write time</div>
                            </div>
                            <div className="mt-2 font-semibold uppercase text-slate-400">SKU</div>
                            <div className="mt-1 font-mono text-slate-700">{p.sku_code}</div>
                            <div className="text-[11px] text-slate-500">
                              {skuParts
                                ? `${skuParts.typeCode} / ${skuParts.materialCode} / seq ${skuParts.sequence}`
                                : "Legacy or non-standard SKU"}
                            </div>
                          </div>
                          <div>
                            <div className="font-semibold uppercase text-slate-400">Inventory state</div>
                            <div className="mt-1 font-medium text-slate-800">{inventoryStateLabel(p)}</div>
                            <div className="mt-2 flex flex-wrap gap-1.5 rounded-lg border border-slate-200 bg-white p-2">
                              {CANONICAL_LOCATION_OPTIONS.map((loc) => {
                                const selectedLocations = parseStockingLocation(r.draftLocation);
                                return (
                                  <label key={loc.value} className="flex items-center gap-1 rounded bg-slate-50 px-2 py-1 text-[11px] text-slate-700">
                                    <input
                                      type="checkbox"
                                      checked={selectedLocations.includes(loc.value)}
                                      onChange={(e) => {
                                        const next = e.target.checked
                                          ? [...selectedLocations, loc.value]
                                          : selectedLocations.filter((value) => value !== loc.value);
                                        updateRow(p.sku_code, (rs) => ({
                                          ...rs,
                                          draftLocation: encodeStockingLocation(next),
                                          save: "idle",
                                        }));
                                      }}
                                      disabled={!isOwner || archived}
                                    />
                                    {loc.label}
                                  </label>
                                );
                              })}
                            </div>
                            <label className="mt-2 block">
                              <span className="font-semibold uppercase text-slate-400">Qty on hand</span>
                              <input
                                type="number"
                                min={0}
                                step="0.01"
                                value={r.draftQty}
                                onChange={(e) => updateRow(p.sku_code, (rs) => ({ ...rs, draftQty: e.target.value, save: "idle" }))}
                                disabled={!isOwner || archived}
                                className="mt-1 w-28 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500"
                              />
                            </label>
                          </div>
                          <div>
                            <div className="font-semibold uppercase text-slate-400">Source</div>
                            <div className="mt-1">
                              {p.sourcing_strategy === "supplier_premade"
                                ? "Supplier"
                                : p.sourcing_strategy?.startsWith("manufactured")
                                  ? "Manufactured"
                                  : (p.sourcing_strategy || "—")}
                            </div>
                            <div>{p.supplier_name || p.supplier_id || "—"}</div>
                            <div className="mt-1">Supplier code {p.supplier_item_code || p.internal_code || "—"}</div>
                            <label className="mt-3 block">
                              <span className="font-semibold uppercase text-slate-400">Notes</span>
                              <input
                                type="text"
                                value={r.draftNotes}
                                onChange={(e) => updateRow(p.sku_code, (rs) => ({ ...rs, draftNotes: e.target.value, save: "idle" }))}
                                disabled={!isOwner || archived}
                                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500"
                              />
                            </label>
                            {isOwner && (
                              <div className="mt-3 flex flex-wrap gap-2">
                                {!archived && (
                                  <button
                                    type="button"
                                    onClick={() => void saveRowDetails(p.sku_code)}
                                    className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
                                  >
                                    Save details
                                  </button>
                                )}
                                {archived ? (
                                  <button
                                    type="button"
                                    onClick={() => void restoreRow(p.sku_code)}
                                    className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-emerald-100"
                                  >
                                    Restore item
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    onClick={() => void archiveRow(p.sku_code)}
                                    className="rounded-md border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-50"
                                  >
                                    Archive item
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                          {archived && <span className="rounded bg-slate-200 px-1.5 py-0.5 text-slate-700">Archived {p.archived_at ? relativeTime(Date.parse(p.archived_at)) : ""}</span>}
                          {posState === "live" && <span className="rounded bg-green-100 px-1.5 py-0.5 text-green-800">Live POS</span>}
                          {posState === "no-price" && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-800" title="In Firestore plus collection but no current price doc">POS no price</span>}
                          {posState === "missing" && <span className="text-slate-400">Not live in POS</span>}
                          {r.save === "saving" && <span className="text-slate-500">Saving…</span>}
                          {r.save === "saved" && <span className="text-green-700">Details saved</span>}
                          {r.save === "error" && <span className="text-red-700">{r.error}</span>}
                        </div>
                      </td>
                    </tr>
                  )}
                  {isExpanded && siblings.map((sib) => {
                    const sibImage = masterDataAssetUrl(sib.thumbnail_url || sib.image_urls?.[0]);
                    return (
                      <tr key={sib.sku_code} className="bg-teal-50/40 text-xs">
                        <td className="px-3 py-2" />
                        <td colSpan={7} className="px-3 py-3">
                          <div className="flex items-center gap-3">
                            {sibImage ? (
                              <button type="button" onClick={() => setLightboxImage(sibImage)} className="block shrink-0">
                                <img src={sibImage} loading="lazy" alt="" className="h-9 w-9 rounded object-cover" />
                              </button>
                            ) : <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-white text-slate-300">—</span>}
                            <div className="min-w-0 flex-1">
                              <div className="truncate font-semibold text-slate-700" title={sib.description ?? ""}>
                                {sib.variant_label && <span className="mr-2 rounded bg-teal-100 px-1.5 py-0.5 text-[11px] text-teal-800">{sib.variant_label}</span>}
                                {sib.description || sib.sku_code}
                              </div>
                              <div className="mt-0.5 flex flex-wrap gap-2 text-slate-500">
                                <span className="font-mono">{sib.sku_code}</span>
                                <span>{formatStockingLocation(sib.stocking_location)}</span>
                                <span>{formatMaterialSummary(sib)}</span>
                                <span>S${fmtMoney(sib.cost_price)} cost</span>
                                <span>S${fmtMoney(sib.retail_price)} retail</span>
                                <span>{marginPct(sib.cost_price, sib.retail_price)} margin</span>
                                <span>{sib.sale_ready ? "Ready" : "Not ready"}</span>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-xs text-gray-500">
          Tip: Tab between price cells to enter a column at a time. Edits autosave on blur or Enter. The placeholder
          retail price is a 60% target margin (cost ÷ 0.4 rounded to S$5) — overwrite as needed.
        </p>
          </>
        ) : (
          <MasterDataEmbeddedTool
            tool={activeTool}
            stats={stats}
            posStatus={posStatus}
            onSelectTool={setActiveTool}
          />
        )}
      </div>

      {isOwner && activeTool === "pricing" && selected.size > 0 && (
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

      {lightboxImage && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/75 p-4" onClick={() => setLightboxImage(null)}>
          <img src={lightboxImage} alt="" className="max-h-[90vh] max-w-[90vw] rounded-md bg-white object-contain" />
        </div>
      )}

    </div>
  );
}

function MasterDataEmbeddedTool({
  tool,
  stats,
  posStatus,
  onSelectTool,
}: {
  tool: MasterDataTool;
  stats: Stats | null;
  posStatus: PosStatusResponse | null;
  onSelectTool: (tool: MasterDataTool) => void;
}) {
  const title = tool === "vault" ? "Staging Vault" : "POS Readiness";
  const detail =
    tool === "vault"
      ? "OCR staging, review, and approve without leaving Master Data."
      : "Pre-flight the master catalogue before labels, pricing, and NEC export.";
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex flex-col gap-3 border-b border-slate-200 bg-slate-50/70 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Master data tool</div>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">{title}</h2>
          <p className="mt-1 text-sm text-slate-500">{detail}</p>
        </div>
        <button
          type="button"
          onClick={() => onSelectTool("pricing")}
          className="inline-flex min-h-10 items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
        >
          Back to pricing
        </button>
      </header>
      <div className="p-4">
        <Suspense fallback={<EmbeddedToolLoading />}>
          {tool === "vault" ? (
            <EmbeddedVaultPage embedded />
          ) : (
            <EmbeddedPosReadinessPage
              embedded
              masterStats={stats}
              masterPosStatus={posStatus}
            />
          )}
        </Suspense>
      </div>
    </section>
  );
}

function EmbeddedToolLoading() {
  return (
    <div className="grid gap-3">
      <div className="h-16 animate-pulse rounded-xl bg-slate-100" />
      <div className="h-44 animate-pulse rounded-xl bg-slate-100" />
    </div>
  );
}

function isArchivedProduct(product: ProductRow): boolean {
  return normaliseIdentity(product.status) === "archived";
}

function inventoryBucketsForProduct(product: ProductRow): InventoryBucket[] {
  const apiBuckets = (product.inventory_buckets || [])
    .filter((bucket): bucket is InventoryBucket => (
      bucket === "store" ||
      bucket === "warehouse" ||
      bucket === "on_order" ||
      bucket === "supplier_catalog"
    ));
  if (apiBuckets.length > 0) return apiBuckets;

  const locations = parseStockingLocation(product.stocking_location);
  const buckets: InventoryBucket[] = [];
  if (locations.some((loc) => STORE_LOCATION_VALUES.has(loc))) buckets.push("store");
  if (locations.includes("breeze")) buckets.push("warehouse");
  const status = normaliseIdentity(product.stocking_status).replace(/[^a-z0-9]/g, "");
  const onOrderQty = Number(product.qty_on_order ?? product.on_order_qty ?? 0);
  if (status === "onorder" || status === "incoming" || onOrderQty > 0) {
    buckets.push("on_order");
  }
  const qty = Number(product.qty_on_hand ?? 0);
  if (
    buckets.length === 0 &&
    (product.inventory_type === "catalog" || (product.supplier_item_code && qty <= 0))
  ) {
    buckets.push("supplier_catalog");
  }
  return buckets.length > 0 ? buckets : ["supplier_catalog"];
}

function inventoryStateLabel(product: ProductRow): string {
  if (isArchivedProduct(product)) return "Archived";
  if (product.inventory_state_label) return product.inventory_state_label;
  const buckets = inventoryBucketsForProduct(product);
  if (buckets.includes("on_order")) return "On order";
  if (buckets.includes("store") && buckets.includes("warehouse")) return "Store + warehouse";
  if (buckets.includes("store")) return "In store";
  if (buckets.includes("warehouse")) return "In warehouse";
  return "Supplier catalog";
}

function buildInventorySummary(products: ProductRow[]): Record<InventoryBucket, number> {
  const summary: Record<InventoryBucket, number> = {
    store: 0,
    warehouse: 0,
    on_order: 0,
    supplier_catalog: 0,
  };
  for (const product of products) {
    if (isArchivedProduct(product)) continue;
    for (const bucket of inventoryBucketsForProduct(product)) {
      summary[bucket] += 1;
    }
  }
  return summary;
}

interface DataIntegritySummary {
  duplicateNameGroups: number;
  duplicateBarcodeGroups: number;
  duplicateSkuGroups: number;
  skuWarnings: Map<string, string[]>;
  nameKeyToProducts: Map<string, ProductRow[]>;
}

function groupedBy(
  products: ProductRow[],
  getValue: (product: ProductRow) => string | null | undefined,
): Map<string, ProductRow[]> {
  const groups = new Map<string, ProductRow[]>();
  for (const product of products) {
    const key = getValue(product);
    if (!key) continue;
    const list = groups.get(key) || [];
    list.push(product);
    groups.set(key, list);
  }
  return groups;
}

function buildDataIntegrity(products: ProductRow[]): DataIntegritySummary {
  const nameKeyToProducts = groupedBy(products, (product) => normaliseIdentity(product.description));
  const barcodeGroups = groupedBy(products, (product) => normaliseCode(product.nec_plu || product.plu_code));
  const skuGroups = groupedBy(products, (product) => normaliseCode(product.sku_code));
  const skuWarnings = new Map<string, string[]>();

  const mark = (group: ProductRow[], warning: string) => {
    if (group.length <= 1) return;
    for (const product of group) {
      const existing = skuWarnings.get(product.sku_code) || [];
      skuWarnings.set(product.sku_code, [...existing, warning]);
    }
  };
  for (const group of nameKeyToProducts.values()) mark(group, "Duplicate name");
  for (const group of barcodeGroups.values()) mark(group, "Duplicate barcode");
  for (const group of skuGroups.values()) mark(group, "Duplicate SKU");

  return {
    duplicateNameGroups: Array.from(nameKeyToProducts.values()).filter((group) => group.length > 1).length,
    duplicateBarcodeGroups: Array.from(barcodeGroups.values()).filter((group) => group.length > 1).length,
    duplicateSkuGroups: Array.from(skuGroups.values()).filter((group) => group.length > 1).length,
    skuWarnings,
    nameKeyToProducts,
  };
}

function parseSkuAnatomy(skuCode: string | null | undefined): {
  typeCode: string;
  materialCode: string;
  sequence: number;
} | null {
  const match = /^VE([A-Z0-9]{3})([A-Z0-9]{4})(\d{7})$/i.exec(skuCode || "");
  if (!match) return null;
  return {
    typeCode: match[1].toUpperCase(),
    materialCode: match[2].toUpperCase(),
    sequence: Number.parseInt(match[3], 10),
  };
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

function AttentionMetric({
  label,
  value,
  detail,
  tone: status,
  active = false,
  onClick,
}: {
  label: string;
  value: number;
  detail: string;
  tone?: "good" | "warn";
  active?: boolean;
  onClick?: () => void;
}) {
  const valueTone =
    status === "good"
      ? "text-green-700"
      : status === "warn"
      ? "text-amber-700"
      : "text-slate-900";
  const borderTone =
    active
      ? "border-slate-950 bg-slate-950 text-white shadow-sm"
      : valueTone === "text-green-700"
      ? "border-green-200 bg-green-50/60 hover:bg-green-50"
      : valueTone === "text-amber-700"
      ? "border-amber-200 bg-amber-50/70 hover:bg-amber-50"
      : "border-slate-200 bg-slate-50/70 hover:bg-slate-50";
  const content = (
    <>
      <div className={`truncate text-[10px] font-semibold uppercase tracking-wide sm:text-[11px] ${active ? "text-white/70" : "text-slate-500"}`}>{label}</div>
      <div className={`mt-0.5 text-xl font-semibold leading-none sm:text-2xl ${active ? "text-white" : valueTone}`}>{value}</div>
      <div className={`mt-1 truncate text-[11px] sm:text-xs ${active ? "text-white/70" : "text-slate-500"}`}>{detail}</div>
    </>
  );
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={`min-w-0 rounded-md border px-2 py-2 text-left transition sm:px-3 ${borderTone}`}
      >
        {content}
      </button>
    );
  }
  return (
    <div className={`min-w-0 rounded-md border px-2 py-2 text-left transition sm:px-3 ${borderTone}`}>
      {content}
    </div>
  );
}

function IntegrityPill({
  label,
  value,
  noun,
}: {
  label: string;
  value: number;
  noun: string;
}) {
  const ok = value === 0;
  return (
    <span
      className={`rounded-full border px-2 py-0.5 font-semibold ${
        ok
          ? "border-emerald-200 bg-emerald-50 text-emerald-800"
          : "border-red-200 bg-red-50 text-red-700"
      }`}
    >
      {label}: {ok ? "unique" : `${value} ${noun}${value === 1 ? "" : "s"}`}
    </span>
  );
}
