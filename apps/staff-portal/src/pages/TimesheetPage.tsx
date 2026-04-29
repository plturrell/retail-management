import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Square, FileClock } from "lucide-react";
import { api } from "../lib/api";
import { classNames, formatDate, formatTime } from "../lib/format";
import { PageHeader } from "../components/ui/PageHeader";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { useToast } from "../components/ui/Toast";

const STORE_ID = import.meta.env.VITE_STORE_ID as string;

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

function statusTone(status: string): "positive" | "warning" | "negative" | "neutral" {
  if (status === "approved") return "positive";
  if (status === "pending") return "warning";
  if (status === "rejected") return "negative";
  return "neutral";
}

export default function TimesheetPage() {
  const toast = useToast();

  const [activeEntry, setActiveEntry] = useState<TimeEntry | null>(null);
  const [timerStr, setTimerStr] = useState("00:00:00");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [clockLoading, setClockLoading] = useState(false);

  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [histLoading, setHistLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return toDateInput(d);
  });
  const [dateTo, setDateTo] = useState(() => toDateInput(new Date()));

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get<{ data: TimeEntry | null }>("/timesheets/status");
      setActiveEntry(res.data);
    } catch {
      // user may not be clocked in
    }
  }, []);

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

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (activeEntry) {
      setTimerStr(elapsed(activeEntry.clock_in));
      timerRef.current = setInterval(() => {
        setTimerStr(elapsed(activeEntry.clock_in));
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [activeEntry]);

  const handleClockIn = async () => {
    setClockLoading(true);
    try {
      const res = await api.post<{ data: TimeEntry }>("/timesheets/clock-in", {
        store_id: STORE_ID,
      });
      setActiveEntry(res.data);
      fetchHistory();
      toast.show("Clocked in", "success");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Clock-in failed";
      setError(msg);
      toast.show(msg, "error");
    } finally {
      setClockLoading(false);
    }
  };

  const handleClockOut = async () => {
    setClockLoading(true);
    try {
      await api.post<{ data: TimeEntry }>("/timesheets/clock-out", { break_minutes: 0 });
      setActiveEntry(null);
      fetchHistory();
      toast.show("Clocked out", "success");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Clock-out failed";
      setError(msg);
      toast.show(msg, "error");
    } finally {
      setClockLoading(false);
    }
  };

  const periodHours = entries
    .filter((e) => e.hours_worked != null)
    .reduce((sum, e) => sum + (e.hours_worked ?? 0), 0);

  return (
    <div className="space-y-6">
      <PageHeader title="Timesheet" description="Clock in or out and review your hours." />

      {/* Live clock card */}
      <Card padding="lg" elevated className="overflow-hidden">
        {activeEntry ? (
          <div className="flex flex-col items-center text-center">
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--color-positive-600)] opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--color-positive-600)]" />
              </span>
              <p className="text-sm font-medium text-[var(--color-ink-secondary)]">
                Clocked in at{" "}
                <span className="font-semibold text-[var(--color-ink-primary)]">
                  {formatTime(activeEntry.clock_in)}
                </span>
              </p>
            </div>
            <p
              className="tabular mt-3 text-5xl font-bold tracking-tight text-[var(--color-ink-primary)]"
              aria-live="polite"
            >
              {timerStr}
            </p>
            <Button
              variant="danger"
              size="lg"
              onClick={handleClockOut}
              disabled={clockLoading}
              leadingIcon={<Square size={18} fill="currentColor" />}
              className="mt-5 w-full sm:w-auto sm:px-8"
            >
              {clockLoading ? "Clocking out…" : "Clock out"}
            </Button>
          </div>
        ) : (
          <div className="flex flex-col items-center text-center">
            <p className="text-sm font-medium text-[var(--color-ink-muted)]">You're off the clock</p>
            <p className="tabular mt-3 text-5xl font-bold tracking-tight text-[var(--color-ink-disabled)]">
              00:00:00
            </p>
            <Button
              variant="success"
              size="lg"
              onClick={handleClockIn}
              disabled={clockLoading}
              leadingIcon={<Play size={18} fill="currentColor" />}
              className="mt-5 w-full sm:w-auto sm:px-8"
            >
              {clockLoading ? "Clocking in…" : "Clock in"}
            </Button>
          </div>
        )}
      </Card>

      {error && (
        <div className="rounded-xl border border-[var(--color-negative-600)]/15 bg-[var(--color-negative-50)] p-3 text-sm text-[var(--color-negative-700)]">
          {error}
        </div>
      )}

      {/* History */}
      <section>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-[var(--color-ink-primary)]">
              History
            </h2>
            <p className="text-sm text-[var(--color-ink-muted)]">
              {entries.length} {entries.length === 1 ? "entry" : "entries"} ·{" "}
              <span className="tabular font-semibold text-[var(--color-ink-secondary)]">
                {periodHours.toFixed(1)}h
              </span>{" "}
              total
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
                From
              </label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="mt-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm focus:border-[var(--color-brand-500)] focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-500)]/30"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
                To
              </label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="mt-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm focus:border-[var(--color-brand-500)] focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-500)]/30"
              />
            </div>
          </div>
        </div>

        {histLoading ? (
          <div className="mt-4 space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : entries.length === 0 ? (
          <div className="mt-4">
            <EmptyState
              icon={<FileClock size={20} />}
              title="No entries"
              description="No timesheet entries fall within this date range."
            />
          </div>
        ) : (
          <>
            {/* Mobile cards */}
            <div className="mt-4 space-y-2 md:hidden">
              {entries.map((e) => (
                <Card key={e.id} padding="sm">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-[var(--color-ink-primary)]">
                      {formatDate(e.clock_in, { day: "numeric", month: "short", weekday: "short" })}
                    </span>
                    <Badge tone={statusTone(e.status)}>{e.status}</Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <p className="text-[var(--color-ink-muted)]">In</p>
                      <p className="tabular font-semibold text-[var(--color-ink-primary)]">
                        {formatTime(e.clock_in)}
                      </p>
                    </div>
                    <div>
                      <p className="text-[var(--color-ink-muted)]">Out</p>
                      <p className="tabular font-semibold text-[var(--color-ink-primary)]">
                        {e.clock_out ? formatTime(e.clock_out) : "—"}
                      </p>
                    </div>
                    <div>
                      <p className="text-[var(--color-ink-muted)]">Hours</p>
                      <p className="tabular font-semibold text-[var(--color-ink-primary)]">
                        {e.hours_worked != null ? `${e.hours_worked.toFixed(1)}h` : "—"}
                      </p>
                    </div>
                  </div>
                </Card>
              ))}
            </div>

            {/* Desktop table */}
            <Card padding="none" className="mt-4 hidden overflow-hidden md:block">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--color-border)] bg-[var(--color-surface-muted)] text-left text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
                    <th className="px-4 py-3">Date</th>
                    <th className="px-4 py-3">Clock In</th>
                    <th className="px-4 py-3">Clock Out</th>
                    <th className="px-4 py-3">Hours</th>
                    <th className="px-4 py-3">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((e, idx) => (
                    <tr
                      key={e.id}
                      className={classNames(
                        "transition-colors hover:bg-[var(--color-surface-muted)]",
                        idx !== entries.length - 1 && "border-b border-[var(--color-border)]",
                      )}
                    >
                      <td className="px-4 py-3 font-semibold text-[var(--color-ink-primary)]">
                        {formatDate(e.clock_in, { day: "numeric", month: "short" })}
                      </td>
                      <td className="tabular px-4 py-3 text-[var(--color-ink-secondary)]">
                        {formatTime(e.clock_in)}
                      </td>
                      <td className="tabular px-4 py-3 text-[var(--color-ink-secondary)]">
                        {e.clock_out ? formatTime(e.clock_out) : "—"}
                      </td>
                      <td className="tabular px-4 py-3 font-semibold text-[var(--color-ink-primary)]">
                        {e.hours_worked != null ? e.hours_worked.toFixed(1) : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={statusTone(e.status)}>{e.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </>
        )}
      </section>
    </div>
  );
}
