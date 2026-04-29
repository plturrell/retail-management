import { Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function SystemAdminOnlyRoute({ children }: { children: React.ReactNode }) {
  const { isSystemAdmin, loading } = useAuth();

  if (loading) return null;
  if (!isSystemAdmin) {
    return <Navigate to="/manager" replace />;
  }
  return <>{children}</>;
}
