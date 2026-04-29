import { NavLink, Outlet } from "react-router-dom";
import { useState } from "react";
import { Icon, type IconName } from "./Icon";
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
        `flex flex-col items-center gap-0.5 px-2 py-1.5 text-xs transition-colors md:flex-row md:gap-3 md:rounded-lg md:px-4 md:py-2.5 md:text-sm ${
          isActive
            ? "text-blue-600 md:bg-blue-50 md:font-semibold"
            : "text-gray-500 hover:text-gray-700 md:hover:bg-gray-50"
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
    canViewSensitiveOperations,
    roleLabel,
  } = useAuth();
  const managerNavItems: NavItemConfig[] = [
    { to: "/manager", label: "Manager Ops", icon: "inventory" },
    { to: "/admin/users", label: "Users", icon: "users" },
  ];
  const ownerNavItems: NavItemConfig[] = [
    { to: "/master-data", label: "Master Data", icon: "package" },
    { to: "/vault", label: "Staging Vault", icon: "archive" },
    { to: "/supplier-review", label: "Invoice Review", icon: "document" },
    { to: "/data-quality", label: "Data Quality", icon: "database" },
    { to: "/admin/audit", label: "Audit Log", icon: "shield" },
  ];
  const navItems: NavItemConfig[] = isManager
    ? [
        ...baseNavItems,
        ...managerNavItems,
        ...(canViewSensitiveOperations ? ownerNavItems : []),
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
    <div className="flex h-screen flex-col md:flex-row">
      {/* Sidebar — desktop only */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-gray-200 bg-white md:flex">
        <div className="border-b border-gray-200 px-5 py-4">
          <h1 className="text-lg font-bold text-blue-700">VictoriaEnso</h1>
          <p className="text-xs text-gray-400">
            {canViewSensitiveOperations
              ? "Owner Console"
              : isManager
                ? "Sales Manager Console"
                : "Sales Promoter Portal"}
          </p>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          {navItems.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>
      </aside>

      {/* Main area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <header className="flex flex-col gap-3 border-b border-gray-200 bg-white px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-700 md:hidden">VictoriaEnso</h2>
            <p className="text-xs text-gray-500">
              {selectedStore?.name ?? "Choose a store"}
              {selectedStoreRole ? ` • ${roleLabel}` : ""}
            </p>
            {selectedStore && storeDescriptor(selectedStore) && (
              <p className="text-[11px] text-gray-400">{storeDescriptor(selectedStore)}</p>
            )}
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="flex min-w-[220px] flex-col gap-1">
              <label htmlFor="store-select" className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                Active Store
              </label>
              <select
                id="store-select"
                value={selectedStore?.id ?? ""}
                onChange={(event) => setSelectedStoreId(event.target.value)}
                className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700"
              >
                {stores.map((store) => (
                  <option key={store.id} value={store.id}>
                    {storeDescriptor(store) ? `${store.name} — ${storeDescriptor(store)}` : store.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-right">
                <div className="text-sm font-medium text-gray-700">{profile?.full_name ?? user?.email}</div>
                <div className="text-xs text-gray-500">{user?.email}</div>
              </div>
              {selectedStoreRole && (
                <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold uppercase tracking-wide text-blue-700">
                  {roleLabel}
                </span>
              )}
              <button
                onClick={logout}
                className="inline-flex items-center gap-1.5 rounded-md bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-200"
              >
                <Icon name="log-out" className="h-3.5 w-3.5" />
                Logout
              </button>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto bg-gray-50 p-4 pb-20 md:p-6 md:pb-6">
          <Outlet />
        </main>
      </div>

      {/* Bottom nav — mobile only */}
      <nav className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-gray-200 bg-white py-1 safe-bottom md:hidden">
        {mobilePrimaryItems.map((item) => (
          <NavItem key={item.to} {...item} onClick={() => setMobileMenuOpen(false)} />
        ))}
        <button
          type="button"
          onClick={() => setMobileMenuOpen(true)}
          className="flex flex-col items-center gap-0.5 px-2 py-1.5 text-xs text-gray-500"
          aria-label="Open navigation menu"
        >
          <Icon name="menu" className="h-5 w-5" />
          <span>More</span>
        </button>
      </nav>
      <div
        className={`fixed inset-0 z-50 bg-black/30 md:hidden ${mobileMenuOpen ? "" : "hidden"}`}
        aria-hidden={!mobileMenuOpen}
        onClick={() => setMobileMenuOpen(false)}
      >
        <div
          className="absolute inset-x-0 bottom-0 max-h-[78vh] overflow-y-auto rounded-t-2xl bg-white p-4 pb-8 shadow-2xl"
          onClick={(event) => event.stopPropagation()}
        >
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900">Navigation</h2>
            <button
              type="button"
              onClick={() => setMobileMenuOpen(false)}
              className="rounded-md p-2 text-gray-500 hover:bg-gray-100"
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
                  `flex items-center gap-3 rounded-xl border px-3 py-3 text-sm ${
                    isActive
                      ? "border-blue-200 bg-blue-50 font-semibold text-blue-700"
                      : "border-gray-200 text-gray-700"
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
