/**
 * Create-product form components.
 *
 * Extracted verbatim from MasterDataPage so the same form can render in
 * either of two contexts:
 *
 *   1. The legacy modal overlay launched from the "+ New SKU" / "+ Add
 *      variant" buttons in MasterDataPage.
 *   2. A full-page route at /master-data/add (AddItemPage), which is the
 *      Jobs/Ive-pass replacement currently being landed.
 *
 * The component itself is layout-agnostic: it renders its form pane and the
 * supplier catalog pane side-by-side. Whoever mounts it is responsible for
 * the surrounding chrome (modal overlay vs. page header).
 *
 * Stage 1 is a pure move — no behaviour changes. Stage 3 will polish the
 * page-context layout once the modal is retired.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  masterDataApi,
  type CreateProductRequest,
  type PreviewCodesResponse,
  type ProductRow,
  type SimilarProductMatch,
  type SourcingOption,
  type SupplierCatalogProduct,
  type SupplierSummary,
} from "../lib/master-data-api";
import { BarcodeScannerButton } from "./BarcodeScannerButton";
import {
  CANONICAL_LOCATION_OPTIONS,
  MATERIAL_OPTIONS,
  PRODUCT_CATEGORY_OPTIONS,
  type ProductCategoryValue,
  categoryForProductType,
  cleanMaterialLabel,
  clearCreateDraft,
  composeMaterialText,
  encodeStockingLocation,
  firstMaterialLabel,
  formatStockingLocation,
  loadCreateDraft,
  mergePendingAdditionalMaterial,
  normaliseIdentity,
  parseStockingLocation,
  relativeTime,
  saveCreateDraft,
  useDebouncedValue,
} from "../lib/master-data-helpers";

/**
 * Inventory-creation wizard.
 *
 * Two-pane layout: left is the always-visible form, right slides in when the
 * user picks a supplier-sourced origin and lets them browse / add to that
 * supplier's catalog snapshot. SKU code + NEC PLU are not exposed — they are
 * auto-allocated server-side to keep the SKU/PLU pair aligned.
 *
 * The DeepSeek V3 "Draft with AI" button calls /ai/describe_product to fill
 * description + long_description from the structured fields; the user is
 * always free to edit before saving.
 */
