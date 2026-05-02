import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import ManagerOnlyRoute from "./components/ManagerOnlyRoute";
import OwnerOnlyRoute from "./components/OwnerOnlyRoute";
import SystemAdminOnlyRoute from "./components/SystemAdminOnlyRoute";
import AppShell from "./components/AppShell";
import { ToastProvider } from "./components/ui/Toast";

// Each page becomes its own JS chunk via React.lazy(). Keeping the route
// guards, AppShell, AuthProvider and ToastProvider eager — they're required
// for the very first paint in every authed flow, so deferring them only adds
// a flicker without saving meaningful bytes.
//
// Why split everything (including LoginPage/HomePage):
// - Pre-split the initial bundle was ~452 KB gzipped (well over Vite's 500 KB
//   warning threshold uncompressed). Splitting trims the initial download to
//   the shell + first route only.
// - Even LoginPage drags in firebase + react-router; lazy-loading lets the
//   service worker prefetch sibling routes idle-time.
// - HomePage is small but pays no cost from being lazy: it's still the first
//   chunk loaded after the shell paints.
const LoginPage = lazy(() => import("./pages/LoginPage"));
const ForceChangePasswordPage = lazy(() => import("./pages/ForceChangePasswordPage"));
const HomePage = lazy(() => import("./pages/HomePage"));
const SchedulePage = lazy(() => import("./pages/SchedulePage"));
const TimesheetPage = lazy(() => import("./pages/TimesheetPage"));
const PayPage = lazy(() => import("./pages/PayPage"));
const CommissionPage = lazy(() => import("./pages/CommissionPage"));
const PerformancePage = lazy(() => import("./pages/PerformancePage"));
const ProfilePage = lazy(() => import("./pages/ProfilePage"));
const ManagerOpsPage = lazy(() => import("./pages/ManagerOpsPage"));
const ManagerSchedulePage = lazy(() => import("./pages/ManagerSchedulePage"));
const ManagerTimesheetsPage = lazy(() => import("./pages/ManagerTimesheetsPage"));
const OrdersPage = lazy(() => import("./pages/OrdersPage"));
const FinancialsPage = lazy(() => import("./pages/FinancialsPage"));
const SupplierReviewPage = lazy(() => import("./pages/SupplierReviewPage"));
const VaultPage = lazy(() => import("./pages/VaultPage"));
const DataQualityPage = lazy(() => import("./pages/DataQualityPage"));
const AdminUsersPage = lazy(() => import("./pages/AdminUsersPage"));
const AuditLogPage = lazy(() => import("./pages/AuditLogPage"));
const MasterDataPage = lazy(() => import("./pages/MasterDataPage"));
const CagSettingsPage = lazy(() => import("./pages/CagSettingsPage"));
const PosReadinessPage = lazy(() => import("./pages/PosReadinessPage"));
const PublishPage = lazy(() => import("./pages/PublishPage"));
const AddItemPage = lazy(() => import("./pages/AddItemPage"));

// Tiny route-level fallback. Intentionally minimal so it doesn't flash a heavy
// skeleton when the next chunk arrives in <100 ms on a warm connection.
function RouteFallback() {
  return (
    <div className="flex h-full items-center justify-center p-8 text-sm text-gray-500">
      Loading…
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <Suspense fallback={<RouteFallback />}>
            <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/force-change-password"
              element={
                <ProtectedRoute>
                  <ForceChangePasswordPage />
                </ProtectedRoute>
              }
            />
            <Route
              element={
                <ProtectedRoute>
                  <AppShell />
                </ProtectedRoute>
              }
            >
              <Route index element={<Navigate to="/home" replace />} />
              <Route path="home" element={<HomePage />} />
              <Route path="schedule" element={<SchedulePage />} />
              <Route path="timesheet" element={<TimesheetPage />} />
              <Route path="pay" element={<PayPage />} />
              <Route path="commission" element={<CommissionPage />} />
              <Route path="performance" element={<PerformancePage />} />
              <Route path="profile" element={<ProfilePage />} />
              <Route
                path="vault"
                element={
                  <OwnerOnlyRoute>
                    <VaultPage />
                  </OwnerOnlyRoute>
                }
              />
              <Route
                path="supplier-review"
                element={
                  <OwnerOnlyRoute>
                    <SupplierReviewPage />
                  </OwnerOnlyRoute>
                }
              />
              <Route
                path="manager"
                element={
                  <ManagerOnlyRoute>
                    <ManagerOpsPage />
                  </ManagerOnlyRoute>
                }
              />
              <Route
                path="manager/schedule"
                element={
                  <ManagerOnlyRoute>
                    <ManagerSchedulePage />
                  </ManagerOnlyRoute>
                }
              />
              <Route
                path="manager/timesheets"
                element={
                  <ManagerOnlyRoute>
                    <ManagerTimesheetsPage />
                  </ManagerOnlyRoute>
                }
              />
              <Route
                path="orders"
                element={
                  <ManagerOnlyRoute>
                    <OrdersPage />
                  </ManagerOnlyRoute>
                }
              />
              <Route
                path="financials"
                element={
                  <ManagerOnlyRoute>
                    <FinancialsPage />
                  </ManagerOnlyRoute>
                }
              />
              <Route
                path="master-data"
                element={
                  <OwnerOnlyRoute>
                    <MasterDataPage />
                  </OwnerOnlyRoute>
                }
              />
              <Route
                path="master-data/add"
                element={
                  <OwnerOnlyRoute>
                    <AddItemPage />
                  </OwnerOnlyRoute>
                }
              />
              <Route
                path="publish"
                element={
                  <OwnerOnlyRoute>
                    <PublishPage />
                  </OwnerOnlyRoute>
                }
              />
              <Route
                path="data-quality"
                element={
                  <OwnerOnlyRoute>
                    <DataQualityPage />
                  </OwnerOnlyRoute>
                }
              />
              <Route
                path="admin/users"
                element={
                  <ManagerOnlyRoute>
                    <AdminUsersPage />
                  </ManagerOnlyRoute>
                }
              />
              <Route
                path="settings/cag-nec"
                element={
                  <SystemAdminOnlyRoute>
                    <CagSettingsPage />
                  </SystemAdminOnlyRoute>
                }
              />
              <Route
                path="pos-readiness"
                element={
                  <OwnerOnlyRoute>
                    <PosReadinessPage />
                  </OwnerOnlyRoute>
                }
              />
              <Route
                path="admin/audit"
                element={
                  <SystemAdminOnlyRoute>
                    <AuditLogPage />
                  </SystemAdminOnlyRoute>
                }
              />
            </Route>
            <Route path="*" element={<Navigate to="/schedule" replace />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
