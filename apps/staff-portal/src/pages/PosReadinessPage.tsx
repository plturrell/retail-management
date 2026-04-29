import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { DataQualityResponse, Product } from "../lib/data-quality-types";

/**
 * POS Readiness hub.
 *
 * Stitches the four pipeline pillars (items → pricing → labels → NEC export)
 * into a single guided checklist. Each row shows a current count and links
 * to the existing fix surface, so operators don't have to bounce between
 * Master Data, Data Quality, and CAG settings to find the next action.
 *
 * Loads in parallel:
 *   - /data-quality/products            → SKU + price coverage
 *   - /data-quality/plus/bulk-preview   → missing / invalid PLUs
 *   - /cag/export/preview               → NEC export readiness (warnings/errors)
 *   - /cag/config                       → SFTP credentials configured
 */

interface PluPreview {
  summary: { total?: number; missing?: number; invalid?: number; misaligned?: number };
}

interface NecPreview {
  sellable_count: number;
  excluded_count: number;
  errors: { sku_code: string; message: string }[];
  warnings: { sku_code: string; message: string }[];
  is_ready: boolean;
  excluded_summary: Record<string, number>;
}

interface CagConfigPublic {
  is_configured: boolean;
  has_password: boolean;
  has_key_passphrase: boolean;
  key_path: string;
  tenant_folder: string;
  default_nec_store_id: string;
}

type StepStatus = "ok" | "warn" | "blocked" | "loading";

interface StepCard {
  id: string;
  index: number;
  title: string;
  status: StepStatus;
  metric: string | number;
  detail: string;
  cta: { label: string; to: string } | null;
}

export default function PosReadinessPage() {
  const [dq, setDq] = useState<DataQualityResponse | null>(null);
  const [plu, setPlu] = useState<PluPreview | null>(null);
  const [nec, setNec] = useState<NecPreview | null>(null);
  const [necErr, setNecErr] = useState<string | null>(null);
  const [cag, setCag] = useState<CagConfigPublic | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    const [dqRes, pluRes, cagRes, necRes] = await Promise.allSettled([
      api.get<DataQualityResponse>("/data-quality/products"),
      api.get<PluPreview>("/data-quality/plus/bulk-preview"),
      api.get<CagConfigPublic>("/cag/config"),
      api.get<NecPreview>("/cag/export/preview"),
    ]);
    if (dqRes.status === "fulfilled") setDq(dqRes.value);
    if (pluRes.status === "fulfilled") setPlu(pluRes.value);
    if (cagRes.status === "fulfilled") setCag(cagRes.value);
    if (necRes.status === "fulfilled") {
      setNec(necRes.value);
      setNecErr(null);
    } else {
      setNec(null);
      setNecErr(necRes.reason instanceof Error ? necRes.reason.message : "Preview failed");
    }
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const items = useMemo(() => (dq ? dq.products : []), [dq]);

  const counts = useMemo(() => {
    const saleReady = items.filter((p) => p.sale_ready);
    const missingDescription = items.filter(
      (p) => !p.description || (p.description as string).trim() === "",
    ).length;
    const missingPrice = saleReady.filter(
      (p: Product & { retail_price?: number | null }) =>
        p.retail_price === null || p.retail_price === undefined,
    ).length;
    const blockedSales = items.filter((p) => p.block_sales).length;
    return {
      total: items.length,
      saleReady: saleReady.length,
      missingDescription,
      missingPrice,
      blockedSales,
    };
  }, [items]);

  const steps: StepCard[] = useMemo(() => {
    if (loading) {
      return Array.from({ length: 6 }).map((_, i) => ({
        id: `sk-${i}`,
        index: i + 1,
        title: "…",
        status: "loading" as StepStatus,
        metric: "—",
        detail: "Loading",
        cta: null,
      }));
    }

    return [
      {
        id: "items",
        index: 1,
        title: "Items have descriptions and brand",
        status: counts.missingDescription === 0 ? "ok" : "blocked",
        metric: counts.missingDescription === 0 ? "✓" : counts.missingDescription,
        detail:
          counts.missingDescription === 0
            ? `${counts.total} items present, all have descriptions`
            : `${counts.missingDescription} item(s) without a description`,
        cta:
          counts.missingDescription === 0
            ? null
            : { label: "Fix in Master Data", to: "/master-data" },
      },
      {
        id: "pricing",
        index: 2,
        title: "Sale-ready items have a retail price",
        status: counts.missingPrice === 0 ? "ok" : "blocked",
        metric: counts.missingPrice === 0 ? "✓" : counts.missingPrice,
        detail:
          counts.missingPrice === 0
            ? `${counts.saleReady} sale-ready item(s) priced`
            : `${counts.missingPrice} sale-ready item(s) without a price`,
        cta:
          counts.missingPrice === 0
            ? null
            : { label: "Set prices in Data Quality", to: "/data-quality" },
      },
      {
        id: "plus",
        index: 3,
        title: "Every SKU has a valid EAN-13 PLU",
        status:
          (plu?.summary.total ?? 0) === 0 ? "ok" : (plu?.summary.missing ?? 0) > 0 ? "blocked" : "warn",
        metric: (plu?.summary.total ?? 0) === 0 ? "✓" : plu?.summary.total ?? "?",
        detail:
          (plu?.summary.total ?? 0) === 0
            ? "All PLUs valid and SKU-aligned"
            : `${plu?.summary.missing ?? 0} missing · ${plu?.summary.invalid ?? 0} invalid · ${plu?.summary.misaligned ?? 0} misaligned`,
        cta:
          (plu?.summary.total ?? 0) === 0
            ? null
            : { label: "Generate / repair PLUs", to: "/data-quality" },
      },
      {
        id: "labels",
        index: 4,
        title: "Print barcode labels for sale-ready items",
        status: counts.saleReady > 0 ? "ok" : "warn",
        metric: counts.saleReady,
        detail:
          counts.saleReady > 0
            ? `${counts.saleReady} item(s) ready to print on P-touch`
            : "No sale-ready items yet — finish steps 1–3 first",
        cta: { label: "Open label printer", to: "/master-data" },
      },
      {
        id: "config",
        index: 5,
        title: "CAG / NEC SFTP credentials configured",
        status: cag?.is_configured ? "ok" : "blocked",
        metric: cag?.is_configured ? "✓" : "—",
        detail: cag?.is_configured
          ? `Tenant ${cag.tenant_folder || "(default)"} · default Store ${cag.default_nec_store_id || "—"}`
          : "Host / username / key (or password) not set",
        cta: cag?.is_configured
          ? { label: "Review settings", to: "/settings/cag-nec" }
          : { label: "Configure SFTP", to: "/settings/cag-nec" },
      },
      {
        id: "nec",
        index: 6,
        title: "NEC export pre-flight",
        status: necErr
          ? "blocked"
          : nec?.is_ready
            ? nec.warnings.length > 0
              ? "warn"
              : "ok"
            : "blocked",
        metric: necErr
          ? "ERR"
          : nec
            ? `${nec.sellable_count}`
            : "—",
        detail: necErr
          ? necErr
          : nec
            ? `${nec.sellable_count} sellable · ${nec.errors.length} error(s) · ${nec.warnings.length} warning(s)`
            : "No preview available",
        cta: { label: "Open Data Quality → Preview", to: "/data-quality" },
      },
    ];
  }, [loading, counts, plu, cag, nec, necErr]);

  const blockedCount = steps.filter((s) => s.status === "blocked").length;
  const warnCount = steps.filter((s) => s.status === "warn").length;
  const overall: StepStatus = loading
    ? "loading"
    : blockedCount > 0
      ? "blocked"
      : warnCount > 0
        ? "warn"
        : "ok";

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-1">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">POS Readiness</h1>
          <p className="mt-1 text-xs text-gray-500">
            One-screen checklist that funnels items → pricing → labels → NEC export. Each row shows
            the current gap and links to the relevant fix surface.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <OverallBadge status={overall} />
          <button
            onClick={() => void load()}
            disabled={refreshing}
            className="rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-200 disabled:opacity-50"
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      <div className="grid gap-3">
        {steps.map((s) => (
          <StepRow key={s.id} step={s} />
        ))}
      </div>
    </div>
  );
}

