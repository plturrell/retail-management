import { useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "../lib/api";

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

function fmt(n: number) {
  return `$${n.toFixed(2)}`;
}

export default function CommissionPage() {
  const { profile: userProfile, selectedStore, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentSales, setCurrentSales] = useState(0);
  const [currentCommission, setCurrentCommission] = useState(0);
  const [history, setHistory] = useState<MonthData[]>([]);
  const [rules, setRules] = useState<CommissionRule[]>([]);
  const [flatRate, setFlatRate] = useState<number | null>(null);

  useEffect(() => {
    if (authLoading) return;

    if (!userProfile?.id || !selectedStore?.id) {
      setError("No assigned store selected");
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    (async () => {
      try {
        const [runsRes, rulesRes, profileRes] = await Promise.allSettled([
          api.get<{ data: PayrollRun[] }>(`/stores/${selectedStore.id}/payroll`),
          api.get<{ data: CommissionRule[] }>(`/stores/${selectedStore.id}/commission-rules`),
          api.get<{ data: EmployeeProfile }>(`/employees/${userProfile.id}/profile`),
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

          // Build monthly history (last 6 months)
          const monthMap = new Map<string, MonthData>();
          for (const run of runs) {
            const d = new Date(run.period_end + "T00:00:00");
            const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
            const label = d.toLocaleDateString("en-SG", { month: "short", year: "2-digit" });
            const mySlips = (run.payslips || []).filter((s) => s.user_id === userProfile.id);
            const sales = mySlips.reduce((t, s) => t + s.commission_sales, 0);
            const comm = mySlips.reduce((t, s) => t + s.commission_amount, 0);
            const existing = monthMap.get(key) || { month: label, sales: 0, commission: 0 };
            monthMap.set(key, { month: label, sales: existing.sales + sales, commission: existing.commission + comm });
          }
          const sorted = [...monthMap.entries()]
            .sort(([a], [b]) => a.localeCompare(b))
            .slice(-6)
            .map(([, v]) => v);
          setHistory(sorted);

          // Current period = most recent run
          if (runs.length > 0) {
            const latest = runs[0];
            const mySlips = (latest.payslips || []).filter((s) => s.user_id === userProfile.id);
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
  }, [authLoading, userProfile?.id, selectedStore?.id]);

  if (authLoading || loading) return <div className="flex items-center justify-center py-20 text-gray-400">Loading commission data…</div>;
  if (error) return <div className="rounded-lg bg-red-50 p-4 text-sm text-red-600">{error}</div>;

  return (
    <div>
      <h1 className="text-xl font-bold text-gray-800">Commission</h1>
      <p className="mt-1 text-sm text-gray-500">Your sales commission earnings and rules.</p>

      {/* Current period summary */}
      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium text-gray-400 uppercase">Total Sales</p>
          <p className="mt-1 text-2xl font-bold text-gray-800">{fmt(currentSales)}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium text-gray-400 uppercase">Commission Earned</p>
          <p className="mt-1 text-2xl font-bold text-green-700">{fmt(currentCommission)}</p>
        </div>
      </div>

      {/* Historical chart */}
      {history.length > 0 && (
        <div className="mt-6 rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Commission History (Last 6 Months)</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={history} margin={{ top: 5, right: 5, left: -10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => `$${v}`} />
              <Tooltip formatter={(v: number) => fmt(v)} />
              <Bar dataKey="commission" fill="#16a34a" radius={[4, 4, 0, 0]} name="Commission" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Commission rules */}
      <div className="mt-6 rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Commission Rules</h2>
        {rules.length > 0 ? (
          <div className="space-y-4">
            {rules.map((rule) => (
              <div key={rule.id}>
                <p className="text-sm font-medium text-gray-800">{rule.name}</p>
                <div className="mt-1 overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-gray-100 text-gray-400">
                        <th className="py-1 text-left font-medium">Sales Range</th>
                        <th className="py-1 text-right font-medium">Rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rule.tiers.map((tier, i) => (
                        <tr key={i} className="border-b border-gray-50">
                          <td className="py-1.5 text-gray-700">
                            ${tier.min.toLocaleString()} – {tier.max != null ? `$${tier.max.toLocaleString()}` : "∞"}
                          </td>
                          <td className="py-1.5 text-right text-gray-700 font-medium">
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
          <p className="text-sm text-gray-600">
            Flat commission rate: <span className="font-semibold text-gray-800">{flatRate}%</span> on all attributed sales.
          </p>
        ) : (
          <p className="text-sm text-gray-400">No commission rules configured for your store.</p>
        )}
      </div>
    </div>
  );
}
