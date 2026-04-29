import { Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function OwnerOnlyRoute({ children }: { children: React.ReactNode }) {
  const { isOwner, loading } = useAuth();

  if (loading) return null;
  if (!isOwner) {
    return <Navigate to="/manager" replace />;
  }
  return <>{children}</>;
}
