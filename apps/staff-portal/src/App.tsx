import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import { ToastProvider } from "./components/ui/Toast";
import ProtectedRoute from "./components/ProtectedRoute";
import AppShell from "./components/AppShell";
import LoginPage from "./pages/LoginPage";
import SchedulePage from "./pages/SchedulePage";
import TimesheetPage from "./pages/TimesheetPage";
import PayPage from "./pages/PayPage";
import CommissionPage from "./pages/CommissionPage";
import PerformancePage from "./pages/PerformancePage";
import ProfilePage from "./pages/ProfilePage";

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
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
      </ToastProvider>
    </AuthProvider>
  );
}
