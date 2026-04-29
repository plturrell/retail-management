import { Link } from "react-router-dom";
import { Icon, type IconName } from "../components/Icon";
import { useAuth } from "../contexts/AuthContext";

interface ActionCardProps {
  to: string;
  icon: IconName;
  title: string;
  body: string;
  tone?: "blue" | "green" | "amber" | "slate" | "red";
}

const toneClasses: Record<NonNullable<ActionCardProps["tone"]>, string> = {
  amber: "bg-amber-50 text-amber-700 border-amber-100",
  blue: "bg-blue-50 text-blue-700 border-blue-100",
  green: "bg-emerald-50 text-emerald-700 border-emerald-100",
  red: "bg-red-50 text-red-700 border-red-100",
  slate: "bg-slate-50 text-slate-700 border-slate-100",
};

function ActionCard({ to, icon, title, body, tone = "slate" }: ActionCardProps) {
  return (
    <Link
      to={to}
      className="group rounded-[22px] border border-white/70 bg-white/78 p-4 shadow-[0_10px_28px_rgba(15,23,42,0.06)] backdrop-blur-xl transition hover:-translate-y-0.5 hover:border-blue-200 hover:bg-white hover:shadow-[0_16px_42px_rgba(15,23,42,0.1)]"
    >
      <div className={`inline-flex rounded-2xl border p-2.5 ${toneClasses[tone]}`}>
        <Icon name={icon} className="h-5 w-5" />
      </div>
      <h2 className="mt-4 text-[15px] font-semibold text-slate-950">{title}</h2>
      <p className="mt-1 text-sm leading-6 text-slate-500">{body}</p>
    </Link>
  );
}

function StoreSummaryCard() {
  const { selectedStore, roleLabel, stores } = useAuth();
  return (
    <section className="ve-panel p-5 md:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-400">Active Store</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">{selectedStore?.name ?? "Choose a store"}</h2>
          <p className="mt-1 text-sm text-slate-500">{selectedStore?.location || "Select a store from the header to load role-specific tools."}</p>
        </div>
        <span className="shrink-0 rounded-full bg-blue-50 px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.14em] text-blue-700">
          {roleLabel}
        </span>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 p-4">
          <p className="text-xs font-medium text-slate-400">Assigned Stores</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">{stores.length}</p>
        </div>
        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 p-4">
          <p className="text-xs font-medium text-slate-400">Store Type</p>
          <p className="mt-2 text-sm font-semibold capitalize text-slate-950">{selectedStore?.store_type ?? "Retail"}</p>
        </div>
        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 p-4">
          <p className="text-xs font-medium text-slate-400">Status</p>
          <p className="mt-2 text-sm font-semibold capitalize text-slate-950">{selectedStore?.operational_status ?? "Active"}</p>
        </div>
      </div>
    </section>
  );
}

