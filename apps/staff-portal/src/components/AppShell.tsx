import { NavLink, Outlet } from "react-router-dom";
import { useState } from "react";
import { Icon, type IconName } from "./Icon";
import { Bell } from "./ui/Bell";
import { useAuth, type StoreSummary } from "../contexts/AuthContext";

interface NavItemConfig {
  to: string;
  label: string;
  icon: IconName;
}

const baseNavItems: NavItemConfig[] = [
  { to: "/home", label: "Today", icon: "home" },
  { to: "/schedule", label: "Schedule", icon: "calendar" },
  { to: "/timesheet", label: "Timesheet", icon: "clock" },
  { to: "/pay", label: "Pay", icon: "wallet" },
  { to: "/commission", label: "Commission", icon: "receipt" },
  { to: "/performance", label: "Performance", icon: "bar-chart" },
  { to: "/profile", label: "Profile", icon: "user" },
];

function NavItem({ to, label, icon, onClick }: NavItemConfig & { onClick?: () => void }) {
  return (
    <NavLink
      to={to}
      onClick={onClick}
      className={({ isActive }) =>
        `group flex min-h-12 flex-col items-center justify-center gap-0.5 px-2 py-1.5 text-[11px] font-medium transition-all md:min-h-0 md:flex-row md:justify-start md:gap-3 md:rounded-2xl md:px-4 md:py-3 md:text-[14px] ${
          isActive
            ? "text-blue-600 md:bg-blue-50 md:font-semibold md:shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]"
            : "text-slate-500 hover:text-slate-900 md:hover:bg-white/70"
        }`
      }
    >
      <Icon name={icon} className="h-5 w-5 md:h-4 md:w-4" />
      <span>{label}</span>
    </NavLink>
  );
}

function formatStoreType(storeType: StoreSummary["store_type"]): string | null {
  switch (storeType) {
    case "pop_up":
      return "pop-up";
    case "flagship":
    case "outlet":
    case "warehouse":
    case "online":
    case "hybrid":
      return storeType;
    case "retail":
    case undefined:
      return null;
    default:
      return String(storeType);
  }
}

function storeDescriptor(
  store: Pick<
    StoreSummary,
    "store_type" | "operational_status" | "is_home_base" | "is_temp_warehouse" | "planned_open_date"
  >,
) {
  const tags: string[] = [];
  const storeTypeLabel = formatStoreType(store.store_type);
  if (storeTypeLabel) tags.push(storeTypeLabel);
  if (store.is_home_base) tags.push("home base");
  if (store.is_temp_warehouse) tags.push("temp warehouse");
  if (store.operational_status && store.operational_status !== "active") tags.push(store.operational_status);
  if (store.planned_open_date) tags.push(`opens ${store.planned_open_date}`);
  return tags.join(" • ");
}

