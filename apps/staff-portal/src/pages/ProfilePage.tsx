import { useEffect, useState } from "react";
import { EmailAuthProvider, reauthenticateWithCredential } from "firebase/auth";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../lib/api";
import { emailToUsername } from "../lib/authIdentity";
import { auth } from "../lib/firebase";
import BiometricsCard from "../components/BiometricsCard";
import ConfirmDialog from "../components/ConfirmDialog";

interface EmployeeProfile {
  date_of_birth: string;
  nationality: string;
  basic_salary: number;
  hourly_rate: number | null;
  commission_rate: number | null;
  bank_account: string | null;
  bank_name: string;
  cpf_account_number: string | null;
  start_date: string;
  end_date: string | null;
  is_active: boolean;
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs font-medium text-gray-400 uppercase tracking-wide">{label}</dt>
      <dd className="mt-0.5 text-sm text-gray-800">{value || "—"}</dd>
    </div>
  );
}

interface SessionRow {
  fingerprint: string;
  ip: string | null;
  user_agent: string | null;
  first_seen: string | null;
  last_seen: string | null;
  count: number;
}

function prettyUserAgent(ua: string | null): string {
  if (!ua) return "Unknown device";
  // Cheap heuristic — good enough for an at-a-glance list. No need to ship
  // a full UA-parsing library for 10 users.
  if (/iPhone/i.test(ua)) return "iPhone (Safari)";
  if (/iPad/i.test(ua)) return "iPad (Safari)";
  if (/Android/i.test(ua)) return "Android";
  if (/Macintosh/i.test(ua) && /Safari/i.test(ua) && !/Chrome/i.test(ua)) return "Mac (Safari)";
  if (/Macintosh/i.test(ua) && /Chrome/i.test(ua)) return "Mac (Chrome)";
  if (/Windows/i.test(ua) && /Chrome/i.test(ua)) return "Windows (Chrome)";
  if (/Windows/i.test(ua) && /Edge/i.test(ua)) return "Windows (Edge)";
  if (/Firefox/i.test(ua)) return "Firefox";
  return ua.slice(0, 60) + (ua.length > 60 ? "…" : "");
}

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 2) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return d.toLocaleDateString();
}

