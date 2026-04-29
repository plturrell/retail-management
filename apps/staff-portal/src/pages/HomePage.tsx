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
      className="group rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition hover:border-blue-200 hover:shadow-md"
    >
      <div className={`inline-flex rounded-lg border p-2 ${toneClasses[tone]}`}>
        <Icon name={icon} className="h-5 w-5" />
      </div>
      <h2 className="mt-3 text-sm font-semibold text-gray-900">{title}</h2>
      <p className="mt-1 text-sm leading-6 text-gray-500">{body}</p>
    </Link>
  );
}

function StoreSummaryCard() {
  const { selectedStore, roleLabel, stores } = useAuth();
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Active Store</p>
          <h2 className="mt-1 text-lg font-semibold text-gray-900">{selectedStore?.name ?? "Choose a store"}</h2>
          <p className="mt-1 text-sm text-gray-500">{selectedStore?.location || "Select a store from the header to load role-specific tools."}</p>
        </div>
        <span className="shrink-0 rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-blue-700">
          {roleLabel}
        </span>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg bg-gray-50 p-3">
          <p className="text-xs text-gray-400">Assigned Stores</p>
          <p className="mt-1 text-lg font-semibold text-gray-900">{stores.length}</p>
        </div>
        <div className="rounded-lg bg-gray-50 p-3">
          <p className="text-xs text-gray-400">Store Type</p>
          <p className="mt-1 text-sm font-semibold capitalize text-gray-900">{selectedStore?.store_type ?? "Retail"}</p>
        </div>
        <div className="rounded-lg bg-gray-50 p-3">
          <p className="text-xs text-gray-400">Status</p>
          <p className="mt-1 text-sm font-semibold capitalize text-gray-900">{selectedStore?.operational_status ?? "Active"}</p>
        </div>
      </div>
    </section>
  );
}

export default function HomePage() {
  const { canViewSensitiveOperations, isManager, profile } = useAuth();

  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm text-gray-500">Welcome back{profile?.full_name ? `, ${profile.full_name.split(" ")[0]}` : ""}.</p>
        <h1 className="mt-1 text-2xl font-bold text-gray-900">Today</h1>
      </div>

      <StoreSummaryCard />

      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">Quick Actions</h2>
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
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">Manager Focus</h2>
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
        <section className="rounded-xl border border-blue-100 bg-blue-50 p-4">
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
