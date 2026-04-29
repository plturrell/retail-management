import { useEffect, useMemo, useState } from "react";
import {
  cagExportApi,
  masterDataApi,
  type BulkPublishItem,
  type BulkPublishResponse,
  type CagPushResponse,
  type LabelsExportResult,
  type ProductRow,
} from "../lib/master-data-api";
import { useToast } from "../components/ui/Toast";
import { Icon } from "../components/Icon";

type Step = 1 | 2 | 3 | 4;

interface DraftRow {
  product: ProductRow;
  draftPrice: string;
}

const STEP_LABELS: Record<Step, string> = {
  1: "Select SKUs",
  2: "Set prices",
  3: "Export labels",
  4: "Push to NEC",
};

export default function PublishPage() {
  const toast = useToast();
  const [step, setStep] = useState<Step>(1);
  const [products, setProducts] = useState<ProductRow[]>([]);
  const [productsLoading, setProductsLoading] = useState(false);
  const [productsError, setProductsError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkPublishResponse | null>(null);
  const [labelsBusy, setLabelsBusy] = useState(false);
  const [labelsResult, setLabelsResult] = useState<LabelsExportResult | null>(null);
  const [txtBusy, setTxtBusy] = useState(false);
  const [pushBusy, setPushBusy] = useState(false);
  const [pushResult, setPushResult] = useState<CagPushResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    setProductsLoading(true);
    setProductsError(null);
    masterDataApi
      .listProducts({ launch_only: true, needs_price: true })
      .then((res) => {
        if (cancelled) return;
        setProducts(res.products);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setProductsError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (cancelled) return;
        setProductsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const draftRows = useMemo<DraftRow[]>(
    () =>
      Array.from(selected)
        .map((sku) => products.find((p) => p.sku_code === sku))
        .filter((p): p is ProductRow => Boolean(p))
        .map((p) => ({ product: p, draftPrice: drafts[p.sku_code] ?? "" })),
    [selected, products, drafts],
  );

  function toggleSelected(sku: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(sku)) next.delete(sku);
      else next.add(sku);
      return next;
    });
  }

  async function publishBulk() {
    const items: BulkPublishItem[] = draftRows
      .map(({ product, draftPrice }) => {
        const price = parseFloat(draftPrice);
        if (!price || price <= 0) return null;
        return { sku: product.sku_code, retail_price: price };
      })
      .filter((x): x is BulkPublishItem => x !== null);
    if (items.length === 0) {
      toast.push({ variant: "warning", title: "No prices to publish", body: "Enter at least one price." });
      return;
    }
    setBulkBusy(true);
    try {
      const res = await masterDataApi.publishPricesBulk({ items });
      setBulkResult(res);
      toast.push({
        variant: res.ok ? "success" : "warning",
        title: `Published ${res.succeeded}/${res.succeeded + res.failed}`,
        body: res.failed > 0 ? `${res.failed} failed — see results below.` : undefined,
      });
      if (res.ok) setStep(3);
    } catch (err) {
      toast.push({
        variant: "error",
        title: "Bulk publish failed",
        body: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBulkBusy(false);
    }
  }

  async function exportLabels() {
    setLabelsBusy(true);
    try {
      const res = await masterDataApi.exportLabels({
        skus: Array.from(selected),
        include_box: true,
      });
      setLabelsResult(res);
      if (res.download_url) {
        window.open(res.download_url, "_blank", "noopener,noreferrer");
      }
      toast.push({
        variant: res.ok ? "success" : "error",
        title: res.ok ? "Labels exported" : "Label export failed",
        body: res.missing_skus?.length ? `Missing SKUs: ${res.missing_skus.join(", ")}` : undefined,
      });
      if (res.ok) setStep(4);
    } catch (err) {
      toast.push({
        variant: "error",
        title: "Label export failed",
        body: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLabelsBusy(false);
    }
  }

  async function downloadTxt() {
    setTxtBusy(true);
    try {
      const { blob, filename } = await cagExportApi.txt();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.push({ variant: "success", title: "CAG TXT bundle downloaded" });
    } catch (err) {
      toast.push({
        variant: "error",
        title: "TXT download failed",
        body: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setTxtBusy(false);
    }
  }

  async function pushNow() {
    setPushBusy(true);
    try {
      const res = await cagExportApi.push();
      setPushResult(res);
      toast.push({
        variant: "success",
        title: `Pushed ${res.files_uploaded.length} file(s)`,
        body: `${res.bytes_uploaded.toLocaleString()} bytes`,
      });
    } catch (err) {
      toast.push({
        variant: "error",
        title: "SFTP push failed",
        body: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setPushBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Publish</h1>
        <p className="text-sm text-gray-500">
          Pick SKUs, set prices, print labels, and push the master bundle to NEC — in one place.
        </p>
      </div>

      <Stepper step={step} onJump={setStep} />

      {step === 1 && (
        <Step1Select
          products={products}
          loading={productsLoading}
          error={productsError}
          selected={selected}
          onToggle={toggleSelected}
          onNext={() => setStep(2)}
        />
      )}
      {step === 2 && (
        <Step2Prices
          rows={draftRows}
          drafts={drafts}
          onPriceChange={(sku, value) => setDrafts((d) => ({ ...d, [sku]: value }))}
          onPublish={publishBulk}
          busy={bulkBusy}
          result={bulkResult}
          onBack={() => setStep(1)}
        />
      )}
      {step === 3 && (
        <Step3Labels
          rows={draftRows}
          onExport={exportLabels}
          busy={labelsBusy}
          result={labelsResult}
          onBack={() => setStep(2)}
          onSkip={() => setStep(4)}
        />
      )}
      {step === 4 && (
        <Step4Push
          onDownload={downloadTxt}
          downloadBusy={txtBusy}
          onPush={pushNow}
          pushBusy={pushBusy}
          pushResult={pushResult}
          onBack={() => setStep(3)}
        />
      )}
    </div>
  );
}

function Stepper({ step, onJump }: { step: Step; onJump(s: Step): void }) {
  return (
    <ol className="flex items-center gap-2 overflow-x-auto rounded-lg border border-gray-200 bg-white p-3">
      {(Object.entries(STEP_LABELS) as [string, string][]).map(([sStr, label]) => {
        const s = Number(sStr) as Step;
        const active = s === step;
        const done = s < step;
        return (
          <li key={s} className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onJump(s)}
              className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm ${
                active
                  ? "bg-blue-600 text-white"
                  : done
                    ? "bg-blue-50 text-blue-700"
                    : "bg-gray-100 text-gray-500 hover:bg-gray-200"
              }`}
            >
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-white/20 text-xs font-bold">
                {done ? <Icon name="check" className="h-3 w-3" /> : s}
              </span>
              <span className="font-medium">{label}</span>
            </button>
            {s < 4 && <Icon name="chevron-right" className="h-4 w-4 text-gray-300" />}
          </li>
        );
      })}
    </ol>
  );
}

function Step1Select({
  products,
  loading,
  error,
  selected,
  onToggle,
  onNext,
}: {
  products: ProductRow[];
  loading: boolean;
  error: string | null;
  selected: Set<string>;
  onToggle(sku: string): void;
  onNext(): void;
}) {
  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-gray-700">Pick SKUs that need a price</h2>
      {error && <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      {loading && <div className="text-sm text-gray-500">Loading products…</div>}
      {!loading && products.length === 0 && (
        <div className="text-sm text-gray-500">No launch SKUs are missing a price right now.</div>
      )}
      <div className="max-h-96 overflow-y-auto rounded-md border border-gray-100">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="w-10 px-3 py-2"></th>
              <th className="px-3 py-2">SKU</th>
              <th className="px-3 py-2">Description</th>
              <th className="px-3 py-2">PLU</th>
              <th className="px-3 py-2 text-right">Cost</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.sku_code} className="border-t border-gray-100">
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selected.has(p.sku_code)}
                    onChange={() => onToggle(p.sku_code)}
                    aria-label={`Select ${p.sku_code}`}
                  />
                </td>
                <td className="px-3 py-2 font-mono text-xs text-gray-700">{p.sku_code}</td>
                <td className="px-3 py-2 text-gray-700">{p.description ?? "—"}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{p.nec_plu ?? "—"}</td>
                <td className="px-3 py-2 text-right text-gray-700">
                  {p.cost_price !== null && p.cost_price !== undefined ? p.cost_price.toFixed(2) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500">{selected.size} selected</div>
        <button
          type="button"
          onClick={onNext}
          disabled={selected.size === 0}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          Next: Set prices
        </button>
      </div>
    </div>
  );
}

function Step2Prices({
  rows,
  drafts,
  onPriceChange,
  onPublish,
  busy,
  result,
  onBack,
}: {
  rows: DraftRow[];
  drafts: Record<string, string>;
  onPriceChange(sku: string, value: string): void;
  onPublish(): void;
  busy: boolean;
  result: BulkPublishResponse | null;
  onBack(): void;
}) {
  const errorBySku = new Map(
    (result?.results ?? []).filter((r) => !r.ok).map((r) => [r.sku, r.error?.message ?? "failed"]),
  );
  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-gray-700">Set the tax-inclusive retail price</h2>
      <div className="overflow-x-auto rounded-md border border-gray-100">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-3 py-2">SKU</th>
              <th className="px-3 py-2">Description</th>
              <th className="px-3 py-2 text-right">Cost</th>
              <th className="px-3 py-2 text-right">Retail (incl. GST)</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ product }) => (
              <tr key={product.sku_code} className="border-t border-gray-100">
                <td className="px-3 py-2 font-mono text-xs text-gray-700">{product.sku_code}</td>
                <td className="px-3 py-2 text-gray-700">{product.description ?? "—"}</td>
                <td className="px-3 py-2 text-right text-gray-500">
                  {product.cost_price !== null && product.cost_price !== undefined
                    ? product.cost_price.toFixed(2)
                    : "—"}
                </td>
                <td className="px-3 py-2 text-right">
                  <input
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    min="0"
                    value={drafts[product.sku_code] ?? ""}
                    onChange={(e) => onPriceChange(product.sku_code, e.target.value)}
                    className="w-24 rounded-md border border-gray-200 px-2 py-1 text-right text-sm"
                    aria-label={`Retail price for ${product.sku_code}`}
                  />
                </td>
                <td className="px-3 py-2 text-xs text-red-600">
                  {errorBySku.get(product.sku_code) ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between">
        <button type="button" onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back
        </button>
        <button
          type="button"
          onClick={onPublish}
          disabled={busy || rows.length === 0}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          {busy ? "Publishing…" : "Publish prices"}
        </button>
      </div>
    </div>
  );
}

function Step3Labels({
  rows,
  onExport,
  busy,
  result,
  onBack,
  onSkip,
}: {
  rows: DraftRow[];
  onExport(): void;
  busy: boolean;
  result: LabelsExportResult | null;
  onBack(): void;
  onSkip(): void;
}) {
  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-gray-700">Export labels</h2>
      <p className="text-sm text-gray-500">
        Generate a print-ready PDF for the {rows.length} selected SKU(s). Skip if you've already
        printed.
      </p>
      {result && (
        <div className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-600">
          <div>PLU count: {result.plu_count ?? "—"}</div>
          {result.missing_skus && result.missing_skus.length > 0 && (
            <div className="text-amber-700">
              Missing SKUs: {result.missing_skus.join(", ")}
            </div>
          )}
          {result.skus_no_plu && result.skus_no_plu.length > 0 && (
            <div className="text-amber-700">
              SKUs without PLU: {result.skus_no_plu.join(", ")}
            </div>
          )}
        </div>
      )}
      <div className="flex items-center justify-between">
        <button type="button" onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back
        </button>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onSkip}
            className="rounded-md border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50"
          >
            Skip
          </button>
          <button
            type="button"
            onClick={onExport}
            disabled={busy || rows.length === 0}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {busy ? "Exporting…" : "Export labels"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Step4Push({
  onDownload,
  downloadBusy,
  onPush,
  pushBusy,
  pushResult,
  onBack,
}: {
  onDownload(): void;
  downloadBusy: boolean;
  onPush(): void;
  pushBusy: boolean;
  pushResult: CagPushResponse | null;
  onBack(): void;
}) {
  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-gray-700">Push to NEC</h2>
      <p className="text-sm text-gray-500">
        Download the CAG TXT bundle for inspection, then push it to the NEC SFTP inbox. Cloud
        Scheduler also runs this every 3 hours automatically.
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onDownload}
          disabled={downloadBusy}
          className="rounded-md border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {downloadBusy ? "Downloading…" : "Download TXT bundle"}
        </button>
        <button
          type="button"
          onClick={onPush}
          disabled={pushBusy}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          {pushBusy ? "Pushing…" : "Push to SFTP now"}
        </button>
      </div>
      {pushResult && (
        <div className="rounded-md bg-green-50 px-3 py-2 text-xs text-green-800">
          <div>
            Uploaded {pushResult.files_uploaded.length} file(s) ·{" "}
            {pushResult.bytes_uploaded.toLocaleString()} bytes
          </div>
          <div className="mt-1 font-mono text-[10px] text-green-700">
            {pushResult.files_uploaded.join(", ")}
          </div>
          {pushResult.errors.length > 0 && (
            <div className="mt-1 text-red-700">
              {pushResult.errors.length} error(s): {pushResult.errors.join("; ")}
            </div>
          )}
        </div>
      )}
      <div className="flex items-center justify-start">
        <button type="button" onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back
        </button>
      </div>
    </div>
  );
}