function SessionsCard() {
  const [rows, setRows] = useState<SessionRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);

  const load = async () => {
    setErr("");
    try {
      const res = await api.get<{ data: SessionRow[] }>("/users/me/sessions");
      setRows(res.data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load sessions");
    }
  };

  useEffect(() => { void load(); }, []);

  const signOutOthers = async () => {
    setConfirmOpen(false);
    setBusy(true);
    setMsg(""); setErr("");
    try {
      const res = await api.post<{ message: string }>("/users/me/sign-out-other-devices", {});
      setMsg(res.message || "Other devices signed out.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not sign out other devices");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Active devices</h2>
        <button
          type="button"
          onClick={() => setConfirmOpen(true)}
          disabled={busy || !rows || rows.length <= 1}
          title={rows && rows.length <= 1 ? "No other devices to sign out" : "Revoke refresh tokens on every device (including this one when its current token expires)"}
          className="rounded border border-gray-300 bg-white px-2.5 py-1 text-[11px] font-semibold text-gray-700 hover:border-red-300 hover:text-red-600 disabled:opacity-40"
        >
          {busy ? "Signing out…" : "Sign out other devices"}
        </button>
      </div>
      {err && <div className="mb-2 text-xs text-red-700">{err}</div>}
      {msg && <div className="mb-2 text-xs text-green-700">{msg}</div>}
      {rows === null ? (
        <div className="text-xs text-gray-400">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="text-xs text-gray-400">No recorded sessions yet.</div>
      ) : (
        <ul className="divide-y divide-gray-100 text-sm">
          {rows.map((r) => (
            <li key={r.fingerprint} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <div className="font-medium text-gray-800">{prettyUserAgent(r.user_agent)}</div>
                <div className="mt-0.5 text-[11px] text-gray-500">
                  {r.ip || "unknown network"} · seen {r.count}×
                </div>
              </div>
              <div className="shrink-0 text-right text-[11px] text-gray-500">
                <div>Last: {relativeTime(r.last_seen)}</div>
                <div>First: {relativeTime(r.first_seen)}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] text-gray-400">
        Devices are grouped by browser + approximate network. Sign-out revokes all refresh
        tokens including this browser's — you'll need to sign in again within the hour.
      </p>
      <ConfirmDialog
        open={confirmOpen}
        title="Sign out other devices?"
        body="This revokes refresh tokens on every device. This browser may also need a fresh sign-in within the hour."
        confirmLabel="Sign out devices"
        tone="danger"
        busy={busy}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => void signOutOthers()}
      />
    </div>
  );
}

function ChangePasswordCard({ email }: { email: string | null | undefined }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState<string>("");
  const [err, setErr] = useState<string>("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setOk(""); setErr("");
    if (next.length < 10) return setErr("New password must be at least 10 characters");
    if (next !== confirm) return setErr("New password and confirmation do not match");
    if (!email) return setErr("No email on current account");
    const user = auth.currentUser;
    if (!user) return setErr("Not signed in");

    setBusy(true);
    try {
      // 1) Re-authenticate with the CURRENT password to prove it's really them.
      const cred = EmailAuthProvider.credential(email, current);
      await reauthenticateWithCredential(user, cred);
      // 2) Ask the backend to rotate the password (Firebase Admin SDK).
      await api.post<{ message: string }>("/users/me/change-password", { new_password: next });
      setOk("Password updated. Other devices may require a fresh sign-in.");
      setCurrent(""); setNext(""); setConfirm("");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("auth/wrong-password") || msg.includes("auth/invalid-credential")) {
        setErr("Current password is incorrect");
      } else if (msg.includes("auth/too-many-requests")) {
        setErr("Too many attempts — wait a few minutes and try again");
      } else {
        setErr(msg);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Security</h2>
      <form onSubmit={submit} className="grid max-w-md grid-cols-1 gap-3">
        <label className="text-xs font-medium text-gray-600">
          Current password
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            required
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </label>
        <label className="text-xs font-medium text-gray-600">
          New password (≥ 10 characters, not a known breached password)
          <input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
            minLength={10}
            required
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </label>
        <label className="text-xs font-medium text-gray-600">
          Confirm new password
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            minLength={10}
            required
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </label>
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={busy}
            className="rounded bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? "Updating…" : "Update password"}
          </button>
          {ok && <span className="text-xs text-green-700">{ok}</span>}
          {err && <span className="text-xs text-red-700">{err}</span>}
        </div>
      </form>
    </div>
  );
}

export default function ProfilePage() {
  const { user, profile: userProfile, stores, selectedStore, roleLabel, loading: authLoading } = useAuth();
  const [employeeProfile, setEmployeeProfile] = useState<EmployeeProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);

  useEffect(() => {
    if (!userProfile?.id) {
      setProfileLoading(false);
      return;
    }

    setProfileLoading(true);
    (async () => {
      try {
        try {
          const profRes = await api.get<{ data: EmployeeProfile }>(`/employees/${userProfile.id}/profile`);
          setEmployeeProfile(profRes.data);
        } catch { /* profile may not exist */ }
      } finally {
        setProfileLoading(false);
      }
    })();
  }, [userProfile?.id]);

  if (authLoading || profileLoading) {
    return <div className="flex items-center justify-center py-20 text-gray-400">Loading profile…</div>;
  }

  const statusLabel = employeeProfile?.is_active ? "Active" : employeeProfile ? "Inactive" : undefined;
  const nationalityLabel = employeeProfile?.nationality
    ? { citizen: "Singapore Citizen", pr: "Permanent Resident", foreigner: "Foreigner" }[employeeProfile.nationality] ?? employeeProfile.nationality
    : undefined;
  const assignedLocations = stores.map((store) => store.name).join(", ");

  return (
    <div>
      <h1 className="text-xl font-bold text-gray-800">Profile</h1>
      <p className="mt-1 text-sm text-gray-500">Your account, assigned locations, and employment details.</p>

      {/* Personal info */}
      <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Personal Information</h2>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Full Name" value={userProfile?.full_name} />
          <Field label="Username" value={emailToUsername(userProfile?.email ?? user?.email)} />
          <Field label="Phone" value={userProfile?.phone} />
          <Field label="Current Role" value={selectedStore ? roleLabel : undefined} />
          <Field label="Current Store" value={selectedStore?.name} />
          <Field label="Assigned Locations" value={assignedLocations} />
          <Field label="Nationality" value={nationalityLabel} />
          <Field label="Employment Status" value={statusLabel} />
        </dl>
      </div>

      {/* Employment details */}
      {employeeProfile && (
        <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Employment Details</h2>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Hire Date" value={employeeProfile.start_date ? new Date(employeeProfile.start_date + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" }) : undefined} />
            {employeeProfile.end_date && <Field label="End Date" value={new Date(employeeProfile.end_date + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" })} />}
            <Field label="Basic Salary" value={`$${employeeProfile.basic_salary.toFixed(2)}`} />
            {employeeProfile.hourly_rate != null && <Field label="Hourly Rate" value={`$${employeeProfile.hourly_rate.toFixed(2)}/hr`} />}
            {employeeProfile.commission_rate != null && <Field label="Commission Rate" value={`${employeeProfile.commission_rate}%`} />}
          </dl>
        </div>
      )}

      {/* Bank details */}
      {employeeProfile && (employeeProfile.bank_account || employeeProfile.cpf_account_number) && (
        <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Bank & CPF</h2>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Bank" value={employeeProfile.bank_name} />
            <Field label="Bank Account" value={employeeProfile.bank_account} />
            <Field label="CPF Account" value={employeeProfile.cpf_account_number} />
          </dl>
        </div>
      )}

      {/* Security — change password */}
      <ChangePasswordCard email={userProfile?.email ?? user?.email ?? null} />

      {/* Security — biometric / passkey sign-in */}
      <BiometricsCard />

      {/* Security — active devices / sessions */}
      <SessionsCard />
    </div>
  );
}
