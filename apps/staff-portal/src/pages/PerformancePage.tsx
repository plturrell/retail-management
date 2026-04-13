import { useCallback, useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { api } from "../lib/api";

// ── Types ────────────────────────────────────────────────

type Period = "week" | "month" | "quarter";

interface StaffPerformanceItem {
  user_id: string;
  full_name: string;
  total_sales: number;
  order_count: number;
  avg_order_value: number;
  rank: number;
}

interface StaffPerformanceOverview {
  generated_at: string;
  store_id: string;
  period_from: string;
  period_to: string;
  staff: StaffPerformanceItem[];
  total_store_sales: number;
}

interface StaffInsightsResponse {
  user_id: string;
  full_name: string;
  summary: {
    total_sales: number;
    order_count: number;
    avg_order_value: number;
    period_from: string;
    period_to: string;
  };
  ai_insights: string | null;
}

interface UserStoreRole {
  store_id: string;
  role: string;
}

interface UserMe {
  id: string;
  full_name: string;
  email: string;
  store_roles: UserStoreRole[];
}

// ── Helpers ──────────────────────────────────────────────

function periodDates(period: Period): { from: string; to: string; prevFrom: string; prevTo: string } {
  const today = new Date();
  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  if (period === "week") {
    const dow = today.getDay();
    const startOfWeek = new Date(today);
    startOfWeek.setDate(today.getDate() - ((dow + 6) % 7)); // Monday
    const prevStart = new Date(startOfWeek);
    prevStart.setDate(prevStart.getDate() - 7);
    const prevEnd = new Date(startOfWeek);
    prevEnd.setDate(prevEnd.getDate() - 1);
    return { from: fmt(startOfWeek), to: fmt(today), prevFrom: fmt(prevStart), prevTo: fmt(prevEnd) };
  }

  if (period === "month") {
    const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    const prevStart = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const prevEnd = new Date(startOfMonth);
    prevEnd.setDate(prevEnd.getDate() - 1);
    return { from: fmt(startOfMonth), to: fmt(today), prevFrom: fmt(prevStart), prevTo: fmt(prevEnd) };
  }

  // quarter
  const qMonth = Math.floor(today.getMonth() / 3) * 3;
  const startOfQ = new Date(today.getFullYear(), qMonth, 1);
  const prevQStart = new Date(today.getFullYear(), qMonth - 3, 1);
  const prevQEnd = new Date(startOfQ);
  prevQEnd.setDate(prevQEnd.getDate() - 1);
  return { from: fmt(startOfQ), to: fmt(today), prevFrom: fmt(prevQStart), prevTo: fmt(prevQEnd) };
}

function fmtCurrency(v: number): string {
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function changePct(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}

// Generate last 6 months labels
function last6Months(): { key: string; label: string }[] {
  const months: { key: string; label: string }[] = [];
  const now = new Date();
  for (let i = 5; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    months.push({
      key: d.toISOString().slice(0, 7),
      label: d.toLocaleDateString("en-US", { month: "short" }),
    });
  }
  return months;
}

// ── Component ────────────────────────────────────────────

export default function PerformancePage() {
  const [period, setPeriod] = useState<Period>("month");
  const [storeId, setStoreId] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);

  // Current period data
  const [perfData, setPerfData] = useState<StaffPerformanceOverview | null>(null);
  const [prevPerfData, setPrevPerfData] = useState<StaffPerformanceOverview | null>(null);
  const [insights, setInsights] = useState<StaffInsightsResponse | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Trend data — one fetch per month for last 6 months
  const [trendData, setTrendData] = useState<{ month: string; sales: number }[]>([]);

  // 1. Get user profile on mount
  useEffect(() => {
    api
      .get<{ data: UserMe }>("/api/users/me")
      .then((res) => {
        setUserId(res.data.id);
        const firstStore = res.data.store_roles[0];
        if (firstStore) setStoreId(firstStore.store_id);
      })
      .catch(() => setError("Failed to load user profile"));
  }, []);

  // 2. Fetch performance for current + previous period
  const fetchPerformance = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const { from, to, prevFrom, prevTo } = periodDates(period);
      const [current, previous] = await Promise.all([
        api.get<StaffPerformanceOverview>(
          `/api/stores/${storeId}/analytics/staff-performance?from=${from}&to=${to}`
        ),
        api.get<StaffPerformanceOverview>(
          `/api/stores/${storeId}/analytics/staff-performance?from=${prevFrom}&to=${prevTo}`
        ),
      ]);
      setPerfData(current);
      setPrevPerfData(previous);
    } catch {
      setError("Failed to load performance data");
    } finally {
      setLoading(false);
    }
  }, [storeId, period]);

  useEffect(() => {
    fetchPerformance();
  }, [fetchPerformance]);

  // 3. Fetch AI insights
  useEffect(() => {
    if (!storeId || !userId) return;
    setInsightsLoading(true);
    api
      .get<StaffInsightsResponse>(
        `/api/stores/${storeId}/analytics/staff/${userId}/insights`
      )
      .then(setInsights)
      .catch(() => {})
      .finally(() => setInsightsLoading(false));
  }, [storeId, userId]);

  // 4. Build 6-month trend from individual monthly fetches
  useEffect(() => {
    if (!storeId || !userId) return;
    const months = last6Months();
    Promise.all(
      months.map(async (m) => {
        const start = `${m.key}-01`;
        const endDate = new Date(
          parseInt(m.key.slice(0, 4)),
          parseInt(m.key.slice(5, 7)),
          0
        );
        const end = endDate.toISOString().slice(0, 10);
        try {
          const res = await api.get<StaffPerformanceOverview>(
            `/api/stores/${storeId}/analytics/staff-performance?from=${start}&to=${end}`
          );
          const me = res.staff.find((s) => s.user_id === userId);
          return { month: m.label, sales: me?.total_sales ?? 0 };
        } catch {
          return { month: m.label, sales: 0 };
        }
      })
    ).then(setTrendData);
  }, [storeId, userId]);

  // Derived values
  const myData = useMemo(
    () => perfData?.staff.find((s) => s.user_id === userId) ?? null,
    [perfData, userId]
  );
  const myPrevData = useMemo(
    () => prevPerfData?.staff.find((s) => s.user_id === userId) ?? null,
    [prevPerfData, userId]
  );

  const periodLabel = period === "week" ? "This Week" : period === "month" ? "This Month" : "This Quarter";
  const totalStaff = perfData?.staff.length ?? 0;
  const myRank = myData?.rank ?? null;
  const salesChange = changePct(myData?.total_sales ?? 0, myPrevData?.total_sales ?? 0);

  // ── Render ─────────────────────────────────────────────

  if (error && !perfData) {
    return (
      <div>
        <h1 className="text-xl font-bold text-gray-800">Performance</h1>
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-600">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header + Period Selector */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Performance</h1>
          <p className="mt-1 text-sm text-gray-500">Track your sales performance and targets.</p>
        </div>
        <div className="flex gap-1 rounded-lg bg-gray-100 p-1">
          {(["week", "month", "quarter"] as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                period === p
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {p === "week" ? "Week" : p === "month" ? "Month" : "Quarter"}
            </button>
          ))}
        </div>
      </div>


      {/* Sales Summary Cards */}
      {loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse rounded-lg border border-gray-200 bg-white p-5">
              <div className="h-3 w-20 rounded bg-gray-200" />
              <div className="mt-3 h-7 w-28 rounded bg-gray-200" />
              <div className="mt-2 h-3 w-16 rounded bg-gray-200" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <SummaryCard
            label={periodLabel}
            value={fmtCurrency(myData?.total_sales ?? 0)}
            change={salesChange}
          />
          <SummaryCard
            label="Orders"
            value={String(myData?.order_count ?? 0)}
            subtitle={`Avg ${fmtCurrency(myData?.avg_order_value ?? 0)} per order`}
          />
          <SummaryCard
            label="Store Total"
            value={fmtCurrency(perfData?.total_store_sales ?? 0)}
            subtitle={
              myData && perfData && perfData.total_store_sales > 0
                ? `You: ${Math.round((myData.total_sales / perfData.total_store_sales) * 100)}% of total`
                : undefined
            }
          />
        </div>
      )}

      {/* Sales Trend Chart */}
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-gray-700">Sales Trend — Last 6 Months</h2>
        <div className="mt-4 h-56">
          {trendData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                <YAxis
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
                />
                <Tooltip
                  formatter={(value: number) => [fmtCurrency(value), "Sales"]}
                  contentStyle={{ fontSize: 13 }}
                />
                <Line
                  type="monotone"
                  dataKey="sales"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={{ r: 4, fill: "#3b82f6" }}
                  activeDot={{ r: 6 }}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-gray-400">
              Loading trend data…
            </div>
          )}
        </div>
      </div>

      {/* Peer Ranking */}
      {!loading && perfData && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-gray-700">Peer Ranking</h2>
          {myRank !== null ? (
            <p className="mt-2 text-sm text-gray-600">
              You are ranked{" "}
              <span className="font-bold text-blue-600">#{myRank}</span> of{" "}
              <span className="font-semibold">{totalStaff}</span> salespeople{" "}
              {periodLabel.toLowerCase()}.
            </p>
          ) : (
            <p className="mt-2 text-sm text-gray-400">No ranking data available.</p>
          )}

          <div className="mt-4 space-y-2">
            {perfData.staff.map((s, idx) => {
              const isMe = s.user_id === userId;
              const pct =
                perfData.total_store_sales > 0
                  ? (s.total_sales / perfData.total_store_sales) * 100
                  : 0;
              return (
                <div key={s.user_id} className="flex items-center gap-3">
                  <span className="w-6 text-right text-xs font-medium text-gray-400">
                    #{s.rank}
                  </span>
                  <div className="flex-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className={isMe ? "font-semibold text-blue-700" : "text-gray-600"}>
                        {isMe ? "You" : `Salesperson ${idx + 1}`}
                      </span>
                      <span className="font-medium text-gray-700">
                        {fmtCurrency(s.total_sales)}
                      </span>
                    </div>
                    <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-gray-100">
                      <div
                        className={`h-full rounded-full ${isMe ? "bg-blue-500" : "bg-gray-300"}`}
                        style={{ width: `${Math.max(pct, 2)}%` }}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* AI Insights Panel */}
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="flex items-center gap-2">
          <span className="text-lg">✨</span>
          <h2 className="text-sm font-semibold text-gray-700">AI Insights</h2>
        </div>

        {insightsLoading ? (
          <div className="mt-4 space-y-2">
            <div className="h-3 w-full animate-pulse rounded bg-gray-200" />
            <div className="h-3 w-5/6 animate-pulse rounded bg-gray-200" />
            <div className="h-3 w-4/6 animate-pulse rounded bg-gray-200" />
            <p className="mt-3 text-xs text-gray-400">Generating personalized insights…</p>
          </div>
        ) : insights?.ai_insights ? (
          <div className="mt-3 rounded-lg bg-blue-50 p-4">
            <p className="whitespace-pre-line text-sm leading-relaxed text-gray-700">
              {insights.ai_insights}
            </p>
          </div>
        ) : (
          <p className="mt-3 text-sm text-gray-400">
            No AI insights available yet. Check back after more sales data is recorded.
          </p>
        )}
      </div>
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────

function SummaryCard({
  label,
  value,
  change,
  subtitle,
}: {
  label: string;
  value: string;
  change?: number | null;
  subtitle?: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-1 text-2xl font-bold text-gray-900">{value}</p>
      {change !== undefined && change !== null && (
        <p
          className={`mt-1 text-xs font-medium ${
            change >= 0 ? "text-green-600" : "text-red-500"
          }`}
        >
          {change >= 0 ? "↑" : "↓"} {Math.abs(change)}% vs previous period
        </p>
      )}
      {subtitle && <p className="mt-1 text-xs text-gray-400">{subtitle}</p>}
    </div>
  );
}