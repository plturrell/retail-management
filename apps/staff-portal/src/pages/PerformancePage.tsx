import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
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
type CanonicalStoreCode = "BREEZE-01" | "JEWEL-01" | "TAKA-01" | "ISETAN-01" | "ONLINE-01";

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

interface ProfitLossLabor {
  hours_worked: number;
  sales_order_count: number;
  sales_amount: number;
  payroll_gross: number;
  cpf_employer: number;
  total_labor_cost: number;
  sales_per_labor_hour: number;
  labor_cost_percent_of_sales: number;
}

interface ProfitLossReport {
  period: {
    from_date: string;
    to_date: string;
  };
  net_profit: number;
  margin_percent: number;
  labor: ProfitLossLabor;
}

interface EmployeeCostLine {
  user_id: string;
  full_name: string;
  hours_worked: number;
  sales_amount: number;
  sales_order_count: number;
  sales_per_hour: number;
  gross_pay: number;
  cpf_employer: number;
  labor_cost_percent_of_sales: number;
  total_cost: number;
}

interface EmployeeCostReport {
  period: {
    from_date: string;
    to_date: string;
  };
  employees: EmployeeCostLine[];
  total_hours_worked: number;
  total_sales_amount: number;
  total_sales_order_count: number;
  sales_per_labor_hour: number;
  total_salary: number;
  total_cpf_employer: number;
  total_cost: number;
}

interface BackfillMetricsResponse {
  store_id: string;
  runs_scanned: number;
  runs_updated: number;
  payslips_updated: number;
}

interface StoreProfitabilitySnapshot {
  storeId: string | null;
  storeName: string;
  storeCode: CanonicalStoreCode;
  available: boolean;
  salesAmount: number;
  laborCost: number;
  totalHours: number;
  salesPerLaborHour: number;
  netProfit: number;
  marginPercent: number;
  salesOrderCount: number;
}

const CANONICAL_STORE_ORDER: CanonicalStoreCode[] = [
  "BREEZE-01",
  "JEWEL-01",
  "TAKA-01",
  "ISETAN-01",
  "ONLINE-01",
];

const CANONICAL_STORE_LABELS: Record<CanonicalStoreCode, string> = {
  "BREEZE-01": "Breeze",
  "JEWEL-01": "Jewel",
  "TAKA-01": "Takashimaya",
  "ISETAN-01": "Isetan",
  "ONLINE-01": "Online",
};

const STORE_ALIASES: Record<CanonicalStoreCode, string[]> = {
  "BREEZE-01": [
    "breeze",
    "breezebyeast",
    "victoriaensobreezebyeast",
    "victoriaensobreeze",
    "hqwarehouse",
  ],
  "JEWEL-01": [
    "jewel",
    "jewelchangi",
    "jewelchangiairport",
    "jewelb1241",
    "jewelb1241",
  ],
  "TAKA-01": [
    "taka",
    "takashimaya",
    "takashimayashoppingcentre",
  ],
  "ISETAN-01": [
    "isetan",
    "isetanscotts",
    "shawhouse",
  ],
  "ONLINE-01": [
    "online",
    "onlinestore",
    "website",
    "shopify",
    "webstore",
  ],
};

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

