import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../lib/api";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from "recharts";

// ── Types ──────────────────────────────────────────────────────────────────

interface Order {
  id: string;
  order_date: string;
  status: "open" | "completed" | "voided";
  subtotal: number;
  discount_total: number;
  tax_total: number;
  grand_total: number;
  payment_method: string;
  items: { qty: number }[];
}

interface FinancialSummary {
  totalRevenue: number;
  totalOrders: number;
  completedOrders: number;
  voidedOrders: number;
  averageOrderValue: number;
  discountsGiven: number;
  taxCollected: number;
  topPaymentMethod: string;
}

interface DailyRevenue {
  day: string;
  revenue: number;
}

function fmt(n: number) {
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function buildSummary(orders: Order[]): FinancialSummary {
  const completed = orders.filter((o) => o.status === "completed");
  const totalRevenue = completed.reduce((s, o) => s + o.grand_total, 0);

  const paymentCounts: Record<string, number> = {};
  completed.forEach((o) => {
    paymentCounts[o.payment_method] = (paymentCounts[o.payment_method] ?? 0) + 1;
  });
  const topPaymentMethod =
    Object.entries(paymentCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "—";

  return {
    totalRevenue,
    totalOrders: orders.length,
    completedOrders: completed.length,
    voidedOrders: orders.filter((o) => o.status === "voided").length,
    averageOrderValue: completed.length > 0 ? totalRevenue / completed.length : 0,
    discountsGiven: orders.reduce((s, o) => s + o.discount_total, 0),
    taxCollected: completed.reduce((s, o) => s + o.tax_total, 0),
    topPaymentMethod,
  };
}

function buildDailyRevenue(orders: Order[]): DailyRevenue[] {
  const completed = orders.filter((o) => o.status === "completed");
  const daily: Record<string, number> = {};

  completed.forEach((o) => {
    const dayKey = o.order_date.slice(0, 10);
    daily[dayKey] = (daily[dayKey] ?? 0) + o.grand_total;
  });

  return Object.entries(daily)
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-14)
    .map(([day, revenue]) => ({
      day: new Date(day + "T00:00:00").toLocaleDateString("en-SG", { month: "short", day: "numeric" }),
      revenue,
    }));
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function FinancialsPage() {
  const { selectedStore, loading: authLoading } = useAuth();
  const storeId = selectedStore?.id ?? null;

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<FinancialSummary | null>(null);
  const [dailyRevenue, setDailyRevenue] = useState<DailyRevenue[]>([]);

  const load = useCallback(async () => {
    if (!storeId) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.get<{ data: Order[] }>(`/stores/${storeId}/orders?page_size=500`);
      setSummary(buildSummary(res.data));
      setDailyRevenue(buildDailyRevenue(res.data));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load financial data");
    } finally {
      setIsLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    if (!authLoading && storeId) void load();
  }, [authLoading, storeId, load]);

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Financials</h1>
          <p className="mt-1 text-sm text-gray-500">Revenue overview and sales performance for this store.</p>
        </div>
        <button
          onClick={load}
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

      {isLoading && (
        <div className="flex justify-center py-20">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600" />
        </div>
      )}

      {!isLoading && summary && (
        <>
          {/* Hero Revenue Card */}
          <div className="rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 p-8 text-white shadow-lg">
            <p className="text-sm font-medium text-emerald-100">Total Revenue</p>
            <p className="mt-2 text-5xl font-bold tracking-tight">{fmt(summary.totalRevenue)}</p>
            <div className="mt-3 flex items-center gap-4 text-sm text-emerald-100">
              <span>{summary.totalOrders} orders</span>
              <span>·</span>
              <span>Avg {fmt(summary.averageOrderValue)} per sale</span>
            </div>
          </div>

          {/* Metric Grid */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <MetricCard
              icon={
                <svg className="h-5 w-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              }
              iconBg="bg-green-50"
              label="Completed"
              value={summary.completedOrders.toString()}
            />
            <MetricCard
              icon={
                <svg className="h-5 w-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              }
              iconBg="bg-red-50"
              label="Voided"
              value={summary.voidedOrders.toString()}
            />
            <MetricCard
              icon={
                <svg className="h-5 w-5 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                </svg>
              }
              iconBg="bg-orange-50"
              label="Discounts"
              value={fmt(summary.discountsGiven)}
            />
            <MetricCard
              icon={
                <svg className="h-5 w-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-4 8h4" />
                </svg>
              }
              iconBg="bg-blue-50"
              label="Tax Collected"
              value={fmt(summary.taxCollected)}
            />
          </div>

          {/* Daily Revenue Chart */}
          {dailyRevenue.length > 0 && (
            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
              <h2 className="text-base font-semibold text-gray-900 mb-1">Daily Revenue</h2>
              <p className="text-xs text-gray-500 mb-5">Last {dailyRevenue.length} days with completed orders</p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={dailyRevenue} margin={{ top: 0, right: 0, left: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 11, fill: "#94a3b8" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tickFormatter={(v) => `$${Math.round(v)}`}
                    tick={{ fontSize: 11, fill: "#94a3b8" }}
                    axisLine={false}
                    tickLine={false}
                    width={56}
                  />
                  <Tooltip
                    formatter={(v: number) => [fmt(v), "Revenue"]}
                    contentStyle={{ borderRadius: 12, border: "1px solid #e2e8f0", boxShadow: "0 4px 16px rgba(0,0,0,0.08)" }}
                    labelStyle={{ fontWeight: 600, color: "#111827" }}
                  />
                  <Bar dataKey="revenue" fill="#10b981" radius={[6, 6, 0, 0]} maxBarSize={48} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Top Payment Method */}
          <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm flex items-center gap-4">
            <div className="rounded-xl bg-blue-50 p-3">
              <svg className="h-6 w-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
              </svg>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-gray-500">Top Payment Method</p>
              <p className="mt-0.5 text-lg font-bold text-gray-900">{summary.topPaymentMethod}</p>
            </div>
          </div>
        </>
      )}

      {!isLoading && !summary && !error && (
        <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-gray-200 bg-white/50 p-16 text-center">
          <div className="rounded-full bg-gray-50 p-4">
            <svg className="h-8 w-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="mt-4 text-lg font-semibold text-gray-900">No Financial Data</h3>
          <p className="mt-2 text-sm text-gray-500">Financial data will appear once orders are processed.</p>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  icon, iconBg, label, value,
}: {
  icon: React.ReactNode;
  iconBg: string;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm flex flex-col gap-3">
      <div className={`w-fit rounded-xl p-2 ${iconBg}`}>{icon}</div>
      <div>
        <p className="text-xl font-bold text-gray-900">{value}</p>
        <p className="text-sm text-gray-500 mt-0.5">{label}</p>
      </div>
    </div>
  );
}
