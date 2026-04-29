import {
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { api } from "../lib/api";
import { useAuth } from "../contexts/AuthContext";
import { ManagerWorkflowStudio } from "../components/ManagerWorkflowStudio";
import type {
  BOMRecipe,
  DataEnvelope,
  InventoryAdjustmentHistory,
  InventoryInsight,
  InventoryType,
  ManagerRecommendation,
  ManagerSummary,
  PurchaseOrder,
  RecommendationStatus,
  SourcingStrategy,
  StageInventoryPosition,
  StockTransfer,
  Supplier,
  SupplyChainSummary,
  WorkOrder,
} from "../lib/manager-contracts";

function formatCurrency(value: number | null | undefined) {
  if (value == null) return "N/A";
  return new Intl.NumberFormat("en-SG", {
    style: "currency",
    currency: "SGD",
  }).format(value);
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "Not yet";
  return new Date(value).toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function inventoryTypeLabel(value: InventoryType) {
  switch (value) {
    case "purchased":
      return "Purchased";
    case "material":
      return "Material";
    case "finished":
      return "Finished";
  }
}

function sourcingLabel(value: SourcingStrategy) {
  switch (value) {
    case "supplier_premade":
      return "Supplier pre-made";
    case "manufactured_standard":
      return "Manufactured standard";
    case "manufactured_custom":
      return "Manufactured custom";
  }
}

function workflowActionLabel(value: string | null | undefined) {
  switch (value) {
    case "purchase_order":
      return "Create PO";
    case "work_order":
      return "Start Work Order";
    case "transfer":
      return "Receive Transfer";
    case "price_review":
      return "Price Review";
    default:
      return "Review";
  }
}

function statusTone(status: RecommendationStatus) {
  switch (status) {
    case "approved":
    case "applied":
      return "bg-emerald-50 text-emerald-700";
    case "rejected":
    case "expired":
      return "bg-gray-100 text-gray-600";
    case "queued":
    case "unavailable":
      return "bg-amber-50 text-amber-700";
    default:
      return "bg-blue-50 text-blue-700";
  }
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</div>
      <div className={`mt-2 text-2xl font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

export default function ManagerOpsPage() {
  const { selectedStore, canViewSensitiveOperations, roleLabel } = useAuth();
  const [summary, setSummary] = useState<ManagerSummary | null>(null);
  const [supplySummary, setSupplySummary] = useState<SupplyChainSummary | null>(null);
  const [inventory, setInventory] = useState<InventoryInsight[]>([]);
  const [recommendations, setRecommendations] = useState<ManagerRecommendation[]>([]);
  const [adjustments, setAdjustments] = useState<InventoryAdjustmentHistory[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [stagePositions, setStagePositions] = useState<StageInventoryPosition[]>([]);
  const [purchaseOrders, setPurchaseOrders] = useState<PurchaseOrder[]>([]);
  const [bomRecipes, setBomRecipes] = useState<BOMRecipe[]>([]);
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [transfers, setTransfers] = useState<StockTransfer[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchText, setSearchText] = useState("");
  const [showLowStock, setShowLowStock] = useState(false);
  const [showAnomalies, setShowAnomalies] = useState(false);
  const [selectedSkuId, setSelectedSkuId] = useState<string | null>(null);
  const [adjustQty, setAdjustQty] = useState(1);
  const [adjustReason, setAdjustReason] = useState("");

  const deferredSearch = useDeferredValue(searchText);

  const loadManagerData = async () => {
    if (!selectedStore) return;
    setLoading(true);
    setError(null);
    try {
      const [
        summaryRes,
        inventoryRes,
        recommendationsRes,
        adjustmentsRes,
      ] = await Promise.all([
        api.get<DataEnvelope<ManagerSummary>>(`/stores/${selectedStore.id}/copilot/summary`),
        api.get<DataEnvelope<InventoryInsight[]>>(`/stores/${selectedStore.id}/copilot/inventory`),
        api.get<DataEnvelope<ManagerRecommendation[]>>(`/stores/${selectedStore.id}/copilot/recommendations`),
        api.get<DataEnvelope<InventoryAdjustmentHistory[]>>(`/stores/${selectedStore.id}/copilot/adjustments`),
      ]);
      setSummary(summaryRes.data);
      setInventory(inventoryRes.data);
      setRecommendations(recommendationsRes.data);
      setAdjustments(adjustmentsRes.data);
      if (canViewSensitiveOperations) {
        const [
          supplySummaryRes,
          suppliersRes,
          stageRes,
          purchaseOrdersRes,
          bomRecipesRes,
          workOrdersRes,
          transfersRes,
        ] = await Promise.all([
          api.get<DataEnvelope<SupplyChainSummary>>(`/stores/${selectedStore.id}/supply-chain/summary`),
          api.get<DataEnvelope<Supplier[]>>(`/stores/${selectedStore.id}/supply-chain/suppliers?active_only=true`),
          api.get<DataEnvelope<StageInventoryPosition[]>>(`/stores/${selectedStore.id}/supply-chain/stages`),
          api.get<DataEnvelope<PurchaseOrder[]>>(`/stores/${selectedStore.id}/supply-chain/purchase-orders`),
          api.get<DataEnvelope<BOMRecipe[]>>(`/stores/${selectedStore.id}/supply-chain/bom-recipes`),
          api.get<DataEnvelope<WorkOrder[]>>(`/stores/${selectedStore.id}/supply-chain/work-orders`),
          api.get<DataEnvelope<StockTransfer[]>>(`/stores/${selectedStore.id}/supply-chain/transfers`),
        ]);
        setSupplySummary(supplySummaryRes.data);
        setSuppliers(suppliersRes.data);
        setStagePositions(stageRes.data);
        setPurchaseOrders(purchaseOrdersRes.data);
        setBomRecipes(bomRecipesRes.data);
        setWorkOrders(workOrdersRes.data);
        setTransfers(transfersRes.data);
      } else {
        setSupplySummary(null);
        setSuppliers([]);
        setStagePositions([]);
        setPurchaseOrders([]);
        setBomRecipes([]);
        setWorkOrders([]);
        setTransfers([]);
      }
      if (!selectedSkuId && inventoryRes.data[0]) {
        setSelectedSkuId(inventoryRes.data[0].sku_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load manager data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadManagerData();
  }, [canViewSensitiveOperations, selectedStore?.id]);

  const filteredInventory = useMemo(() => {
    const normalizedSearch = deferredSearch.trim().toLowerCase();
    return inventory.filter((item) => {
      if (showLowStock && !item.low_stock) return false;
      if (showAnomalies && !item.anomaly_flag) return false;
      if (!normalizedSearch) return true;
      return (
        item.sku_code.toLowerCase().includes(normalizedSearch) ||
        item.description.toLowerCase().includes(normalizedSearch)
      );
    });
  }, [deferredSearch, inventory, showAnomalies, showLowStock]);

  useEffect(() => {
    if (!filteredInventory.length) {
      setSelectedSkuId(null);
      return;
    }
    if (!selectedSkuId || !filteredInventory.some((item) => item.sku_id === selectedSkuId)) {
      setSelectedSkuId(filteredInventory[0].sku_id);
    }
  }, [filteredInventory, selectedSkuId]);

  const selectedItem = filteredInventory.find((item) => item.sku_id === selectedSkuId) ?? null;
  const selectedRecommendations = useMemo(
    () =>
      recommendations.filter((recommendation) => recommendation.sku_id === selectedItem?.sku_id),
    [recommendations, selectedItem?.sku_id]
  );
  const recentAdjustments = useMemo(
    () => adjustments.filter((entry) => entry.sku_id === selectedItem?.sku_id).slice(0, 5),
    [adjustments, selectedItem?.sku_id]
  );
  const selectedStages = useMemo(
    () => stagePositions.filter((entry) => entry.sku_id === selectedItem?.sku_id),
    [stagePositions, selectedItem?.sku_id]
  );
  const selectedPurchaseOrders = useMemo(
    () =>
      purchaseOrders
        .filter((order) => order.lines.some((line) => line.sku_id === selectedItem?.sku_id))
        .slice(0, 5),
    [purchaseOrders, selectedItem?.sku_id]
  );
  const selectedWorkOrders = useMemo(
    () => workOrders.filter((order) => order.finished_sku_id === selectedItem?.sku_id).slice(0, 5),
    [workOrders, selectedItem?.sku_id]
  );
  const selectedTransfers = useMemo(
    () => transfers.filter((transfer) => transfer.sku_id === selectedItem?.sku_id).slice(0, 5),
    [transfers, selectedItem?.sku_id]
  );

  const triggerAnalysis = async (forceRefresh = false) => {
    if (!selectedStore) return;
    setBusyAction("analysis");
    setError(null);
    try {
      await api.post(`/stores/${selectedStore.id}/copilot/recommendations/analyze`, {
        force_refresh: forceRefresh,
        lookback_days: 30,
        low_stock_threshold: 5,
      });
      await loadManagerData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to trigger analysis.");
    } finally {
      setBusyAction(null);
    }
  };

  const handleRecommendationAction = async (
    recommendationId: string,
    action: "approve" | "reject" | "apply"
  ) => {
    if (!selectedStore) return;
    setBusyAction(recommendationId + action);
    setError(null);
    try {
      await api.post(
        `/stores/${selectedStore.id}/copilot/recommendations/${recommendationId}/${action}`,
        {
          note:
            action === "reject"
              ? "Rejected from the manager operations console."
              : action === "apply"
                ? "Applied from the manager operations console."
                : "Approved from the manager operations console.",
        }
      );
      await loadManagerData();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Unable to ${action} recommendation.`);
    } finally {
      setBusyAction(null);
    }
  };

  const handleReceivePurchaseOrder = async (order: PurchaseOrder) => {
    if (!selectedStore) return;
    const lines = order.lines
      .filter((line) => line.open_quantity > 0)
      .map((line) => ({
        line_id: line.line_id,
        quantity_received: line.open_quantity,
      }));
    if (!lines.length) return;
    setBusyAction(`receive-${order.id}`);
    setError(null);
    try {
      await api.post(`/stores/${selectedStore.id}/supply-chain/purchase-orders/${order.id}/receive`, {
        lines,
        note: "Received from the manager operations console.",
      });
      await loadManagerData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to receive purchase order.");
    } finally {
      setBusyAction(null);
    }
  };

  const handleStartWorkOrder = async (workOrderId: string) => {
    if (!selectedStore) return;
    setBusyAction(`start-${workOrderId}`);
    setError(null);
    try {
      await api.post(`/stores/${selectedStore.id}/supply-chain/work-orders/${workOrderId}/start`, {});
      await loadManagerData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to start work order.");
    } finally {
      setBusyAction(null);
    }
  };

  const handleCompleteWorkOrder = async (workOrder: WorkOrder) => {
    if (!selectedStore) return;
    setBusyAction(`complete-${workOrder.id}`);
    setError(null);
    try {
      await api.post(`/stores/${selectedStore.id}/supply-chain/work-orders/${workOrder.id}/complete`, {
        completed_quantity: Math.max(workOrder.target_quantity - workOrder.completed_quantity, 1),
        note: "Completed from the manager operations console.",
      });
      await loadManagerData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to complete work order.");
    } finally {
      setBusyAction(null);
    }
  };

  const handleReceiveTransfer = async (transferId: string) => {
    if (!selectedStore) return;
    setBusyAction(`transfer-${transferId}`);
    setError(null);
    try {
      await api.post(`/stores/${selectedStore.id}/supply-chain/transfers/${transferId}/receive`, {
        note: "Received from the manager operations console.",
      });
      await loadManagerData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to receive transfer.");
    } finally {
      setBusyAction(null);
    }
  };

  const handleAdjustment = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedStore || !selectedItem || !selectedItem.inventory_id || !adjustReason.trim()) return;
    setBusyAction("adjustment");
    setError(null);
    try {
      await api.post(
        `/stores/${selectedStore.id}/inventory/${selectedItem.inventory_id}/adjust`,
        {
          quantity: adjustQty,
          reason: adjustReason.trim(),
          source: "manual",
        }
      );
      setAdjustReason("");
      setAdjustQty(1);
      await loadManagerData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to adjust inventory.");
    } finally {
      setBusyAction(null);
    }
  };

  if (!selectedStore) {
    return (
      <div className="rounded-2xl border border-gray-200 bg-white p-8 text-sm text-gray-600 shadow-sm">
        Choose a store to open the manager operations console.
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-gray-500">
        Loading manager operations…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Manager Operations</h1>
          <p className="mt-1 text-sm text-gray-500">
            {canViewSensitiveOperations
              ? `Inventory, pricing, and operational control for ${selectedStore.name}.`
              : `Sales-manager view for ${selectedStore.name}: stock health, location inventory, pricing, and recommendation review without supplier or finance detail.`}
          </p>
          <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-gray-400">{roleLabel}</p>
          <p className="mt-2 text-xs uppercase tracking-wide text-gray-400">
            Analysis status: {summary?.analysis_status ?? "ready"} • Last run:{" "}
            {formatDateTime(summary?.last_generated_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => void loadManagerData()}
            className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            Refresh
          </button>
          <button
            onClick={() => void triggerAnalysis(true)}
            disabled={busyAction === "analysis"}
            className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-60"
          >
            {busyAction === "analysis" ? "Running brain…" : "Run Inventory Brain"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Low Stock" value={String(summary?.low_stock_count ?? 0)} tone="text-red-600" />
        <StatCard label="Anomalies" value={String(summary?.anomaly_count ?? 0)} tone="text-amber-600" />
        <StatCard
          label="Pending Reorders"
          value={String(summary?.pending_reorder_recommendations ?? 0)}
          tone="text-blue-600"
        />
        <StatCard
          label="Pending Price Reviews"
          value={String(summary?.pending_price_recommendations ?? 0)}
          tone="text-indigo-600"
        />
        <StatCard
          label="Pending Stock Investigations"
          value={String(summary?.pending_stock_anomalies ?? 0)}
          tone="text-emerald-600"
        />
      </div>

      {canViewSensitiveOperations ? (
        <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
          <StatCard
            label="Open POs"
            value={String(summary?.open_purchase_orders ?? supplySummary?.open_purchase_orders ?? 0)}
            tone="text-sky-600"
          />
          <StatCard
            label="Active Work Orders"
            value={String(summary?.active_work_orders ?? supplySummary?.active_work_orders ?? 0)}
            tone="text-violet-600"
          />
          <StatCard
            label="In-Transit Transfers"
            value={String(summary?.in_transit_transfers ?? supplySummary?.in_transit_transfers ?? 0)}
            tone="text-cyan-600"
          />
          <StatCard
            label="Purchased Units"
            value={String(summary?.purchased_units ?? supplySummary?.purchased_units ?? 0)}
            tone="text-slate-600"
          />
          <StatCard
            label="Material Units"
            value={String(summary?.material_units ?? supplySummary?.material_units ?? 0)}
            tone="text-orange-600"
          />
          <StatCard
            label="Finished Units"
            value={String(summary?.finished_units ?? supplySummary?.finished_units ?? 0)}
            tone="text-emerald-600"
          />
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <StatCard
            label="Finished Units"
            value={String(summary?.finished_units ?? 0)}
            tone="text-emerald-600"
          />
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-3 border-b border-gray-100 pb-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Inventory Watchlist</h2>
              <p className="text-sm text-gray-500">Filter live stock health for the pilot store.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <input
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                placeholder="Search SKU or description"
                className="rounded-xl border border-gray-200 px-3 py-2 text-sm"
              />
              <button
                onClick={() => setShowLowStock((value) => !value)}
                className={`rounded-xl px-3 py-2 text-sm font-medium ${
                  showLowStock ? "bg-red-50 text-red-700" : "bg-gray-100 text-gray-700"
                }`}
              >
                Low stock
              </button>
              <button
                onClick={() => setShowAnomalies((value) => !value)}
                className={`rounded-xl px-3 py-2 text-sm font-medium ${
                  showAnomalies ? "bg-amber-50 text-amber-700" : "bg-gray-100 text-gray-700"
                }`}
              >
                Anomalies
              </button>
            </div>
          </div>

          <div className="mt-4 grid gap-3">
            {filteredInventory.map((item) => (
              <button
                key={item.sku_id}
                onClick={() => setSelectedSkuId(item.sku_id)}
                className={`rounded-2xl border px-4 py-4 text-left transition ${
                  item.sku_id === selectedItem?.sku_id
                    ? "border-blue-200 bg-blue-50 shadow-sm"
                    : "border-gray-200 bg-white hover:border-gray-300"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-400">{item.sku_code}</div>
                    <div className="mt-1 text-sm font-semibold text-gray-900">{item.description}</div>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-700">
                        {inventoryTypeLabel(item.inventory_type)}
                      </span>
                      <span className="rounded-full bg-violet-50 px-2.5 py-1 font-semibold text-violet-700">
                        {sourcingLabel(item.sourcing_strategy)}
                      </span>
                      {item.low_stock && (
                        <span className="rounded-full bg-red-50 px-2.5 py-1 font-semibold text-red-700">
                          Low stock
                        </span>
                      )}
                      {item.anomaly_flag && (
                        <span className="rounded-full bg-amber-50 px-2.5 py-1 font-semibold text-amber-700">
                          Anomaly
                        </span>
                      )}
                      {item.pending_recommendation_count > 0 && (
                        <span className="rounded-full bg-blue-50 px-2.5 py-1 font-semibold text-blue-700">
                          {item.pending_recommendation_count} open actions
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold text-gray-900">{formatCurrency(item.current_price)}</div>
                    <div className="mt-1 text-xs text-gray-500">Qty {item.qty_on_hand}</div>
                    {canViewSensitiveOperations ? (
                      <div className="mt-1 text-xs text-gray-400">
                        Upstream {item.purchased_qty + item.material_qty + item.in_transit_qty}
                      </div>
                    ) : (
                      <div className="mt-1 text-xs text-gray-400">
                        Reorder {item.reorder_level} / {item.reorder_qty}
                      </div>
                    )}
                  </div>
                </div>
              </button>
            ))}
            {!filteredInventory.length && (
              <div className="rounded-2xl border border-dashed border-gray-200 px-4 py-10 text-center text-sm text-gray-500">
                No inventory items match the current filter.
              </div>
            )}
          </div>
        </section>

        <section className="space-y-4">
          <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-900">SKU Detail</h2>
            {selectedItem ? (
              <div className="mt-4 space-y-4">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                    {selectedItem.sku_code}
                  </div>
                  <div className="mt-1 text-lg font-semibold text-gray-900">{selectedItem.description}</div>
                  {selectedItem.long_description && (
                    <p className="mt-2 text-sm text-gray-600">{selectedItem.long_description}</p>
                  )}
                </div>
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-2xl bg-gray-50 p-3">
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Current Price</dt>
                    <dd className="mt-1 font-semibold text-gray-900">{formatCurrency(selectedItem.current_price)}</dd>
                  </div>
                  {canViewSensitiveOperations && (
                    <div className="rounded-2xl bg-gray-50 p-3">
                      <dt className="text-xs uppercase tracking-wide text-gray-400">Cost Price</dt>
                      <dd className="mt-1 font-semibold text-gray-900">{formatCurrency(selectedItem.cost_price)}</dd>
                    </div>
                  )}
                  <div className="rounded-2xl bg-gray-50 p-3">
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Inventory Type</dt>
                    <dd className="mt-1 font-semibold text-gray-900">
                      {inventoryTypeLabel(selectedItem.inventory_type)}
                    </dd>
                  </div>
                  <div className="rounded-2xl bg-gray-50 p-3">
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Sourcing</dt>
                    <dd className="mt-1 font-semibold text-gray-900">
                      {sourcingLabel(selectedItem.sourcing_strategy)}
                    </dd>
                  </div>
                  <div className="rounded-2xl bg-gray-50 p-3">
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Qty On Hand</dt>
                    <dd className="mt-1 font-semibold text-gray-900">{selectedItem.qty_on_hand}</dd>
                  </div>
                  <div className="rounded-2xl bg-gray-50 p-3">
                    <dt className="text-xs uppercase tracking-wide text-gray-400">
                      {canViewSensitiveOperations ? "Finished / In Transit" : "Available to Sell"}
                    </dt>
                    <dd className="mt-1 font-semibold text-gray-900">
                      {canViewSensitiveOperations
                        ? `${selectedItem.finished_qty} / ${selectedItem.in_transit_qty}`
                        : String(Math.max(selectedItem.finished_qty - selectedItem.finished_allocated_qty, 0))}
                    </dd>
                  </div>
                  {canViewSensitiveOperations && (
                    <>
                      <div className="rounded-2xl bg-gray-50 p-3">
                        <dt className="text-xs uppercase tracking-wide text-gray-400">Purchased / Inbound</dt>
                        <dd className="mt-1 font-semibold text-gray-900">
                          {selectedItem.purchased_qty} / {selectedItem.purchased_incoming_qty}
                        </dd>
                      </div>
                      <div className="rounded-2xl bg-gray-50 p-3">
                        <dt className="text-xs uppercase tracking-wide text-gray-400">Material / Reserved</dt>
                        <dd className="mt-1 font-semibold text-gray-900">
                          {selectedItem.material_qty} / {selectedItem.material_allocated_qty}
                        </dd>
                      </div>
                      <div className="rounded-2xl bg-gray-50 p-3">
                        <dt className="text-xs uppercase tracking-wide text-gray-400">Active Work Orders</dt>
                        <dd className="mt-1 font-semibold text-gray-900">{selectedItem.active_work_order_count}</dd>
                      </div>
                    </>
                  )}
                  <div className="rounded-2xl bg-gray-50 p-3">
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Reorder Target</dt>
                    <dd className="mt-1 font-semibold text-gray-900">
                      {selectedItem.reorder_level} / {selectedItem.reorder_qty}
                    </dd>
                  </div>
                  <div className="rounded-2xl bg-gray-50 p-3">
                    <dt className="text-xs uppercase tracking-wide text-gray-400">30-Day Sales</dt>
                    <dd className="mt-1 font-semibold text-gray-900">{selectedItem.recent_sales_qty} units</dd>
                  </div>
                  <div className="rounded-2xl bg-gray-50 p-3">
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Days of Cover</dt>
                    <dd className="mt-1 font-semibold text-gray-900">
                      {selectedItem.days_of_cover != null ? `${selectedItem.days_of_cover} days` : "N/A"}
                    </dd>
                  </div>
                </dl>
                {canViewSensitiveOperations && selectedItem.supplier_name && (
                  <div className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
                    Supplier: {selectedItem.supplier_name}
                  </div>
                )}
                {selectedItem.anomaly_reason && (
                  <div className="rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
                    {selectedItem.anomaly_reason}
                  </div>
                )}
                <form onSubmit={handleAdjustment} className="rounded-2xl border border-gray-200 p-4">
                  <div className="text-sm font-semibold text-gray-900">Manual Stock Adjustment</div>
                  <p className="mt-1 text-sm text-gray-500">
                    Required for reconciliation. Changes are saved to adjustment history.
                  </p>
                  {!selectedItem.inventory_id && (
                    <div className="mt-3 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
                      This SKU does not have a finished store-stock record yet. Receive a transfer or complete a work
                      order before using manual stock adjustments.
                    </div>
                  )}
                  <div className="mt-3 grid gap-3 sm:grid-cols-[120px_1fr]">
                    <input
                      type="number"
                      value={adjustQty}
                      onChange={(event) => setAdjustQty(Number(event.target.value))}
                      className="rounded-xl border border-gray-200 px-3 py-2 text-sm"
                    />
                    <input
                      value={adjustReason}
                      onChange={(event) => setAdjustReason(event.target.value)}
                      placeholder="Reason for the change"
                      className="rounded-xl border border-gray-200 px-3 py-2 text-sm"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={busyAction === "adjustment" || !adjustReason.trim() || !selectedItem.inventory_id}
                    className="mt-3 rounded-xl bg-gray-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                  >
                    {busyAction === "adjustment" ? "Saving…" : "Save Adjustment"}
                  </button>
                </form>
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-dashed border-gray-200 px-4 py-10 text-center text-sm text-gray-500">
                Pick a SKU to review its pricing risk, sales context, and manual adjustments.
              </div>
            )}
          </div>

          <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-900">Recent Adjustment History</h2>
            <div className="mt-4 space-y-3">
              {recentAdjustments.map((entry) => (
                <div key={entry.id} className="rounded-2xl bg-gray-50 px-4 py-3 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className={`font-semibold ${entry.quantity_delta >= 0 ? "text-emerald-700" : "text-red-700"}`}>
                      {entry.quantity_delta >= 0 ? "+" : ""}
                      {entry.quantity_delta}
                    </span>
                    <span className="text-xs text-gray-500">{formatDateTime(entry.created_at)}</span>
                  </div>
                  <div className="mt-1 text-gray-700">{entry.reason}</div>
                  <div className="mt-1 text-xs text-gray-500">Resulting qty: {entry.resulting_qty}</div>
                </div>
              ))}
              {!recentAdjustments.length && (
                <div className="rounded-2xl border border-dashed border-gray-200 px-4 py-8 text-center text-sm text-gray-500">
                  No adjustments recorded yet for this SKU.
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-2 border-b border-gray-100 pb-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Recommendations Inbox</h2>
            <p className="text-sm text-gray-500">
              Review AI suggestions before anything changes in inventory or pricing.
            </p>
          </div>
          <div className="text-xs uppercase tracking-wide text-gray-400">
            {recommendations.length} persisted recommendations
          </div>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {(selectedRecommendations.length ? selectedRecommendations : recommendations).map((recommendation) => (
            <article key={recommendation.id} className="rounded-2xl border border-gray-200 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                    {recommendation.type.replace("_", " ")}
                  </div>
                  <h3 className="mt-1 text-base font-semibold text-gray-900">{recommendation.title}</h3>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-700">
                      {inventoryTypeLabel(recommendation.inventory_type)}
                    </span>
                    <span className="rounded-full bg-violet-50 px-2.5 py-1 font-semibold text-violet-700">
                      {sourcingLabel(recommendation.sourcing_strategy)}
                    </span>
                    {canViewSensitiveOperations && recommendation.supplier_name && (
                      <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-semibold text-emerald-700">
                        {recommendation.supplier_name}
                      </span>
                    )}
                  </div>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${statusTone(recommendation.status)}`}>
                  {recommendation.status}
                </span>
              </div>
              <p className="mt-3 text-sm leading-6 text-gray-600">{recommendation.rationale}</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <div className="rounded-2xl bg-gray-50 p-3 text-sm">
                  <div className="text-xs uppercase tracking-wide text-gray-400">Confidence</div>
                  <div className="mt-1 font-semibold text-gray-900">
                    {Math.round(recommendation.confidence * 100)}%
                  </div>
                </div>
                <div className="rounded-2xl bg-gray-50 p-3 text-sm">
                  <div className="text-xs uppercase tracking-wide text-gray-400">Current Price</div>
                  <div className="mt-1 font-semibold text-gray-900">{formatCurrency(recommendation.current_price)}</div>
                </div>
                <div className="rounded-2xl bg-gray-50 p-3 text-sm">
                  <div className="text-xs uppercase tracking-wide text-gray-400">Suggested Action</div>
                  <div className="mt-1 font-semibold text-gray-900">
                    {recommendation.suggested_price != null
                      ? formatCurrency(recommendation.suggested_price)
                      : recommendation.suggested_order_qty != null
                        ? `${recommendation.suggested_order_qty} units`
                        : "Review needed"}
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    {workflowActionLabel(recommendation.workflow_action)}
                  </div>
                </div>
              </div>
              {recommendation.expected_impact && (
                <div className="mt-3 rounded-2xl bg-blue-50 px-4 py-3 text-sm text-blue-800">
                  {recommendation.expected_impact}
                </div>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                {recommendation.status === "pending" && (
                  <>
                    <button
                      onClick={() => void handleRecommendationAction(recommendation.id, "approve")}
                      disabled={busyAction === recommendation.id + "approve"}
                      className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => void handleRecommendationAction(recommendation.id, "reject")}
                      disabled={busyAction === recommendation.id + "reject"}
                      className="rounded-xl bg-gray-100 px-4 py-2 text-sm font-semibold text-gray-700 disabled:opacity-60"
                    >
                      Reject
                    </button>
                  </>
                )}
                {recommendation.status === "approved" &&
                  (canViewSensitiveOperations || recommendation.workflow_action === "price_review" ? (
                    <button
                      onClick={() => void handleRecommendationAction(recommendation.id, "apply")}
                      disabled={busyAction === recommendation.id + "apply"}
                      className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                    >
                      Mark Applied
                    </button>
                  ) : (
                    <span className="rounded-xl bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
                      Owner director applies procurement actions
                    </span>
                  ))}
                <span className="self-center text-xs uppercase tracking-wide text-gray-400">
                  Generated {formatDateTime(recommendation.generated_at)}
                </span>
              </div>
            </article>
          ))}
        </div>
      </section>

      {canViewSensitiveOperations ? (
        <>
          <section className="grid gap-6 xl:grid-cols-3">
            <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3 border-b border-gray-100 pb-4">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">Stage Ledger</h2>
                  <p className="text-sm text-gray-500">
                    Purchased, material, and finished positions for the selected SKU.
                  </p>
                </div>
                <div className="text-xs uppercase tracking-wide text-gray-400">
                  {selectedStages.length} records
                </div>
              </div>
              <div className="mt-4 space-y-3">
                {selectedStages.map((entry) => (
                  <div key={entry.id} className="rounded-2xl bg-gray-50 px-4 py-3 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-semibold text-gray-900">
                        {inventoryTypeLabel(entry.inventory_type)}
                      </span>
                      <span className="text-xs text-gray-500">{entry.available_quantity} available</span>
                    </div>
                    <div className="mt-2 text-gray-600">
                      On hand {entry.quantity_on_hand} • Incoming {entry.incoming_quantity} • Reserved{" "}
                      {entry.allocated_quantity}
                    </div>
                  </div>
                ))}
                {!selectedStages.length && (
                  <div className="rounded-2xl border border-dashed border-gray-200 px-4 py-8 text-center text-sm text-gray-500">
                    No explicit ledger entries for this SKU yet.
                  </div>
                )}
                <div className="rounded-2xl border border-gray-100 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Active Suppliers
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {suppliers.slice(0, 6).map((supplier) => (
                      <span key={supplier.id} className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-700">
                        {supplier.name}
                      </span>
                    ))}
                    {!suppliers.length && <span className="text-xs text-slate-500">No suppliers configured yet.</span>}
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="border-b border-gray-100 pb-4">
                <h2 className="text-lg font-semibold text-gray-900">Procurement & Delivery</h2>
                <p className="text-sm text-gray-500">
                  Open purchase orders and transfers connected to this SKU.
                </p>
              </div>
              <div className="mt-4 space-y-4">
                {selectedPurchaseOrders.map((order) => (
                  <div key={order.id} className="rounded-2xl border border-gray-200 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-xs uppercase tracking-wide text-gray-400">{order.supplier_name ?? "Supplier"}</div>
                        <div className="mt-1 text-sm font-semibold text-gray-900">
                          {order.total_quantity} units • {formatCurrency(order.total_cost)}
                        </div>
                      </div>
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${statusTone(order.status === "partially_received" ? "approved" : order.status === "received" ? "applied" : "pending")}`}>
                        {order.status.replace("_", " ")}
                      </span>
                    </div>
                    <div className="mt-3 text-xs text-gray-500">
                      Open qty {order.lines.reduce((total, line) => total + line.open_quantity, 0)}
                    </div>
                    {order.status !== "received" && order.lines.some((line) => line.open_quantity > 0) && (
                      <button
                        onClick={() => void handleReceivePurchaseOrder(order)}
                        disabled={busyAction === `receive-${order.id}`}
                        className="mt-3 rounded-xl bg-sky-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                      >
                        Receive Remaining
                      </button>
                    )}
                  </div>
                ))}
                {selectedTransfers.map((transfer) => (
                  <div key={transfer.id} className="rounded-2xl border border-gray-200 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-xs uppercase tracking-wide text-gray-400">
                          {inventoryTypeLabel(transfer.from_inventory_type)} → {inventoryTypeLabel(transfer.to_inventory_type)}
                        </div>
                        <div className="mt-1 text-sm font-semibold text-gray-900">{transfer.quantity} units</div>
                      </div>
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${statusTone(transfer.status === "received" ? "applied" : "pending")}`}>
                        {transfer.status.replace("_", " ")}
                      </span>
                    </div>
                    {transfer.status === "in_transit" && (
                      <button
                        onClick={() => void handleReceiveTransfer(transfer.id)}
                        disabled={busyAction === `transfer-${transfer.id}`}
                        className="mt-3 rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                      >
                        Receive Transfer
                      </button>
                    )}
                  </div>
                ))}
                {!selectedPurchaseOrders.length && !selectedTransfers.length && (
                  <div className="rounded-2xl border border-dashed border-gray-200 px-4 py-8 text-center text-sm text-gray-500">
                    No active purchase orders or transfers for this SKU yet.
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="border-b border-gray-100 pb-4">
                <h2 className="text-lg font-semibold text-gray-900">Manufacturing Queue</h2>
                <p className="text-sm text-gray-500">
                  Active work orders for standard and custom manufactured output.
                </p>
              </div>
              <div className="mt-4 space-y-4">
                {selectedWorkOrders.map((workOrder) => (
                  <div key={workOrder.id} className="rounded-2xl border border-gray-200 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-xs uppercase tracking-wide text-gray-400">
                          {workOrder.work_order_type}
                        </div>
                        <div className="mt-1 text-sm font-semibold text-gray-900">
                          {workOrder.completed_quantity} / {workOrder.target_quantity} complete
                        </div>
                      </div>
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${statusTone(workOrder.status === "completed" ? "applied" : workOrder.status === "in_progress" ? "approved" : "pending")}`}>
                        {workOrder.status.replace("_", " ")}
                      </span>
                    </div>
                    <div className="mt-3 text-xs text-gray-500">
                      {workOrder.components.length} material lines • Due {workOrder.due_date ?? "Not set"}
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {workOrder.status === "scheduled" && (
                        <button
                          onClick={() => void handleStartWorkOrder(workOrder.id)}
                          disabled={busyAction === `start-${workOrder.id}`}
                          className="rounded-xl bg-violet-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                        >
                          Start Work Order
                        </button>
                      )}
                      {workOrder.status !== "completed" && (
                        <button
                          onClick={() => void handleCompleteWorkOrder(workOrder)}
                          disabled={busyAction === `complete-${workOrder.id}`}
                          className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                        >
                          Complete Remaining
                        </button>
                      )}
                    </div>
                  </div>
                ))}
                {!selectedWorkOrders.length && (
                  <div className="rounded-2xl border border-dashed border-gray-200 px-4 py-8 text-center text-sm text-gray-500">
                    No work orders are currently linked to this SKU.
                  </div>
                )}
              </div>
            </div>
          </section>

          <ManagerWorkflowStudio
            storeId={selectedStore.id}
            selectedItem={selectedItem}
            inventory={inventory}
            suppliers={suppliers}
            bomRecipes={bomRecipes}
            onMutated={loadManagerData}
          />
        </>
      ) : (
        <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900">Owner-Only Operations</h2>
          <p className="mt-2 text-sm text-gray-600">
            Supplier, purchase-order, manufacturing, transfer, invoice-review, cost, and financial workflows are hidden from store managers.
          </p>
          <p className="mt-3 text-sm text-gray-500">
            This view stays focused on store stock, selling price, manual adjustments, and recommendation review for the locations assigned to you.
          </p>
        </section>
      )}
    </div>
  );
}