function normalizeStoreToken(value: string | null | undefined) {
  return (value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function canonicalStoreCodeForStore(store: {
  store_code?: string | null;
  name: string;
  location?: string;
  address?: string;
}): CanonicalStoreCode | null {
  const normalizedStoreCode = normalizeStoreToken(store.store_code);
  const directMatch = CANONICAL_STORE_ORDER.find(
    (code) => normalizeStoreToken(code) === normalizedStoreCode
  );
  if (directMatch) {
    return directMatch;
  }

  const tokens = [
    normalizeStoreToken(store.name),
    normalizeStoreToken(store.location),
    normalizeStoreToken(store.address),
  ];

  for (const code of CANONICAL_STORE_ORDER) {
    const aliases = STORE_ALIASES[code];
    if (tokens.some((token) => aliases.includes(token))) {
      return code;
    }
  }

  return null;
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
  const {
    profile: userProfile,
    selectedStore,
    stores,
    loading: authLoading,
    canViewSensitiveOperations,
  } = useAuth();
  const [period, setPeriod] = useState<Period>("month");

  // Current period data
  const [perfData, setPerfData] = useState<StaffPerformanceOverview | null>(null);
  const [prevPerfData, setPrevPerfData] = useState<StaffPerformanceOverview | null>(null);
  const [insights, setInsights] = useState<StaffInsightsResponse | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [profitLoss, setProfitLoss] = useState<ProfitLossReport | null>(null);
  const [employeeCosts, setEmployeeCosts] = useState<EmployeeCostReport | null>(null);
  const [comparisonData, setComparisonData] = useState<StoreProfitabilitySnapshot[]>([]);
  const [ownerLoading, setOwnerLoading] = useState(false);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillMessage, setBackfillMessage] = useState<string | null>(null);
  const [ownerRefreshKey, setOwnerRefreshKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Trend data — one fetch per month for last 6 months
  const [trendData, setTrendData] = useState<{ month: string; sales: number }[]>([]);
  const storeId = selectedStore?.id ?? null;
  const userId = userProfile?.id ?? null;
  const activePeriod = useMemo(() => periodDates(period), [period]);
  const ownerStoreIds = useMemo(
    () =>
      new Set(
        (userProfile?.store_roles ?? [])
          .filter((role) => role.role === "owner")
          .map((role) => role.store_id)
      ),
    [userProfile?.store_roles]
  );
  const comparisonStores = useMemo(() => {
    const ownedStores = stores
      .filter((store) => ownerStoreIds.has(store.id))
      .map((store) => ({
        ...store,
        canonicalCode: canonicalStoreCodeForStore(store),
      }));

    return CANONICAL_STORE_ORDER.map((code) => {
      const matchedStore = ownedStores.find((store) => store.canonicalCode === code);
      return {
        canonicalCode: code,
        storeId: matchedStore?.id ?? null,
        storeName: matchedStore?.name ?? CANONICAL_STORE_LABELS[code],
      };
    });
  }, [ownerStoreIds, stores]);

  // 2. Fetch performance for current + previous period
  const fetchPerformance = useCallback(async () => {
    if (!storeId) {
      setPerfData(null);
      setPrevPerfData(null);
      setError("No assigned store selected");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const { from, to, prevFrom, prevTo } = activePeriod;
      const [current, previous] = await Promise.all([
        api.get<StaffPerformanceOverview>(
          `/stores/${storeId}/analytics/staff-performance?from=${from}&to=${to}`
        ),
        api.get<StaffPerformanceOverview>(
          `/stores/${storeId}/analytics/staff-performance?from=${prevFrom}&to=${prevTo}`
        ),
      ]);
      setPerfData(current);
      setPrevPerfData(previous);
    } catch {
      setError("Failed to load performance data");
    } finally {
      setLoading(false);
    }
  }, [activePeriod, storeId]);

  useEffect(() => {
    if (authLoading) return;
    void fetchPerformance();
  }, [authLoading, fetchPerformance]);

  useEffect(() => {
    if (!storeId || !canViewSensitiveOperations) {
      setProfitLoss(null);
      setEmployeeCosts(null);
      setOwnerLoading(false);
      return;
    }

    setOwnerLoading(true);
    Promise.all([
      api.get<{ data: ProfitLossReport }>(
        `/stores/${storeId}/reports/profit-loss?from=${activePeriod.from}&to=${activePeriod.to}`
      ),
      api.get<{ data: EmployeeCostReport }>(
        `/stores/${storeId}/reports/employee-costs?from=${activePeriod.from}&to=${activePeriod.to}`
      ),
    ])
      .then(([profitLossRes, employeeCostsRes]) => {
        setProfitLoss(profitLossRes.data);
        setEmployeeCosts(employeeCostsRes.data);
      })
      .catch(() => {
        setProfitLoss(null);
        setEmployeeCosts(null);
      })
      .finally(() => setOwnerLoading(false));
  }, [activePeriod.from, activePeriod.to, canViewSensitiveOperations, ownerRefreshKey, storeId]);

  useEffect(() => {
    if (!canViewSensitiveOperations) {
      setComparisonData([]);
      setComparisonLoading(false);
      return;
    }

    setComparisonLoading(true);
    Promise.all(
      comparisonStores.map(async (store) => {
        if (!store.storeId) {
          return {
            storeId: null,
            storeName: store.storeName,
            storeCode: store.canonicalCode,
            available: false,
            salesAmount: 0,
            laborCost: 0,
            totalHours: 0,
            salesPerLaborHour: 0,
            netProfit: 0,
            marginPercent: 0,
            salesOrderCount: 0,
          } satisfies StoreProfitabilitySnapshot;
        }

        try {
          const response = await api.get<{ data: ProfitLossReport }>(
            `/stores/${store.storeId}/reports/profit-loss?from=${activePeriod.from}&to=${activePeriod.to}`
          );
          return {
            storeId: store.storeId,
            storeName: store.storeName,
            storeCode: store.canonicalCode,
            available: true,
            salesAmount: response.data.labor.sales_amount,
            laborCost: response.data.labor.total_labor_cost,
            totalHours: response.data.labor.hours_worked,
            salesPerLaborHour: response.data.labor.sales_per_labor_hour,
            netProfit: response.data.net_profit,
            marginPercent: response.data.margin_percent,
            salesOrderCount: response.data.labor.sales_order_count,
          } satisfies StoreProfitabilitySnapshot;
        } catch {
          return {
            storeId: store.storeId,
            storeName: store.storeName,
            storeCode: store.canonicalCode,
            available: false,
            salesAmount: 0,
            laborCost: 0,
            totalHours: 0,
            salesPerLaborHour: 0,
            netProfit: 0,
            marginPercent: 0,
            salesOrderCount: 0,
          } satisfies StoreProfitabilitySnapshot;
        }
      })
    )
      .then(setComparisonData)
      .finally(() => setComparisonLoading(false));
  }, [activePeriod.from, activePeriod.to, canViewSensitiveOperations, comparisonStores, ownerRefreshKey]);

  // 3. Fetch AI insights
  useEffect(() => {
    if (!storeId || !userId) {
      setInsights(null);
      return;
    }
    setInsightsLoading(true);
    api
      .get<StaffInsightsResponse>(
        `/stores/${storeId}/analytics/staff/${userId}/insights`
      )
      .then(setInsights)
      .catch(() => {})
      .finally(() => setInsightsLoading(false));
  }, [storeId, userId]);

  // 4. Build 6-month trend from individual monthly fetches
  useEffect(() => {
    if (!storeId || !userId) {
      setTrendData([]);
      return;
    }
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
            `/stores/${storeId}/analytics/staff-performance?from=${start}&to=${end}`
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
  const topEmployeeCosts = employeeCosts?.employees.slice(0, 5) ?? [];
  const crossStoreTotals = useMemo(
    () =>
      comparisonData.reduce(
        (totals, store) => ({
          salesAmount: totals.salesAmount + store.salesAmount,
          laborCost: totals.laborCost + store.laborCost,
          netProfit: totals.netProfit + store.netProfit,
        }),
        { salesAmount: 0, laborCost: 0, netProfit: 0 }
      ),
    [comparisonData]
  );

  const handleBackfillMetrics = useCallback(async () => {
    const storesToBackfill = comparisonStores.filter((store) => store.storeId);
    if (storesToBackfill.length === 0) return;

    setBackfillMessage(null);
    setBackfilling(true);
    try {
      const responses = await Promise.all(
        storesToBackfill.map((store) =>
          api.post<{ data: BackfillMetricsResponse }>(
            `/stores/${store.storeId}/payroll/backfill-metrics`,
            {}
          )
        )
      );
      const summary = responses.reduce(
        (totals, response) => ({
          runsUpdated: totals.runsUpdated + response.data.runs_updated,
          payslipsUpdated: totals.payslipsUpdated + response.data.payslips_updated,
        }),
        { runsUpdated: 0, payslipsUpdated: 0 }
      );
      setBackfillMessage(
        `Backfilled ${summary.runsUpdated} payroll runs and ${summary.payslipsUpdated} payslips across ${storesToBackfill.length} stores.`
      );
      setOwnerRefreshKey((value) => value + 1);
    } catch {
      setBackfillMessage("Backfill failed. Please try again for the selected stores.");
    } finally {
      setBackfilling(false);
    }
  }, [comparisonStores]);

  // ── Render ─────────────────────────────────────────────

  if (authLoading) {
    return <div className="flex items-center justify-center py-20 text-gray-400">Loading performance…</div>;
  }

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

      {canViewSensitiveOperations && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-gray-700">Store Labor Profitability</h2>
              <p className="mt-1 text-xs text-gray-400">
                Payroll, approved hours, and attributed sales for the selected store and period.
              </p>
            </div>
            <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-amber-700">
              Owner View
            </span>
          </div>

          {ownerLoading ? (
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-4">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="animate-pulse rounded-lg border border-gray-100 bg-gray-50 p-4">
                  <div className="h-3 w-20 rounded bg-gray-200" />
                  <div className="mt-3 h-6 w-24 rounded bg-gray-200" />
                </div>
              ))}
            </div>
          ) : profitLoss ? (
            <>
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <SummaryCard label="Store Sales" value={fmtCurrency(profitLoss.labor.sales_amount)} />
                <SummaryCard
                  label="Labor Cost"
                  value={fmtCurrency(profitLoss.labor.total_labor_cost)}
                  subtitle={`${profitLoss.labor.labor_cost_percent_of_sales.toFixed(1)}% of sales`}
                />
                <SummaryCard
                  label="Sales / Labor Hr"
                  value={fmtCurrency(profitLoss.labor.sales_per_labor_hour)}
                  subtitle={`${profitLoss.labor.hours_worked.toFixed(1)} approved hours`}
                />
                <SummaryCard
                  label="Net Profit"
                  value={fmtCurrency(profitLoss.net_profit)}
                  subtitle={`${profitLoss.margin_percent.toFixed(1)}% margin`}
                />
              </div>
              <div className="mt-4 grid grid-cols-1 gap-3 text-sm text-gray-600 sm:grid-cols-3">
                <DetailCard
                  label="Orders Counted"
                  value={String(profitLoss.labor.sales_order_count)}
                  detail="Store-attributed completed sales"
                />
                <DetailCard
                  label="Payroll Gross"
                  value={fmtCurrency(profitLoss.labor.payroll_gross)}
                  detail="Before employer CPF"
                />
                <DetailCard
                  label="Employer CPF"
                  value={fmtCurrency(profitLoss.labor.cpf_employer)}
                  detail="Additional labor burden"
                />
              </div>
            </>
          ) : (
            <p className="mt-4 text-sm text-gray-400">No owner profitability data available for this period.</p>
          )}
        </div>
      )}

      {canViewSensitiveOperations && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-gray-700">Five-Store Comparison</h2>
              <p className="mt-1 text-xs text-gray-400">
                Compare Breeze, Jewel, Takashimaya, Isetan, and Online side by side for the selected period.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void handleBackfillMetrics()}
              disabled={backfilling}
              className="rounded-md border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {backfilling ? "Backfilling…" : "Backfill Historical Payroll Metrics"}
            </button>
          </div>

          {backfillMessage && (
            <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {backfillMessage}
            </div>
          )}

          {comparisonLoading ? (
            <div className="mt-4 space-y-2">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="h-16 animate-pulse rounded-lg bg-gray-100" />
              ))}
            </div>
          ) : (
            <>
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
                <SummaryCard label="Combined Sales" value={fmtCurrency(crossStoreTotals.salesAmount)} />
                <SummaryCard label="Combined Labor Cost" value={fmtCurrency(crossStoreTotals.laborCost)} />
                <SummaryCard label="Combined Net Profit" value={fmtCurrency(crossStoreTotals.netProfit)} />
              </div>

              <div className="mt-4 overflow-hidden rounded-lg border border-gray-100">
                <div className="grid grid-cols-[minmax(0,2fr)_repeat(5,minmax(0,1fr))] gap-3 bg-gray-50 px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                  <span>Location</span>
                  <span>Sales</span>
                  <span>Labor Cost</span>
                  <span>Hours</span>
                  <span>Sales / Hr</span>
                  <span>Net Profit</span>
                </div>
                {comparisonData.map((store) => (
                  <div
                    key={store.storeCode}
                    className="grid grid-cols-[minmax(0,2fr)_repeat(5,minmax(0,1fr))] gap-3 border-t border-gray-100 px-4 py-3 text-sm text-gray-700"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium text-gray-900">{CANONICAL_STORE_LABELS[store.storeCode]}</p>
                      <p className="text-xs text-gray-400">
                        {store.available ? `${store.salesOrderCount} completed orders` : "No accessible data"}
                      </p>
                    </div>
                    <span>{store.available ? fmtCurrency(store.salesAmount) : "—"}</span>
                    <span>{store.available ? fmtCurrency(store.laborCost) : "—"}</span>
                    <span>{store.available ? `${store.totalHours.toFixed(1)}h` : "—"}</span>
                    <span>{store.available ? fmtCurrency(store.salesPerLaborHour) : "—"}</span>
                    <div>
                      <p>{store.available ? fmtCurrency(store.netProfit) : "—"}</p>
                      {store.available && (
                        <p className="text-xs text-gray-400">{store.marginPercent.toFixed(1)}% margin</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

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
                        {isMe ? "You" : canViewSensitiveOperations ? s.full_name : `Salesperson ${idx + 1}`}
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

      {canViewSensitiveOperations && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-gray-700">Salesperson Productivity</h2>
          <p className="mt-1 text-xs text-gray-400">
            Store-linked payroll cost against approved hours and attributed sales.
          </p>

          {ownerLoading ? (
            <div className="mt-4 space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-14 animate-pulse rounded-lg bg-gray-100" />
              ))}
            </div>
          ) : employeeCosts && topEmployeeCosts.length > 0 ? (
            <div className="mt-4 space-y-3">
              <div className="grid grid-cols-1 gap-3 text-sm text-gray-600 sm:grid-cols-4">
                <DetailCard
                  label="Store Hours"
                  value={employeeCosts.total_hours_worked.toFixed(1)}
                  detail="Approved hours in period"
                />
                <DetailCard
                  label="Tracked Sales"
                  value={fmtCurrency(employeeCosts.total_sales_amount)}
                  detail={`${employeeCosts.total_sales_order_count} orders`}
                />
                <DetailCard
                  label="Sales / Labor Hr"
                  value={fmtCurrency(employeeCosts.sales_per_labor_hour)}
                  detail="Store productivity"
                />
                <DetailCard
                  label="Labor Cost"
                  value={fmtCurrency(employeeCosts.total_cost)}
                  detail="Gross pay + employer CPF"
                />
              </div>

              <div className="overflow-hidden rounded-lg border border-gray-100">
                <div className="grid grid-cols-[minmax(0,2fr)_repeat(4,minmax(0,1fr))] gap-3 bg-gray-50 px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                  <span>Salesperson</span>
                  <span>Sales</span>
                  <span>Hours</span>
                  <span>Sales / Hr</span>
                  <span>Labor %</span>
                </div>
                {topEmployeeCosts.map((employee) => (
                  <div
                    key={employee.user_id}
                    className="grid grid-cols-[minmax(0,2fr)_repeat(4,minmax(0,1fr))] gap-3 border-t border-gray-100 px-4 py-3 text-sm text-gray-700"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium text-gray-900">{employee.full_name}</p>
                      <p className="text-xs text-gray-400">{employee.sales_order_count} attributed orders</p>
                    </div>
                    <span>{fmtCurrency(employee.sales_amount)}</span>
                    <span>{employee.hours_worked.toFixed(1)}h</span>
                    <span>{fmtCurrency(employee.sales_per_hour)}</span>
                    <span>{employee.labor_cost_percent_of_sales.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-gray-400">No salesperson productivity data available for this period.</p>
          )}
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

function DetailCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-1 text-lg font-bold text-gray-900">{value}</p>
      <p className="mt-1 text-xs text-gray-500">{detail}</p>
    </div>
  );
}
