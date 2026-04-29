import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../lib/api";
import { Icon } from "../components/Icon";

// ---- helpers ----

interface Shift {
  id: string;
  schedule_id: string;
  user_id: string;
  shift_date: string; // "YYYY-MM-DD"
  start_time: string; // "HH:MM:SS"
  end_time: string;
  break_minutes: number;
  notes: string | null;
  hours: number;
}

function startOfWeek(d: Date): Date {
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1); // Monday
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

function fmtDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function fmtTime(t: string): string {
  // "HH:MM:SS" → "HH:MM AM/PM"
  const [h, m] = t.split(":").map(Number);
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  return `${h12}:${String(m).padStart(2, "0")} ${ampm}`;
}

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// ---- component ----

export default function SchedulePage() {
  const { selectedStore, loading: authLoading } = useAuth();
  const storeId = selectedStore?.id ?? null;
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchShifts = useCallback(async () => {
    if (!storeId) {
      setShifts([]);
      setLoading(false);
      setError(authLoading ? null : "No store selected");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const from = fmtDate(weekStart);
      const to = fmtDate(addDays(weekStart, 6));
      const res = await api.get<{ data: Shift[] }>(
        `/stores/${storeId}/schedules/my-shifts?from=${from}&to=${to}`,
      );
      setShifts(res.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load shifts");
    } finally {
      setLoading(false);
    }
  }, [authLoading, storeId, weekStart]);

  useEffect(() => {
    if (authLoading) return;
    void fetchShifts();
  }, [authLoading, fetchShifts]);

  const today = fmtDate(new Date());

  // group shifts by date
  const shiftsByDate = new Map<string, Shift[]>();
  for (const s of shifts) {
    const arr = shiftsByDate.get(s.shift_date) ?? [];
    arr.push(s);
    shiftsByDate.set(s.shift_date, arr);
  }

  const weekLabel = `${addDays(weekStart, 0).toLocaleDateString("en-SG", { month: "short", day: "numeric" })} – ${addDays(weekStart, 6).toLocaleDateString("en-SG", { month: "short", day: "numeric", year: "numeric" })}`;

  return (
    <div>
      <h1 className="text-xl font-bold text-gray-800">Schedule</h1>
      <p className="mt-1 text-sm text-gray-500">Your weekly shifts</p>

      {/* Week navigation */}
      <div className="mt-4 flex items-center justify-between rounded-lg bg-white px-4 py-3 shadow-sm">
        <button
          onClick={() => setWeekStart(addDays(weekStart, -7))}
          className="rounded-md p-2 text-gray-600 hover:bg-gray-100"
          aria-label="Previous week"
        >
          <Icon name="chevron-left" className="h-5 w-5" />
        </button>
        <div className="text-center">
          <p className="text-sm font-semibold text-gray-800">{weekLabel}</p>
          <button
            onClick={() => setWeekStart(startOfWeek(new Date()))}
            className="mt-0.5 text-xs text-blue-600 hover:underline"
          >
            Today
          </button>
        </div>
        <button
          onClick={() => setWeekStart(addDays(weekStart, 7))}
          className="rounded-md p-2 text-gray-600 hover:bg-gray-100"
          aria-label="Next week"
        >
          <Icon name="chevron-right" className="h-5 w-5" />
        </button>
      </div>

      {/* Loading / Error */}
      {loading && (
        <div className="mt-6 text-center text-sm text-gray-400">Loading shifts…</div>
      )}
      {error && (
        <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}

      {/* Week grid */}
      {!loading && (
        <div className="mt-4 space-y-2">
          {Array.from({ length: 7 }, (_, i) => {
            const dayDate = addDays(weekStart, i);
            const dateStr = fmtDate(dayDate);
            const isToday = dateStr === today;
            const dayShifts = shiftsByDate.get(dateStr) ?? [];

            return (
              <div
                key={dateStr}
                className={`rounded-lg border bg-white p-3 transition-colors ${
                  isToday
                    ? "border-blue-400 bg-blue-50 ring-1 ring-blue-200"
                    : "border-gray-200"
                }`}
              >
                {/* Day header */}
                <div className="flex items-center gap-2">
                  <span
                    className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold ${
                      isToday
                        ? "bg-blue-600 text-white"
                        : "bg-gray-100 text-gray-700"
                    }`}
                  >
                    {dayDate.getDate()}
                  </span>
                  <span className={`text-sm font-medium ${isToday ? "text-blue-700" : "text-gray-600"}`}>
                    {DAY_LABELS[i]}
                  </span>
                  {isToday && (
                    <span className="ml-1 rounded-full bg-blue-600 px-2 py-0.5 text-[10px] font-semibold uppercase text-white">
                      Today
                    </span>
                  )}
                </div>

                {/* Shifts */}
                {dayShifts.length === 0 ? (
                  <p className="mt-2 text-xs text-gray-400 italic">No shifts</p>
                ) : (
                  <div className="mt-2 space-y-2">
                    {dayShifts.map((shift) => (
                      <div
                        key={shift.id}
                        className="flex items-start justify-between rounded-md bg-gray-50 px-3 py-2"
                      >
                        <div>
                          <p className="text-sm font-semibold text-gray-800">
                            {fmtTime(shift.start_time)} – {fmtTime(shift.end_time)}
                          </p>
                          <p className="mt-0.5 text-xs text-gray-500">
                            {shift.hours}h ({shift.break_minutes}min break)
                          </p>
                          {shift.notes && (
                            <p className="mt-1 text-xs text-gray-500">{shift.notes}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
