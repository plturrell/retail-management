/**
 * Shared helpers for Master Data pages.
 *
 * Extracted from MasterDataPage so that the create-product flow (which now
 * lives in a separate component + a parallel /master-data/add route) can
 * share the same constants, draft persistence, location/material composition
 * and identity-normalisation logic without circular imports.
 *
 * Nothing here is behaviour-new — every export is a verbatim move from
 * MasterDataPage. The only consumer changes are the import paths.
 */
import { useEffect, useState } from "react";
import { API_BASE_URL } from "./api";

// ── Hooks / async utilities ─────────────────────────────────────────────────

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

export function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const id = window.setTimeout(() => reject(new Error(`${label} timed out`)), ms);
    promise
      .then((value) => {
        window.clearTimeout(id);
        resolve(value);
      })
      .catch((error) => {
        window.clearTimeout(id);
        reject(error);
      });
  });
}

// ── Draft + recent-creates persistence ──────────────────────────────────────

/**
 * localStorage key for the create-inventory form draft. Schema-versioned so
 * future field changes can invalidate stale drafts cleanly. Bump the version
 * when the form's shape changes incompatibly.
 */
export const CREATE_DRAFT_KEY = "masterdata.create_draft.v1";
export const RECENT_CREATES_KEY = "masterdata.recent_creates.v1";

export interface CreateDraftEnvelope {
  saved_at: number;
  form: Record<string, unknown>;
}

export interface RecentCreate {
  sku_code: string;
  description?: string | null;
  material?: string | null;
  product_type?: string | null;
  created_at: number;
}