export default function HomePage() {
  const { canViewSensitiveOperations, isManager, profile } = useAuth();

  return (
    <div className="mx-auto max-w-[1180px] space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="ve-title text-[34px] font-semibold leading-tight tracking-tight md:text-[40px]">
            Good morning{profile?.full_name ? `, ${profile.full_name.split(" ")[0]}` : ""}.
          </h1>
          <p className="mt-1 text-[15px] text-slate-500">Here’s what’s happening across your store.</p>
        </div>
        <div className="inline-flex items-center gap-2 self-start rounded-2xl border border-slate-200 bg-white/75 px-3 py-2 text-sm font-medium text-slate-600 shadow-sm backdrop-blur-xl md:self-auto">
          <Icon name="calendar" className="h-4 w-4" />
          {new Date().toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric", weekday: "short" })}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        {[
          ["Sales Today", "S$24,530", "12.6% vs yesterday", "green"],
          ["Transactions", "312", "8.4% vs yesterday", "green"],
          ["Average Sale", "S$78.62", "3.1% vs yesterday", "green"],
          ["Needs Price", "63", "Inventory readiness", "amber"],
        ].map(([label, value, detail, tone]) => (
          <div key={label} className="ve-panel p-4">
            <p className="text-xs font-semibold text-slate-500">{label}</p>
            <p className="mt-3 text-[28px] font-semibold tracking-tight text-slate-950">{value}</p>
            <p className={`mt-2 text-xs font-semibold ${tone === "green" ? "text-emerald-600" : "text-amber-600"}`}>
              {detail}
            </p>
            <div className="mt-4 h-8 rounded-[12px] bg-[linear-gradient(135deg,rgba(10,99,246,0.16),transparent_58%),linear-gradient(90deg,transparent,rgba(10,99,246,0.2),transparent)]" />
          </div>
        ))}
      </div>

      <StoreSummaryCard />

      <section>
        <h2 className="text-[12px] font-bold uppercase tracking-[0.16em] text-slate-400">Quick Actions</h2>
        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <ActionCard
            to="/schedule"
            icon="calendar"
            title="Next shifts"
            body="Check this week's rota and store assignments."
            tone="blue"
          />
          <ActionCard
            to="/timesheet"
            icon="clock"
            title="Clock in or out"
            body="Start your shift, end your shift, and review hours."
            tone="green"
          />
          <ActionCard
            to="/pay"
            icon="wallet"
            title="Pay and CPF"
            body="Review payslips, net pay, and deductions."
            tone="slate"
          />
          <ActionCard
            to="/performance"
            icon="bar-chart"
            title="Performance"
            body="See sales, orders, and productivity trends."
            tone="amber"
          />
        </div>
      </section>

      {isManager && (
        <section>
          <h2 className="text-[12px] font-bold uppercase tracking-[0.16em] text-slate-400">Manager Focus</h2>
          <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <ActionCard
              to="/manager"
              icon="inventory"
              title="Inventory actions"
              body="Triage low stock, anomalies, reorders, and adjustments."
              tone="blue"
            />
            <ActionCard
              to="/manager/schedule"
              icon="calendar-days"
              title="Team Schedule"
              body="Create weekly rotas, assign shifts, and manage coverage."
              tone="amber"
            />
            <ActionCard
              to="/manager/timesheets"
              icon="clock"
              title="Timesheet Approvals"
              body="Review staff hours, breaks, and prep for payroll."
              tone="green"
            />
            <ActionCard
              to="/orders"
              icon="receipt"
              title="Orders"
              body="Browse, filter, and inspect all sales orders."
              tone="blue"
            />
            <ActionCard
              to="/financials"
              icon="document-text"
              title="Financials"
              body="Revenue summary, daily chart, and payment breakdown."
              tone="slate"
            />
            <ActionCard
              to="/admin/users"
              icon="users"
              title="Users and access"
              body="Invite staff, reset passwords, and handle disabled accounts."
              tone="slate"
            />
            {canViewSensitiveOperations && (
              <>
                <ActionCard
                  to="/master-data"
                  icon="package"
                  title="Master data"
                  body="Price SKUs and regenerate backend-synced NEC exports."
                  tone="blue"
                />
                <ActionCard
                  to="/supplier-review"
                  icon="receipt"
                  title="Invoice review"
                  body="Review supplier documents and payment details."
                  tone="amber"
                />
                <ActionCard
                  to="/data-quality"
                  icon="database"
                  title="Catalogue cleanup"
                  body="Fix product data, missing prices, and stock readiness."
                  tone="red"
                />
              </>
            )}
          </div>
        </section>
      )}

      {canViewSensitiveOperations && (
        <section className="rounded-[22px] border border-blue-100 bg-blue-50/80 p-4 shadow-sm">
          <div className="flex items-start gap-3">
            <Icon name="shield" className="mt-0.5 h-5 w-5 text-blue-700" />
            <div>
              <h2 className="text-sm font-semibold text-blue-900">Owner controls are active</h2>
              <p className="mt-1 text-sm leading-6 text-blue-800">
                Cost, supplier, audit, vault, and data-quality tools are visible for this store. Switch stores from the header if you need a different permission context.
              </p>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
