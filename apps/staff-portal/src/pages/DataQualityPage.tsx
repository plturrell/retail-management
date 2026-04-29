import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE_URL, api } from "../lib/api";
import type {
  DataQualityResponse,
  FilterMode,
  Product,
  ProductCorrection,
  ReferenceData,
} from "../lib/data-quality-types";
import { auth } from "../lib/firebase";

/* ───────────────── NEC preview types ───────────────── */

interface NecPreviewIssue {
  sku_code: string;
  field: string;
  severity: "error" | "warning";
  message: string;
}

interface PluBulkPlanRow {
  sku_id: string;
  sku_code: string;
  description: string;
  old_plu: string | null;
  new_plu: string;
  reason: "missing" | "invalid" | "misaligned";
}

interface PluBulkPlan {
  applied: boolean;
  summary: Record<string, number>;
  plan: PluBulkPlanRow[];
  plan_total: number;
}

interface NecPreview {
  sellable_count: number;
  excluded_count: number;
  counts: Record<string, number>;
  tenant_code: string;
  nec_store_id: string;
  taxable: boolean;
  is_ready: boolean;
  errors: NecPreviewIssue[];
  warnings: NecPreviewIssue[];
  excluded_summary: Record<string, number>;
}

/* ───────────────── helpers ───────────────── */

function badge(severity: "error" | "warning") {
  return severity === "error"
    ? "inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700"
    : "inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-700";
}

/* Catalogue pillars — mirrors CAG_CATG_MAP in tools/scripts/export_nec_jewel.py */
const HOMEWARE_TYPES = new Set([
  "Figurine", "Sculpture", "Bookend", "Bowl", "Vase", "Box", "Tray",
  "Decorative Object", "Wall Art", "Gift Set", "Repair Service",
]);
const JEWELLERY_TYPES = new Set([
  "Bracelet", "Necklace", "Ring", "Earring", "Charm", "Pendant",
  "Bead Strand", "Accessory",
]);
const MINERALS_TYPES = new Set([
  "Loose Gemstone", "Raw Specimen", "Crystal Cluster", "Crystal Point",
  "Tumbled Stone", "Gemstone Bead", "Healing Crystal",
]);

function catLabel(cat: string) {
  const map: Record<string, string> = {
    finished_for_sale: "Finished (NEC POS)",
    catalog_to_stock: "Catalog (Purchase)",
    material: "Material",
    store_operations: "Store Ops",
  };
  return map[cat] ?? cat;
}

function stockBadge(status: string) {
  switch (status) {
    case "in_stock":
      return "bg-green-100 text-green-700";
    case "to_order":
      return "bg-blue-100 text-blue-700";
    case "not_stocked":
      return "bg-gray-100 text-gray-500";
    case "to_manufacture":
      return "bg-purple-100 text-purple-700";
    default:
      return "bg-gray-100 text-gray-500";
  }
}

/* ───────────────── Stat Card ───────────────── */

function StatCard({ label, value, sub, accent }: { label: string; value: number | string; sub?: string; accent?: string }) {
  return (
    <div className={`rounded-xl border px-4 py-3 ${accent ?? "border-gray-200 bg-white"}`}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-1 text-2xl font-bold text-gray-800">{value}</p>
      {sub && <p className="text-xs text-gray-500">{sub}</p>}
    </div>
  );
}

/* ───────────────── Inline Select ───────────────── */

function InlineSelect({
  value,
  options,
  onChange,
  className = "",
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`w-full rounded border border-gray-200 bg-white px-1.5 py-1 text-xs focus:border-blue-400 focus:outline-none ${className}`}
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

/* ───────────────── Inline Text ───────────────── */

function InlineText({
  value,
  onChange,
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  className?: string;
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`w-full rounded border border-gray-200 bg-white px-1.5 py-1 text-xs focus:border-blue-400 focus:outline-none ${className}`}
    />
  );
}

/* ───────────────── Product Row ───────────────── */

