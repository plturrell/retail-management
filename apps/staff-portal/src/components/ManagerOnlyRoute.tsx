import { Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function ManagerOnlyRoute({ children }: { children: React.ReactNode }) {
  const { isManager, loading } = useAuth();

  if (loading) return null;
  if (!isManager) {
    return <Navigate to="/schedule" replace />;
  }
  return <>{children}</>;
}