function OverallBadge({ status }: { status: StepStatus }) {
  const map: Record<StepStatus, { label: string; cls: string }> = {
    ok: { label: "READY TO PUSH", cls: "bg-emerald-100 text-emerald-700" },
    warn: { label: "READY WITH WARNINGS", cls: "bg-amber-100 text-amber-700" },
    blocked: { label: "ACTION REQUIRED", cls: "bg-red-100 text-red-700" },
    loading: { label: "Loading…", cls: "bg-gray-100 text-gray-500" },
  };
  const { label, cls } = map[status];
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${cls}`}>{label}</span>
  );
}

function StepRow({ step }: { step: StepCard }) {
  const ringCls =
    step.status === "ok"
      ? "border-emerald-200 bg-emerald-50/50"
      : step.status === "warn"
        ? "border-amber-200 bg-amber-50/50"
        : step.status === "blocked"
          ? "border-red-200 bg-red-50/50"
          : "border-gray-200 bg-white";
  const dotCls =
    step.status === "ok"
      ? "bg-emerald-500"
      : step.status === "warn"
        ? "bg-amber-500"
        : step.status === "blocked"
          ? "bg-red-500"
          : "bg-gray-300";
  return (
    <div className={`flex items-center gap-4 rounded-xl border ${ringCls} p-4`}>
      <div className="flex h-10 w-10 flex-none items-center justify-center rounded-full bg-white text-sm font-bold text-gray-600 ring-1 ring-gray-200">
        {step.index}
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${dotCls}`} />
          <h3 className="text-sm font-semibold text-gray-800">{step.title}</h3>
        </div>
        <p className="mt-1 text-xs text-gray-600">{step.detail}</p>
      </div>
      <div className="text-right">
        <div className="text-2xl font-bold text-gray-800">{step.metric}</div>
        {step.cta && (
          <Link
            to={step.cta.to}
            className="mt-1 inline-block rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700"
          >
            {step.cta.label}
          </Link>
        )}
      </div>
    </div>
  );
}
