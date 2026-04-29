export type ReviewLineStatus = "unreviewed" | "verified" | "needs_follow_up";
export type ReviewItemStatus = "unreviewed" | "catalog_matched" | "sku_mapped" | "needs_follow_up";
export type ReviewFinancialStatus = "unreviewed" | "unpaid" | "partially_paid" | "paid" | "disputed";

export type ReviewLineState = {
  status: ReviewLineStatus;
  note: string;
  matchedCatalogProductId: string | null;
  targetSkuId: string;
  updatedAt: string | null;
};

export type ReviewOrderState = {
  itemStatus: ReviewItemStatus;
  itemNote: string;
  itemReviewedAt: string | null;
  financialStatus: ReviewFinancialStatus;
  financialNote: string;
  financialReviewedAt: string | null;
  lines: Record<string, ReviewLineState>;
};

export type SupplierReviewWorkspaceState = {
  schemaVersion: 2;
  supplierId: string;
  savedAt: string | null;
  orders: Record<string, ReviewOrderState>;
};

export const defaultLineReview = (): ReviewLineState => ({
  status: "unreviewed",
  note: "",
  matchedCatalogProductId: null,
  targetSkuId: "",
  updatedAt: null,
});

export const defaultOrderReview = (): ReviewOrderState => ({
  itemStatus: "unreviewed",
  itemNote: "",
  itemReviewedAt: null,
  financialStatus: "unreviewed",
  financialNote: "",
  financialReviewedAt: null,
  lines: {},
});

type LegacyReviewOrderStatus = "unreviewed" | "verified" | "needs_reconciliation";

type LegacyReviewOrderState = {
  status?: LegacyReviewOrderStatus;
  note?: string;
  reviewedAt?: string | null;
  lines?: Record<string, ReviewLineState>;
};

type LegacySupplierReviewWorkspaceState = {
  schemaVersion?: 1;
  supplierId?: string;
  savedAt?: string | null;
  orders?: Record<string, LegacyReviewOrderState>;
};

function storageKey(supplierId: string) {
  return `supplier-review:${supplierId}`;
}

export function createWorkspaceState(supplierId: string): SupplierReviewWorkspaceState {
  return {
    schemaVersion: 2,
    supplierId,
    savedAt: null,
    orders: {},
  };
}

function migrateLegacyOrderState(order: LegacyReviewOrderState | undefined): ReviewOrderState {
  const migrated = defaultOrderReview();
  if (!order) return migrated;

  if (order.status === "verified") {
    migrated.itemStatus = "catalog_matched";
    migrated.itemNote = order.note ?? "";
    migrated.itemReviewedAt = order.reviewedAt ?? null;
  } else if (order.status === "needs_reconciliation") {
    migrated.financialStatus = "disputed";
    migrated.financialNote = order.note ?? "";
    migrated.financialReviewedAt = order.reviewedAt ?? null;
  }

  migrated.lines = order.lines ?? {};
  return migrated;
}

export function loadWorkspaceState(supplierId: string): SupplierReviewWorkspaceState {
  if (typeof window === "undefined") {
    return createWorkspaceState(supplierId);
  }

  try {
    const raw = window.localStorage.getItem(storageKey(supplierId));
    if (!raw) {
      return createWorkspaceState(supplierId);
    }

    const parsed = JSON.parse(raw) as Partial<SupplierReviewWorkspaceState> | LegacySupplierReviewWorkspaceState;
    if (parsed.supplierId !== supplierId) {
      return createWorkspaceState(supplierId);
    }

    if (parsed.schemaVersion === 2) {
      return {
        schemaVersion: 2,
        supplierId,
        savedAt: parsed.savedAt ?? null,
        orders: parsed.orders ?? {},
      };
    }

    const legacy = parsed as LegacySupplierReviewWorkspaceState;
    const migratedOrders = Object.fromEntries(
      Object.entries(legacy.orders ?? {}).map(([orderNumber, orderState]) => [
        orderNumber,
        migrateLegacyOrderState(orderState),
      ]),
    );

    return {
      schemaVersion: 2,
      supplierId,
      savedAt: legacy.savedAt ?? null,
      orders: migratedOrders,
    };
  } catch {
    return createWorkspaceState(supplierId);
  }
}

export function persistWorkspaceState(state: SupplierReviewWorkspaceState) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKey(state.supplierId), JSON.stringify(state));
}
