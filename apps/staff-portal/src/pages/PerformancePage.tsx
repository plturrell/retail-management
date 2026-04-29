import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from "recharts";
import { Sparkles, ArrowUpRight, ArrowDownRight, Trophy } from "lucide-react";
import { api } from "../lib/api";
import { classNames, formatMoney, formatMoneyCompact, formatInt } from "../lib/format";
import { PageHeader } from "../components/ui/PageHeader";
import { Card } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Skeleton";
import { SegmentedControl } from "../components/ui/SegmentedControl";

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

function periodDates(period: Period): {
  from: string;
  to: string;
  prevFrom: string;
  prevTo: string;
} {
  const today = new Date();
  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  if (period === "week") {
    const dow = today.getDay();
    const startOfWeek = new Date(today);
    startOfWeek.setDate(today.getDate() - ((dow + 6) % 7));
    const prevStart = new Date(startOfWeek);
    prevStart.setDate(prevStart.getDate() - 7);
    const prevEnd = new Date(startOfWeek);
    prevEnd.setDate(prevEnd.getDate() - 1);
    return {
      from: fmt(startOfWeek),
      to: fmt(today),
      prevFrom: fmt(prevStart),
      prevTo: fmt(prevEnd),
    };
  }

  if (period === "month") {
    const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    const prevStart = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const prevEnd = new Date(startOfMonth);
    prevEnd.setDate(prevEnd.getDate() - 1);
    return {
      from: fmt(startOfMonth),
      to: fmt(today),
      prevFrom: fmt(prevStart),
      prevTo: fmt(prevEnd),
    };
  }

  const qMonth = Math.floor(today.getMonth() / 3) * 3;
  const startOfQ = new Date(today.getFullYear(), qMonth, 1);
  const prevQStart = new Date(today.getFullYear(), qMonth - 3, 1);
  const prevQEnd = new Date(startOfQ);
  prevQEnd.setDate(prevQEnd.getDate() - 1);
  return {
    from: fmt(startOfQ),
    to: fmt(today),
    prevFrom: fmt(prevQStart),
    prevTo: fmt(prevQEnd),
  };
}

function changePct(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}

function last6Months(): { key: string; label: string }[] {
  const months: { key: string; label: string }[] = [];
  const now = new Date();
  for (let i = 5; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    months.push({
      key: d.toISOString().slice(0, 7),
      label: d.toLocaleDateString("en-SG", { month: "short" }),
    });
  }
  return months;
}

