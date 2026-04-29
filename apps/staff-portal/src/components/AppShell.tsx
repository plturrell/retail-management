import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  CalendarDays,
  Clock4,
  Wallet,
  Gem,
  TrendingUp,
  UserRound,
  LogOut,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { classNames } from "../lib/format";

interface NavEntry {
  to: string;
  label: string;
  icon: LucideIcon;
}

const navItems: NavEntry[] = [
  { to: "/schedule", label: "Schedule", icon: CalendarDays },
  { to: "/timesheet", label: "Timesheet", icon: Clock4 },
  { to: "/pay", label: "Pay", icon: Wallet },
  { to: "/commission", label: "Commission", icon: Gem },
  { to: "/performance", label: "Performance", icon: TrendingUp },
  { to: "/profile", label: "Profile", icon: UserRound },
];

const titleMap: Record<string, string> = {
  "/schedule": "Schedule",
  "/timesheet": "Timesheet",
  "/pay": "Pay",
  "/commission": "Commission",
  "/performance": "Performance",
  "/profile": "Profile",
};

function SidebarItem({ to, label, icon: Icon }: NavEntry) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        classNames(
          "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-150",
          isActive
            ? "bg-[var(--color-brand-50)] text-[var(--color-brand-700)]"
            : "text-[var(--color-ink-secondary)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink-primary)]",
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon
            size={18}
            strokeWidth={isActive ? 2.4 : 2}
            className={isActive ? "text-[var(--color-brand-600)]" : ""}
          />
          <span>{label}</span>
        </>
      )}
    </NavLink>
  );
}

function BottomNavItem({ to, label, icon: Icon }: NavEntry) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        classNames(
          "relative flex min-h-[56px] flex-1 flex-col items-center justify-center gap-1 px-1 transition-colors",
          isActive
            ? "text-[var(--color-brand-700)]"
            : "text-[var(--color-ink-muted)] active:text-[var(--color-ink-primary)]",
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute top-0 h-0.5 w-8 rounded-b-full bg-[var(--color-brand-600)]" />
          )}
          <Icon size={22} strokeWidth={isActive ? 2.4 : 2} />
          <span className="text-[10px] font-semibold tracking-wide">{label}</span>
        </>
      )}
    </NavLink>
  );
}

export default function AppShell() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const pageTitle = titleMap[location.pathname] ?? "RetailSG";

  return (
    <div className="flex h-screen flex-col bg-[var(--color-surface-muted)] md:flex-row">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)] md:flex">
        <div className="flex h-16 items-center gap-2.5 border-b border-[var(--color-border)] px-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-brand-600)] text-sm font-bold text-white shadow-sm">
            R
          </div>
          <div>
            <p className="text-sm font-bold tracking-tight text-[var(--color-ink-primary)]">
              RetailSG
            </p>
            <p className="text-[11px] text-[var(--color-ink-muted)]">Staff Portal</p>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-3">
          {navItems.map((item) => (
            <SidebarItem key={item.to} {...item} />
          ))}
        </nav>
        <div className="border-t border-[var(--color-border)] p-3">
          <button
            onClick={logout}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-[var(--color-ink-secondary)] transition-colors hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-negative-600)]"
          >
            <LogOut size={18} strokeWidth={2} />
            <span>Sign out</span>
          </button>
          {user?.email && (
            <p className="mt-2 truncate px-3 text-[11px] text-[var(--color-ink-muted)]">
              {user.email}
            </p>
          )}
        </div>
      </aside>

      {/* Main column */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-surface)]/85 px-4 backdrop-blur-md sm:h-16 md:px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--color-brand-600)] text-xs font-bold text-white md:hidden">
              R
            </div>
            <h2 className="text-base font-semibold tracking-tight text-[var(--color-ink-primary)]">
              {pageTitle}
            </h2>
          </div>

          <div className="relative">
            <button
              onClick={() => setMenuOpen((v) => !v)}
              aria-label="Account menu"
              className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--color-brand-50)] text-sm font-bold text-[var(--color-brand-700)] transition-colors hover:bg-[var(--color-brand-100)]"
            >
              {(user?.email?.[0] ?? "U").toUpperCase()}
            </button>
            {menuOpen && (
              <>
                <button
                  className="fixed inset-0 z-40 cursor-default"
                  aria-label="Close menu"
                  onClick={() => setMenuOpen(false)}
                />
                <div className="animate-rise absolute right-0 top-12 z-50 w-60 overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-floating)]">
                  <div className="border-b border-[var(--color-border)] px-4 py-3">
                    <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-ink-muted)]">
                      Signed in as
                    </p>
                    <p className="mt-0.5 truncate text-sm font-semibold text-[var(--color-ink-primary)]">
                      {user?.email}
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      setMenuOpen(false);
                      logout();
                    }}
                    className="flex w-full items-center gap-2.5 px-4 py-3 text-sm font-medium text-[var(--color-negative-600)] transition-colors hover:bg-[var(--color-negative-50)]"
                  >
                    <LogOut size={16} />
                    <span>Sign out</span>
                  </button>
                </div>
              </>
            )}
          </div>
        </header>

        {/* Page content */}
        <main
          key={location.pathname}
          className="animate-fade-in flex-1 overflow-y-auto p-4 pb-24 md:p-8 md:pb-8"
        >
          <div className="mx-auto w-full max-w-5xl">
            <Outlet />
          </div>
        </main>
      </div>

      {/* Mobile bottom navigation */}
      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 z-40 flex items-stretch justify-around border-t border-[var(--color-border)] bg-[var(--color-surface)]/95 px-1 backdrop-blur-md safe-bottom md:hidden"
      >
        {navItems.map((item) => (
          <BottomNavItem key={item.to} {...item} />
        ))}
      </nav>
    </div>
  );
}
