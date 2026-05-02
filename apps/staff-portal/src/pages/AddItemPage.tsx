/**
 * AddItemPage — full-feature inventory creation on its own URL.
 *
 * Mounts the shared ``CreateProductModal`` (extracted from MasterDataPage in
 * Stage 1b) as a routed page. The modal still renders its own overlay chrome
 * for now; Stage 3 will strip it once we're using the URL entry point in
 * earnest. Until then, navigating to ``/master-data/add`` shows the same
 * dialog the "+ Create inventory" button used to launch — same fields,
 * same supplier panel, same dedup, same sequence preview — but reachable
 * via URL and the browser back button.
 *
 * Query params:
 *   ``?variant_of=SKU`` — open in variant-mode with that parent preselected.
 *   ``?variant=1``      — open in variant-mode without a preset parent.
 */
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  masterDataApi,
  newIdempotencyKey,
  type CreateProductRequest,
  type ProductRow,
} from "../lib/master-data-api";
import { useAuth } from "../contexts/AuthContext";
import { CreateProductModal } from "../components/CreateProductForm";
import { clearCreateDraft, rememberCreatedProduct } from "../lib/master-data-helpers";

export default function AddItemPage() {
  const { isOwner } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const variantOf = params.get("variant_of") || "";
  const variantMode = variantOf !== "" || params.get("variant") === "1";

  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [products, setProducts] = useState<ProductRow[]>([]);

  // Pull the full product list once so the modal can drive its variant
  // parent dropdown and exact-name dedup. listProducts has no auth gate
  // beyond owner; the surrounding ``isOwner`` check already guards the page.
  useEffect(() => {
    if (!isOwner) return;
    let cancelled = false;
    masterDataApi.listProducts({ group_variants: false }).then(
      (r) => { if (!cancelled) setProducts(r.products); },
      () => { /* non-fatal: form still works without dedup */ },
    );
    return () => { cancelled = true; };
  }, [isOwner]);

  if (!isOwner) {
    // Same gate as MasterDataPage's create flow — the server enforces it
    // too, but the UI shouldn't render the form for non-owner accounts.
    return (
      <div className="p-8 text-sm text-slate-600">
        Restricted to owner accounts.
      </div>
    );
  }

  const handleSubmit = async (
    req: CreateProductRequest,
    images: File[],
    opts: { print_label_now: boolean },
  ) => {
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const result = await masterDataApi.createProduct(req, {
        idempotencyKey: newIdempotencyKey(),
      });
      for (const image of images) {
        await masterDataApi.uploadProductImage(result.product.sku_code, image);
      }
      clearCreateDraft();
      rememberCreatedProduct(result.product);
      const newSku = result.product.sku_code;

      // Optional P-touch label download. Mirrors the legacy modal's
      // ``print_label_now`` behaviour: if the export fails the create still
      // succeeds; the user can re-trigger from the grid.
      if (opts.print_label_now) {
        try {
          const labelRes = await masterDataApi.exportLabels({
            skus: [newSku],
            include_box: false,
            output_name: `ptouch_${newSku}.xlsx`,
          });
          if (labelRes.ok && labelRes.download_url) {
            const filename =
              labelRes.download_url.split("/").pop() || `ptouch_${newSku}.xlsx`;
            const blob = await masterDataApi.downloadExport(filename);
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = filename;
            link.click();
            URL.revokeObjectURL(url);
          }
        } catch {
          // non-blocking
        }
      }

      navigate(`/master-data?focus=${encodeURIComponent(newSku)}`);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <CreateProductModal
      mode="page"
      submitting={submitting}
      errorMessage={errorMessage}
      variantMode={variantMode}
      presetVariantParent={variantOf || undefined}
      variantParents={products}
      existingProducts={products}
      onCancel={() => navigate("/master-data")}
      onSubmit={handleSubmit}
      onPickExisting={(sku) =>
        navigate(`/master-data?focus=${encodeURIComponent(sku)}`)
      }
      onPickAsVariantOf={(sku) =>
        navigate(`/master-data/add?variant_of=${encodeURIComponent(sku)}`)
      }
    />
  );
}