function ProductRow({
  product,
  reference,
  isEditing,
  draft,
  onStartEdit,
  onDraftChange,
  onSave,
  onCancel,
}: {
  product: Product;
  reference: ReferenceData;
  isEditing: boolean;
  draft: Partial<Product> | null;
  onStartEdit: () => void;
  onDraftChange: (field: string, value: string | boolean | number | null) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const p = product;
  const issues = p._quality_issues ?? [];
  const hasErrors = issues.some((i) => i.severity === "error");
  const hasWarnings = issues.some((i) => i.severity === "warning");

  const rowBg = hasErrors
    ? "bg-red-50/50"
    : hasWarnings
      ? "bg-amber-50/40"
      : "";

  if (isEditing && draft) {
    return (
      <tr className="bg-blue-50/60">
        <td className="px-2 py-2 text-xs text-gray-400">{p.id.slice(0, 8)}</td>
        <td className="px-2 py-2">
          <InlineText value={draft.description ?? p.description} onChange={(v) => onDraftChange("description", v)} />
        </td>
        <td className="px-2 py-2">
          <InlineText value={draft.material ?? p.material} onChange={(v) => onDraftChange("material", v)} />
        </td>
        <td className="px-2 py-2">
          <InlineSelect value={draft.product_type ?? p.product_type} options={reference.product_types} onChange={(v) => onDraftChange("product_type", v)} />
        </td>
        <td className="px-2 py-2">
          <InlineSelect value={draft.inventory_category ?? p.inventory_category} options={reference.inventory_categories} onChange={(v) => onDraftChange("inventory_category", v)} />
        </td>
        <td className="px-2 py-2">
          <InlineSelect value={draft.stocking_status ?? p.stocking_status} options={reference.stocking_statuses} onChange={(v) => onDraftChange("stocking_status", v)} />
        </td>
        <td className="px-2 py-2">
          <InlineSelect
            value={draft.stocking_location ?? p.stocking_location ?? ""}
            options={["", ...reference.stocking_locations]}
            onChange={(v) => onDraftChange("stocking_location", v)}
          />
        </td>
        <td className="px-2 py-2 text-center">
          <input
            type="checkbox"
            checked={draft.sale_ready ?? p.sale_ready}
            onChange={(e) => onDraftChange("sale_ready", e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600"
          />
        </td>
        <td className="px-2 py-2">
          <input
            type="number"
            value={draft.cost_price ?? p.cost_price ?? ""}
            onChange={(e) => onDraftChange("cost_price", e.target.value ? Number(e.target.value) : null)}
            className="w-20 rounded border border-gray-200 bg-white px-1.5 py-1 text-xs"
          />
        </td>
        <td className="px-2 py-2">
          <input
            type="number"
            step="0.01"
            value={draft.retail_price ?? p.retail_price ?? ""}
            onChange={(e) => onDraftChange("retail_price", e.target.value ? Number(e.target.value) : null)}
            className="w-20 rounded border border-blue-300 bg-white px-1.5 py-1 text-xs font-semibold focus:border-blue-500 focus:outline-none"
            placeholder="SGD"
          />
        </td>
        <td className="px-2 py-2">
          <div className="flex gap-1">
            <button onClick={onSave} className="rounded bg-blue-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-blue-700">
              Save
            </button>
            <button onClick={onCancel} className="rounded bg-gray-200 px-2 py-1 text-[11px] font-semibold text-gray-600 hover:bg-gray-300">
              Cancel
            </button>
          </div>
        </td>
      </tr>
    );
  }

  return (
    <tr className={`border-b border-gray-100 hover:bg-gray-50/80 ${rowBg}`}>
      <td className="px-2 py-2 text-xs text-gray-400 font-mono">{p.id.slice(0, 8)}</td>
      <td className="px-2 py-2">
        <div className="text-xs font-medium text-gray-800 max-w-[200px] truncate" title={p.description}>
          {p.description}
        </div>
        {p.internal_code && <div className="text-[10px] text-gray-400 font-mono">{p.internal_code}</div>}
      </td>
      <td className="px-2 py-2 text-xs text-gray-600">{p.material || <span className="text-gray-300">—</span>}</td>
      <td className="px-2 py-2 text-xs text-gray-600">{p.product_type}</td>
      <td className="px-2 py-2">
        <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
          {catLabel(p.inventory_category)}
        </span>
      </td>
      <td className="px-2 py-2">
        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${stockBadge(p.stocking_status)}`}>
          {p.stocking_status || "—"}
        </span>
      </td>
      <td className="px-2 py-2 text-xs text-gray-500">{p.stocking_location || <span className="text-gray-300">—</span>}</td>
      <td className="px-2 py-2 text-center">
        {p.sale_ready ? (
          <span className="inline-block h-4 w-4 rounded-full bg-green-500 text-white text-[10px] leading-4 text-center">&#10003;</span>
        ) : (
          <span className="inline-block h-4 w-4 rounded-full bg-gray-200" />
        )}
      </td>
      <td className="px-2 py-2 text-xs text-gray-600 text-right font-mono">
        {p.cost_price != null ? `$${p.cost_price.toFixed(0)}` : <span className="text-gray-300">—</span>}
      </td>
      <td className="px-2 py-2 text-xs text-right font-mono">
        {p.retail_price != null ? (
          <span className="font-semibold text-blue-700">${p.retail_price.toFixed(0)}</span>
        ) : (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">NEED PRICE</span>
        )}
      </td>
      <td className="px-2 py-2">
        <div className="flex items-center gap-1">
          {issues.map((iss, idx) => (
            <span key={idx} className={badge(iss.severity)} title={`${iss.field}: ${iss.message}`}>
              {iss.severity === "error" ? "!" : "?"}
            </span>
          ))}
          <button
            onClick={onStartEdit}
            className="ml-1 rounded bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600 hover:bg-blue-100 hover:text-blue-700"
          >
            Edit
          </button>
        </div>
      </td>
    </tr>
  );
}

/* ───────────────── Main Page ───────────────── */

const PAGE_SIZE = 50;

export default function DataQualityPage() {
  const [data, setData] = useState<DataQualityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<FilterMode>("all");
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<Product> | null>(null);
  const [saving, setSaving] = useState(false);
  // Discriminated so the banner can render success vs. failure distinctly —
  // every call site below sets `kind` explicitly.
  const [saveMsg, setSaveMsg] = useState<{ text: string; kind: "success" | "error" } | null>(null);
  const [page, setPage] = useState(0);
  const [pendingCorrections, setPendingCorrections] = useState<Map<string, ProductCorrection>>(new Map());
  // Pending retail_price changes are tracked separately because they persist
  // to Postgres via /data-quality/prices/bulk (the corrections endpoint only
  // rewrites the JSON master list, which the NEC exporter no longer reads).
  const [pendingPrices, setPendingPrices] = useState<Map<string, { sku_code: string; legacy_code: string; retail_price: number }>>(new Map());
  const [savingPrices, setSavingPrices] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportingTxt, setExportingTxt] = useState(false);
  const [pushingSftp, setPushingSftp] = useState(false);
  const [cagStoreId, setCagStoreId] = useState<string>(() => localStorage.getItem("cag_nec_store_id") ?? "");
  const [cagAirside, setCagAirside] = useState<boolean>(() => localStorage.getItem("cag_nec_airside") === "1");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [preview, setPreview] = useState<NecPreview | null>(null);
  const [pluPlan, setPluPlan] = useState<PluBulkPlan | null>(null);
  const [pluLoading, setPluLoading] = useState(false);
  const [pluApplying, setPluApplying] = useState(false);
  const tableRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get<DataQualityResponse>("/data-quality/products");
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  /* Filter + search */
  const filtered = useMemo(() => {
    if (!data) return [];
    let list = data.products;
    const q = search.toLowerCase().trim();
    if (q) {
      list = list.filter(
        (p) =>
          p.description.toLowerCase().includes(q) ||
          p.material.toLowerCase().includes(q) ||
          p.product_type.toLowerCase().includes(q) ||
          p.internal_code.toLowerCase().includes(q) ||
          p.sku_code.toLowerCase().includes(q),
      );
    }
    switch (filter) {
      case "errors":
        list = list.filter((p) => p._quality_issues.some((i) => i.severity === "error"));
        break;
      case "warnings":
        list = list.filter((p) => p._quality_issues.some((i) => i.severity === "warning"));
        break;
      case "clean":
        list = list.filter((p) => p._issue_count === 0);
        break;
      case "finished_for_sale":
      case "catalog_to_stock":
      case "material":
      case "store_operations":
        list = list.filter((p) => p.inventory_category === filter);
        break;
      case "sale_ready":
        list = list.filter((p) => p.sale_ready);
        break;
      case "not_stocked":
        list = list.filter((p) => p.stocking_status === "not_stocked");
        break;
      case "missing_price":
        list = list.filter((p) => p.retail_price == null);
        break;
      case "homeware":
        list = list.filter((p) => HOMEWARE_TYPES.has(p.product_type));
        break;
      case "jewellery":
        list = list.filter((p) => JEWELLERY_TYPES.has(p.product_type));
        break;
      case "minerals":
        list = list.filter((p) => MINERALS_TYPES.has(p.product_type));
        break;
    }
    return list;
  }, [data, filter, search]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const pageProducts = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  useEffect(() => { setPage(0); }, [filter, search]);

  /* Editing */
  const startEdit = (p: Product) => {
    setEditingId(p.id);
    setDraft({
      description: p.description,
      material: p.material,
      product_type: p.product_type,
      inventory_category: p.inventory_category,
      stocking_status: p.stocking_status,
      stocking_location: p.stocking_location,
      sale_ready: p.sale_ready,
      cost_price: p.cost_price,
      retail_price: p.retail_price,
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraft(null);
  };

  const saveSingleEdit = () => {
    if (!editingId || !draft) return;
    const product = data?.products.find((p) => p.id === editingId);

    // Split the draft: retail_price goes to /prices/bulk (Postgres),
    // everything else goes to /corrections (JSON master list).
    const correction: ProductCorrection = { id: editingId };
    let newRetailPrice: number | null | undefined = undefined;
    for (const [k, v] of Object.entries(draft)) {
      if (v === undefined) continue;
      if (k === "retail_price") {
        newRetailPrice = v as number | null;
      } else {
        correction[k] = v as string | number | boolean | null;
      }
    }

    // Stage the non-price corrections (keep existing behavior).
    if (Object.keys(correction).length > 1) {
      setPendingCorrections((prev) => {
        const next = new Map(prev);
        next.set(editingId, correction);
        return next;
      });
    }

    // Stage the price change separately if it actually changed.
    if (product && newRetailPrice !== undefined && newRetailPrice !== product.retail_price) {
      setPendingPrices((prev) => {
        const next = new Map(prev);
        if (newRetailPrice == null) {
          next.delete(editingId);
        } else {
          next.set(editingId, {
            sku_code: product.sku_code,
            legacy_code: product.internal_code,
            retail_price: newRetailPrice,
          });
        }
        return next;
      });
    }

    // Optimistically update local data
    if (data) {
      const products = data.products.map((p) => {
        if (p.id === editingId) {
          return { ...p, ...draft } as Product;
        }
        return p;
      });
      setData({ ...data, products });
    }
    setEditingId(null);
    setDraft(null);
  };

  /* Save retail prices to Postgres via /data-quality/prices/bulk.
     These are what the NEC exporter reads — only SKUs with a price row
     pass the sellability gate. */
  const savePrices = async () => {
    if (pendingPrices.size === 0) return;
    setSavingPrices(true);
    setSaveMsg(null);
    try {
      const prices = Array.from(pendingPrices.values()).map((p) => ({
        sku_code: p.sku_code || undefined,
        legacy_code: p.legacy_code || undefined,
        retail_price: p.retail_price,
      }));
      const res = await api.post<{ updated: number; created: number; not_found: string[]; message: string }>(
        "/data-quality/prices/bulk",
        { prices },
      );
      setSaveMsg({ text: res.message, kind: "success" });
      setPendingPrices(new Map());
    } catch (err) {
      setSaveMsg({ text: err instanceof Error ? err.message : "Price save failed", kind: "error" });
    } finally {
      setSavingPrices(false);
    }
  };

  /* Bulk save */
  const savePending = async () => {
    if (pendingCorrections.size === 0) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      const corrections = Array.from(pendingCorrections.values());
      const res = await api.post<{ applied: number; message: string }>("/data-quality/corrections", { corrections });
      setSaveMsg({ text: res.message, kind: "success" });
      setPendingCorrections(new Map());
      await load();
    } catch (err) {
      setSaveMsg({ text: err instanceof Error ? err.message : "Save failed", kind: "error" });
    } finally {
      setSaving(false);
    }
  };

  const downloadNecExport = async () => {
    setExporting(true);
    setSaveMsg("");
    try {
      const user = auth.currentUser;
      if (!user) throw new Error("Not authenticated");

      const token = await user.getIdToken();
      const res = await fetch(`${API_BASE_URL}/data-quality/exports/nec-jewel`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!res.ok) {
        const body = await res.text();
        throw new Error(`API ${res.status}: ${body}`);
      }

      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") ?? "";
      const filenameMatch = disposition.match(/filename="?([^"]+)"?/i);
      const filename = filenameMatch?.[1] ?? "nec_jewel_master_data.xlsx";
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
      setSaveMsg(`Downloaded ${filename}`);
    } catch (err) {
      setSaveMsg(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  const downloadCagTxtBundle = async () => {
    if (!cagStoreId.trim()) {
      setSaveMsg("Enter the 5-digit NEC Store ID before downloading the CAG TXT bundle");
      return;
    }
    localStorage.setItem("cag_nec_store_id", cagStoreId.trim());
    localStorage.setItem("cag_nec_airside", cagAirside ? "1" : "0");
    setExportingTxt(true);
    setSaveMsg("");
    try {
      const user = auth.currentUser;
      if (!user) throw new Error("Not authenticated");
      const token = await user.getIdToken();
      const params = new URLSearchParams({
        nec_store_id: cagStoreId.trim(),
        taxable: cagAirside ? "false" : "true",
      });
      const res = await fetch(`${API_BASE_URL}/cag/export/txt?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`API ${res.status}: ${body}`);
      }
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") ?? "";
      const counts = res.headers.get("X-Cag-File-Counts") ?? "";
      const m = disposition.match(/filename="?([^"]+)"?/i);
      const filename = m?.[1] ?? `cag_nec_master_${Date.now()}.zip`;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setSaveMsg(`Downloaded ${filename}${counts ? ` — ${counts}` : ""}`);
    } catch (err) {
      setSaveMsg(err instanceof Error ? err.message : "CAG TXT export failed");
    } finally {
      setExportingTxt(false);
    }
  };

  const previewPluPlan = async () => {
    setPluLoading(true);
    setSaveMsg("");
    try {
      const res = await api.get<PluBulkPlan>("/data-quality/plus/bulk-preview");
      setPluPlan(res);
    } catch (err) {
      setSaveMsg(err instanceof Error ? `PLU preview failed: ${err.message}` : "PLU preview failed");
    } finally {
      setPluLoading(false);
    }
  };

  const applyPluPlan = async () => {
    if (!pluPlan) return;
    if (
      !confirm(
        `Generate / repair ${pluPlan.summary.total} PLU code(s)?\n\n` +
          `• missing: ${pluPlan.summary.missing ?? 0}\n` +
          `• invalid: ${pluPlan.summary.invalid ?? 0}\n` +
          `• misaligned: ${pluPlan.summary.misaligned ?? 0}\n\n` +
          "This rewrites Firestore. Existing aligned PLUs are left untouched.",
      )
    )
      return;
    setPluApplying(true);
    try {
      const res = await api.post<PluBulkPlan>("/data-quality/plus/bulk-apply", {});
      setPluPlan(res);
      setSaveMsg(`PLU bulk-assign applied — ${res.summary.total ?? 0} row(s) updated.`);
      void load();
    } catch (err) {
      setSaveMsg(err instanceof Error ? `PLU apply failed: ${err.message}` : "PLU apply failed");
    } finally {
      setPluApplying(false);
    }
  };

  const runNecPreview = async () => {
    setPreviewLoading(true);
    setSaveMsg("");
    try {
      const params = new URLSearchParams({ taxable: cagAirside ? "false" : "true" });
      if (cagStoreId.trim()) params.set("nec_store_id", cagStoreId.trim());
      const res = await api.get<NecPreview>(`/cag/export/preview?${params.toString()}`);
      setPreview(res);
    } catch (err) {
      setSaveMsg(err instanceof Error ? `Preview failed: ${err.message}` : "Preview failed");
    } finally {
      setPreviewLoading(false);
    }
  };

  const pushCagBundleToSftp = async () => {
    if (!cagStoreId.trim()) {
      setSaveMsg("Enter the 5-digit NEC Store ID before pushing");
      return;
    }
    if (!confirm("Push the master TXT bundle to the CAG SFTP Inbound/Working folder?")) return;
    localStorage.setItem("cag_nec_store_id", cagStoreId.trim());
    localStorage.setItem("cag_nec_airside", cagAirside ? "1" : "0");
    setPushingSftp(true);
    setSaveMsg("");
    try {
      const user = auth.currentUser;
      if (!user) throw new Error("Not authenticated");
      const token = await user.getIdToken();
      const params = new URLSearchParams({
        nec_store_id: cagStoreId.trim(),
        taxable: cagAirside ? "false" : "true",
      });
      const res = await fetch(`${API_BASE_URL}/cag/export/push?${params.toString()}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail ?? `API ${res.status}`);
      const counts = Object.entries(body.counts ?? {})
        .map(([k, v]) => `${k}=${v}`)
        .join(", ");
      setSaveMsg(
        `SFTP push OK — ${body.files_uploaded.length} files, ${body.bytes_uploaded} bytes (${counts}).`,
      );
    } catch (err) {
      setSaveMsg(err instanceof Error ? `SFTP push failed: ${err.message}` : "SFTP push failed");
    } finally {
      setPushingSftp(false);
    }
  };

  /* Bulk actions */
  const bulkSetField = (field: string, value: string | boolean, matchFilter: (p: Product) => boolean) => {
    if (!data) return;
    const corrections = new Map(pendingCorrections);
    const products = data.products.map((p) => {
      if (!matchFilter(p)) return p;
      const existing = corrections.get(p.id) ?? { id: p.id };
      existing[field] = value;
      corrections.set(p.id, existing);
      return { ...p, [field]: value } as Product;
    });
    setPendingCorrections(corrections);
    setData({ ...data, products });
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
        <p className="text-sm font-semibold text-red-700">Failed to load data</p>
        <p className="mt-1 text-xs text-red-500">{error}</p>
        <button onClick={load} className="mt-3 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700">
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const { quality_summary: qs, reference: ref } = data;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Data Quality Review</h1>
          <p className="text-xs text-gray-500">
            Master product list — {data.total_products} products — generated {data.generated_at}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {pendingPrices.size > 0 && (
            <span className="rounded-full bg-blue-100 px-2.5 py-1 text-xs font-semibold text-blue-700">
              {pendingPrices.size} price{pendingPrices.size === 1 ? "" : "s"} pending
            </span>
          )}
          {pendingCorrections.size > 0 && (
            <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700">
              {pendingCorrections.size} correction{pendingCorrections.size === 1 ? "" : "s"}
            </span>
          )}
          <button
            onClick={savePrices}
            disabled={pendingPrices.size === 0 || savingPrices}
            title="Write retail prices to Postgres — makes them available to the NEC POS export"
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {savingPrices ? "Saving prices..." : `Save Prices (${pendingPrices.size})`}
          </button>
          <button
            onClick={savePending}
            disabled={pendingCorrections.size === 0 || saving}
            className="rounded-lg bg-gray-700 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Corrections"}
          </button>
          <button
            onClick={downloadNecExport}
            disabled={exporting}
            title="Generate the live Jewel NEC POS workbook (Excel artefact)"
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {exporting ? "Exporting..." : "Download NEC Excel"}
          </button>
          <div className="flex items-center gap-1 rounded-lg border border-emerald-300 bg-emerald-50 px-2 py-1">
            <input
              type="text"
              inputMode="numeric"
              value={cagStoreId}
              onChange={(e) => setCagStoreId(e.target.value)}
              placeholder="NEC Store ID"
              title="5-digit NEC-assigned Store ID (e.g. 80001)"
              className="w-28 rounded border border-emerald-200 bg-white px-2 py-1 text-xs"
            />
            <label className="flex items-center gap-1 text-[11px] text-emerald-800" title="Airside stores price tax-exclusive">
              <input
                type="checkbox"
                checked={cagAirside}
                onChange={(e) => setCagAirside(e.target.checked)}
              />
              airside
            </label>
            <button
              onClick={runNecPreview}
              disabled={previewLoading}
              title="Dry-run the export: counts + spec violations without writing any files"
              className="rounded bg-blue-600 px-2 py-1 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {previewLoading ? "Checking..." : "Preview"}
            </button>
            <button
              onClick={downloadCagTxtBundle}
              disabled={exportingTxt}
              title="Build the spec-compliant 6-file TXT bundle (CATG/SKU/PLU/PRICE/INVDETAILS/PROMO) as ZIP"
              className="rounded bg-emerald-700 px-2 py-1 text-xs font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
            >
              {exportingTxt ? "Building..." : "TXT (.zip)"}
            </button>
            <button
              onClick={pushCagBundleToSftp}
              disabled={pushingSftp}
              title="Upload the bundle to CAG SFTP Inbound/Working/<tenant>/"
              className="rounded bg-emerald-900 px-2 py-1 text-xs font-semibold text-white hover:bg-black disabled:opacity-50"
            >
              {pushingSftp ? "Pushing..." : "Push SFTP"}
            </button>
          </div>
          <button
            onClick={previewPluPlan}
            disabled={pluLoading}
            title="Find SKUs with missing / invalid / misaligned NEC EAN-13 PLU barcodes"
            className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {pluLoading ? "Scanning..." : "Fix PLUs"}
          </button>
          <button onClick={load} className="rounded-lg bg-gray-100 px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-200">
            Refresh
          </button>
        </div>
      </div>

      {saveMsg && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">{saveMsg}</div>
      )}

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-3xl overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="flex items-start justify-between border-b border-gray-200 bg-gray-50 px-5 py-3">
              <div>
                <h3 className="text-base font-semibold text-gray-800">NEC export pre-flight</h3>
                <p className="text-xs text-gray-500">
                  Tenant <code>{preview.tenant_code}</code> · Store <code>{preview.nec_store_id}</code> ·{" "}
                  {preview.taxable ? "Landside (G — taxable)" : "Airside (N — non-taxable)"}
                </p>
              </div>
              <button
                onClick={() => setPreview(null)}
                className="rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-700"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <div className="max-h-[70vh] space-y-4 overflow-y-auto px-5 py-4">
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={
                    preview.is_ready
                      ? "rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700"
                      : "rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-700"
                  }
                >
                  {preview.is_ready ? "READY TO PUSH" : "NOT READY"}
                </span>
                <span className="text-xs text-gray-600">
                  {preview.sellable_count} sellable · {preview.excluded_count} excluded
                </span>
                {preview.errors.length > 0 && (
                  <span className="text-xs font-semibold text-red-700">{preview.errors.length} error(s)</span>
                )}
                {preview.warnings.length > 0 && (
                  <span className="text-xs font-semibold text-amber-700">
                    {preview.warnings.length} warning(s)
                  </span>
                )}
              </div>

              <section>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Row counts (per file)
                </h4>
                <div className="grid grid-cols-3 gap-2 text-xs sm:grid-cols-6">
                  {Object.entries(preview.counts).map(([k, v]) => (
                    <div key={k} className="rounded border border-gray-200 bg-gray-50 px-3 py-2">
                      <div className="text-[11px] uppercase text-gray-500">{k}</div>
                      <div className="text-sm font-semibold text-gray-800">{v}</div>
                    </div>
                  ))}
                </div>
              </section>

              {Object.keys(preview.excluded_summary).length > 0 && (
                <section>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Excluded items by reason
                  </h4>
                  <ul className="space-y-1 text-xs text-gray-700">
                    {Object.entries(preview.excluded_summary).map(([k, v]) => (
                      <li key={k}>
                        <span className="font-mono text-[11px] text-gray-500">{k}</span> — {v}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {preview.errors.length > 0 && (
                <section>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-red-600">
                    Errors (must fix before push)
                  </h4>
                  <IssueTable issues={preview.errors} />
                </section>
              )}

              {preview.warnings.length > 0 && (
                <section>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-600">
                    Warnings (push will succeed but data may be truncated/odd)
                  </h4>
                  <IssueTable issues={preview.warnings} />
                </section>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-gray-200 bg-gray-50 px-5 py-3">
              <button
                onClick={() => setPreview(null)}
                className="rounded-lg bg-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-300"
              >
                Close
              </button>
              <button
                onClick={() => {
                  setPreview(null);
                  void pushCagBundleToSftp();
                }}
                disabled={!preview.is_ready}
                className="rounded-lg bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-800 disabled:opacity-40"
              >
                Push to SFTP
              </button>
            </div>
          </div>
        </div>
      )}

      {pluPlan && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-3xl overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="flex items-start justify-between border-b border-gray-200 bg-gray-50 px-5 py-3">
              <div>
                <h3 className="text-base font-semibold text-gray-800">PLU bulk-assign / repair</h3>
                <p className="text-xs text-gray-500">
                  Generates aligned EAN-13 barcodes (prefix <code>200</code>) for every SKU that
                  lacks a valid one. Existing valid + aligned PLUs are left untouched.
                </p>
              </div>
              <button
                onClick={() => setPluPlan(null)}
                className="rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-700"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <div className="max-h-[70vh] space-y-4 overflow-y-auto px-5 py-4">
              <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                <div className="rounded border border-gray-200 bg-gray-50 px-3 py-2">
                  <div className="text-[11px] uppercase text-gray-500">total</div>
                  <div className="text-sm font-semibold text-gray-800">{pluPlan.summary.total ?? 0}</div>
                </div>
                <div className="rounded border border-red-200 bg-red-50 px-3 py-2">
                  <div className="text-[11px] uppercase text-red-600">missing</div>
                  <div className="text-sm font-semibold text-red-700">{pluPlan.summary.missing ?? 0}</div>
                </div>
                <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2">
                  <div className="text-[11px] uppercase text-amber-600">invalid</div>
                  <div className="text-sm font-semibold text-amber-700">{pluPlan.summary.invalid ?? 0}</div>
                </div>
                <div className="rounded border border-blue-200 bg-blue-50 px-3 py-2">
                  <div className="text-[11px] uppercase text-blue-600">misaligned</div>
                  <div className="text-sm font-semibold text-blue-700">{pluPlan.summary.misaligned ?? 0}</div>
                </div>
              </div>

              {pluPlan.applied && (
                <div className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
                  Applied. Reload Data Quality to see the new PLUs propagate.
                </div>
              )}

              {pluPlan.plan.length === 0 ? (
                <p className="text-xs italic text-gray-500">
                  No PLUs need attention — every SKU has a valid, SKU-aligned EAN-13 barcode.
                </p>
              ) : (
                <div className="overflow-x-auto rounded border border-gray-200">
                  <table className="min-w-full text-xs">
                    <thead className="bg-gray-50 text-[11px] uppercase tracking-wide text-gray-500">
                      <tr>
                        <th className="px-2 py-1 text-left">SKU</th>
                        <th className="px-2 py-1 text-left">Reason</th>
                        <th className="px-2 py-1 text-left">Old PLU</th>
                        <th className="px-2 py-1 text-left">→ New PLU</th>
                        <th className="px-2 py-1 text-left">Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pluPlan.plan.map((row) => (
                        <tr key={row.sku_id} className="border-t border-gray-100">
                          <td className="px-2 py-1 font-mono text-[11px]">{row.sku_code}</td>
                          <td className="px-2 py-1">
                            <span
                              className={
                                row.reason === "missing"
                                  ? "rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-700"
                                  : row.reason === "invalid"
                                    ? "rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700"
                                    : "rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-700"
                              }
                            >
                              {row.reason}
                            </span>
                          </td>
                          <td className="px-2 py-1 font-mono text-[11px] text-gray-500">
                            {row.old_plu ?? "—"}
                          </td>
                          <td className="px-2 py-1 font-mono text-[11px] text-emerald-700">{row.new_plu}</td>
                          <td className="px-2 py-1 text-gray-700">{row.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {pluPlan.plan_total > pluPlan.plan.length && (
                    <p className="px-2 py-1 text-[11px] italic text-gray-500">
                      Showing first {pluPlan.plan.length} of {pluPlan.plan_total}. Apply will process all rows.
                    </p>
                  )}
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-gray-200 bg-gray-50 px-5 py-3">
              <button
                onClick={() => setPluPlan(null)}
                className="rounded-lg bg-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-300"
              >
                Close
              </button>
              <button
                onClick={() => void applyPluPlan()}
                disabled={pluApplying || pluPlan.plan_total === 0 || pluPlan.applied}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-40"
              >
                {pluApplying
                  ? "Applying..."
                  : pluPlan.applied
                    ? "Applied"
                    : `Apply (${pluPlan.plan_total})`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <StatCard label="Total Products" value={data.total_products} />
        <StatCard label="Errors" value={qs.total_errors} accent="border-red-200 bg-red-50" />
        <StatCard label="Warnings" value={qs.total_warnings} accent="border-amber-200 bg-amber-50" />
        <StatCard label="Clean" value={qs.products_clean} sub={`${Math.round((qs.products_clean / data.total_products) * 100)}%`} accent="border-green-200 bg-green-50" />
        <StatCard label="Sale Ready" value={data.products.filter((p) => p.sale_ready).length} accent="border-blue-200 bg-blue-50" />
        <StatCard label="Not Stocked" value={data.products.filter((p) => p.stocking_status === "not_stocked").length} />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3">
        <span className="text-xs font-semibold text-gray-500">Filter:</span>
        {([
          ["all", "All"],
          ["errors", "Errors"],
          ["warnings", "Warnings"],
          ["clean", "Clean"],
          ["finished_for_sale", "Finished (NEC)"],
          ["catalog_to_stock", "Catalog"],
          ["material", "Materials"],
          ["store_operations", "Store Ops"],
          ["sale_ready", "Sale-Ready"],
          ["not_stocked", "Not Stocked"],
          ["missing_price", "Missing Price"],
          ["homeware", "Homeware"],
          ["jewellery", "Jewellery"],
          ["minerals", "Minerals"],
        ] as [FilterMode, string][]).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              filter === key ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {label}
            {key !== "all" && (
              <span className="ml-1 opacity-70">
                ({key === "errors" ? qs.total_errors
                  : key === "warnings" ? qs.total_warnings
                  : key === "clean" ? qs.products_clean
                  : key === "sale_ready" ? data.products.filter((p) => p.sale_ready).length
                  : key === "not_stocked" ? data.products.filter((p) => p.stocking_status === "not_stocked").length
                  : key === "missing_price" ? data.products.filter((p) => p.retail_price == null).length
                  : key === "homeware" ? data.products.filter((p) => HOMEWARE_TYPES.has(p.product_type)).length
                  : key === "jewellery" ? data.products.filter((p) => JEWELLERY_TYPES.has(p.product_type)).length
                  : key === "minerals" ? data.products.filter((p) => MINERALS_TYPES.has(p.product_type)).length
                  : data.products.filter((p) => p.inventory_category === key).length})
              </span>
            )}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, material, SKU..."
            className="w-56 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs focus:border-blue-400 focus:outline-none"
          />
        </div>
      </div>

      {/* Bulk Actions */}
      {(filter === "not_stocked" || filter === "catalog_to_stock" || filter === "errors") && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-blue-200 bg-blue-50/50 px-4 py-2">
          <span className="text-xs font-semibold text-blue-700">Bulk Actions ({filtered.length} items):</span>
          {filter === "not_stocked" && (
            <>
              <button
                onClick={() => bulkSetField("stocking_location", "takashimaya_counter", (p) => p.stocking_status === "not_stocked")}
                className="rounded bg-blue-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-blue-700"
              >
                Assign to Takashimaya
              </button>
              <button
                onClick={() => bulkSetField("stocking_location", "warehouse", (p) => p.stocking_status === "not_stocked")}
                className="rounded bg-gray-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-gray-700"
              >
                Assign to Warehouse
              </button>
              <button
                onClick={() => {
                  bulkSetField("stocking_status", "to_order", (p) => p.stocking_status === "not_stocked");
                }}
                className="rounded bg-green-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-green-700"
              >
                Mark as To Order
              </button>
            </>
          )}
          {filter === "catalog_to_stock" && (
            <button
              onClick={() => bulkSetField("sale_ready", true, (p) => p.inventory_category === "catalog_to_stock" && !p.sale_ready)}
              className="rounded bg-green-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-green-700"
            >
              Mark All Sale-Ready
            </button>
          )}
        </div>
      )}

      {/* Results count + pagination */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">
          Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filtered.length)} of {filtered.length} products
        </p>
        {totalPages > 1 && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(Math.max(0, page - 1))}
              disabled={page === 0}
              className="rounded bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 disabled:opacity-40"
            >
              Prev
            </button>
            <span className="px-2 text-xs text-gray-500">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
              disabled={page >= totalPages - 1}
              className="rounded bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        )}
      </div>

      {/* Table */}
      <div ref={tableRef} className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50/80">
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">ID</th>
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Description</th>
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Material</th>
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Type</th>
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Category</th>
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Stock Status</th>
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Location</th>
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400 text-center">Sale</th>
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400 text-right">Cost</th>
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-blue-500 text-right">Retail</th>
              <th className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Issues</th>
            </tr>
          </thead>
          <tbody>
            {pageProducts.map((p) => (
              <ProductRow
                key={p.id}
                product={p}
                reference={ref}
                isEditing={editingId === p.id}
                draft={editingId === p.id ? draft : null}
                onStartEdit={() => startEdit(p)}
                onDraftChange={(field, value) => setDraft((prev) => (prev ? { ...prev, [field]: value } : null))}
                onSave={saveSingleEdit}
                onCancel={cancelEdit}
              />
            ))}
          </tbody>
        </table>
        {pageProducts.length === 0 && (
          <div className="py-12 text-center text-sm text-gray-400">No products match current filters</div>
        )}
      </div>

      {/* Bottom pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-1">
          <button
            onClick={() => { setPage(Math.max(0, page - 1)); tableRef.current?.scrollIntoView({ behavior: "smooth" }); }}
            disabled={page === 0}
            className="rounded bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-200 disabled:opacity-40"
          >
            Previous
          </button>
          {Array.from({ length: Math.min(totalPages, 10) }, (_, i) => {
            const p = totalPages <= 10 ? i : page < 5 ? i : page > totalPages - 6 ? totalPages - 10 + i : page - 5 + i;
            return (
              <button
                key={p}
                onClick={() => { setPage(p); tableRef.current?.scrollIntoView({ behavior: "smooth" }); }}
                className={`rounded px-2.5 py-1.5 text-xs font-medium ${p === page ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
              >
                {p + 1}
              </button>
            );
          })}
          <button
            onClick={() => { setPage(Math.min(totalPages - 1, page + 1)); tableRef.current?.scrollIntoView({ behavior: "smooth" }); }}
            disabled={page >= totalPages - 1}
            className="rounded bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-200 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function IssueTable({ issues }: { issues: NecPreviewIssue[] }) {
  return (
    <div className="max-h-56 overflow-y-auto rounded border border-gray-200">
      <table className="min-w-full text-xs">
        <thead className="bg-gray-50 text-[11px] uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-2 py-1 text-left">SKU</th>
            <th className="px-2 py-1 text-left">Field</th>
            <th className="px-2 py-1 text-left">Severity</th>
            <th className="px-2 py-1 text-left">Message</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((i, idx) => (
            <tr key={`${i.sku_code}-${i.field}-${idx}`} className="border-t border-gray-100">
              <td className="px-2 py-1 font-mono text-[11px]">{i.sku_code}</td>
              <td className="px-2 py-1 font-mono text-[11px]">{i.field}</td>
              <td className="px-2 py-1">
                <span className={badge(i.severity)}>{i.severity}</span>
              </td>
              <td className="px-2 py-1 text-gray-700">{i.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