export default function PerformancePage() {
  const [period, setPeriod] = useState<Period>("month");
  const [storeId, setStoreId] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);

  const [perfData, setPerfData] = useState<StaffPerformanceOverview | null>(null);
  const [prevPerfData, setPrevPerfData] = useState<StaffPerformanceOverview | null>(null);
  const [insights, setInsights] = useState<StaffInsightsResponse | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [trendData, setTrendData] = useState<{ month: string; sales: number }[]>([]);

  useEffect(() => {
    api
      .get<{ data: UserMe }>("/users/me")
      .then((res) => {
        setUserId(res.data.id);
        const firstStore = res.data.store_roles[0];
        if (firstStore) setStoreId(firstStore.store_id);
      })
      .catch(() => setError("Failed to load user profile"));
  }, []);

  const fetchPerformance = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const { from, to, prevFrom, prevTo } = periodDates(period);
      const [current, previous] = await Promise.all([
        api.get<StaffPerformanceOverview>(
          `/stores/${storeId}/analytics/staff-performance?from=${from}&to=${to}`,
        ),
        api.get<StaffPerformanceOverview>(
          `/stores/${storeId}/analytics/staff-performance?from=${prevFrom}&to=${prevTo}`,
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

  useEffect(() => {
    if (!storeId || !userId) return;
    setInsightsLoading(true);
    api
      .get<StaffInsightsResponse>(`/stores/${storeId}/analytics/staff/${userId}/insights`)
      .then(setInsights)
      .catch(() => {})
      .finally(() => setInsightsLoading(false));
  }, [storeId, userId]);

  useEffect(() => {
    if (!storeId || !userId) return;
    const months = last6Months();
    Promise.all(
      months.map(async (m) => {
        const start = `${m.key}-01`;
        const endDate = new Date(parseInt(m.key.slice(0, 4)), parseInt(m.key.slice(5, 7)), 0);
        const end = endDate.toISOString().slice(0, 10);
        try {
          const res = await api.get<StaffPerformanceOverview>(
            `/stores/${storeId}/analytics/staff-performance?from=${start}&to=${end}`,
          );
          const me = res.staff.find((s) => s.user_id === userId);
          return { month: m.label, sales: me?.total_sales ?? 0 };
        } catch {
          return { month: m.label, sales: 0 };
        }
      }),
    ).then(setTrendData);
  }, [storeId, userId]);

  const myData = useMemo(
    () => perfData?.staff.find((s) => s.user_id === userId) ?? null,
    [perfData, userId],
  );
  const myPrevData = useMemo(
    () => prevPerfData?.staff.find((s) => s.user_id === userId) ?? null,
    [prevPerfData, userId],
  );

  const periodLabel =
    period === "week" ? "This Week" : period === "month" ? "This Month" : "This Quarter";
  const totalStaff = perfData?.staff.length ?? 0;
  const myRank = myData?.rank ?? null;
  const salesChange = changePct(myData?.total_sales ?? 0, myPrevData?.total_sales ?? 0);

  if (error && !perfData) {
    return (
      <div className="space-y-6">
        <PageHeader title="Performance" />
        <div className="rounded-xl border border-[var(--color-negative-600)]/15 bg-[var(--color-negative-50)] p-6 text-center text-sm text-[var(--color-negative-700)]">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Performance"
        description="Track your sales performance and rank."
        action={
          <SegmentedControl<Period>
            ariaLabel="Time period"
            segments={[
              { value: "week", label: "Week" },
              { value: "month", label: "Month" },
              { value: "quarter", label: "Quarter" },
            ]}
            value={period}
            onChange={setPeriod}
          />
        }
      />

      {/* Summary cards */}
      {loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <SummaryCard
            label={periodLabel}
            value={formatMoneyCompact(myData?.total_sales ?? 0)}
            change={salesChange}
            highlight
          />
          <SummaryCard
            label="Orders"
            value={formatInt(myData?.order_count ?? 0)}
            subtitle={`Avg ${formatMoneyCompact(myData?.avg_order_value ?? 0)} / order`}
          />
          <SummaryCard
            label="Store Total"
            value={formatMoneyCompact(perfData?.total_store_sales ?? 0)}
            subtitle={
              myData && perfData && perfData.total_store_sales > 0
                ? `You: ${Math.round((myData.total_sales / perfData.total_store_sales) * 100)}% of total`
                : undefined
            }
          />
        </div>
      )}

      {/* Trend chart */}
      <Card padding="lg">
        <div className="flex items-baseline justify-between">
          <div>
            <h2 className="text-base font-semibold text-[var(--color-ink-primary)]">
              Sales trend
            </h2>
            <p className="text-xs text-[var(--color-ink-muted)]">Last 6 months</p>
          </div>
        </div>
        <div className="mt-4 h-60">
          {trendData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trendData} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <defs>
                  <linearGradient id="salesFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-brand-500)" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="var(--color-brand-500)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis
                  dataKey="month"
                  tick={{ fontSize: 12, fill: "#64748b" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 12, fill: "#64748b" }}
                  tickFormatter={(v: number) => formatMoneyCompact(v)}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  formatter={(value: number) => [formatMoney(value), "Sales"]}
                  contentStyle={{
                    fontSize: 13,
                    borderRadius: 12,
                    border: "1px solid #e2e8f0",
                    boxShadow: "0 10px 30px -8px rgba(15,23,42,0.18)",
                  }}
                  cursor={{ stroke: "#94a3b8", strokeDasharray: "3 3" }}
                />
                <Area
                  type="monotone"
                  dataKey="sales"
                  stroke="transparent"
                  fill="url(#salesFill)"
                />
                <Line
                  type="monotone"
                  dataKey="sales"
                  stroke="var(--color-brand-600)"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: "var(--color-brand-600)", strokeWidth: 0 }}
                  activeDot={{ r: 6, strokeWidth: 2, stroke: "#fff" }}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center">
              <Skeleton className="h-full w-full" />
            </div>
          )}
        </div>
      </Card>

      {/* Peer ranking */}
      {!loading && perfData && (
        <Card padding="lg">
          <div className="flex items-center gap-2">
            <Trophy size={18} className="text-[var(--color-warning-600)]" />
            <h2 className="text-base font-semibold text-[var(--color-ink-primary)]">
              Peer ranking
            </h2>
          </div>
          {myRank !== null ? (
            <p className="mt-1 text-sm text-[var(--color-ink-secondary)]">
              You are{" "}
              <span className="font-bold text-[var(--color-brand-700)]">#{myRank}</span> of{" "}
              <span className="font-semibold text-[var(--color-ink-primary)]">{totalStaff}</span>{" "}
              salespeople {periodLabel.toLowerCase()}.
            </p>
          ) : (
            <p className="mt-1 text-sm text-[var(--color-ink-muted)]">
              No ranking data available.
            </p>
          )}

          <div className="mt-4 space-y-2.5">
            {perfData.staff.map((s, idx) => {
              const isMe = s.user_id === userId;
              const pct =
                perfData.total_store_sales > 0
                  ? (s.total_sales / perfData.total_store_sales) * 100
                  : 0;
              return (
                <div key={s.user_id} className="flex items-center gap-3">
                  <span className="tabular w-7 shrink-0 text-right text-xs font-semibold text-[var(--color-ink-muted)]">
                    #{s.rank}
                  </span>
                  <div className="flex-1">
                    <div className="flex items-center justify-between text-xs">
                      <span
                        className={
                          isMe
                            ? "font-semibold text-[var(--color-brand-700)]"
                            : "text-[var(--color-ink-secondary)]"
                        }
                      >
                        {isMe ? "You" : `Salesperson ${idx + 1}`}
                      </span>
                      <span className="tabular font-semibold text-[var(--color-ink-primary)]">
                        {formatMoneyCompact(s.total_sales)}
                      </span>
                    </div>
                    <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-[var(--color-surface-subtle)]">
                      <div
                        className={classNames(
                          "h-full rounded-full transition-all duration-500",
                          isMe ? "bg-[var(--color-brand-600)]" : "bg-[var(--color-border-strong)]",
                        )}
                        style={{ width: `${Math.max(pct, 2)}%` }}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* AI Insights */}
      <Card padding="lg">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--color-brand-500)] to-[var(--color-brand-700)] text-white">
            <Sparkles size={14} />
          </div>
          <h2 className="text-base font-semibold text-[var(--color-ink-primary)]">AI Insights</h2>
        </div>

        {insightsLoading ? (
          <div className="mt-4 space-y-2">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
            <Skeleton className="h-3 w-4/6" />
            <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
              Generating personalised insights…
            </p>
          </div>
        ) : insights?.ai_insights ? (
          <div className="mt-3 rounded-xl bg-gradient-to-br from-[var(--color-brand-50)] to-[var(--color-surface)] p-4 ring-1 ring-[var(--color-brand-500)]/15">
            <p className="whitespace-pre-line text-sm leading-relaxed text-[var(--color-ink-secondary)]">
              {insights.ai_insights}
            </p>
          </div>
        ) : (
          <p className="mt-3 text-sm text-[var(--color-ink-muted)]">
            No AI insights available yet. Check back after more sales data is recorded.
          </p>
        )}
      </Card>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  change,
  subtitle,
  highlight,
}: {
  label: string;
  value: string;
  change?: number | null;
  subtitle?: string;
  highlight?: boolean;
}) {
  const positive = change != null && change >= 0;
  return (
    <Card
      padding="lg"
      className={classNames(
        highlight &&
          "bg-gradient-to-br from-[var(--color-brand-50)] to-[var(--color-surface)] border-[var(--color-brand-500)]/20",
      )}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
        {label}
      </p>
      <p className="tabular mt-1 text-2xl font-bold tracking-tight text-[var(--color-ink-primary)]">
        {value}
      </p>
      {change !== undefined && change !== null && (
        <p
          className={classNames(
            "mt-1.5 inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-xs font-semibold",
            positive
              ? "bg-[var(--color-positive-50)] text-[var(--color-positive-700)]"
              : "bg-[var(--color-negative-50)] text-[var(--color-negative-700)]",
          )}
        >
          {positive ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
          {Math.abs(change)}%
          <span className="font-normal opacity-80">vs prev</span>
        </p>
      )}
      {subtitle && <p className="mt-1.5 text-xs text-[var(--color-ink-muted)]">{subtitle}</p>}
    </Card>
  );
}
