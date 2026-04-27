import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AppShell from "./components/AppShell";
import LoginPage from "./pages/LoginPage";
import SchedulePage from "./pages/SchedulePage";
import TimesheetPage from "./pages/TimesheetPage";
import PayPage from "./pages/PayPage";
import CommissionPage from "./pages/CommissionPage";
import PerformancePage from "./pages/PerformancePage";
import ProfilePage from "./pages/ProfilePage";
import MasterDataPage from "./pages/MasterDataPage";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          {/*
            TRACK 1 (May 1) — local-only mode: this route is intentionally outside
            the auth gate so the price-entry workflow keeps working while Firebase
            Auth is unavailable. The mini-server it talks to (tools/server/master_data_api.py)
            is bound to LAN only. TRACK 2 TODO: move under <ProtectedRoute> once
            Railway-backed auth is live.
          */}
          <Route path="/master-data" element={<MasterDataPage />} />
          <Route
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/schedule" replace />} />
            <Route path="schedule" element={<SchedulePage />} />
            <Route path="timesheet" element={<TimesheetPage />} />
            <Route path="pay" element={<PayPage />} />
            <Route path="commission" element={<CommissionPage />} />
            <Route path="performance" element={<PerformancePage />} />
            <Route path="profile" element={<ProfilePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/schedule" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
