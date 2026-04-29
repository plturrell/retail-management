import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { Gem } from "lucide-react";
import { api } from "../lib/api";
import { formatMoney, formatMoneyCompact } from "../lib/format";
import { PageHeader } from "../components/ui/PageHeader";
import { Card } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";

interface UserMe {
  id: string;
  store_roles: { store_id: string; role: string }[];
}

interface PaySlip {
  user_id: string;
  commission_sales: number;
  commission_amount: number;
}

interface PayrollRun {
  id: string;
  period_start: string;
  period_end: string;
  status: string;
  payslips: PaySlip[];
}

interface CommissionTier {
  min: number;
  max: number | null;
  rate: number;
}

interface CommissionRule {
  id: string;
  name: string;
  tiers: CommissionTier[];
  is_active: boolean;
}

interface EmployeeProfile {
  commission_rate: number | null;
}

interface MonthData {
  month: string;
  sales: number;
  commission: number;
}

export default function CommissionPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentSales, setCurrentSales] = useState(0);
  const [currentCommission, setCurrentCommission] = useState(0);
  const [history, setHistory] = useState<MonthData[]>([]);
  const [rules, setRules] = useState<CommissionRule[]>([]);
  const [flatRate, setFlatRate] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const me = await api.get<{ data: UserMe }>("/users/me");
        const userId = me.data.id;
        const storeId = me.data.store_roles?.[0]?.store_id;
        if (!storeId) {
          setError("No store assigned");
          setLoading(false);
          return;
        }

        const [runsRes, rulesRes, profileRes] = await Promise.allSettled([
          api.get<{ data: PayrollRun[] }>(`/stores/${storeId}/payroll`),
          api.get<{ data: CommissionRule[] }>(`/stores/${storeId}/commission-rules`),
          api.get<{ data: EmployeeProfile }>(`/employees/${userId}/profile`),
        ]);

        if (profileRes.status === "fulfilled" && profileRes.value.data.commission_rate) {
          setFlatRate(profileRes.value.data.commission_rate);
        }

        if (rulesRes.status === "fulfilled") {
          setRules(rulesRes.value.data);
        }

        if (runsRes.status === "fulfilled") {
          const runs = runsRes.value.data
            .filter((r) => r.status === "approved" || r.status === "calculated")
            .sort((a, b) => b.period_end.localeCompare(a.period_end));

          const monthMap = new Map<string, MonthData>();
          for (const run of runs) {
            const d = new Date(run.period_end + "T00:00:00");
            const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
            const label = d.toLocaleDateString("en-SG", { month: "short", year: "2-digit" });
            const mySlips = (run.payslips || []).filter((s) => s.user_id === userId);
            const sales = mySlips.reduce((t, s) => t + s.commission_sales, 0);
            const comm = mySlips.reduce((t, s) => t + s.commission_amount, 0);
            const existing = monthMap.get(key) || { month: label, sales: 0, commission: 0 };
            monthMap.set(key, {
              month: label,
              sales: existing.sales + sales,
              commission: existing.commission + comm,
            });
          }
          const sorted = [...monthMap.entries()]
            .sort(([a], [b]) => a.localeCompare(b))
            .slice(-6)
            .map(([, v]) => v);
          setHistory(sorted);

          if (runs.length > 0) {
            const latest = runs[0];
            const mySlips = (latest.payslips || []).filter((s) => s.user_id === userId);
            setCurrentSales(mySlips.reduce((t, s) => t + s.commission_sales, 0));
            setCurrentCommission(mySlips.reduce((t, s) => t + s.commission_amount, 0));
          }
        }
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load commission data");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader title="Commission" description="Sales-driven earnings and rules." />

      {error && (
        <div className="rounded-xl border border-[var(--color-negative-600)]/15 bg-[var(--color-negative-50)] p-3 text-sm text-[var(--color-negative-700)]">
          {error}
        </div>
      )}

      {/* Summary cards */}
      {loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Card padding="lg">
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
              Total Sales
            </p>
            <p className="tabular mt-1 text-3xl font-bold tracking-tight text-[var(--color-ink-primary)]">
              {formatMoney(currentSales)}
            </p>
            <p className="mt-1 text-xs text-[var(--color-ink-muted)]">Most recent payroll period</p>
          </Card>
          <Card
            padding="lg"
            className="bg-gradient-to-br from-[var(--color-positive-50)] to-[var(--color-surface)] border-[var(--color-positive-600)]/20"
          >
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-positive-700)]/80">
              Commission Earned
            </p>
            <p className="tabular mt-1 text-3xl font-bold tracking-tight text-[var(--color-positive-700)]">
              {formatMoney(currentCommission)}
            </p>
            <p className="mt-1 text-xs text-[var(--color-ink-muted)]">Most recent payroll period</p>
          </Card>
        </div>
      )}

      {/* History chart */}
      {!loading && history.length > 0 && (
        <Card padding="lg">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-[var(--color-ink-primary)]">
                Commission history
              </h2>
              <p className="text-xs text-[var(--color-ink-muted)]">Last 6 months</p>
            </div>
          </div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={history} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
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
                  formatter={(v: number) => [formatMoney(v), "Commission"]}
                  contentStyle={{
                    fontSize: 13,
                    borderRadius: 12,
                    border: "1px solid #e2e8f0",
                    boxShadow: "0 10px 30px -8px rgba(15,23,42,0.18)",
                  }}
                  cursor={{ fill: "rgba(59,130,246,0.06)" }}
                />
                <Bar
                  dataKey="commission"
                  fill="var(--color-positive-600)"
                  radius={[6, 6, 0, 0]}
                  name="Commission"
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* Rules */}
      <Card padding="lg">
        <h2 className="text-base font-semibold text-[var(--color-ink-primary)]">
          Commission rules
        </h2>
        <p className="mt-0.5 text-xs text-[var(--color-ink-muted)]">
          How your commission is calculated
        </p>

        {rules.length > 0 ? (
          <div className="mt-4 space-y-5">
            {rules.map((rule) => (
              <div key={rule.id}>
                <p className="text-sm font-semibold text-[var(--color-ink-primary)]">{rule.name}</p>
                <div className="mt-2 overflow-hidden rounded-xl border border-[var(--color-border)]">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[var(--color-border)] bg-[var(--color-surface-muted)] text-xs uppercase tracking-wide text-[var(--color-ink-muted)]">
                        <th className="px-3 py-2 text-left font-semibold">Sales range</th>
                        <th className="px-3 py-2 text-right font-semibold">Rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rule.tiers.map((tier, i) => (
                        <tr
                          key={i}
                          className="border-b border-[var(--color-border)] last:border-0"
                        >
                          <td className="tabular px-3 py-2 text-[var(--color-ink-secondary)]">
                            {formatMoneyCompact(tier.min)} –{" "}
                            {tier.max != null ? formatMoneyCompact(tier.max) : "∞"}
                          </td>
                          <td className="tabular px-3 py-2 text-right font-semibold text-[var(--color-ink-primary)]">
                            {(tier.rate * 100).toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        ) : flatRate != null ? (
          <div className="mt-4 rounded-xl bg-[var(--color-brand-50)] p-4">
            <p className="text-sm text-[var(--color-ink-secondary)]">
              Flat commission rate of{" "}
              <span className="font-bold text-[var(--color-brand-700)]">{flatRate}%</span> on all
              attributed sales.
            </p>
          </div>
        ) : loading ? (
          <Skeleton className="mt-4 h-12 w-full" />
        ) : (
          <div className="mt-4">
            <EmptyState
              icon={<Gem size={20} />}
              title="No rules set"
              description="No commission rules are configured for your store yet."
            />
          </div>
        )}
      </Card>
    </div>
  );
}
