import { useEffect, useState, type ReactNode } from "react";
import { ChevronDown, Receipt } from "lucide-react";
import { api } from "../lib/api";
import { classNames, formatMoney } from "../lib/format";
import { PageHeader } from "../components/ui/PageHeader";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";

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

type EnrichedSlip = PaySlip & {
  period_start: string;
  period_end: string;
  run_status: string;
};

function periodLabel(start: string, end: string) {
  const s = new Date(start + "T00:00:00");
  const e = new Date(end + "T00:00:00");
  return `${s.toLocaleDateString("en-SG", { month: "long", year: "numeric" })} (${s.getDate()}–${e.getDate()})`;
}

export default function PayPage() {
  const [payslips, setPayslips] = useState<EnrichedSlip[]>([]);
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
        if (!storeId) {
          setError("No store assigned");
          setLoading(false);
          return;
        }

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
                .map((s) => ({
                  ...s,
                  period_start: r.period_start,
                  period_end: r.period_end,
                  run_status: r.status,
                })),
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

  return (
    <div className="space-y-6">
      <PageHeader title="Payslips" description="Your pay history with full breakdowns." />

      {error && (
        <div className="rounded-xl border border-[var(--color-negative-600)]/15 bg-[var(--color-negative-50)] p-3 text-sm text-[var(--color-negative-700)]">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : payslips.length === 0 ? (
        <EmptyState
          icon={<Receipt size={20} />}
          title="No payslips yet"
          description="Once your employer runs payroll, your pay history will appear here."
        />
      ) : (
        <div className="space-y-3">
          {payslips.map((s) => {
            const expanded = expandedId === s.id;
            return (
              <Card key={s.id} padding="none" className="overflow-hidden">
                <button
                  onClick={() => setExpandedId(expanded ? null : s.id)}
                  aria-expanded={expanded}
                  className="flex w-full items-center justify-between gap-3 px-4 py-4 text-left transition-colors hover:bg-[var(--color-surface-muted)] focus-visible:bg-[var(--color-surface-muted)]"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-[var(--color-ink-primary)]">
                      {periodLabel(s.period_start, s.period_end)}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-[var(--color-ink-muted)]">
                      Gross {formatMoney(s.gross_pay)} · CPF {formatMoney(s.cpf_employee)} · Comm{" "}
                      {formatMoney(s.commission_amount)}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <p className="tabular text-lg font-bold text-[var(--color-positive-700)]">
                        {formatMoney(s.net_pay)}
                      </p>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
                        Net pay
                      </p>
                    </div>
                    <ChevronDown
                      size={18}
                      className={classNames(
                        "shrink-0 text-[var(--color-ink-muted)] transition-transform duration-200",
                        expanded && "rotate-180",
                      )}
                    />
                  </div>
                </button>

                {expanded && (
                  <div className="animate-fade-in space-y-4 border-t border-[var(--color-border)] bg-[var(--color-surface-muted)] px-4 py-4">
                    <Section title="Base Pay">
                      <Row
                        label={`Hours worked${s.hours_worked != null ? ` (${s.hours_worked.toFixed(1)}h)` : ""}`}
                        detail={
                          profile?.hourly_rate
                            ? `× ${formatMoney(profile.hourly_rate)}/hr`
                            : "Salaried"
                        }
                        amount={s.basic_salary}
                      />
                    </Section>
                    {(s.overtime_hours > 0 || s.overtime_pay > 0) && (
                      <Section title="Overtime">
                        <Row
                          label={`OT hours (${s.overtime_hours.toFixed(1)}h)`}
                          detail={
                            profile?.hourly_rate
                              ? `× ${formatMoney(profile.hourly_rate * 1.5)}/hr`
                              : ""
                          }
                          amount={s.overtime_pay}
                        />
                      </Section>
                    )}
                    {s.commission_amount > 0 && (
                      <Section title="Commission">
                        <Row
                          label={`Sales: ${formatMoney(s.commission_sales)}`}
                          detail={
                            profile?.commission_rate ? `${profile.commission_rate}%` : "Tiered"
                          }
                          amount={s.commission_amount}
                        />
                      </Section>
                    )}
                    <Section title="CPF Contributions">
                      <Row label="Employee (deducted)" amount={-s.cpf_employee} negative />
                      <Row
                        label="Employer (additional)"
                        detail="Not deducted from pay"
                        amount={s.cpf_employer}
                        muted
                      />
                    </Section>
                    {(s.allowances > 0 || s.deductions > 0) && (
                      <Section title="Other">
                        {s.allowances > 0 && <Row label="Allowances" amount={s.allowances} />}
                        {s.deductions > 0 && (
                          <Row label="Deductions" amount={-s.deductions} negative />
                        )}
                      </Section>
                    )}
                    <div className="flex items-center justify-between border-t border-[var(--color-border)] pt-3">
                      <span className="text-sm font-semibold text-[var(--color-ink-primary)]">
                        Net Pay
                      </span>
                      <span className="tabular text-xl font-bold text-[var(--color-positive-700)]">
                        {formatMoney(s.net_pay)}
                      </span>
                    </div>
                    {s.notes && (
                      <p className="text-xs italic text-[var(--color-ink-muted)]">{s.notes}</p>
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
        {title}
      </p>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Row({
  label,
  detail,
  amount,
  negative,
  muted,
}: {
  label: string;
  detail?: string;
  amount: number;
  negative?: boolean;
  muted?: boolean;
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <div>
        <span className="text-[var(--color-ink-secondary)]">{label}</span>
        {detail && <span className="ml-2 text-xs text-[var(--color-ink-muted)]">{detail}</span>}
      </div>
      <span
        className={classNames(
          "tabular font-semibold",
          negative
            ? "text-[var(--color-negative-600)]"
            : muted
              ? "text-[var(--color-ink-muted)]"
              : "text-[var(--color-ink-primary)]",
        )}
      >
        {negative ? `−${formatMoney(Math.abs(amount))}` : formatMoney(amount)}
      </span>
    </div>
  );
}
