import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, CalendarOff, StickyNote } from "lucide-react";
import { api } from "../lib/api";
import { classNames, formatTimeFromHMS } from "../lib/format";
import { PageHeader } from "../components/ui/PageHeader";
import { Card } from "../components/ui/Card";
import { IconButton } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { Badge } from "../components/ui/Badge";

const STORE_ID = import.meta.env.VITE_STORE_ID as string;

interface Shift {
  id: string;
  schedule_id: string;
  user_id: string;
  shift_date: string;
  start_time: string;
  end_time: string;
  break_minutes: number;
  notes: string | null;
  hours: number;
}

function startOfWeek(d: Date): Date {
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  const mon = new Date(d);
  mon.setDate(diff);
  mon.setHours(0, 0, 0, 0);
  return mon;
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function fmtDateKey(d: Date): string {
  return d.toISOString().slice(0, 10);
}

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function SchedulePage() {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchShifts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const from = fmtDateKey(weekStart);
      const to = fmtDateKey(addDays(weekStart, 6));
      const res = await api.get<{ data: Shift[] }>(
        `/stores/${STORE_ID}/schedules/my-shifts?from=${from}&to=${to}`,
      );
      setShifts(res.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load shifts");
    } finally {
      setLoading(false);
    }
  }, [weekStart]);

  useEffect(() => {
    fetchShifts();
  }, [fetchShifts]);

  const today = fmtDateKey(new Date());

  const shiftsByDate = useMemo(() => {
    const map = new Map<string, Shift[]>();
    for (const s of shifts) {
      const arr = map.get(s.shift_date) ?? [];
      arr.push(s);
      map.set(s.shift_date, arr);
    }
    return map;
  }, [shifts]);

  const totalHours = useMemo(
    () => shifts.reduce((sum, s) => sum + (s.hours ?? 0), 0),
    [shifts],
  );

  const weekLabel = `${addDays(weekStart, 0).toLocaleDateString("en-SG", {
    month: "short",
    day: "numeric",
  })} – ${addDays(weekStart, 6).toLocaleDateString("en-SG", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })}`;

  return (
    <div className="space-y-6">
      <PageHeader title="Schedule" description="Your weekly shifts at a glance." />

      {/* Week navigation */}
      <Card padding="sm" className="flex items-center justify-between">
        <IconButton
          label="Previous week"
          onClick={() => setWeekStart(addDays(weekStart, -7))}
        >
          <ChevronLeft size={20} />
        </IconButton>
        <div className="flex flex-col items-center text-center">
          <p className="text-sm font-semibold text-[var(--color-ink-primary)]">{weekLabel}</p>
          <button
            onClick={() => setWeekStart(startOfWeek(new Date()))}
            className="mt-0.5 rounded-md px-2 py-0.5 text-xs font-semibold text-[var(--color-brand-600)] hover:bg-[var(--color-brand-50)]"
          >
            Jump to today
          </button>
        </div>
        <IconButton label="Next week" onClick={() => setWeekStart(addDays(weekStart, 7))}>
          <ChevronRight size={20} />
        </IconButton>
      </Card>

      {/* Week summary */}
      {!loading && !error && (
        <Card padding="md" className="flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
              Week total
            </p>
            <p className="tabular mt-0.5 text-2xl font-bold text-[var(--color-ink-primary)]">
              {totalHours.toFixed(1)}
              <span className="ml-1 text-base font-medium text-[var(--color-ink-muted)]">hrs</span>
            </p>
          </div>
          <Badge tone="brand">{shifts.length} shifts</Badge>
        </Card>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-[var(--color-negative-600)]/15 bg-[var(--color-negative-50)] p-3 text-sm text-[var(--color-negative-700)]">
          {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      )}

      {/* Day cards */}
      {!loading && !error && (
        <div className="space-y-2">
          {Array.from({ length: 7 }, (_, i) => {
            const dayDate = addDays(weekStart, i);
            const dateStr = fmtDateKey(dayDate);
            const isToday = dateStr === today;
            const dayShifts = shiftsByDate.get(dateStr) ?? [];

            return (
              <Card
                key={dateStr}
                padding="md"
                className={classNames(
                  "transition-all duration-200",
                  isToday &&
                    "ring-2 ring-[var(--color-brand-500)]/30 border-[var(--color-brand-500)]/40",
                )}
              >
                <div className="flex items-center gap-3">
                  <div
                    className={classNames(
                      "flex h-10 w-10 flex-col items-center justify-center rounded-xl text-xs font-bold",
                      isToday
                        ? "bg-[var(--color-brand-600)] text-white"
                        : "bg-[var(--color-surface-subtle)] text-[var(--color-ink-secondary)]",
                    )}
                  >
                    <span className="text-[10px] font-medium tracking-wide opacity-80">
                      {DAY_LABELS[i]}
                    </span>
                    <span className="text-base font-bold leading-none">{dayDate.getDate()}</span>
                  </div>
                  <div className="flex-1">
                    {isToday && (
                      <Badge tone="brand" className="mb-0.5">
                        Today
                      </Badge>
                    )}
                  </div>
                </div>

                {dayShifts.length === 0 ? (
                  <p className="mt-2 pl-13 text-xs text-[var(--color-ink-muted)]">No shifts</p>
                ) : (
                  <div className="mt-3 space-y-2">
                    {dayShifts.map((shift) => (
                      <div
                        key={shift.id}
                        className="flex items-start justify-between gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-muted)] px-3 py-2.5"
                      >
                        <div className="min-w-0">
                          <p className="tabular text-sm font-semibold text-[var(--color-ink-primary)]">
                            {formatTimeFromHMS(shift.start_time)} –{" "}
                            {formatTimeFromHMS(shift.end_time)}
                          </p>
                          <p className="mt-0.5 text-xs text-[var(--color-ink-muted)]">
                            {shift.hours.toFixed(1)}h · {shift.break_minutes}m break
                          </p>
                          {shift.notes && (
                            <p className="mt-1.5 flex items-start gap-1.5 text-xs text-[var(--color-ink-secondary)]">
                              <StickyNote
                                size={12}
                                className="mt-0.5 shrink-0 text-[var(--color-ink-muted)]"
                              />
                              <span>{shift.notes}</span>
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            );
          })}

          {shifts.length === 0 && (
            <EmptyState
              icon={<CalendarOff size={20} />}
              title="No shifts this week"
              description="Your schedule for this week hasn't been published yet."
            />
          )}
        </div>
      )}
    </div>
  );
}
