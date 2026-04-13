import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

const navItems = [
  { to: "/schedule", label: "Schedule", icon: "📅" },
  { to: "/timesheet", label: "Timesheet", icon: "⏱️" },
  { to: "/pay", label: "Pay", icon: "💰" },
  { to: "/commission", label: "Commission", icon: "💎" },
  { to: "/performance", label: "Performance", icon: "📊" },
  { to: "/profile", label: "Profile", icon: "👤" },
];

function NavItem({ to, label, icon }: { to: string; label: string; icon: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex flex-col items-center gap-0.5 px-2 py-1.5 text-xs transition-colors md:flex-row md:gap-3 md:rounded-lg md:px-4 md:py-2.5 md:text-sm ${
          isActive
            ? "text-blue-600 md:bg-blue-50 md:font-semibold"
            : "text-gray-500 hover:text-gray-700 md:hover:bg-gray-50"
        }`
      }
    >
      <span className="text-lg md:text-base">{icon}</span>
      <span>{label}</span>
    </NavLink>
  );
}

export default function AppShell() {
  const { user, logout } = useAuth();

  return (
    <div className="flex h-screen flex-col md:flex-row">
      {/* Sidebar — desktop only */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-gray-200 bg-white md:flex">
        <div className="border-b border-gray-200 px-5 py-4">
          <h1 className="text-lg font-bold text-blue-700">RetailSG</h1>
          <p className="text-xs text-gray-400">Staff Portal</p>
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
        <header className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-700 md:hidden">RetailSG Staff</h2>
          <div className="hidden md:block" />
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-600">{user?.email}</span>
            <button
              onClick={logout}
              className="rounded-md bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-200"
            >
              Logout
            </button>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto bg-gray-50 p-4 pb-20 md:p-6 md:pb-6">
          <Outlet />
        </main>
      </div>

      {/* Bottom nav — mobile only */}
      <nav className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-gray-200 bg-white py-1 safe-bottom md:hidden">
        {navItems.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
      </nav>
    </div>
  );
}
