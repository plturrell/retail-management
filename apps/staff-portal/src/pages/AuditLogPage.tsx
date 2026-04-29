/**
 * Owner-only audit log viewer.
 *
 * Browses Firestore `audit_events` via GET /api/audit with filters for
 * event_type / actor_email / target_email. Cursor-paginated (Firestore
 * start_after) so we don't pay for offset.
 *
 * This is the human-readable side of the compliance trail; it lets owners
 * see exactly who reset whose password, when, and from where — the #1
 * thing an auditor will ask for.
 */
import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";

interface Actor {
  user_id: string | null;
  email: string | null;
  uid: string | null;
}

interface AuditEvent {
  id: string;
  event_type: string;
  actor: Actor;
  target: Actor | null;
  metadata: Record<string, unknown>;
  ip: string | null;
  user_agent: string | null;
  created_at: string | null;
}

interface AuditPage {
  events: AuditEvent[];
  next_cursor: string | null;
}

function formatTs(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function eventColor(e: string): string {
  if (e.startsWith("password.")) return "bg-amber-100 text-amber-800";
  if (e.startsWith("role.")) return "bg-blue-100 text-blue-800";
  if (e.startsWith("user.disable")) return "bg-red-100 text-red-800";
  if (e.startsWith("user.enable")) return "bg-green-100 text-green-800";
  if (e.startsWith("user.invite")) return "bg-purple-100 text-purple-800";
  if (e.startsWith("session.")) return "bg-gray-200 text-gray-800";
  if (e.startsWith("auth.lockout")) return "bg-red-100 text-red-800";
  if (e.startsWith("webauthn.")) return "bg-indigo-100 text-indigo-800";
  return "bg-gray-100 text-gray-700";
}

function prettyUa(ua: string | null): string {
  if (!ua) return "";
  if (/iPhone/i.test(ua)) return "iPhone";
  if (/Android/i.test(ua)) return "Android";
  if (/Macintosh/i.test(ua) && /Safari/i.test(ua) && !/Chrome/i.test(ua)) return "Mac Safari";
  if (/Macintosh/i.test(ua) && /Chrome/i.test(ua)) return "Mac Chrome";
  if (/Windows/i.test(ua)) return "Windows";
  return ua.slice(0, 30);
}

export default function AuditLogPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [eventTypes, setEventTypes] = useState<string[]>([]);

  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [targetFilter, setTargetFilter] = useState("");

  const queryString = useMemo(() => {
    const p = new URLSearchParams();
    if (eventTypeFilter) p.set("event_type", eventTypeFilter);
    if (actorFilter) p.set("actor_email", actorFilter.trim().toLowerCase());
    if (targetFilter) p.set("target_email", targetFilter.trim().toLowerCase());
    if (cursor) p.set("cursor", cursor);
    p.set("limit", "50");
    const s = p.toString();
    return s ? `?${s}` : "";
  }, [eventTypeFilter, actorFilter, targetFilter, cursor]);

  const load = async (replace: boolean) => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get<{ data: AuditPage }>(`/audit${queryString}`);
      setEvents((prev) => (replace ? res.data.events : [...prev, ...res.data.events]));
      setNextCursor(res.data.next_cursor);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load audit log");
    } finally {
      setLoading(false);
    }
  };

  // Initial load + reload on filter change.
  useEffect(() => {
    setCursor(null);
    void load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventTypeFilter, actorFilter, targetFilter]);

  // Load event type options once.
  useEffect(() => {
    (async () => {
      try {
        const res = await api.get<{ data: string[] }>("/audit/event-types");
        setEventTypes(res.data);
      } catch {
        /* non-fatal */
      }
    })();
  }, []);

  const renderSummary = (e: AuditEvent): string => {
    const a = e.actor.email || e.actor.user_id || "unknown";
    const t = e.target?.email || e.target?.user_id || "";
    switch (e.event_type) {
      case "password.self_change":
        return `${a} changed their own password`;
      case "password.admin_reset":
        return `${a} reset password for ${t}`;
      case "password.policy_reject":
        return `${a} tried to set a password that failed policy (${String(e.metadata?.reason ?? "")})`;
      case "role.grant":
        return `${a} granted ${String(e.metadata?.role ?? "")} to ${t} at store ${String(e.metadata?.store_id ?? "")}`;
      case "role.update":
        return `${a} changed ${t}'s role from ${String(e.metadata?.old_role ?? "")} to ${String(e.metadata?.new_role ?? "")}`;
      case "role.revoke":
        return `${a} revoked ${String(e.metadata?.role ?? "")} from ${t}`;
      case "user.disable":
        return `${a} disabled ${t}`;
      case "user.enable":
        return `${a} re-enabled ${t}`;
      case "user.invite":
        return `${a} invited ${t}`;
      case "session.revoke_others":
        return `${a} signed out other devices`;
      case "auth.lockout":
        return `${t} was locked out after repeated failed sign-ins`;
      case "webauthn.register":
        return `${a} registered a new passkey ("${String(e.metadata?.name ?? "biometric device")}")`;
      case "webauthn.login":
        return `${a} signed in using a passkey (biometric)`;
      case "webauthn.revoke":
        return `${a} removed a passkey ("${String(e.metadata?.name ?? "biometric device")}")`;
      default:
        return `${e.event_type}: actor=${a}, target=${t}`;
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-gray-800">Audit log</h1>
        <p className="mt-1 text-sm text-gray-500">
          Tamper-evident record of password changes, role grants, account state changes,
          and session events. Owners only. Rows are newest-first.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white p-3">
        <label className="text-xs font-semibold text-gray-500">Event type</label>
        <select
          value={eventTypeFilter}
          onChange={(e) => setEventTypeFilter(e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"
        >
          <option value="">All</option>
          {eventTypes.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        <input
          type="email"
          placeholder="Actor email…"
          value={actorFilter}
          onChange={(e) => setActorFilter(e.target.value)}
          className="w-48 rounded border border-gray-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"
        />
        <input
          type="email"
          placeholder="Target email…"
          value={targetFilter}
          onChange={(e) => setTargetFilter(e.target.value)}
          className="w-48 rounded border border-gray-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"
        />

        {(eventTypeFilter || actorFilter || targetFilter) && (
          <button
            onClick={() => { setEventTypeFilter(""); setActorFilter(""); setTargetFilter(""); }}
            className="text-xs text-blue-600 hover:underline"
          >
            Clear filters
          </button>
        )}

        <div className="ml-auto text-xs text-gray-400">{events.length} row{events.length === 1 ? "" : "s"}</div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        {loading && events.length === 0 ? (
          <div className="px-4 py-10 text-center text-sm text-gray-400">Loading…</div>
        ) : events.length === 0 ? (
          <div className="px-4 py-10 text-center text-sm text-gray-400">No events match.</div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                <th className="px-3 py-2">When</th>
                <th className="px-3 py-2">Event</th>
                <th className="px-3 py-2">Summary</th>
                <th className="px-3 py-2">Origin</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {events.map((e) => (
                <tr key={e.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px] text-gray-600">
                    {formatTs(e.created_at)}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${eventColor(e.event_type)}`}
                    >
                      {e.event_type}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-700">{renderSummary(e)}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-500">
                    {e.ip || "—"}
                    {e.user_agent && <span className="ml-1 text-gray-400">({prettyUa(e.user_agent)})</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {nextCursor && (
        <div className="flex justify-center">
          <button
            onClick={() => { setCursor(nextCursor); void load(false); }}
            disabled={loading}
            className="rounded bg-gray-900 px-4 py-2 text-xs font-semibold text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {loading ? "Loading…" : "Load older events"}
          </button>
        </div>
      )}
    </div>
  );
}