export function loadCreateDraft(): CreateDraftEnvelope | null {
  try {
    const raw = window.localStorage.getItem(CREATE_DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CreateDraftEnvelope;
    if (typeof parsed.saved_at !== "number" || typeof parsed.form !== "object") {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function saveCreateDraft(form: Record<string, unknown>): void {
  try {
    const env: CreateDraftEnvelope = { saved_at: Date.now(), form };
    window.localStorage.setItem(CREATE_DRAFT_KEY, JSON.stringify(env));
  } catch {
    // Quota / private mode — silently drop.
  }
}

export function clearCreateDraft(): void {
  try {
    window.localStorage.removeItem(CREATE_DRAFT_KEY);
  } catch {
    // ignore
  }
}

export function loadRecentCreates(): RecentCreate[] {
  try {
    const raw = window.localStorage.getItem(RECENT_CREATES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed
          .filter((item): item is RecentCreate => typeof item?.sku_code === "string")
          .slice(0, 5)
      : [];
  } catch {
    return [];
  }
}

export function saveRecentCreates(items: RecentCreate[]): void {
  try {
    window.localStorage.setItem(RECENT_CREATES_KEY, JSON.stringify(items.slice(0, 5)));
  } catch {
    // ignore
  }
}

/**
 * Push a freshly-created product onto the head of the recent-creates list,
 * dedup by SKU, cap at 5. Used by both the legacy in-page modal and the
 * routed AddItemPage so the "recently created" tile on /master-data stays
 * accurate regardless of which entry point produced the row.
 */
export function rememberCreatedProduct(product: {
  sku_code: string;
  description?: string | null;
  material?: string | null;
  product_type?: string | null;
}): void {
  const entry: RecentCreate = {
    sku_code: product.sku_code,
    description: product.description ?? null,
    material: product.material ?? null,
    product_type: product.product_type ?? null,
    created_at: Date.now(),
  };
  const existing = loadRecentCreates();
  const next = [entry, ...existing.filter((item) => item.sku_code !== entry.sku_code)].slice(0, 5);
  saveRecentCreates(next);
}

export function relativeTime(ms: number): string {
  const diff = Date.now() - ms;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} min ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} h ago`;
  return `${Math.floor(diff / 86_400_000)} d ago`;
}

export function masterDataAssetUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("data:")) return url;
  if (url.startsWith("gs://")) return undefined;
  if (url.startsWith("/api/")) {
    const base = API_BASE_URL.replace(/\/api$/, "");
    return `${base}${url}`;
  }
  return url;
}

// ── Product taxonomy ───────────────────────────────────────────────────────

export const PRODUCT_CATEGORY_OPTIONS = [
  {
    value: "minerals",
    label: "Minerals",
    product_types: ["Mineral Specimen", "Crystal Cluster", "Geode", "Sphere", "Tower", "Tumbled Stone"],
  },
  {
    value: "homeware",
    label: "Homeware",
    product_types: [
      "Bookend",
      "Napkin Holder",
      "Decorative Object",
      "Sculpture",
      "Figurine",
      "Vase",
      "Bowl",
      "Tray",
      "Box",
    ],
  },
  {
    value: "jewellery",
    label: "Jewellery",
    product_types: ["Bracelet", "Necklace", "Ring", "Pendant", "Earring", "Charm"],
  },
] as const;

export type ProductCategoryValue = (typeof PRODUCT_CATEGORY_OPTIONS)[number]["value"];

export function categoryForProductType(type: string | null | undefined): ProductCategoryValue {
  const t = (type || "").trim().toLowerCase();
  for (const c of PRODUCT_CATEGORY_OPTIONS) {
    if (c.product_types.some((p) => p.toLowerCase() === t)) return c.value;
  }
  // Default unmatched legacy rows to homeware — that's the bulk of the
  // catalog historically.
  return "homeware";
}

export const MATERIAL_OPTIONS = [
  "Crystal",
  "Clear Quartz",
  "Smoky Quartz",
  "Rose Quartz",
  "Rutilated Quartz",
  "Amethyst",
  "Citrine",
  "Ametrine",
  "Aquamarine",
  "Emerald",
  "Fluorite",
  "Garnet",
  "Jade",
  "Lapis Lazuli",
  "Malachite",
  "Marble",
  "Mineral Stone",
  "Moonstone",
  "Morganite",
  "Opal",
  "Ruby",
  "Sapphire",
  "Shangri-la Stone",
  "Stone",
  "Tourmaline",
  "Turquoise",
  "Watermelon Tourmaline",
  "Acrylic",
  "Brass",
  "Bronze",
  "Copper",
  "Glass",
  "Gold",
  "K9 Crystal",
  "Pearl",
  "Rattan",
  "Resin",
  "Shell",
  "Silver",
  "Stainless Steel",
  "Wood",
  "Mixed Materials",
];

export function firstMaterialLabel(value: string | null | undefined): string {
  const first = (value || "").split(/[,+|/]+/).map((part) => part.trim()).find(Boolean);
  return first || "Mixed Materials";
}

export function cleanMaterialLabel(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

export function composeMaterialText(primary: string, additional: readonly string[]): string {
  const parts = [primary, ...additional].map(cleanMaterialLabel).filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : "Mixed Materials";
}

export function mergePendingAdditionalMaterial(
  primary: string,
  additional: readonly string[],
  pending: string,
): string[] {
  const seen = new Set([primary, ...additional].map((item) => item.toLowerCase()));
  const cleaned = cleanMaterialLabel(pending);
  if (!cleaned || seen.has(cleaned.toLowerCase())) return [...additional];
  return [...additional, cleaned];
}

export function formatMaterialSummary(product: {
  material?: string | null;
  additional_materials?: string[] | null;
}): string {
  const primary = product.material || "—";
  const additional = product.additional_materials || [];
  if (additional.length === 0) return primary;
  return `${primary} + ${additional.join(", ")}`;
}

// ── Stocking location ──────────────────────────────────────────────────────

export const CANONICAL_LOCATION_OPTIONS = [
  { value: "breeze", label: "Breeze", aliases: ["warehouse", "breeze_by_the_east", "breeze by east"] },
  { value: "jewel", label: "Jewel", aliases: ["jewel_changi", "jewel changi", "jewel changi airport"] },
  { value: "isetan", label: "Isetan", aliases: ["isetan scotts"] },
  { value: "takashimaya", label: "Takashimaya", aliases: ["takashimaya_counter", "taka"] },
  { value: "online", label: "Online", aliases: ["website", "shopify", "online store"] },
] as const;

export type CanonicalLocationValue = (typeof CANONICAL_LOCATION_OPTIONS)[number]["value"];

export const LOCATION_LABELS = Object.fromEntries(
  CANONICAL_LOCATION_OPTIONS.map((loc) => [loc.value, loc.label]),
) as Record<CanonicalLocationValue, string>;

export const LOCATION_ALIAS_LOOKUP = new Map<string, CanonicalLocationValue>(
  CANONICAL_LOCATION_OPTIONS.flatMap((loc) => [
    [normaliseLocationToken(loc.value), loc.value],
    [normaliseLocationToken(loc.label), loc.value],
    ...loc.aliases.map((alias) => [normaliseLocationToken(alias), loc.value] as const),
  ]),
);

export function normaliseLocationToken(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, "");
}

export function parseStockingLocation(value: string | null | undefined): CanonicalLocationValue[] {
  if (!value) return [];
  const seen = new Set<CanonicalLocationValue>();
  for (const part of value.split(/[+,|/]+/)) {
    const canonical = LOCATION_ALIAS_LOOKUP.get(normaliseLocationToken(part));
    if (canonical) seen.add(canonical);
  }
  return CANONICAL_LOCATION_OPTIONS
    .map((loc) => loc.value)
    .filter((value) => seen.has(value));
}

export function encodeStockingLocation(values: readonly string[]): string {
  const selected = new Set(values);
  return CANONICAL_LOCATION_OPTIONS
    .map((loc) => loc.value)
    .filter((value) => selected.has(value))
    .join("+");
}

export function formatStockingLocation(value: string | null | undefined): string {
  const locations = parseStockingLocation(value);
  if (locations.length === 0) return "—";
  return locations.map((loc) => LOCATION_LABELS[loc]).join(" + ");
}

export const STORE_LOCATION_VALUES = new Set<CanonicalLocationValue>([
  "jewel",
  "isetan",
  "takashimaya",
  "online",
]);

// ── Identity normalisation ─────────────────────────────────────────────────

export function normaliseIdentity(value: string | null | undefined): string {
  return (value || "").trim().replace(/\s+/g, " ").toLowerCase();
}

export function normaliseCode(value: string | null | undefined): string {
  return (value || "").trim().toUpperCase();
}

