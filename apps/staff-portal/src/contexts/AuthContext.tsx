import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import {
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut,
  type User,
} from "firebase/auth";
import { auth, firebaseConfigError, missingFirebaseConfig } from "../lib/firebase";
import { api } from "../lib/api";

const SELECTED_STORE_KEY = "retailsg.selectedStoreId";

export interface StoreRole {
  id: string;
  store_id: string;
  role: "staff" | "manager" | "owner" | "system_admin";
}

export type StoreRoleName = StoreRole["role"];

export function getRoleLabel(role: StoreRoleName | null | undefined) {
  switch (role) {
    case "system_admin":
      return "System Admin";
    case "owner":
      return "Owner Director";
    case "manager":
      return "Store Manager";
    case "staff":
      return "Sales Promoter";
    default:
      return "Team Member";
  }
}

export interface BackendProfile {
  id: string;
  firebase_uid: string;
  email: string;
  full_name: string;
  phone: string | null;
  store_roles: StoreRole[];
}

export interface StoreSummary {
  id: string;
  store_code?: string | null;
  name: string;
  location: string;
  address: string;
  store_type?: "flagship" | "outlet" | "pop_up" | "warehouse" | "online" | "retail" | "hybrid";
  operational_status?: "active" | "staging" | "planned" | "inactive";
  is_home_base?: boolean;
  is_temp_warehouse?: boolean;
  planned_open_date?: string | null;
  notes?: string | null;
  is_active: boolean;
}

