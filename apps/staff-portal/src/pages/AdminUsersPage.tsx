import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../contexts/AuthContext";
import { emailToUsername } from "../lib/authIdentity";
import ConfirmDialog from "../components/ConfirmDialog";

interface UserWithRoles {
  id: string;
  email: string;
  full_name: string;
  firebase_uid: string;
  disabled: boolean;
  must_change_password: boolean;
  highest_role: "owner" | "manager" | "staff" | "";
  store_codes: string[];
}

interface ResetResult {
  user_id: string;
  email: string;
  reset_link: string;
  expires_in_seconds: number;
  message: string;
}

interface InviteResult {
  user_id: string;
  email: string;
  setup_link: string;
  expires_in_seconds: number;
  email_sent: boolean;
  message: string;
}

interface StoreOption {
  id: string;
  store_code: string;
  name: string;
}

const ROLE_ORDER: Record<string, number> = { owner: 3, manager: 2, staff: 1, "": 0 };

function roleBadge(role: string) {
  switch (role) {
    case "owner":
      return "bg-purple-100 text-purple-700";
    case "manager":
      return "bg-blue-100 text-blue-700";
    case "staff":
      return "bg-gray-100 text-gray-600";
    default:
      return "bg-red-50 text-red-500";
  }
}

export default function AdminUsersPage() {
  const { profile, isOwner } = useAuth();
  const [users, setUsers] = useState<UserWithRoles[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<"all" | "owner" | "manager" | "staff">("all");
  const [resettingId, setResettingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [lastReset, setLastReset] = useState<ResetResult | null>(null);
  const [resetError, setResetError] = useState("");
  const [actionError, setActionError] = useState("");

  // Invitation modal state
  const [inviteOpen, setInviteOpen] = useState(false);
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState<"staff" | "manager" | "owner">("staff");
  const [inviteStoreIds, setInviteStoreIds] = useState<string[]>([]);
  const [inviteBusy, setInviteBusy] = useState(false);
  const [inviteErr, setInviteErr] = useState("");
  const [lastInvite, setLastInvite] = useState<InviteResult | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<{
    kind: "toggle" | "reset";
    user: UserWithRoles;
  } | null>(null);

  const openInviteModal = async () => {
    setInviteErr("");
    setLastInvite(null);
    setInviteEmail("");
    setInviteName("");
    setInviteRole("staff");
    setInviteStoreIds([]);
    setInviteOpen(true);
    // Lazy-load stores the first time
    if (stores.length === 0) {
      try {
        const res = await api.get<{ data: StoreOption[] }>("/stores");
        setStores(res.data);
      } catch {
        /* ignore; user can still submit without stores */
      }
    }
  };

  const submitInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setInviteErr("");
    if (!inviteEmail.trim()) return setInviteErr("Email is required");
    if (inviteRole !== "staff" && !isOwner) return setInviteErr("Only owners can invite managers or owners");
    setInviteBusy(true);
    try {
      const res = await api.post<InviteResult>("/users/invite", {
        email: inviteEmail.trim().toLowerCase(),
        full_name: inviteName.trim(),
        role: inviteRole,
        store_ids: inviteStoreIds,
      });
      setLastInvite(res);
      await load(); // refresh the table to show the new user
    } catch (err) {
      setInviteErr(err instanceof Error ? err.message : "Invite failed");
    } finally {
      setInviteBusy(false);
    }
  };

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get<{ data: UserWithRoles[] }>("/users");
      setUsers(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const requestToggleDisabled = (u: UserWithRoles) => {
    setActionError("");
    if (u.highest_role === "owner" && !isOwner) {
      setActionError("Only owners can disable an owner account.");
      return;
    }
    setPendingConfirm({ kind: "toggle", user: u });
  };

  const toggleDisabled = async (u: UserWithRoles) => {
    const action = u.disabled ? "enable" : "disable";
    const verb = u.disabled ? "re-enable" : "disable";

    setTogglingId(u.id);
    try {
      await api.post(`/users/${u.id}/${action}`, {});
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : `Could not ${verb} account`);
    } finally {
      setTogglingId(null);
    }
  };

  const requestReset = (u: UserWithRoles) => {
    setResetError("");
    const targetIsOwner = u.highest_role === "owner";
    if (targetIsOwner && !isOwner) {
      setResetError("Only owners can reset an owner's password.");
      return;
    }
    setPendingConfirm({ kind: "reset", user: u });
  };

  const confirmAndReset = async (u: UserWithRoles) => {
    setResettingId(u.id);
    setLastReset(null);
    try {
      const res = await api.post<ResetResult>(`/users/${u.id}/reset-password`, {});
      setLastReset(res);
    } catch (e) {
      setResetError(e instanceof Error ? e.message : "Reset failed");
    } finally {
      setResettingId(null);
    }
  };

  const runPendingConfirm = async () => {
    if (!pendingConfirm) return;
    const { kind, user } = pendingConfirm;
    setPendingConfirm(null);
    if (kind === "toggle") {
      await toggleDisabled(user);
    } else {
      await confirmAndReset(user);
    }
  };

  const filtered = users
    .filter((u) => (roleFilter === "all" ? true : u.highest_role === roleFilter))
    .filter((u) => {
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      return (
        emailToUsername(u.email).toLowerCase().includes(q) ||
        u.full_name.toLowerCase().includes(q) ||
        u.store_codes.some((c) => c.toLowerCase().includes(q))
      );
    })
    .sort(
      (a, b) =>
        (ROLE_ORDER[b.highest_role] ?? 0) - (ROLE_ORDER[a.highest_role] ?? 0) ||
        emailToUsername(a.email).localeCompare(emailToUsername(b.email)),
    );

  const counts = {
    all: users.length,
    owner: users.filter((u) => u.highest_role === "owner").length,
    manager: users.filter((u) => u.highest_role === "manager").length,
    staff: users.filter((u) => u.highest_role === "staff").length,
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Users & Access</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage staff accounts, view roles, and reset passwords.
            {isOwner ? " As an owner, you can reset any user's password." : " You can reset passwords for staff and managers at your stores — owner passwords are owner-only."}
          </p>
        </div>
        <button
          onClick={openInviteModal}
          className="shrink-0 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-700"
        >
          + Invite user
        </button>
      </div>

      {/* Just-generated reset-link banner */}
      {lastReset && (
        <div className="rounded-lg border border-green-300 bg-green-50 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-green-800">
                Password reset link generated for {emailToUsername(lastReset.email)}
              </div>
              <div className="mt-1 text-xs text-green-700">
                Share this link with the user via a secure channel (Signal, 1Password, in-person).
                It expires in {Math.round(lastReset.expires_in_seconds / 60)} minutes and can be used once.
                Their existing sessions have been signed out.
              </div>
              <div className="mt-2 flex items-center gap-2">
                <code className="block min-w-0 flex-1 overflow-x-auto rounded bg-white px-2 py-1 font-mono text-[11px] text-gray-800 ring-1 ring-green-200">
                  {lastReset.reset_link}
                </code>
                <button
                  onClick={() => navigator.clipboard.writeText(lastReset.reset_link)}
                  className="shrink-0 rounded border border-green-400 px-2 py-1 text-xs font-medium text-green-700 hover:bg-green-100"
                >
                  Copy link
                </button>
              </div>
            </div>
            <button
              onClick={() => setLastReset(null)}
              className="shrink-0 text-xs text-green-700 hover:underline"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {(resetError || actionError) && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {resetError || actionError}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3">
        <span className="text-xs font-semibold text-gray-500">Filter:</span>
        {(["all", "owner", "manager", "staff"] as const).map((key) => (
          <button
            key={key}
            onClick={() => setRoleFilter(key)}
            className={`rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors ${
              roleFilter === key ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {key} <span className="ml-1 opacity-70">({counts[key]})</span>
          </button>
        ))}
        <div className="ml-auto">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search username, name, or store…"
            className="w-72 rounded border border-gray-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        {loading ? (
          <div className="px-4 py-10 text-center text-sm text-gray-400">Loading users…</div>
        ) : error ? (
          <div className="px-4 py-10 text-center text-sm text-red-600">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="px-4 py-10 text-center text-sm text-gray-400">No users match.</div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Username</th>
                <th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Stores</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((u) => {
                const isSelf = profile?.id === u.id;
                const canReset =
                  !isSelf && (u.highest_role !== "owner" || isOwner);
                const canToggle = canReset; // same permission matrix as reset
                return (
                  <tr key={u.id} className={`hover:bg-gray-50 ${u.disabled ? "opacity-60" : ""}`}>
                    <td className="px-3 py-2 font-medium text-gray-800">
                      <div className="flex flex-wrap items-center gap-1">
                        <span>{u.full_name || <span className="text-gray-400">—</span>}</span>
                        {isSelf && (
                          <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">
                            you
                          </span>
                        )}
                        {u.disabled && (
                          <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold text-red-700">
                            disabled
                          </span>
                        )}
                        {u.must_change_password && !u.disabled && (
                          <span
                            title="User has a pending reset link — must change password on next login"
                            className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700"
                          >
                            must reset
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-600">{emailToUsername(u.email)}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${roleBadge(
                          u.highest_role,
                        )}`}
                      >
                        {u.highest_role || "no role"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600">
                      {u.store_codes.length > 0 ? u.store_codes.join(", ") : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {isSelf ? (
                        <span className="text-[11px] text-gray-400">
                          Use <a href="/profile" className="text-blue-600 hover:underline">Profile</a> for your own account
                        </span>
                      ) : !canReset ? (
                        <span className="text-[11px] text-gray-400">owner-only</span>
                      ) : (
                        <div className="flex justify-end gap-1.5">
                          <button
                            onClick={() => requestReset(u)}
                            disabled={resettingId === u.id || u.disabled}
                            title={u.disabled ? "Re-enable the account first" : "Generate a one-time password reset link"}
                            className="rounded border border-gray-300 bg-white px-2.5 py-1 text-[11px] font-semibold text-gray-700 hover:border-blue-300 hover:text-blue-600 disabled:opacity-40"
                          >
                            {resettingId === u.id ? "Sending…" : "Reset password"}
                          </button>
                          {canToggle && (
                            <button
                              onClick={() => requestToggleDisabled(u)}
                              disabled={togglingId === u.id}
                              className={`rounded border px-2.5 py-1 text-[11px] font-semibold disabled:opacity-40 ${
                                u.disabled
                                  ? "border-green-300 bg-white text-green-700 hover:bg-green-50"
                                  : "border-gray-300 bg-white text-gray-700 hover:border-red-300 hover:text-red-600"
                              }`}
                            >
                              {togglingId === u.id ? "Working…" : u.disabled ? "Enable" : "Disable"}
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {inviteOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => { if (!inviteBusy) setInviteOpen(false); }}
        >
          <div
            className="w-full max-w-lg rounded-xl bg-white p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-gray-900">Invite a new user</h2>
              <button
                onClick={() => setInviteOpen(false)}
                disabled={inviteBusy}
                className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-50"
              >
                Close
              </button>
            </div>

            {lastInvite ? (
              <div className="space-y-3">
                <div className="rounded border border-green-300 bg-green-50 p-3">
                  <div className="text-sm font-semibold text-green-800">Invite created for {emailToUsername(lastInvite.email)}</div>
                  <div className="mt-1 text-xs text-green-700">{lastInvite.message}</div>
                </div>
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase text-gray-500">Setup link (expires in 1 hour)</div>
                  <div className="flex items-center gap-2">
                    <code className="block min-w-0 flex-1 overflow-x-auto rounded bg-gray-50 px-2 py-1 font-mono text-[11px] text-gray-800 ring-1 ring-gray-200">
                      {lastInvite.setup_link}
                    </code>
                    <button
                      onClick={() => navigator.clipboard.writeText(lastInvite.setup_link)}
                      className="shrink-0 rounded border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    >
                      Copy
                    </button>
                  </div>
                  {!lastInvite.email_sent && (
                    <p className="mt-2 text-[11px] text-amber-700">
                      Email delivery failed — share this link directly via a secure channel.
                    </p>
                  )}
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <button
                    onClick={() => setInviteOpen(false)}
                    className="rounded bg-gray-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-700"
                  >
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={submitInvite} className="grid grid-cols-1 gap-3">
                <label className="text-xs font-medium text-gray-600">
                  Email
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    required
                    className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                    placeholder="newhire@victoriaenso.com"
                  />
                </label>
                <label className="text-xs font-medium text-gray-600">
                  Full name (optional)
                  <input
                    type="text"
                    value={inviteName}
                    onChange={(e) => setInviteName(e.target.value)}
                    className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </label>
                <label className="text-xs font-medium text-gray-600">
                  Role
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value as "staff" | "manager" | "owner")}
                    className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                  >
                    <option value="staff">Staff (Sales Promoter)</option>
                    <option value="manager" disabled={!isOwner}>Manager (Sales Manager){!isOwner && " — owner-only"}</option>
                    <option value="owner" disabled={!isOwner}>Owner (Director){!isOwner && " — owner-only"}</option>
                  </select>
                </label>
                <div>
                  <div className="mb-1 text-xs font-medium text-gray-600">Assign to stores</div>
                  <div className="max-h-40 overflow-y-auto rounded border border-gray-200 p-2">
                    {stores.length === 0 ? (
                      <div className="text-xs text-gray-400">No stores available.</div>
                    ) : (
                      stores.map((s) => (
                        <label key={s.id} className="flex items-center gap-2 py-0.5 text-xs text-gray-700">
                          <input
                            type="checkbox"
                            checked={inviteStoreIds.includes(s.id)}
                            onChange={(e) => {
                              setInviteStoreIds((prev) =>
                                e.target.checked ? [...prev, s.id] : prev.filter((x) => x !== s.id),
                              );
                            }}
                          />
                          <span className="font-mono">{s.store_code}</span>
                          <span className="text-gray-500">{s.name}</span>
                        </label>
                      ))
                    )}
                  </div>
                </div>

                {inviteErr && (
                  <div className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">
                    {inviteErr}
                  </div>
                )}

                <div className="mt-1 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setInviteOpen(false)}
                    disabled={inviteBusy}
                    className="rounded border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={inviteBusy}
                    className="rounded bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {inviteBusy ? "Creating invite…" : "Send invite"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={pendingConfirm !== null}
        title={
          pendingConfirm?.kind === "reset"
            ? `Reset ${emailToUsername(pendingConfirm.user.email)}?`
            : pendingConfirm?.user.disabled
              ? `Enable ${emailToUsername(pendingConfirm.user.email)}?`
              : `Disable ${emailToUsername(pendingConfirm?.user.email)}?`
        }
        body={
          pendingConfirm?.kind === "reset"
            ? "This generates a one-time password reset link, signs out active sessions, and requires the user to set a new password."
            : pendingConfirm?.user.disabled
              ? "This account will be able to sign in again."
              : "This account will be signed out and unable to log in until re-enabled."
        }
        confirmLabel={
          pendingConfirm?.kind === "reset"
            ? "Generate reset link"
            : pendingConfirm?.user.disabled
              ? "Enable account"
              : "Disable account"
        }
        tone={pendingConfirm?.kind === "toggle" && !pendingConfirm.user.disabled ? "danger" : "default"}
        busy={Boolean(
          pendingConfirm?.user.id &&
            (pendingConfirm.kind === "reset"
              ? resettingId === pendingConfirm.user.id
              : togglingId === pendingConfirm.user.id),
        )}
        onCancel={() => setPendingConfirm(null)}
        onConfirm={() => void runPendingConfirm()}
      />
    </div>
  );
}
