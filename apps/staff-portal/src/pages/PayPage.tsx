import { useEffect, useState } from "react";
import { api } from "../lib/api";

interface PaySlip {
  id: string;
  payroll_run_id: string;
  user_id: string;
  basic_salary: number;
  hours_worked: number | null;
  overtime_hours: number;
  overtime_pay: number;
  allowances: number;
  deductions: number;
  commission_sales: number;
  commission_amount: number;
  gross_pay: number;
  cpf_employee: number;
  cpf_employer: number;
  net_pay: number;
  notes: string | null;
  created_at: string;
}

interface PayrollRun {
  id: string;
  store_id: string;
  period_start: string;
  period_end: string;
  status: string;
  total_gross: number;
  total_net: number;
  payslips: PaySlip[];
}

interface UserMe {
  id: string;
  full_name: string;
  email: string;
  store_roles: { store_id: string; role: string }[];
}

interface EmployeeProfile {
  hourly_rate: number | null;
  commission_rate: number | null;
}

function fmt(n: number) {
  return `$${n.toFixed(2)}`;
}

function periodLabel(start: string, end: string) {
  const s = new Date(start + "T00:00:00");
  const e = new Date(end + "T00:00:00");
  return `${s.toLocaleDateString("en-SG", { month: "short", year: "numeric" })} (${s.getDate()}–${e.getDate()})`;
}

export default function PayPage() {
  const [payslips, setPayslips] = useState<(PaySlip & { period_start: string; period_end: string; run_status: string })[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [profile, setProfile] = useState<EmployeeProfile | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const me = await api.get<{ data: UserMe }>("/users/me");
        const userId = me.data.id;
        const storeId = me.data.store_roles?.[0]?.store_id;
        if (!storeId) { setError("No store assigned"); setLoading(false); return; }

        const [runsRes, profileRes] = await Promise.allSettled([
          api.get<{ data: PayrollRun[] }>(`/stores/${storeId}/payroll`),
          api.get<{ data: EmployeeProfile }>(`/employees/${userId}/profile`),
        ]);

        if (profileRes.status === "fulfilled") setProfile(profileRes.value.data);

        if (runsRes.status === "fulfilled") {
          const runs = runsRes.value.data;
          const mine = runs
            .filter((r) => r.status === "approved" || r.status === "calculated")
            .flatMap((r) =>
              (r.payslips || [])
                .filter((s) => s.user_id === userId)
                .map((s) => ({ ...s, period_start: r.period_start, period_end: r.period_end, run_status: r.status }))
            )
            .sort((a, b) => b.period_end.localeCompare(a.period_end));
          setPayslips(mine);
        }
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load payslips");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="flex items-center justify-center py-20 text-gray-400">Loading payslips…</div>;
  if (error) return <div className="rounded-lg bg-red-50 p-4 text-sm text-red-600">{error}</div>;

  return (
    <div>
      <h1 className="text-xl font-bold text-gray-800">Payslips</h1>
      <p className="mt-1 text-sm text-gray-500">View your pay history and breakdowns.</p>

      {payslips.length === 0 ? (
        <div className="mt-6 rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center text-gray-400">
          No payslips found yet.
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          {payslips.map((s) => {
            const expanded = expandedId === s.id;
            return (
              <div key={s.id} className="rounded-lg border border-gray-200 bg-white overflow-hidden">
                {/* Summary row */}
                <button
                  onClick={() => setExpandedId(expanded ? null : s.id)}
                  className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                >
                  <div>
                    <p className="text-sm font-semibold text-gray-800">{periodLabel(s.period_start, s.period_end)}</p>
                    <p className="mt-0.5 text-xs text-gray-400">
                      Gross {fmt(s.gross_pay)} · CPF {fmt(s.cpf_employee)} · Comm {fmt(s.commission_amount)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-bold text-green-700">{fmt(s.net_pay)}</p>
                    <p className="text-[10px] uppercase text-gray-400">Net Pay</p>
                  </div>
                </button>

                {/* Detail breakdown */}
                {expanded && (
                  <div className="border-t border-gray-100 bg-gray-50 px-4 py-4 space-y-3">
                    <Section title="Base Pay">
                      <Row label={`Hours worked${s.hours_worked != null ? ` (${s.hours_worked.toFixed(1)}h)` : ""}`}
                           detail={profile?.hourly_rate ? `× $${profile.hourly_rate.toFixed(2)}/hr` : "Salaried"}
                           amount={s.basic_salary} />
                    </Section>
                    {(s.overtime_hours > 0 || s.overtime_pay > 0) && (
                      <Section title="Overtime">
                        <Row label={`OT hours (${s.overtime_hours.toFixed(1)}h)`}
                             detail={profile?.hourly_rate ? `× $${(profile.hourly_rate * 1.5).toFixed(2)}/hr` : ""}
                             amount={s.overtime_pay} />
                      </Section>
                    )}
                    {s.commission_amount > 0 && (
                      <Section title="Commission">
                        <Row label={`Sales total: ${fmt(s.commission_sales)}`}
                             detail={profile?.commission_rate ? `${profile.commission_rate}%` : "Tiered"}
                             amount={s.commission_amount} />
                      </Section>
                    )}
                    <Section title="CPF Contributions">
                      <Row label="Employee (deducted)" amount={-s.cpf_employee} negative />
                      <Row label="Employer (additional)" detail="Not deducted from pay" amount={s.cpf_employer} muted />
                    </Section>
                    {(s.allowances > 0 || s.deductions > 0) && (
                      <Section title="Other">
                        {s.allowances > 0 && <Row label="Allowances" amount={s.allowances} />}
                        {s.deductions > 0 && <Row label="Deductions" amount={-s.deductions} negative />}
                      </Section>
                    )}
                    <div className="border-t border-gray-200 pt-3 flex justify-between items-center">
                      <span className="text-sm font-semibold text-gray-700">Net Pay</span>
                      <span className="text-lg font-bold text-green-700">{fmt(s.net_pay)}</span>
                    </div>
                    {s.notes && <p className="text-xs text-gray-400 italic">{s.notes}</p>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">{title}</p>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Row({ label, detail, amount, negative, muted }: {
  label: string; detail?: string; amount: number; negative?: boolean; muted?: boolean;
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <div>
        <span className="text-gray-700">{label}</span>
        {detail && <span className="ml-2 text-xs text-gray-400">{detail}</span>}
      </div>
      <span className={negative ? "text-red-600 font-medium" : muted ? "text-gray-400" : "text-gray-800 font-medium"}>
        {negative ? `−${fmt(Math.abs(amount))}` : fmt(amount)}
      </span>
    </div>
  );
}