export function CreateProductModal({
  submitting,
  errorMessage,
  variantMode = false,
  presetVariantParent,
  variantParents,
  existingProducts,
  mode = "modal",
  onCancel,
  onSubmit,
  onPickExisting,
  onPickAsVariantOf,
}: {
  submitting: boolean;
  errorMessage: string | null;
  variantMode?: boolean;
  /** When set, the modal opens in variantMode with this SKU pre-selected. */
  presetVariantParent?: string;
  variantParents: ProductRow[];
  existingProducts: ProductRow[];
  /**
   * ``"modal"`` (default) renders a fixed-position overlay with backdrop blur
   * — used by callers that mount the form on top of an existing screen.
   * ``"page"`` drops the overlay so the form sits flush in a routed page
   * (see /master-data/add). Field layout, dedup panel, and submission flow
   * are identical across both.
   */
  mode?: "modal" | "page";
  onCancel: () => void;
  onSubmit: (
    req: CreateProductRequest,
    images: File[],
    opts: { print_label_now: boolean },
  ) => void;
  /** Called when the user accepts a dedup match — close + filter grid to it. */
  onPickExisting: (sku: string) => void;
  /** Called when the user picks "Add as variant of this match". */
  onPickAsVariantOf: (sku: string) => void;
}) {
  // ── Server-driven taxonomy ───────────────────────────────────────────────
  const [sourcingOptions, setSourcingOptions] = useState<SourcingOption[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierSummary[]>([]);
  const [taxonomyError, setTaxonomyError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      masterDataApi.getSourcingOptions(),
      masterDataApi.listSuppliers(),
    ])
      .then(([opts, sups]) => {
        if (cancelled) return;
        setSourcingOptions(opts.options);
        setSuppliers(sups.suppliers);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setTaxonomyError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Form state ───────────────────────────────────────────────────────────
  const [form, setForm] = useState({
    sourcing_strategy: "",
    supplier_slug: "",
    supplier_id: "",
    supplier_name: "",
    supplier_item_code: "",
    description: "",
    long_description: "",
    // Top-level product category — Homeware is the most common starting point;
    // staff can flip to Minerals or Jewellery and the product_type list
    // re-filters in `updateCategory()` below.
    category: "homeware" as ProductCategoryValue,
    product_type: PRODUCT_CATEGORY_OPTIONS[1].product_types[0] as string,
    material: MATERIAL_OPTIONS[0] as string,
    additional_materials: [] as string[],
    additional_material_input: "",
    size: "",
    qty_on_hand: "",
    // Where the row is physically held. Resolved to the server's default
    // (first list entry) when the user hasn't explicitly picked one yet.
    stocking_location: "",
    cost_price: "",
    cost_currency: "SGD",
    notes: "",
    retail_price: "",
    publish_now: false,
    // When set, the parent fires a follow-up exportLabels({ skus: [newSku] })
    // and downloads the P-touch xlsx as part of the same submit. Default off
    // so a typical "just create the row" submit doesn't trigger a download.
    print_label_now: false,
    variant_of_sku: "",
    variant_label: "",
    // Optional manual sequence override — used when the operator has
    // pre-printed a barcode label and needs the next-issued SKU+PLU pair to
    // match it (e.g. the 13 Hengwei homeware tags labelled 1–13). Empty
    // string means "let the server auto-allocate the next free sequence".
    sequence_override: "",
  });
  const [images, setImages] = useState<File[]>([]);
  const [localError, setLocalError] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiNote, setAiNote] = useState<string | null>(null);
  // DeepSeek V3 also returns a canonical short name. We keep it separate from
  // `description` so the user can pick one independently of the other.
  const [suggestedName, setSuggestedName] = useState<string | null>(null);

  // Draft persist — restore on first mount, prompt user to keep or discard.
  // Tracked in state so we can render the banner; null once they decide.
  const [draftBanner, setDraftBanner] = useState<{ saved_at: number } | null>(() => {
    const draft = loadCreateDraft();
    return draft ? { saved_at: draft.saved_at } : null;
  });

  // Persist every form change. Skip the very first render to avoid clobbering
  // the existing draft with an empty form before the user has decided whether
  // to resume it.
  const initialRenderRef = useRef(true);
  useEffect(() => {
    if (initialRenderRef.current) {
      initialRenderRef.current = false;
      return;
    }
    saveCreateDraft(form as unknown as Record<string, unknown>);
  }, [form]);

  const resumeDraft = () => {
    const draft = loadCreateDraft();
    if (draft) {
      setForm((f) => ({ ...f, ...(draft.form as typeof f) }));
    }
    setDraftBanner(null);
  };
  const discardDraft = () => {
    clearCreateDraft();
    setDraftBanner(null);
  };

  // When the parent re-opens the modal in variant-mode with a preset parent
  // (e.g. user clicked "+ Add as variant of …" from the dedup panel), copy
  // it into the form once. Subsequent edits to variant_of_sku stay sticky.
  const presetVariantAppliedRef = useRef(false);
  useEffect(() => {
    if (!presetVariantParent || presetVariantAppliedRef.current) return;
    presetVariantAppliedRef.current = true;
    setForm((f) => ({ ...f, variant_of_sku: presetVariantParent }));
  }, [presetVariantParent]);

  // ── Dedup / similar-products check ───────────────────────────────────────
  // Stage 1 (lexical) auto-fires on description changes; stage 2 (DeepSeek
  // verdicts) fires only when the user clicks the "double-check with AI"
  // button. See find_similar_products() in the legacy server module.
  const [similarMatches, setSimilarMatches] = useState<SimilarProductMatch[]>([]);
  const [similarBusy, setSimilarBusy] = useState(false);
  const [similarAiUsed, setSimilarAiUsed] = useState(false);
  const [similarError, setSimilarError] = useState<string | null>(null);
  const [similarDismissed, setSimilarDismissed] = useState(false);
  const debouncedDescription = useDebouncedValue(form.description, 350);
  const debouncedMaterial = useDebouncedValue(form.material, 350);
  const debouncedProductType = useDebouncedValue(form.product_type, 350);
  const debouncedSize = useDebouncedValue(form.size, 350);

  useEffect(() => {
    // Reset the "user dismissed this panel" flag once they meaningfully edit
    // the description so we re-show fresh hits.
    setSimilarDismissed(false);
  }, [debouncedDescription]);

  useEffect(() => {
    if (variantMode) {
      // In variant mode the user has already opted into the existing family,
      // so suppressing dedup hits keeps the panel out of the way.
      setSimilarMatches([]);
      return;
    }
    const desc = debouncedDescription.trim();
    if (desc.length < 8) {
      setSimilarMatches([]);
      return;
    }
    let cancelled = false;
    setSimilarBusy(true);
    setSimilarError(null);
    masterDataApi
      .checkSimilarProducts({
        description: desc,
        product_type: debouncedProductType || null,
        material: debouncedMaterial || null,
        size: debouncedSize || null,
        use_ai: false,
      })
      .then((res) => {
        if (cancelled) return;
        setSimilarMatches(res.matches);
        setSimilarAiUsed(res.ai_used);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Non-blocking — staff can still create the row, they just don't get
        // the dedup heads-up. Log it inline so the bug is visible without
        // crashing the modal.
        setSimilarError(err instanceof Error ? err.message : String(err));
        setSimilarMatches([]);
      })
      .finally(() => {
        if (!cancelled) setSimilarBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    variantMode,
    debouncedDescription,
    debouncedProductType,
    debouncedMaterial,
    debouncedSize,
  ]);

  const runAiVerdictPass = useCallback(async () => {
    const desc = form.description.trim();
    if (desc.length < 8 || similarMatches.length === 0) return;
    setSimilarBusy(true);
    setSimilarError(null);
    try {
      const res = await masterDataApi.checkSimilarProducts({
        description: desc,
        product_type: form.product_type || null,
        material: form.material || null,
        size: form.size || null,
        use_ai: true,
      });
      setSimilarMatches(res.matches);
      setSimilarAiUsed(res.ai_used);
    } catch (err: unknown) {
      setSimilarError(err instanceof Error ? err.message : String(err));
    } finally {
      setSimilarBusy(false);
    }
  }, [form.description, form.product_type, form.material, form.size, similarMatches.length]);

  const sourcingMeta = useMemo(
    () => sourcingOptions.find((o) => o.value === form.sourcing_strategy) ?? null,
    [sourcingOptions, form.sourcing_strategy],
  );
  const requiresSupplier = sourcingMeta?.requires_supplier ?? false;
  const selectedVariantParent = variantParents.find((p) => p.sku_code === form.variant_of_sku) || null;
  const additionalMaterialOptions = MATERIAL_OPTIONS.filter(
    (material) => (
      material.toLowerCase() !== form.material.toLowerCase() &&
      !form.additional_materials.some((item) => item.toLowerCase() === material.toLowerCase())
    ),
  );

  // Default to the first sourcing option once the taxonomy loads, so the
  // wizard never sits with an empty origin (which would block submit).
  useEffect(() => {
    if (!form.sourcing_strategy && sourcingOptions.length > 0) {
      setForm((f) => ({ ...f, sourcing_strategy: sourcingOptions[0].value }));
    }
  }, [sourcingOptions, form.sourcing_strategy]);

  // ── Live SKU/PLU preview ────────────────────────────────────────────────
  // Echo the codes the create endpoint would assign, so the operator can
  // confirm the SKU+PLU before submitting — especially important when they
  // type a `sequence_override` to claim a pre-printed barcode label.
  // Debounce on the same cadence as the dedup search to avoid one fetch per
  // keystroke. Re-fires when product_type, material, or seq override change.
  const [previewState, setPreviewState] = useState<{
    data: PreviewCodesResponse | null;
    loading: boolean;
    error: string | null;
  }>({ data: null, loading: false, error: null });
  const debouncedSequenceOverride = useDebouncedValue(form.sequence_override, 350);
  useEffect(() => {
    const productType = debouncedProductType.trim();
    const material = debouncedMaterial.trim();
    if (!productType || !material) {
      setPreviewState({ data: null, loading: false, error: null });
      return;
    }
    let parsedOverride: number | null = null;
    if (debouncedSequenceOverride.trim()) {
      const n = Number.parseInt(debouncedSequenceOverride, 10);
      if (!Number.isFinite(n) || n < 1 || n > 999_999) {
        setPreviewState({
          data: null,
          loading: false,
          error: "Sequence override must be a whole number between 1 and 999999.",
        });
        return;
      }
      parsedOverride = n;
    }
    let cancelled = false;
    setPreviewState((s) => ({ ...s, loading: true, error: null }));
    masterDataApi
      .previewCodes({
        product_type: productType,
        material,
        sequence_override: parsedOverride,
      })
      .then((res) => {
        if (cancelled) return;
        setPreviewState({ data: res, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setPreviewState({
          data: null,
          loading: false,
          error: err instanceof Error ? err.message : String(err),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedProductType, debouncedMaterial, debouncedSequenceOverride]);

  useEffect(() => {
    if (!variantMode || !selectedVariantParent) return;
    setForm((f) => {
      const primaryMaterial = selectedVariantParent.material || f.material;
      const inheritedType = selectedVariantParent.product_type || f.product_type;
      return {
        ...f,
        product_type: inheritedType,
        // Inherit the parent's category if we can map its product_type, else
        // fall back to whatever the parent had stored or the form default.
        category: selectedVariantParent.category as ProductCategoryValue
          || categoryForProductType(inheritedType),
        material: primaryMaterial,
        additional_materials: selectedVariantParent.additional_materials || f.additional_materials,
        sourcing_strategy: selectedVariantParent.sourcing_strategy || f.sourcing_strategy,
        supplier_id: selectedVariantParent.supplier_id || f.supplier_id,
        supplier_name: selectedVariantParent.supplier_name || f.supplier_name,
        description: selectedVariantParent.description || f.description,
        long_description: selectedVariantParent.long_description || f.long_description,
      };
    });
  }, [variantMode, selectedVariantParent]);

  const update = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  // Top-level product category. Re-anchors product_type to the first valid
  // option for the new category so e.g. switching Homeware → Jewellery
  // doesn't leave "Vase" selected. If the current product_type is still
  // listed under the new category (rare but possible in future taxonomies),
  // we keep it.
  const updateCategory = (value: ProductCategoryValue) => {
    const next = PRODUCT_CATEGORY_OPTIONS.find((c) => c.value === value) || PRODUCT_CATEGORY_OPTIONS[1];
    setForm((f) => ({
      ...f,
      category: next.value,
        product_type: (next.product_types as readonly string[]).includes(f.product_type)
          ? f.product_type
        : next.product_types[0] as string,
    }));
  };

  const updatePrimaryMaterial = (value: string) => {
    const material = cleanMaterialLabel(value);
    setForm((f) => ({
      ...f,
      material,
    }));
  };

  const addAdditionalMaterial = (value = form.additional_material_input) => {
    const material = cleanMaterialLabel(value);
    if (!material) return;
    setForm((f) => {
      const duplicate = [f.material, ...f.additional_materials].some(
        (item) => item.toLowerCase() === material.toLowerCase(),
      );
      return {
        ...f,
        additional_material_input: "",
        additional_materials: duplicate ? f.additional_materials : [...f.additional_materials, material],
      };
    });
  };

  const removeAdditionalMaterial = (value: string) => {
    setForm((f) => ({
      ...f,
      additional_materials: f.additional_materials.filter(
        (item) => item.toLowerCase() !== value.toLowerCase(),
      ),
    }));
  };

  const pickSupplier = (slug: string) => {
    const sup = suppliers.find((s) => s.slug === slug);
    if (!sup) {
      setForm((f) => ({ ...f, supplier_slug: "", supplier_id: "", supplier_name: "" }));
      return;
    }
    setForm((f) => ({
      ...f,
      supplier_slug: slug,
      supplier_id: sup.supplier_id || sup.slug.toUpperCase(),
      supplier_name: sup.supplier_name,
    }));
  };

  // When the user picks a row from the supplier catalog, autofill the
  // structured fields so they don't retype what we already have.
  const applyCatalogPick = (item: SupplierCatalogProduct, supplier: SupplierSummary) => {
    const pickedMaterial = firstMaterialLabel(item.materials);
    setForm((f) => ({
      ...f,
      supplier_slug: supplier.slug,
      supplier_id: supplier.supplier_id || supplier.slug.toUpperCase(),
      supplier_name: supplier.supplier_name,
      supplier_item_code: item.primary_supplier_item_code || item.raw_model || "",
      material: pickedMaterial,
      size: f.size || (item.size || ""),
      // Heuristic cost: take the first listed CNY price as a starting point;
      // user converts to SGD or overrides as needed.
      cost_price:
        f.cost_price ||
        (item.price_options_cny && item.price_options_cny.length > 0
          ? String(item.price_options_cny[0])
          : ""),
      cost_currency:
        f.cost_price
          ? f.cost_currency
          : item.price_options_cny && item.price_options_cny.length > 0
            ? "CNY"
            : f.cost_currency,
    }));
  };

  const draftDescriptionWithAi = async () => {
    setAiNote(null);
    setLocalError(null);
    setAiBusy(true);
    try {
      const additionalMaterials = mergePendingAdditionalMaterial(
        form.material,
        form.additional_materials,
        form.additional_material_input,
      );
      const resp = await masterDataApi.aiDescribeProduct({
        product_type: form.product_type,
        material: composeMaterialText(form.material, additionalMaterials),
        size: form.size.trim() || null,
        supplier_name: form.supplier_name.trim() || null,
        supplier_item_code: form.supplier_item_code.trim() || null,
        sourcing_strategy: form.sourcing_strategy || null,
      });
      setForm((f) => ({
        ...f,
        description: resp.description,
        long_description: resp.long_description,
      }));
      setSuggestedName(resp.suggested_name || null);
      setAiNote(
        resp.is_fallback
          ? "AI unavailable — used a deterministic template. Edit before saving."
          : `Drafted with ${resp.model || "DeepSeek V3"} — please review.`,
      );
    } catch (err) {
      setAiNote(`AI assist failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setAiBusy(false);
    }
  };

  const submit = () => {
    setLocalError(null);
    if (!form.sourcing_strategy) {
      setLocalError("Pick where this inventory came from.");
      return;
    }
    if (requiresSupplier && !form.supplier_slug) {
      setLocalError("Pick a supplier from the supplier panel before saving.");
      return;
    }
    if (!form.description.trim()) {
      setLocalError("Description is required (or click 'Draft with AI').");
      return;
    }
    const exactNameMatch = existingProducts.find(
      (p) => normaliseIdentity(p.description) === normaliseIdentity(form.description),
    );
    if (!variantMode && exactNameMatch) {
      setLocalError(`Item name already exists on ${exactNameMatch.sku_code}. Use that SKU or add a variant.`);
      return;
    }
    if (!form.material.trim()) {
      setLocalError("Primary material is required.");
      return;
    }
    if (variantMode) {
      if (!form.variant_of_sku) {
        setLocalError("Pick the existing SKU this variant belongs to.");
        return;
      }
      if (!form.variant_label.trim()) {
        setLocalError("Variant label is required.");
        return;
      }
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
    let sequenceOverride: number | null = null;
    if (form.sequence_override.trim()) {
      const parsed = Number.parseInt(form.sequence_override, 10);
      if (!Number.isFinite(parsed) || parsed < 1 || parsed > 999_999) {
        setLocalError("Sequence override must be a whole number between 1 and 999999.");
        return;
      }
      sequenceOverride = parsed;
      // Cross-check the live preview: if the server already told us this
      // override collides, refuse client-side instead of letting the create
      // call return 409 after the user has filled out the rest of the form.
      if (
        previewState.data
        && previewState.data.sequence_source === "override"
        && previewState.data.collision
      ) {
        const which = previewState.data.collision === "sku_code" ? "SKU" : "PLU";
        setLocalError(
          `Sequence ${sequenceOverride} is already taken — the ${which} for `
          + `that number is in use. Pick a different number or clear the field.`,
        );
        return;
      }
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
    const additionalMaterials = mergePendingAdditionalMaterial(
      form.material,
      form.additional_materials,
      form.additional_material_input,
    );

    const selectedCategory =
      PRODUCT_CATEGORY_OPTIONS.find((c) => c.value === form.category)
      || PRODUCT_CATEGORY_OPTIONS[1];
    const req: CreateProductRequest = {
      description: form.description.trim(),
      long_description: form.long_description.trim() || null,
      // Server stores the human label ("Homeware" / "Minerals" / "Jewellery")
      // so reports + downstream filters group on a stable display string.
      category: selectedCategory.label,
      product_type: form.product_type,
      material: form.material,
      additional_materials: additionalMaterials,
      size: form.size.trim() || null,
      supplier_id: requiresSupplier ? form.supplier_id || null : null,
      supplier_name: requiresSupplier ? form.supplier_name.trim() || null : null,
      supplier_item_code: requiresSupplier ? form.supplier_item_code.trim() || null : null,
      cost_price: cost,
      cost_currency: cost !== null ? form.cost_currency || "SGD" : null,
      qty_on_hand: qty,
      // Pass through the picked location; server falls back to the legacy
      // jewel_changi default when omitted. Keep `null` instead of `""` to
      // make the "user hasn't picked" case explicit on the wire.
      stocking_location: form.stocking_location || null,
      sourcing_strategy: form.sourcing_strategy,
      // inventory_type derives from sourcing_strategy server-side, so don't send it.
      notes: form.notes.trim() || null,
      retail_price: retail,
      variant_of_sku: variantMode ? form.variant_of_sku : null,
      variant_label: variantMode ? form.variant_label.trim() : null,
      sequence_override: sequenceOverride,
    };
    onSubmit(req, images, { print_label_now: form.print_label_now });
  };

  const selectedSupplier = suppliers.find((s) => s.slug === form.supplier_slug) || null;
  const selectedCategoryLabel =
    PRODUCT_CATEGORY_OPTIONS.find((c) => c.value === form.category)?.label || "Homeware";
  const summaryMaterials = mergePendingAdditionalMaterial(
    form.material,
    form.additional_materials,
    form.additional_material_input,
  );
  const summaryMaterialText = composeMaterialText(form.material, summaryMaterials);
  const summaryPriceNumber = Number.parseFloat(form.retail_price);
  const summaryPrice = form.publish_now && Number.isFinite(summaryPriceNumber) && summaryPriceNumber > 0
    ? `S$${summaryPriceNumber.toFixed(2)}`
    : "Set later";

  // In modal mode the form is a fixed overlay; in page mode it sits flush in
  // the routed page so the browser back button + URL drive the close. The
  // inner card layout (header, two-pane grid, footer) is identical either way.
  const isPage = mode === "page";
  const overlayClass = isPage
    ? "flex w-full justify-center"
    : "fixed inset-0 z-[80] flex items-stretch justify-center bg-slate-950/45 p-0 backdrop-blur-sm sm:items-center sm:p-4";
  const cardClass = isPage
    ? "flex w-full max-w-6xl flex-col bg-white"
    : "flex h-[100dvh] max-h-[100dvh] w-full max-w-6xl flex-col overflow-hidden bg-white shadow-2xl sm:h-auto sm:max-h-[92vh] sm:rounded-2xl";

  return (
    <div className={overlayClass}>
      <div className={cardClass}>
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-200 px-4 py-4 sm:items-center sm:px-6">
          <div className="min-w-0">
            <div className="text-xl font-semibold text-slate-950">Create inventory</div>
            <div className="mt-1 text-sm text-slate-500">SKU and PLU are allocated automatically.</div>
          </div>
          {!isPage && (
            <button onClick={onCancel} className="shrink-0 rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-600 hover:bg-slate-50" disabled={submitting}>
              Cancel
            </button>
          )}
        </header>

        <div className="grid flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_360px] lg:overflow-hidden">
          {/* ── Form pane ───────────────────────────────────────────────── */}
          <div className="flex-1 space-y-4 overflow-visible bg-white px-4 py-4 text-sm sm:px-6 sm:py-5 lg:overflow-auto">
            {taxonomyError && (
              <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
                Couldn’t load taxonomy from server: {taxonomyError}
              </div>
            )}

            {draftBanner && (
              <div className="mb-3 flex items-center justify-between gap-3 rounded-md border border-blue-300 bg-blue-50 p-2 text-xs text-blue-900">
                <span>
                  You have an unfinished draft saved {relativeTime(draftBanner.saved_at)}.
                </span>
                <span className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={resumeDraft}
                    className="rounded border border-blue-400 bg-white px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-100"
                  >
                    Resume
                  </button>
                  <button
                    type="button"
                    onClick={discardDraft}
                    className="rounded border border-blue-200 bg-white px-2 py-1 text-xs text-blue-700 hover:bg-blue-100"
                  >
                    Discard
                  </button>
                </span>
              </div>
            )}

            {variantMode && (
              <div className="mb-4 rounded-md border border-teal-200 bg-teal-50 p-3">
                <div className="mb-2 text-sm font-semibold text-teal-900">Add as variant of existing SKU</div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_180px]">
                  <select
                    value={form.variant_of_sku}
                    onChange={(e) => update("variant_of_sku", e.target.value)}
                    disabled={submitting}
                    className="w-full rounded border border-teal-300 px-2 py-1 text-sm"
                  >
                    <option value="">Pick parent SKU…</option>
                    {variantParents.map((p) => (
                      <option key={p.sku_code} value={p.sku_code}>
                        {p.sku_code} — {p.description || p.product_type || "Product"}
                      </option>
                    ))}
                  </select>
                  <input
                    type="text"
                    placeholder="Variant label *"
                    value={form.variant_label}
                    onChange={(e) => update("variant_label", e.target.value)}
                    disabled={submitting}
                    className="w-full rounded border border-teal-300 px-2 py-1 text-sm"
                  />
                </div>
              </div>
            )}

            {/* Origin picker */}
            <section className="rounded-xl border border-slate-200 bg-slate-50/50 p-4">
              <div className="mb-3">
                <div className="text-sm font-semibold text-slate-900">Source</div>
                <div className="text-xs text-slate-500">How this item entered the business.</div>
              </div>
              <div className="mb-1 text-sm font-semibold text-gray-800">Inventory origin *</div>
              <div className="grid grid-cols-1 gap-2">
                {sourcingOptions.map((opt) => (
                  <label
                    key={opt.value}
                    className={`flex cursor-pointer items-start gap-2 rounded-md border p-2 text-sm transition ${
                      form.sourcing_strategy === opt.value
                        ? "border-emerald-500 bg-emerald-50"
                        : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <input
                      type="radio"
                      name="sourcing_strategy"
                      value={opt.value}
                      checked={form.sourcing_strategy === opt.value}
                      onChange={() => update("sourcing_strategy", opt.value)}
                      disabled={submitting}
                      className="mt-1"
                    />
                    <div>
                      <div className="font-semibold text-gray-900">{opt.label}</div>
                      <div className="text-xs text-gray-600">{opt.description}</div>
                    </div>
                  </label>
                ))}
                {sourcingOptions.length === 0 && !taxonomyError && (
                  <div className="text-xs text-gray-500">Loading origin choices…</div>
                )}
              </div>
            </section>

            {/* Supplier link (only when required) */}
            {requiresSupplier && (
              <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 p-3">
                <div className="mb-2 text-sm font-semibold text-blue-900">Linked supplier</div>
                {selectedSupplier ? (
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <div>
                      <div className="font-semibold text-gray-900">
                        {selectedSupplier.supplier_name}
                      </div>
                      <div className="text-xs text-gray-600">
                        {form.supplier_item_code
                          ? `Item code: ${form.supplier_item_code}`
                          : "No supplier item code yet — pick from catalog →"}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => pickSupplier("")}
                      disabled={submitting}
                      className="text-xs text-blue-700 hover:underline"
                    >
                      Change supplier
                    </button>
                  </div>
                ) : (
                  <div className="text-xs text-gray-700">
                    Pick a supplier from the panel on the right →
                  </div>
                )}
                <div className="mt-3">
                  <Field label="Supplier item code">
                    <div className="flex gap-1">
                      <input
                        type="text"
                        value={form.supplier_item_code}
                        onChange={(e) => update("supplier_item_code", e.target.value)}
                        disabled={submitting}
                        className="w-full rounded border border-blue-200 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
                      />
                      <BarcodeScannerButton
                        disabled={submitting}
                        onDetected={(code) => update("supplier_item_code", code)}
                      />
                    </div>
                  </Field>
                </div>
              </div>
            )}

            {/* Structured fields */}
            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-3">
                <div className="text-sm font-semibold text-slate-900">Product & materials</div>
                <div className="text-xs text-slate-500">Category, product type, materials, stock, and cost.</div>
              </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Category *" hint="Top-level product line.">
                <select
                  value={form.category}
                  onChange={(e) => updateCategory(e.target.value as ProductCategoryValue)}
                  disabled={submitting}
                  className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
                >
                  {PRODUCT_CATEGORY_OPTIONS.map((c) => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </select>
              </Field>
              <Field label="Product type *">
                <select
                  value={form.product_type}
                  onChange={(e) => update("product_type", e.target.value)}
                  disabled={submitting}
                  className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
                >
                  {(PRODUCT_CATEGORY_OPTIONS.find((c) => c.value === form.category)
                    ?? PRODUCT_CATEGORY_OPTIONS[1]
                  ).product_types.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </Field>
              <Field label="Primary material *" hint="First material drives the SKU. Type any new material if it is not listed.">
                <input
                  list="masterdata-material-options"
                  value={form.material}
                  onChange={(e) => updatePrimaryMaterial(e.target.value)}
                  onBlur={() => {
                    const cleaned = cleanMaterialLabel(form.material);
                    updatePrimaryMaterial(cleaned || "Mixed Materials");
                  }}
                  disabled={submitting}
                  className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
                />
                <datalist id="masterdata-material-options">
                  {MATERIAL_OPTIONS.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </datalist>
              </Field>
              <Field label="Other materials" hint="Add as many extra materials as needed. Type custom materials here too.">
                <div className="flex gap-1">
                  <input
                    list="masterdata-additional-material-options"
                    value={form.additional_material_input}
                    onChange={(e) => update("additional_material_input", e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addAdditionalMaterial();
                      }
                    }}
                    disabled={submitting}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
                  />
                  <button
                    type="button"
                    onClick={() => addAdditionalMaterial()}
                    disabled={submitting || !form.additional_material_input.trim()}
                    className="rounded border border-gray-300 px-2 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Add
                  </button>
                </div>
                <datalist id="masterdata-additional-material-options">
                  {additionalMaterialOptions.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </datalist>
                {form.additional_materials.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {form.additional_materials.map((material) => (
                      <button
                        key={material}
                        type="button"
                        onClick={() => removeAdditionalMaterial(material)}
                        disabled={submitting}
                        className="rounded-full border border-gray-300 bg-gray-50 px-2 py-0.5 text-xs text-gray-700 hover:bg-gray-100 disabled:opacity-60"
                        title="Remove material"
                      >
                        {material} x
                      </button>
                    ))}
                  </div>
                )}
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
              <Field
                label="Stocking location"
                hint={formatStockingLocation(form.stocking_location)}
              >
                <div className="flex flex-wrap gap-2 rounded border border-gray-200 bg-gray-50 p-2">
                  {CANONICAL_LOCATION_OPTIONS.map((loc) => {
                    const selectedLocations = parseStockingLocation(form.stocking_location);
                    return (
                      <label key={loc.value} className="flex items-center gap-1 rounded bg-white px-2 py-1 text-xs text-gray-700 shadow-sm">
                        <input
                          type="checkbox"
                          checked={selectedLocations.includes(loc.value)}
                          onChange={(e) => {
                            const next = e.target.checked
                              ? [...selectedLocations, loc.value]
                              : selectedLocations.filter((value) => value !== loc.value);
                            update("stocking_location", encodeStockingLocation(next));
                          }}
                          disabled={submitting}
                        />
                        {loc.label}
                      </label>
                    );
                  })}
                </div>
              </Field>
              <Field label={`Cost price (${form.cost_currency || "SGD"})`} hint="Auto-converted to SGD downstream when needed.">
                <div className="flex gap-1">
                  <input
                    type="number"
                    min={0}
                    step="0.01"
                    value={form.cost_price}
                    onChange={(e) => update("cost_price", e.target.value)}
                    disabled={submitting}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
                  />
                  <select
                    value={form.cost_currency}
                    onChange={(e) => update("cost_currency", e.target.value)}
                    disabled={submitting}
                    className="rounded border border-gray-300 px-1 py-1 text-xs"
                  >
                    <option value="SGD">SGD</option>
                    <option value="CNY">CNY</option>
                    <option value="USD">USD</option>
                  </select>
                </div>
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
            </section>

            {/* Description with AI assist */}
            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-800">
                  Customer-facing copy *
                </span>
                <button
                  type="button"
                  onClick={draftDescriptionWithAi}
                  disabled={submitting || aiBusy}
                  className="rounded-md border border-purple-300 bg-purple-50 px-3 py-1 text-xs font-semibold text-purple-800 hover:bg-purple-100 disabled:opacity-60"
                >
                  {aiBusy ? "Drafting…" : "Draft with DeepSeek V3"}
                </button>
              </div>
              {suggestedName && suggestedName !== form.description && (
                <div className="mb-2 flex flex-wrap items-center gap-2 rounded border border-purple-200 bg-purple-50 px-2 py-1 text-xs">
                  <span className="text-purple-900">Standardised name suggestion:</span>
                  <span className="font-mono text-purple-900">{suggestedName}</span>
                  <button
                    type="button"
                    onClick={() => update("description", suggestedName)}
                    disabled={submitting}
                    className="rounded border border-purple-300 bg-white px-2 py-0.5 text-[11px] font-semibold text-purple-800 hover:bg-purple-100 disabled:opacity-60"
                    title={`Use "${suggestedName}" as the short description`}
                  >
                    Use this name
                  </button>
                  <button
                    type="button"
                    onClick={() => setSuggestedName(null)}
                    className="text-[11px] text-purple-700 hover:underline"
                  >
                    Dismiss
                  </button>
                </div>
              )}
              <Field label="Short description" hint="Max 120 chars. Shown on labels and POS.">
                <input
                  type="text"
                  value={form.description}
                  onChange={(e) => update("description", e.target.value)}
                  maxLength={120}
                  disabled={submitting}
                  className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
                />
              </Field>
              <div className="mt-2">
                <Field label="Long description" hint="Optional. Used in product detail views.">
                  <textarea
                    value={form.long_description}
                    onChange={(e) => update("long_description", e.target.value)}
                    rows={3}
                    disabled={submitting}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
                  />
                </Field>
              </div>
              {aiNote && (
                <div className="mt-2 text-xs text-gray-600">{aiNote}</div>
              )}

              {/* Dedup / similar-product warning panel */}
              {!variantMode && !similarDismissed && (similarBusy || similarMatches.length > 0 || similarError) && (
                <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="text-sm font-semibold text-amber-900">
                      {similarBusy
                        ? "Checking for similar items…"
                        : similarMatches.length > 0
                          ? `Possible duplicates in your master catalog (${similarMatches.length})`
                          : "Catalog check"}
                    </div>
                    <div className="flex items-center gap-2">
                      {similarMatches.length > 0 && !similarAiUsed && (
                        <button
                          type="button"
                          onClick={() => void runAiVerdictPass()}
                          disabled={similarBusy}
                          className="rounded border border-purple-300 bg-white px-2 py-0.5 text-xs font-semibold text-purple-800 hover:bg-purple-50 disabled:opacity-60"
                          title="Send the top hits to DeepSeek V3 for a duplicate / variant / unrelated verdict"
                        >
                          Double-check with AI
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setSimilarDismissed(true)}
                        className="text-xs text-amber-800 hover:underline"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                  {similarError && (
                    <div className="mb-2 text-xs text-red-700">
                      Catalog check failed: {similarError}
                    </div>
                  )}
                  {similarAiUsed && similarMatches.length > 0 && (
                    <div className="mb-2 text-[11px] text-purple-700">
                      AI verdicts applied (DeepSeek V3). Manually review before
                      acting — verdicts are guidance, not authoritative.
                    </div>
                  )}
                  {similarMatches.length === 0 && !similarBusy && !similarError && (
                    <div className="text-xs text-amber-800">
                      No close matches in the catalog — safe to proceed.
                    </div>
                  )}
                  {similarMatches.length > 0 && (
                    <ul className="space-y-2">
                      {similarMatches.map((m) => {
                        const verdictColor =
                          m.verdict === "duplicate"
                            ? "text-red-800 bg-red-100 border-red-300"
                            : m.verdict === "variant"
                              ? "text-teal-800 bg-teal-100 border-teal-300"
                              : m.verdict === "unrelated"
                                ? "text-gray-700 bg-gray-100 border-gray-300"
                                : "text-amber-800 bg-amber-100 border-amber-300";
                        return (
                          <li
                            key={m.sku_code}
                            className={`rounded border ${verdictColor.split(" ").slice(2).join(" ")} bg-white p-2 text-xs`}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="flex-1">
                                <div className="font-mono text-[11px] text-gray-600">
                                  SKU {m.sku_code}
                                  {" · "}
                                  <span className={`rounded px-1 ${verdictColor}`}>
                                    {m.verdict || `${Math.round(m.score * 100)}% match`}
                                  </span>
                                </div>
                                <div className="font-semibold text-gray-900">
                                  {m.description}
                                </div>
                                <div className="mt-0.5 text-[11px] text-gray-600">
                                  {[m.material, m.size, m.product_type]
                                    .filter(Boolean)
                                    .join(" · ")}
                                </div>
                                <div className="mt-1 text-[11px] italic text-gray-700">
                                  {m.reason}
                                </div>
                              </div>
                              <div className="flex flex-col gap-1">
                                <button
                                  type="button"
                                  onClick={() => onPickExisting(m.sku_code)}
                                  className="rounded border border-amber-400 bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900 hover:bg-amber-200"
                                  title="Cancel this create — open the existing SKU in the grid instead"
                                >
                                  Use this SKU
                                </button>
                                <button
                                  type="button"
                                  onClick={() => onPickAsVariantOf(m.sku_code)}
                                  className="rounded border border-teal-400 bg-teal-100 px-2 py-0.5 text-[11px] font-semibold text-teal-900 hover:bg-teal-200"
                                  title="Re-open the modal in variant mode with this SKU as the parent"
                                >
                                  Add as variant
                                </button>
                              </div>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              )}
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-2 text-sm font-semibold text-gray-800">Product photos</div>
              <label
                className="flex cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-gray-300 bg-gray-50 px-3 py-4 text-center text-xs text-gray-600 hover:bg-gray-100"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const picked = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith("image/"));
                  setImages((prev) => [...prev, ...picked].slice(0, 5));
                }}
              >
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    const picked = Array.from(e.target.files || []).filter((f) => f.type.startsWith("image/"));
                    setImages((prev) => [...prev, ...picked].slice(0, 5));
                    e.currentTarget.value = "";
                  }}
                />
                Drop 1-5 photos here, or choose files
              </label>
              {images.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {images.map((file, idx) => (
                    <div key={`${file.name}-${idx}`} className="flex items-center gap-2 rounded border border-gray-200 bg-white px-2 py-1 text-xs">
                      <span className="max-w-[160px] truncate">{file.name}</span>
                      <button
                        type="button"
                        onClick={() => setImages((prev) => prev.filter((_, i) => i !== idx))}
                        className="text-gray-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Live SKU + barcode (PLU) preview */}
            <section className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm">
              <div className="mb-2 flex items-center justify-between">
                <div className="font-semibold text-blue-900">SKU &amp; barcode preview</div>
                {previewState.loading && (
                  <span className="text-xs text-blue-700">Computing…</span>
                )}
              </div>
              {previewState.error ? (
                <div className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-800">
                  {previewState.error}
                </div>
              ) : previewState.data ? (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-blue-700">SKU code</div>
                    <div className="font-mono text-base text-gray-900">
                      {previewState.data.sku_code}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wide text-blue-700">Barcode (EAN-8 PLU)</div>
                    <div className="font-mono text-base text-gray-900">
                      {previewState.data.nec_plu}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wide text-blue-700">Sequence</div>
                    <div className="font-mono text-base text-gray-900">
                      {previewState.data.sequence}
                      {previewState.data.sequence_source === "auto_collision_skip" && (
                        <span className="ml-1 text-xs text-amber-700">
                          (skipped past collisions)
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-xs text-blue-700">
                  Pick a product type and material to see the codes that will
                  be assigned.
                </div>
              )}
              {previewState.data?.collision && (
                <div className="mt-2 rounded border border-red-300 bg-red-50 p-2 text-xs text-red-800">
                  Sequence {previewState.data.sequence} is already taken — the{" "}
                  {previewState.data.collision === "sku_code" ? "SKU" : "PLU"}{" "}
                  for that number is in use. Pick a different number, or clear
                  the override to let the server pick the next free seq.
                </div>
              )}
              <div className="mt-3 border-t border-blue-200 pt-2">
                <label className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-semibold text-blue-900">
                    Sequence override (optional):
                  </span>
                  <input
                    type="number"
                    min={1}
                    max={999_999}
                    step={1}
                    value={form.sequence_override}
                    onChange={(e) => update("sequence_override", e.target.value)}
                    disabled={submitting}
                    placeholder="auto"
                    className="w-24 rounded border border-blue-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
                  />
                  <span className="text-xs text-gray-600">
                    Leave blank to auto-allocate. Use a specific number only
                    when matching a pre-printed barcode label (e.g. claim 1–13
                    for the Hengwei homeware tags already on the shop floor).
                  </span>
                </label>
              </div>
            </section>

            {/* Optional inline publish */}
            <section className="rounded-xl border border-amber-200 bg-amber-50 p-4">
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
              <label className="mt-3 flex items-center gap-2 border-t border-amber-200 pt-2 text-sm font-semibold text-amber-900">
                <input
                  type="checkbox"
                  checked={form.print_label_now}
                  onChange={(e) => update("print_label_now", e.target.checked)}
                  disabled={submitting}
                />
                Generate Brother P-touch label xlsx for this SKU
              </label>
              {form.print_label_now && (
                <div className="mt-1 pl-6 text-xs text-gray-600">
                  After creating the row, the new PLU's label sheet downloads
                  automatically. Open in Brother P-touch Editor and print.
                </div>
              )}
            </section>

            {(localError || errorMessage) && (
              <div className="mt-4 rounded-md border border-red-300 bg-red-50 p-2 text-sm text-red-800">
                {localError || errorMessage}
              </div>
            )}
          </div>

          {/* ── Live summary + supplier-catalog pane ───────────────────── */}
          <aside className="flex min-h-0 flex-col border-t border-slate-200 bg-slate-50/70 lg:border-l lg:border-t-0">
            <div className="border-b border-slate-200 bg-white/90 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Create summary</div>
              <div className="mt-3 space-y-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Item</div>
                  <div className="mt-1 text-sm font-semibold text-slate-950">
                    {form.description.trim() || `${form.product_type} in ${form.material}`}
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {selectedCategoryLabel} · {form.product_type}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
                    <div className="font-semibold text-slate-500">Material</div>
                    <div className="mt-1 break-words text-slate-900">{summaryMaterialText}</div>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
                    <div className="font-semibold text-slate-500">Location</div>
                    <div className="mt-1 text-slate-900">{formatStockingLocation(form.stocking_location)}</div>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
                    <div className="font-semibold text-slate-500">SKU</div>
                    <div className="mt-1 font-mono text-slate-900">
                      {previewState.loading ? "Computing" : previewState.data?.sku_code || "Pending"}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
                    <div className="font-semibold text-slate-500">PLU</div>
                    <div className="mt-1 font-mono text-slate-900">
                      {previewState.loading ? "Computing" : previewState.data?.nec_plu || "Pending"}
                    </div>
                  </div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs">
                  <div className="font-semibold text-slate-500">POS</div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <span className="rounded-full bg-white px-2 py-0.5 font-semibold text-slate-700 ring-1 ring-slate-200">
                      {summaryPrice}
                    </span>
                    {form.print_label_now && (
                      <span className="rounded-full bg-blue-100 px-2 py-0.5 font-semibold text-blue-700">
                        Label xlsx
                      </span>
                    )}
                    {images.length > 0 && (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 font-semibold text-emerald-700">
                        {images.length} photo{images.length === 1 ? "" : "s"}
                      </span>
                    )}
                  </div>
                </div>
                {requiresSupplier && (
                  <div className="rounded-lg border border-blue-200 bg-blue-50 p-2 text-xs text-blue-900">
                    <div className="font-semibold">Supplier required</div>
                    <div className="mt-1">
                      {selectedSupplier
                        ? `${selectedSupplier.supplier_name}${form.supplier_item_code ? ` · ${form.supplier_item_code}` : ""}`
                        : "Pick a supplier below before saving."}
                    </div>
                  </div>
                )}
              </div>
            </div>
            {requiresSupplier ? (
              <SupplierCatalogPane
                suppliers={suppliers}
                selectedSlug={form.supplier_slug}
                onPickSupplier={pickSupplier}
                onPickItem={applyCatalogPick}
                disabled={submitting}
                embedded
              />
            ) : (
              <div className="flex flex-1 items-center justify-center p-4 text-center text-xs text-slate-500">
                Supplier catalog appears here when the selected source needs a supplier.
              </div>
            )}
          </aside>
        </div>

        <footer className="flex shrink-0 flex-col gap-3 border-t border-gray-200 bg-white/95 px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] shadow-[0_-10px_24px_rgba(15,23,42,0.06)] sm:flex-row sm:items-center sm:justify-between sm:px-5 sm:pb-3">
          <div className="text-xs text-gray-500">
            SKU code &amp; barcode (PLU) are auto-allocated to keep them aligned.
          </div>
          <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center">
            <button
              onClick={onCancel}
              disabled={submitting}
              className="min-h-11 rounded-lg border border-gray-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-gray-50 disabled:opacity-60 sm:min-h-0 sm:py-1.5"
            >
              Cancel
            </button>
            <button
              onClick={submit}
              disabled={submitting || !form.description.trim() || !form.sourcing_strategy}
              className="min-h-11 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:bg-gray-400 sm:min-h-0 sm:py-1.5"
            >
              {submitting
                ? "Adding…"
                : [
                    "Add inventory",
                    form.publish_now ? "publish to POS" : null,
                    form.print_label_now ? "download label" : null,
                  ]
                    .filter(Boolean)
                    .join(" & ")}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

/**
 * Right-hand pane shown when the chosen sourcing strategy requires a supplier.
 *
 * Top: supplier picker (folders that have a `catalog_products.json` snapshot
 * are clearly flagged "browseable"; the others can still be selected so staff
 * aren't blocked when adding a SKU from a supplier that doesn't ship a price
 * list).
 *
 * Bottom: catalog browser + inline "add new entry" form for the picked
 * supplier — so the catalog grows naturally as staff discover new items
 * during inventory creation.
 */
export function SupplierCatalogPane({
  suppliers,
  selectedSlug,
  onPickSupplier,
  onPickItem,
  disabled,
  embedded = false,
}: {
  suppliers: SupplierSummary[];
  selectedSlug: string;
  onPickSupplier: (slug: string) => void;
  onPickItem: (item: SupplierCatalogProduct, supplier: SupplierSummary) => void;
  disabled: boolean;
  embedded?: boolean;
}) {
  const [query, setQuery] = useState("");
  // Debounce keystrokes so we don't fire one /catalog request per character —
  // typical staff query is 4-8 chars and they type fast.
  const debouncedQuery = useDebouncedValue(query, 300);
  const searching = query !== debouncedQuery;
  const [items, setItems] = useState<SupplierCatalogProduct[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState({
    supplier_item_code: "",
    display_name: "",
    materials: "",
    size: "",
    color: "",
    unit_price_cny: "",
  });
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const supplier = suppliers.find((s) => s.slug === selectedSlug) || null;

  const refreshCatalog = useCallback(
    async (slug: string, q: string) => {
      if (!slug) {
        setItems([]);
        return;
      }
      setLoading(true);
      setLoadError(null);
      try {
        const resp = await masterDataApi.getSupplierCatalog(slug, { query: q || undefined, limit: 50 });
        setItems(resp.products);
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!selectedSlug) {
      setItems([]);
      return;
    }
    if (!supplier?.has_catalog) {
      setItems([]);
      return;
    }
    void refreshCatalog(selectedSlug, debouncedQuery);
    // refreshCatalog identity is stable; debounced query / slug changes drive the call
  }, [selectedSlug, debouncedQuery, supplier?.has_catalog, refreshCatalog]);

  const submitAdd = async () => {
    if (!selectedSlug) return;
    setAddError(null);
    if (!addForm.supplier_item_code.trim()) {
      setAddError("Supplier item code is required.");
      return;
    }
    setAddBusy(true);
    try {
      const cny = addForm.unit_price_cny.trim()
        ? Number.parseFloat(addForm.unit_price_cny)
        : null;
      const newEntry = await masterDataApi.addSupplierCatalogEntry(selectedSlug, {
        supplier_item_code: addForm.supplier_item_code.trim(),
        display_name: addForm.display_name.trim() || null,
        materials: addForm.materials.trim() || null,
        size: addForm.size.trim() || null,
        color: addForm.color.trim() || null,
        unit_price_cny: cny !== null && Number.isFinite(cny) ? cny : null,
      });
      setShowAdd(false);
      setAddForm({
        supplier_item_code: "",
        display_name: "",
        materials: "",
        size: "",
        color: "",
        unit_price_cny: "",
      });
      // Pull the newly added row to the top so the user can pick it
      // immediately, and refresh the rest in case the listing changed.
      if (supplier) {
        onPickItem(newEntry, supplier);
      }
      await refreshCatalog(selectedSlug, "");
      setQuery("");
    } catch (err) {
      setAddError(err instanceof Error ? err.message : String(err));
    } finally {
      setAddBusy(false);
    }
  };

  return (
    <aside className={embedded ? "flex min-h-[360px] flex-1 flex-col bg-gray-50" : "flex h-full flex-col border-l border-gray-200 bg-gray-50"}>
      <div className="border-b border-gray-200 px-3 py-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Supplier catalog
        </div>
        <select
          value={selectedSlug}
          onChange={(e) => onPickSupplier(e.target.value)}
          disabled={disabled}
          className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
        >
          <option value="">— Pick supplier —</option>
          {suppliers.map((s) => (
            <option key={s.slug} value={s.slug}>
              {s.supplier_name}
              {s.has_catalog ? ` (${s.product_count})` : " · no catalog yet"}
            </option>
          ))}
        </select>
      </div>

      {!selectedSlug ? (
        <div className="flex flex-1 items-center justify-center px-4 text-center text-xs text-gray-500">
          Pick a supplier to browse their catalog or add a new entry.
        </div>
      ) : (
        <>
          <div className="border-b border-gray-200 px-3 py-2">
            <div className="flex gap-1">
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search code, model, material…"
                disabled={disabled || !supplier?.has_catalog}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-100"
              />
              <BarcodeScannerButton
                disabled={disabled || !supplier?.has_catalog}
                onDetected={(code) => setQuery(code)}
                title="Scan barcode to search supplier catalog"
              />
            </div>
            {searching && (
              <div className="mt-1 text-[11px] text-gray-500">Searching…</div>
            )}
            {!supplier?.has_catalog && (
              <div className="mt-1 text-[11px] text-gray-500">
                No structured catalog yet — add the first entry below.
              </div>
            )}
          </div>

          <div className="flex-1 overflow-auto">
            {loading && <div className="px-3 py-2 text-xs text-gray-500">Loading…</div>}
            {loadError && (
              <div className="m-2 rounded border border-red-300 bg-red-50 p-2 text-xs text-red-800">
                {loadError}
              </div>
            )}
            {!loading && items.length === 0 && supplier?.has_catalog && (
              <div className="px-3 py-2 text-xs text-gray-500">
                No matches. Try a different search or add a new entry.
              </div>
            )}
            <ul className="divide-y divide-gray-200">
              {items.map((item) => (
                <li key={item.catalog_product_id || item.primary_supplier_item_code}>
                  <button
                    type="button"
                    onClick={() => supplier && onPickItem(item, supplier)}
                    disabled={disabled}
                    className="block w-full px-3 py-2 text-left text-xs hover:bg-blue-50 disabled:opacity-60"
                  >
                    <div className="font-mono font-semibold text-gray-900">
                      {item.primary_supplier_item_code || item.raw_model}
                    </div>
                    <div className="text-gray-700">
                      {item.display_name || item.materials || "—"}
                    </div>
                    <div className="text-gray-500">
                      {item.size || ""}{item.size && item.color ? " · " : ""}{item.color || ""}
                      {item.price_options_cny && item.price_options_cny.length > 0
                        ? ` · ¥${item.price_options_cny[0]}`
                        : ""}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="border-t border-gray-200 bg-white px-3 py-2">
            {!showAdd ? (
              <button
                type="button"
                onClick={() => setShowAdd(true)}
                disabled={disabled}
                className="w-full rounded-md border border-dashed border-blue-300 px-2 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-60"
              >
                + Add this item to {supplier?.supplier_name || "supplier"} catalog
              </button>
            ) : (
              <div className="space-y-1">
                <div className="text-xs font-semibold text-gray-800">
                  New catalog entry
                </div>
                <div className="flex gap-1">
                  <input
                    type="text"
                    placeholder="Supplier item code *"
                    value={addForm.supplier_item_code}
                    onChange={(e) => setAddForm((f) => ({ ...f, supplier_item_code: e.target.value }))}
                    disabled={addBusy}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-xs font-mono"
                  />
                  <BarcodeScannerButton
                    disabled={addBusy}
                    onDetected={(code) => setAddForm((f) => ({ ...f, supplier_item_code: code }))}
                    title="Scan barcode to fill supplier item code"
                  />
                </div>
                <input
                  type="text"
                  placeholder="Display name"
                  value={addForm.display_name}
                  onChange={(e) => setAddForm((f) => ({ ...f, display_name: e.target.value }))}
                  disabled={addBusy}
                  className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
                />
                <div className="flex gap-1">
                  <input
                    type="text"
                    placeholder="Materials"
                    value={addForm.materials}
                    onChange={(e) => setAddForm((f) => ({ ...f, materials: e.target.value }))}
                    disabled={addBusy}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
                  />
                  <input
                    type="text"
                    placeholder="Size"
                    value={addForm.size}
                    onChange={(e) => setAddForm((f) => ({ ...f, size: e.target.value }))}
                    disabled={addBusy}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
                  />
                </div>
                <div className="flex gap-1">
                  <input
                    type="text"
                    placeholder="Color"
                    value={addForm.color}
                    onChange={(e) => setAddForm((f) => ({ ...f, color: e.target.value }))}
                    disabled={addBusy}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
                  />
                  <input
                    type="number"
                    min={0}
                    step="0.01"
                    placeholder="¥ unit price"
                    value={addForm.unit_price_cny}
                    onChange={(e) => setAddForm((f) => ({ ...f, unit_price_cny: e.target.value }))}
                    disabled={addBusy}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
                  />
                </div>
                {addError && (
                  <div className="rounded border border-red-300 bg-red-50 p-1 text-[11px] text-red-800">
                    {addError}
                  </div>
                )}
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => setShowAdd(false)}
                    disabled={addBusy}
                    className="flex-1 rounded border border-gray-300 px-2 py-1 text-xs hover:bg-gray-100"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={submitAdd}
                    disabled={addBusy}
                    className="flex-1 rounded bg-blue-600 px-2 py-1 text-xs font-semibold text-white hover:bg-blue-700 disabled:bg-gray-400"
                  >
                    {addBusy ? "Saving…" : "Add to catalog"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </aside>
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
