import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../lib/api";

// ── Types ──────────────────────────────────────────────────────────────────

interface OrderItem {
  id: string;
  order_id: string;
  sku_id: string;
  qty: number;
  unit_price: number;
  discount: number;
  line_total: number;
}

interface Order {
  id: string;
  order_number: string;
  store_id: string;
  staff_id?: string;
  order_date: string;
  subtotal: number;
  discount_total: number;
  tax_total: number;
  grand_total: number;
  payment_method: string;
  payment_ref?: string;
  status: "open" | "completed" | "voided";
  source: string;
  items: OrderItem[];
  created_at?: string;
}

const STATUS_OPTIONS: { value: Order["status"] | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "completed", label: "Completed" },
  { value: "voided", label: "Voided" },
];

const STATUS_STYLES: Record<string, string> = {
  open: "bg-blue-100 text-blue-700",
  completed: "bg-green-100 text-green-700",
  voided: "bg-red-100 text-red-700",
};

const SOURCE_LABELS: Record<string, string> = {
  nec_pos: "NEC POS",
  hipay: "HiPay",
  airwallex: "Airwallex",
  shopify: "Shopify",
  manual: "Manual",
};

function fmt(amount: number) {
  return `$${amount.toFixed(2)}`;
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString("en-SG", {
      year: "numeric", month: "short", day: "numeric",
    });
  } catch { return iso; }
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function OrdersPage() {
  const { selectedStore, loading: authLoading } = useAuth();
  const storeId = selectedStore?.id ?? null;

  const [orders, setOrders] = useState<Order[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<Order["status"] | "all">("all");
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const loadOrders = useCallback(async () => {
    if (!storeId) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.get<{ data: Order[] }>(`/stores/${storeId}/orders?page_size=200`);
      setOrders(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load orders");
    } finally {
      setIsLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    if (!authLoading && storeId) void loadOrders();
  }, [authLoading, storeId, loadOrders]);

  // Close panel on outside click
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setSelectedOrder(null);
      }
    }
    if (selectedOrder) document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [selectedOrder]);

  const filtered = orders.filter((o) => {
    const matchStatus = statusFilter === "all" || o.status === statusFilter;
    const q = search.toLowerCase();
    const matchSearch = !q || o.order_number.toLowerCase().includes(q) || o.payment_method.toLowerCase().includes(q);
    return matchStatus && matchSearch;
  });

  return (
    <div className="flex flex-col h-full gap-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Orders</h1>
          <p className="mt-1 text-sm text-gray-500">Browse and inspect all sales orders for this store.</p>
        </div>
        <button
          onClick={loadOrders}
          disabled={isLoading}
          className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50 transition"
        >
          <svg className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700 border border-red-100">{error}</div>
      )}

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <svg className="pointer-events-none absolute inset-y-0 left-3 my-auto h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search by order # or payment method…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="block w-full rounded-xl border border-gray-200 bg-white py-2 pl-9 pr-4 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setStatusFilter(opt.value as Order["status"] | "all")}
              className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
                statusFilter === opt.value
                  ? "bg-blue-600 text-white shadow-sm"
                  : "bg-white text-gray-600 ring-1 ring-inset ring-gray-300 hover:bg-gray-50"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table + Detail Panel */}
      <div className="flex gap-4 flex-1 overflow-hidden">
        {/* Table */}
        <div className={`flex-1 overflow-auto rounded-xl border border-gray-200 bg-white shadow-sm transition-all ${selectedOrder ? "lg:flex-[2]" : ""}`}>
          {isLoading ? (
            <div className="flex justify-center py-20">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="rounded-full bg-gray-100 p-4">
                <svg className="h-8 w-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3h2l.4 2M7 13h10l4-8H5.4m0 0L7 13m0 0l-1.4 5M7 13l-1.4 5m0 0h10.8M17 18a1 1 0 11-2 0 1 1 0 012 0zm-8 0a1 1 0 11-2 0 1 1 0 012 0z" />
                </svg>
              </div>
              <p className="mt-4 text-sm text-gray-500">No orders match your filters.</p>
            </div>
          ) : (
            <table className="min-w-full divide-y divide-gray-100">
              <thead className="bg-gray-50 sticky top-0 z-10">
                <tr>
                  <th className="py-3 pl-4 pr-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 sm:pl-6">Order #</th>
                  <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Date</th>
                  <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Source</th>
                  <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Payment</th>
                  <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Status</th>
                  <th className="px-3 py-3 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {filtered.map((order) => (
                  <tr
                    key={order.id}
                    onClick={() => setSelectedOrder(order)}
                    className={`cursor-pointer transition-colors hover:bg-gray-50 ${selectedOrder?.id === order.id ? "bg-blue-50" : ""}`}
                  >
                    <td className="whitespace-nowrap py-3 pl-4 pr-3 text-sm font-mono font-medium text-gray-900 sm:pl-6">
                      {order.order_number}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">{fmtDate(order.order_date)}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">
                      {SOURCE_LABELS[order.source] ?? order.source}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">{order.payment_method}</td>
                    <td className="whitespace-nowrap px-3 py-3">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_STYLES[order.status] ?? "bg-gray-100 text-gray-600"}`}>
                        {order.status.charAt(0).toUpperCase() + order.status.slice(1)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-right text-sm font-bold text-gray-900">
                      {fmt(order.grand_total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!isLoading && filtered.length > 0 && (
            <div className="border-t border-gray-100 bg-gray-50 px-6 py-2 text-xs text-gray-500">
              {filtered.length} of {orders.length} orders
            </div>
          )}
        </div>

        {/* Detail slide-over panel */}
        {selectedOrder && (
          <div ref={panelRef} className="w-full max-w-md flex-shrink-0 overflow-auto rounded-xl border border-gray-200 bg-white shadow-lg animate-in slide-in-from-right-8">
            <OrderDetailPanel order={selectedOrder} onClose={() => setSelectedOrder(null)} />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Detail Panel ────────────────────────────────────────────────────────────

function OrderDetailPanel({ order, onClose }: { order: Order; onClose: () => void }) {
  const statusStyle = STATUS_STYLES[order.status] ?? "bg-gray-100 text-gray-600";
  const itemCount = order.items.reduce((s, i) => s + i.qty, 0);

  return (
    <div className="flex flex-col h-full">
      {/* Panel header */}
      <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4 bg-gray-50 rounded-t-xl">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Order Details</p>
          <p className="mt-0.5 font-mono text-sm font-semibold text-gray-900">{order.order_number}</p>
        </div>
        <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-600 transition">
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {/* Status + info */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">Status</span>
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${statusStyle}`}>
              {order.status.charAt(0).toUpperCase() + order.status.slice(1)}
            </span>
          </div>
          <InfoRow label="Date" value={fmtDate(order.order_date)} />
          <InfoRow label="Source" value={SOURCE_LABELS[order.source] ?? order.source} />
          <InfoRow label="Payment" value={order.payment_method} />
          {order.payment_ref && <InfoRow label="Reference" value={order.payment_ref} />}
        </div>

        {/* Items */}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">Items ({itemCount})</h3>
          <div className="space-y-2">
            {order.items.map((item) => (
              <div key={item.id} className="flex items-start justify-between gap-3 rounded-lg bg-gray-50 px-3 py-2.5 text-sm">
                <div>
                  <p className="font-mono text-xs font-medium text-gray-700">{item.sku_id}</p>
                  <p className="text-gray-500">{item.qty} × {fmt(item.unit_price)}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-semibold">{fmt(item.line_total)}</p>
                  {item.discount > 0 && (
                    <p className="text-xs text-green-600">−{fmt(item.discount)}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Totals */}
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 space-y-2">
          <InfoRow label="Subtotal" value={fmt(order.subtotal)} />
          {order.discount_total > 0 && <InfoRow label="Discount" value={`−${fmt(order.discount_total)}`} valueClass="text-green-600" />}
          <InfoRow label="Tax" value={fmt(order.tax_total)} />
          <div className="border-t border-gray-200 pt-2 mt-2 flex justify-between">
            <span className="text-sm font-bold text-gray-900">Grand Total</span>
            <span className="text-base font-bold text-gray-900">{fmt(order.grand_total)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value, valueClass = "" }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-gray-500">{label}</span>
      <span className={`font-medium text-gray-900 ${valueClass}`}>{value}</span>
    </div>
  );
}