interface AuthContextValue {
  user: User | null;
  profile: BackendProfile | null;
  stores: StoreSummary[];
  selectedStore: StoreSummary | null;
  selectedStoreRole: StoreRole | null;
  isManager: boolean;
  isOwner: boolean;
  isSystemAdmin: boolean;
  canViewSensitiveOperations: boolean;
  roleLabel: string;
  loading: boolean;
  mustChangePassword: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshProfile: () => Promise<void>;
  refreshTokenClaims: () => Promise<void>;
  setSelectedStoreId: (storeId: string) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<BackendProfile | null>(null);
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [selectedStoreId, setSelectedStoreIdState] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(SELECTED_STORE_KEY);
  });
  const [loading, setLoading] = useState(true);
  const [mustChangePassword, setMustChangePassword] = useState(false);

  const readForceChangeClaim = async (currentUser: User | null): Promise<boolean> => {
    if (!currentUser) return false;
    try {
      // forceRefresh=true pulls the latest custom claims from Firebase; if we don't
      // do this the claim the admin just set won't reach the client until the
      // refresh token naturally expires (~1h).
      const result = await currentUser.getIdTokenResult(true);
      return Boolean(result.claims?.must_change_password);
    } catch {
      return false;
    }
  };

  const refreshTokenClaims = async () => {
    setMustChangePassword(await readForceChangeClaim(auth.currentUser));
  };

  const hydrateSession = async () => {
    const meRes = await api.get<{ data: BackendProfile }>("/users/me");
    const storesRes = await api.get<{
      data: StoreSummary[];
      total: number;
      page: number;
      page_size: number;
    }>("/stores");
    setProfile(meRes.data);
    setStores(storesRes.data);

    const storedStoreId =
      typeof window === "undefined" ? null : window.localStorage.getItem(SELECTED_STORE_KEY);
    const preferredStoreId =
      (storedStoreId && storesRes.data.some((store) => store.id === storedStoreId))
        ? storedStoreId
        : storesRes.data[0]?.id ?? null;
    setSelectedStoreIdState(preferredStoreId);
    if (preferredStoreId) {
      window.localStorage.setItem(SELECTED_STORE_KEY, preferredStoreId);
    }
  };

  useEffect(() => {
    if (firebaseConfigError) {
      setLoading(false);
      return;
    }
    const unsub = onAuthStateChanged(auth, async (u) => {
      setUser(u);
      if (!u) {
        setProfile(null);
        setStores([]);
        setSelectedStoreIdState(null);
        setMustChangePassword(false);
        setLoading(false);
        return;
      }

      setLoading(true);
      try {
        setMustChangePassword(await readForceChangeClaim(u));
        await hydrateSession();
      } catch (err: unknown) {
        // If the backend returns 404 the user record doesn't exist yet,
        // or the Firebase token is stale from a different app registration.
        // Either way, sign out cleanly so the login page appears.
        const msg = err instanceof Error ? err.message : "";
        const isAuthError = msg.includes("404") || msg.includes("401") || msg.includes("400");
        if (isAuthError) {
          await signOut(auth);
        }
        setProfile(null);
        setStores([]);
      } finally {
        setLoading(false);
      }
    });
    return unsub;
  }, []);

  const login = async (email: string, password: string) => {
    await signInWithEmailAndPassword(auth, email, password);
  };

  const logout = async () => {
    await signOut(auth);
    setProfile(null);
    setStores([]);
    setSelectedStoreIdState(null);
  };

  const refreshProfile = async () => {
    if (!auth.currentUser) return;
    setLoading(true);
    try {
      await hydrateSession();
    } finally {
      setLoading(false);
    }
  };

  const setSelectedStoreId = (storeId: string) => {
    setSelectedStoreIdState(storeId);
    window.localStorage.setItem(SELECTED_STORE_KEY, storeId);
  };

  const selectedStore = stores.find((store) => store.id === selectedStoreId) ?? null;
  const selectedStoreRole = selectedStore
    ? profile?.store_roles.find((role) => role.store_id === selectedStore.id) ?? null
    : null;
  // System admins have a global role: any system_admin assignment grants
  // owner-equivalent access to every store, regardless of which store is
  // currently selected. Mirrors the backend short-circuit in
  // ``ensure_store_access`` / ``is_system_admin``.
  const isSystemAdmin = (profile?.store_roles ?? []).some((r) => r.role === "system_admin");
  const isOwner = isSystemAdmin || selectedStoreRole?.role === "owner";
  const isManager =
    isSystemAdmin ||
    selectedStoreRole?.role === "manager" ||
    selectedStoreRole?.role === "owner";
  const canViewSensitiveOperations = isOwner;
  const roleLabel = isSystemAdmin
    ? getRoleLabel("system_admin")
    : getRoleLabel(selectedStoreRole?.role);

  if (firebaseConfigError) {
    return <FirebaseConfigurationError />;
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        profile,
        stores,
        selectedStore,
        selectedStoreRole,
        isManager,
        isOwner,
        isSystemAdmin,
        canViewSensitiveOperations,
        roleLabel,
        loading,
        mustChangePassword,
        login,
        logout,
        refreshProfile,
        refreshTokenClaims,
        setSelectedStoreId,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

function FirebaseConfigurationError() {
  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8 text-gray-800">
      <div className="mx-auto max-w-2xl rounded-xl border border-red-200 bg-white p-6 shadow-sm">
        <div className="rounded-full bg-red-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-red-700">
          Startup blocked
        </div>
        <h1 className="mt-4 text-xl font-bold">Firebase configuration is missing or invalid</h1>
        <p className="mt-2 text-sm text-gray-600">
          The staff portal cannot start authentication until the Firebase web SDK
          values are present in the deployed environment.
        </p>
        {missingFirebaseConfig.length > 0 && (
          <div className="mt-4 rounded-lg border border-red-100 bg-red-50 p-3 text-sm text-red-800">
            Missing: <span className="font-mono">{missingFirebaseConfig.join(", ")}</span>
          </div>
        )}
        {!missingFirebaseConfig.length && (
          <div className="mt-4 rounded-lg border border-red-100 bg-red-50 p-3 text-sm text-red-800">
            {firebaseConfigError}
          </div>
        )}
        <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600">
          Run the Firebase app config sync before launch, then rebuild and redeploy
          the staff portal. Keep API keys out of screenshots and support threads.
        </div>
      </div>
    </div>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
