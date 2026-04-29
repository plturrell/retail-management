/**
 * Renders when the signed-in user carries the Firebase custom claim
 * `must_change_password=true` (set by backend `admin_reset_password` when a
 * manager/owner resets another user's password). The gate is enforced by
 * `ProtectedRoute` — every protected page redirects here until the user
 * successfully rotates their password, at which point the backend clears
 * the claim and we navigate to `/schedule`.
 *
 * This is a stripped-down, full-screen variant of the Profile > Security
 * card. No navigation, no way to bypass.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { EmailAuthProvider, reauthenticateWithCredential, signOut } from "firebase/auth";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../lib/api";
import { emailToUsername } from "../lib/authIdentity";
import { auth } from "../lib/firebase";

export default function ForceChangePasswordPage() {
  const { user, refreshTokenClaims } = useAuth();
  const navigate = useNavigate();
  const email = user?.email ?? "";
  const username = emailToUsername(email);

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    if (next.length < 10) return setErr("New password must be at least 10 characters");
    if (next !== confirm) return setErr("New password and confirmation do not match");
    if (!email) return setErr("No email on current account");
    const u = auth.currentUser;
    if (!u) return setErr("Not signed in");

    setBusy(true);
    try {
      const cred = EmailAuthProvider.credential(email, current);
      await reauthenticateWithCredential(u, cred);
      await api.post<{ message: string }>("/users/me/change-password", { new_password: next });
      // Backend cleared the must_change_password claim; refresh the token so
      // ProtectedRoute stops redirecting us back here.
      await refreshTokenClaims();
      navigate("/schedule", { replace: true });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("auth/wrong-password") || msg.includes("auth/invalid-credential")) {
        setErr("Current password is incorrect");
      } else if (msg.includes("auth/too-many-requests")) {
        setErr("Too many attempts — wait a few minutes and try again");
      } else if (msg.includes("HTTP 400") || msg.includes("400:")) {
        setErr(msg.replace(/^.*?400:\s*/, "") || "Password rejected by server policy");
      } else {
        setErr(msg);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="mb-4">
          <h1 className="text-lg font-bold text-gray-900">Choose a new password</h1>
          <p className="mt-1 text-xs text-gray-500">
            An administrator reset your password, or you signed in using a one-time
            reset link. For your account's safety, you must choose a new password
            before continuing to the app.
          </p>
          {email && (
            <p className="mt-2 font-mono text-[11px] text-gray-500">{username}</p>
          )}
        </div>

        <form onSubmit={submit} className="grid grid-cols-1 gap-3">
          <label className="text-xs font-medium text-gray-600">
            Current (or temporary) password
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

          {err && (
            <div className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">
              {err}
            </div>
          )}

          <div className="mt-2 flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => signOut(auth)}
              className="text-xs text-gray-500 hover:text-gray-700 hover:underline"
            >
              Sign out
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {busy ? "Updating…" : "Set new password"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
