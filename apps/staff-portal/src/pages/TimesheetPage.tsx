import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

const STORE_ID = import.meta.env.VITE_STORE_ID as string;

// ---- types ----

interface TimeEntry {
  id: string;
  user_id: string;
  store_id: string;
  clock_in: string;
  clock_out: string | null;
  break_minutes: number;
  notes: string | null;
  status: string;
  hours_worked: number | null;
}

// ---- helpers ----

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-SG", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-SG", {
    day: "numeric",
    month: "short",
  });
}

function toDateInput(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function elapsed(from: string): string {
  const diff = Math.max(0, Math.floor((Date.now() - new Date(from).getTime()) / 1000));
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const s = diff % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    approved: "bg-green-100 text-green-700",
    pending: "bg-yellow-100 text-yellow-700",
    rejected: "bg-red-100 text-red-700",
  };
  return map[status] ?? "bg-gray-100 text-gray-600";
}

// ---- component ----

export default function TimesheetPage() {
  // clock state
  const [activeEntry, setActiveEntry] = useState<TimeEntry | null>(null);
  const [timerStr, setTimerStr] = useState("00:00:00");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [clockLoading, setClockLoading] = useState(false);

  // history state
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [histLoading, setHistLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // date filter — default to last 7 days
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return toDateInput(d);
  });
  const [dateTo, setDateTo] = useState(() => toDateInput(new Date()));

  // ---- clock status ----
  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get<{ data: TimeEntry | null }>("/timesheets/status");
      setActiveEntry(res.data);
    } catch {
      // ignore — user may not be clocked in
    }
  }, []);

  // ---- history ----
  const fetchHistory = useCallback(async () => {
    setHistLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ page_size: "100" });
      if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
      if (dateTo) {
        const end = new Date(dateTo);
        end.setHours(23, 59, 59, 999);
        params.set("date_to", end.toISOString());
      }
      const res = await api.get<{ data: TimeEntry[] }>(
        `/stores/${STORE_ID}/timesheets?${params}`,
      );
      setEntries(res.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load timesheets");
    } finally {
      setHistLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);
  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // live timer
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (activeEntry) {
      setTimerStr(elapsed(activeEntry.clock_in));
      timerRef.current = setInterval(() => {
        setTimerStr(elapsed(activeEntry.clock_in));
      }, 1000);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [activeEntry]);

  // ---- actions ----
  const handleClockIn = async () => {
    setClockLoading(true);
    try {
      const res = await api.post<{ data: TimeEntry }>("/timesheets/clock-in", {
        store_id: STORE_ID,
      });
      setActiveEntry(res.data);
      fetchHistory();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Clock-in failed");
    } finally {
      setClockLoading(false);
    }
  };

  const handleClockOut = async () => {
    setClockLoading(true);
    try {
      await api.post<{ data: TimeEntry }>("/timesheets/clock-out", {
        break_minutes: 0,
      });
      setActiveEntry(null);
      fetchHistory();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Clock-out failed");
    } finally {
      setClockLoading(false);
    }
  };

  // ---- derived ----
  const weeklyHours = entries
    .filter((e) => e.hours_worked != null)
    .reduce((sum, e) => sum + (e.hours_worked ?? 0), 0);

  return (
    <div>
      <h1 className="text-xl font-bold text-gray-800">Timesheet</h1>
      <p className="mt-1 text-sm text-gray-500">Clock in/out and review your hours</p>

      {/* Clock In / Out Card */}
      <div className="mt-4 rounded-lg bg-white p-5 shadow-sm">
        {activeEntry ? (
          <div className="text-center">
            <p className="text-sm text-gray-500">
              Clocked in at{" "}
              <span className="font-semibold text-gray-800">
                {fmtTime(activeEntry.clock_in)}
              </span>
            </p>
            <p className="mt-2 font-mono text-3xl font-bold text-blue-700">
              {timerStr}
            </p>
            <button
              onClick={handleClockOut}
              disabled={clockLoading}
              className="mt-4 w-full rounded-xl bg-red-600 px-6 py-3 text-sm font-bold text-white shadow-sm hover:bg-red-700 disabled:opacity-50 sm:w-auto"
            >
              {clockLoading ? "Clocking out…" : "🛑 Clock Out"}
            </button>
          </div>
        ) : (
          <div className="text-center">
            <p className="text-sm text-gray-500">You are not clocked in</p>
            <button
              onClick={handleClockIn}
              disabled={clockLoading}
              className="mt-4 w-full rounded-xl bg-green-600 px-6 py-3 text-sm font-bold text-white shadow-sm hover:bg-green-700 disabled:opacity-50 sm:w-auto"
            >
              {clockLoading ? "Clocking in…" : "▶ Clock In"}
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}

      {/* Weekly summary */}
      <div className="mt-4 rounded-lg bg-blue-50 px-4 py-3">
        <p className="text-xs font-medium uppercase text-blue-500">Period Total</p>
        <p className="text-lg font-bold text-blue-800">{weeklyHours.toFixed(1)} hours</p>
        <p className="text-xs text-blue-500">{entries.length} entries</p>
      </div>

      {/* Date filters */}
      <div className="mt-4 flex flex-wrap items-end gap-3 rounded-lg bg-white px-4 py-3 shadow-sm">
        <div className="flex-1 min-w-[120px]">
          <label className="block text-xs font-medium text-gray-500">From</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div className="flex-1 min-w-[120px]">
          <label className="block text-xs font-medium text-gray-500">To</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      {/* History table */}
      {histLoading ? (
        <div className="mt-6 text-center text-sm text-gray-400">Loading history…</div>
      ) : entries.length === 0 ? (
        <div className="mt-6 text-center text-sm text-gray-400">
          No timesheet entries for this period
        </div>
      ) : (
        <>
          {/* Mobile cards */}
          <div className="mt-4 space-y-2 md:hidden">
            {entries.map((e) => (
              <div key={e.id} className="rounded-lg border border-gray-200 bg-white p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-gray-800">
                    {fmtDate(e.clock_in)}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${statusBadge(e.status)}`}
                  >
                    {e.status}
                  </span>
                </div>
                <div className="mt-1 flex gap-4 text-xs text-gray-500">
                  <span>In: {fmtTime(e.clock_in)}</span>
                  <span>Out: {e.clock_out ? fmtTime(e.clock_out) : "—"}</span>
                </div>
                <p className="mt-1 text-sm font-semibold text-gray-700">
                  {e.hours_worked != null ? `${e.hours_worked.toFixed(1)}h` : "—"}
                </p>
              </div>
            ))}
          </div>

          {/* Desktop table */}
          <div className="mt-4 hidden overflow-x-auto rounded-lg border border-gray-200 bg-white md:block">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
                  <th className="px-4 py-2">Date</th>
                  <th className="px-4 py-2">Clock In</th>
                  <th className="px-4 py-2">Clock Out</th>
                  <th className="px-4 py-2">Hours</th>
                  <th className="px-4 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id} className="border-b border-gray-100 last:border-0">
                    <td className="px-4 py-2 font-medium text-gray-800">
                      {fmtDate(e.clock_in)}
                    </td>
                    <td className="px-4 py-2 text-gray-600">{fmtTime(e.clock_in)}</td>
                    <td className="px-4 py-2 text-gray-600">
                      {e.clock_out ? fmtTime(e.clock_out) : "—"}
                    </td>
                    <td className="px-4 py-2 font-semibold text-gray-700">
                      {e.hours_worked != null ? `${e.hours_worked.toFixed(1)}` : "—"}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${statusBadge(e.status)}`}
                      >
                        {e.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
