import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import ManagerOnlyRoute from "./components/ManagerOnlyRoute";
import OwnerOnlyRoute from "./components/OwnerOnlyRoute";
import AppShell from "./components/AppShell";
import LoginPage from "./pages/LoginPage";
import SchedulePage from "./pages/SchedulePage";
import TimesheetPage from "./pages/TimesheetPage";
import PayPage from "./pages/PayPage";
import CommissionPage from "./pages/CommissionPage";
import PerformancePage from "./pages/PerformancePage";
import ProfilePage from "./pages/ProfilePage";
import ManagerOpsPage from "./pages/ManagerOpsPage";
import SupplierReviewPage from "./pages/SupplierReviewPage";
import VaultPage from "./pages/VaultPage";
import DataQualityPage from "./pages/DataQualityPage";
import AdminUsersPage from "./pages/AdminUsersPage";
import ForceChangePasswordPage from "./pages/ForceChangePasswordPage";
import AuditLogPage from "./pages/AuditLogPage";
import MasterDataPage from "./pages/MasterDataPage";
import HomePage from "./pages/HomePage";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
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
              path="master-data"
              element={
                <OwnerOnlyRoute>
                  <MasterDataPage />
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
              path="admin/audit"
              element={
                <OwnerOnlyRoute>
                  <AuditLogPage />
                </OwnerOnlyRoute>
              }
            />
          </Route>
          <Route path="*" element={<Navigate to="/schedule" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