export default function AppShell() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const {
    user,
    logout,
    profile,
    stores,
    selectedStore,
    selectedStoreRole,
    setSelectedStoreId,
    isManager,
    isSystemAdmin,
    canViewSensitiveOperations,
    roleLabel,
  } = useAuth();
  const managerNavItems: NavItemConfig[] = [
    { to: "/manager", label: "Manager Ops", icon: "inventory" },
    { to: "/admin/users", label: "Users", icon: "users" },
  ];
  const ownerNavItems: NavItemConfig[] = [
    { to: "/master-data", label: "Master Data", icon: "package" },
    { to: "/publish", label: "Publish", icon: "spark" },
    { to: "/vault", label: "Staging Vault", icon: "archive" },
    { to: "/supplier-review", label: "Invoice Review", icon: "document" },
    { to: "/pos-readiness", label: "POS Readiness", icon: "check-circle" },
    { to: "/data-quality", label: "Data Quality", icon: "database" },
  ];
  // System-admin-only surfaces: SFTP host fingerprint + raw connection
  // settings, and the audit trail. These are deliberately not visible to
  // owners — see ``require_system_admin`` in the matching backend routes.
  const systemAdminNavItems: NavItemConfig[] = [
    { to: "/settings/cag-nec", label: "CAG / NEC POS", icon: "lock" },
    { to: "/admin/audit", label: "Audit Log", icon: "shield" },
  ];
  const navItems: NavItemConfig[] = isManager
    ? [
        ...baseNavItems,
        ...managerNavItems,
        ...(canViewSensitiveOperations ? ownerNavItems : []),
        ...(isSystemAdmin ? systemAdminNavItems : []),
      ]
    : baseNavItems;
  const mobilePrimaryItems: NavItemConfig[] = [
    navItems.find((item) => item.to === "/home"),
    navItems.find((item) => item.to === "/schedule"),
    navItems.find((item) => item.to === "/timesheet"),
    isManager ? navItems.find((item) => item.to === "/manager") : navItems.find((item) => item.to === "/pay"),
  ].filter(Boolean) as NavItemConfig[];
  const mobileMoreItems = navItems.filter(
    (item) => !mobilePrimaryItems.some((primaryItem) => primaryItem.to === item.to),
  );

  return (
    <div className="flex h-screen flex-col bg-[var(--ve-bg)] text-slate-950 md:flex-row">
      {/* Sidebar — desktop only */}
      <aside className="hidden w-[258px] shrink-0 flex-col border-r border-slate-200/70 bg-white/72 shadow-[inset_-1px_0_0_rgba(255,255,255,0.75)] backdrop-blur-2xl md:flex">
        <div className="px-6 py-6">
          <div className="flex items-center gap-3">
            <img src="/ve-logo.avif" alt="" className="h-9 w-16 rounded-lg bg-white object-contain shadow-sm" />
            <div>
              <h1 className="text-[20px] font-semibold leading-none tracking-tight text-slate-950">VictoriaEnso</h1>
              <p className="mt-1 text-[11px] font-medium text-slate-400">
                {canViewSensitiveOperations
                  ? "Owner Console"
                  : isManager
                    ? "Manager Console"
                    : "Staff Portal"}
              </p>
            </div>
          </div>
          <div className="mt-6 h-px bg-slate-200/80" />
        </div>
        <nav className="flex flex-1 flex-col gap-1.5 px-4 pb-4">
          {navItems.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>
        <div className="p-4">
          <button className="flex w-full items-center gap-3 rounded-2xl border border-slate-200 bg-white/70 px-3 py-3 text-sm font-medium text-slate-500 shadow-sm transition hover:bg-white">
            <Icon name="chevron-left" className="h-4 w-4" />
            Collapse
          </button>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Header */}
        <header className="z-20 border-b border-slate-200/80 bg-white/74 px-4 py-3 shadow-[0_1px_0_rgba(255,255,255,0.8)] backdrop-blur-2xl md:px-6">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-[15px] font-semibold text-slate-900 md:hidden">VictoriaEnso</h2>
              <p className="text-[12px] font-medium text-slate-500">
                {selectedStore?.name ?? "Choose a store"}
                {selectedStoreRole ? ` • ${roleLabel}` : ""}
              </p>
              {selectedStore && storeDescriptor(selectedStore) && (
                <p className="text-[11px] text-slate-400">{storeDescriptor(selectedStore)}</p>
              )}
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="flex min-w-[230px] flex-col gap-1">
                <label htmlFor="store-select" className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                  Active Store
                </label>
                <select
                  id="store-select"
                  value={selectedStore?.id ?? ""}
                  onChange={(event) => setSelectedStoreId(event.target.value)}
                  className="min-h-11 rounded-2xl border border-slate-200 bg-white/80 px-4 py-2 text-[14px] font-medium text-slate-800 shadow-sm"
                >
                  {stores.map((store) => (
                    <option key={store.id} value={store.id}>
                      {storeDescriptor(store) ? `${store.name} — ${storeDescriptor(store)}` : store.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-3">
                <Bell />
                <div className="rounded-2xl border border-slate-200 bg-white/72 px-3 py-2 text-right shadow-sm">
                  <div className="text-sm font-semibold text-slate-800">{profile?.full_name ?? user?.email}</div>
                  <div className="max-w-[190px] truncate text-xs text-slate-500">{user?.email}</div>
                </div>
                {selectedStoreRole && (
                  <span className="rounded-full bg-blue-50 px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.14em] text-blue-700">
                    {roleLabel}
                  </span>
                )}
                <button
                  onClick={logout}
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-200"
                >
                  <Icon name="log-out" className="h-3.5 w-3.5" />
                  Logout
                </button>
              </div>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto bg-[radial-gradient(circle_at_10%_0%,rgba(10,99,246,0.08),transparent_30rem),linear-gradient(135deg,#f8fafc_0%,#eef3f8_100%)] p-4 pb-24 md:p-6 md:pb-6">
          <Outlet />
        </main>
      </div>

      {/* Bottom nav — mobile only */}
      <nav className="safe-bottom fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-slate-200/80 bg-white/84 py-1 shadow-[0_-12px_32px_rgba(15,23,42,0.08)] backdrop-blur-2xl md:hidden">
        {mobilePrimaryItems.map((item) => (
          <NavItem key={item.to} {...item} onClick={() => setMobileMenuOpen(false)} />
        ))}
        <button
          type="button"
          onClick={() => setMobileMenuOpen(true)}
          className="flex min-h-12 flex-col items-center justify-center gap-0.5 px-2 py-1.5 text-[11px] font-medium text-slate-500"
          aria-label="Open navigation menu"
        >
          <Icon name="menu" className="h-5 w-5" />
          <span>More</span>
        </button>
      </nav>
      <div
        className={`fixed inset-0 z-50 bg-slate-950/35 backdrop-blur-sm md:hidden ${mobileMenuOpen ? "" : "hidden"}`}
        aria-hidden={!mobileMenuOpen}
        onClick={() => setMobileMenuOpen(false)}
      >
        <div
          className="absolute inset-x-0 bottom-0 max-h-[78vh] overflow-y-auto rounded-t-[28px] border border-white/60 bg-white/92 p-4 pb-8 shadow-2xl backdrop-blur-2xl"
          onClick={(event) => event.stopPropagation()}
        >
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">Navigation</h2>
            <button
              type="button"
              onClick={() => setMobileMenuOpen(false)}
              className="rounded-2xl p-2 text-slate-500 hover:bg-slate-100"
              aria-label="Close navigation menu"
            >
              <Icon name="x" className="h-5 w-5" />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {mobileMoreItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setMobileMenuOpen(false)}
                className={({ isActive }) =>
                  `flex min-h-14 items-center gap-3 rounded-2xl border px-3 py-3 text-sm ${
                    isActive
                      ? "border-blue-200 bg-blue-50 font-semibold text-blue-700"
                      : "border-slate-200 bg-white/70 text-slate-700"
                  }`
                }
              >
                <Icon name={item.icon} className="h-5 w-5" />
                <span>{item.label}</span>
              </NavLink>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
