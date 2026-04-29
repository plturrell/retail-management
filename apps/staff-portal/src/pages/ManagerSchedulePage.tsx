import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../lib/api";
import { Icon } from "../components/Icon";
import type {
  ScheduleRead,
  ShiftCreate,
  ShiftRead,
  ShiftUpdate,
  StoreEmployeeRead,
  WeeklyScheduleResponse,
} from "../lib/scheduling-contracts";

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

function fmtDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function fmtTime(t: string): string {
  const [h, m] = t.split(":").map(Number);
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  return `${h12}:${String(m).padStart(2, "0")} ${ampm}`;
}

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function ManagerSchedulePage() {
  const { selectedStore, loading: authLoading } = useAuth();
  const storeId = selectedStore?.id ?? null;

  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const [schedule, setSchedule] = useState<ScheduleRead | null>(null);
  const [shifts, setShifts] = useState<ShiftRead[]>([]);
  const [employees, setEmployees] = useState<StoreEmployeeRead[]>([]);
  
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedCell, setSelectedCell] = useState<{ userId: string; date: string } | null>(null);
  const [selectedShift, setSelectedShift] = useState<ShiftRead | null>(null);
  const [showShiftModal, setShowShiftModal] = useState(false);

  const loadScheduleData = useCallback(async () => {
    if (!storeId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // 1. Load employees
      const empRes = await api.get<{ data: StoreEmployeeRead[] }>(`/users/stores/${storeId}/employees?page_size=100`);
      setEmployees(empRes.data);

      // 2. Load schedule for the week
      const ws = fmtDate(weekStart);
      const listRes = await api.get<{ data: ScheduleRead[] }>(`/stores/${storeId}/schedules?week_start=${ws}`);
      const sched = listRes.data[0];

      if (sched) {
        // Fetch detailed schedule to get all shifts
        const detailRes = await api.get<{ data: WeeklyScheduleResponse }>(`/stores/${storeId}/schedules/${sched.id}`);
        setSchedule(detailRes.data.schedule);
        setShifts(detailRes.data.schedule.shifts);
      } else {
        setSchedule(null);
        setShifts([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load schedule");
    } finally {
      setLoading(false);
    }
  }, [storeId, weekStart]);

  useEffect(() => {
    if (authLoading) return;
    void loadScheduleData();
  }, [authLoading, loadScheduleData]);

  const handleInitializeSchedule = async () => {
    if (!storeId) return;
    setActionLoading(true);
    try {
      await api.post(`/stores/${storeId}/schedules`, {
        store_id: storeId,
        week_start: fmtDate(weekStart),
      });
      await loadScheduleData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to initialize schedule");
    } finally {
      setActionLoading(false);
    }
  };

  const handlePublishToggle = async () => {
    if (!storeId || !schedule) return;
    setActionLoading(true);
    try {
      const newStatus = schedule.status === "draft" ? "published" : "draft";
      await api.patch(`/stores/${storeId}/schedules/${schedule.id}`, { status: newStatus });
      await loadScheduleData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change publish status");
    } finally {
      setActionLoading(false);
    }
  };

  const openNewShiftModal = (userId: string, date: string) => {
    setSelectedShift(null);
    setSelectedCell({ userId, date });
    setShowShiftModal(true);
  };

  const openEditShiftModal = (shift: ShiftRead) => {
    setSelectedShift(shift);
    setSelectedCell({ userId: shift.user_id, date: shift.shift_date });
    setShowShiftModal(true);
  };

  const closeShiftModal = () => {
    setShowShiftModal(false);
    setSelectedShift(null);
    setSelectedCell(null);
  };

  const handleSaveShift = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!storeId || !schedule || !selectedCell) return;
    setActionLoading(true);

    const fd = new FormData(e.currentTarget);
    const start_time = fd.get("start_time") as string;
    const end_time = fd.get("end_time") as string;
    const break_minutes = parseInt(fd.get("break_minutes") as string, 10) || 0;
    const notes = fd.get("notes") as string;

    try {
      if (selectedShift) {
        await api.patch(`/stores/${storeId}/schedules/${schedule.id}/shifts/${selectedShift.id}`, {
          start_time: start_time + ":00",
          end_time: end_time + ":00",
          break_minutes,
          notes: notes || null,
        } as ShiftUpdate);
      } else {
        await api.post(`/stores/${storeId}/schedules/${schedule.id}/shifts`, {
          user_id: selectedCell.userId,
          shift_date: selectedCell.date,
          start_time: start_time + ":00",
          end_time: end_time + ":00",
          break_minutes,
          notes: notes || null,
        } as ShiftCreate);
      }
      closeShiftModal();
      await loadScheduleData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to save shift");
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteShift = async () => {
    if (!storeId || !schedule || !selectedShift) return;
    if (!window.confirm("Are you sure you want to delete this shift?")) return;
    
    setActionLoading(true);
    try {
      await api.delete(`/stores/${storeId}/schedules/${schedule.id}/shifts/${selectedShift.id}`);
      closeShiftModal();
      await loadScheduleData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete shift");
    } finally {
      setActionLoading(false);
    }
  };

  const weekLabel = `${addDays(weekStart, 0).toLocaleDateString("en-SG", { month: "short", day: "numeric" })} – ${addDays(weekStart, 6).toLocaleDateString("en-SG", { month: "short", day: "numeric", year: "numeric" })}`;

  return (
    <div className="flex flex-col h-[calc(100vh-2rem)]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Manager Scheduling</h1>
          <p className="mt-1 text-sm text-gray-500">Plan shifts and publish weekly schedules.</p>
        </div>
        {schedule && (
          <button
            onClick={handlePublishToggle}
            disabled={actionLoading}
            className={`px-4 py-2 rounded-lg text-sm font-semibold shadow-sm transition-colors ${
              schedule.status === "published"
                ? "bg-amber-100 text-amber-800 hover:bg-amber-200"
                : "bg-blue-600 text-white hover:bg-blue-700"
            }`}
          >
            {schedule.status === "published" ? "Revert to Draft" : "Publish Schedule"}
          </button>
        )}
      </div>

      {/* Controls */}
      <div className="mt-6 flex items-center justify-between rounded-xl bg-white/50 backdrop-blur-md px-5 py-3 shadow-sm border border-gray-100">
        <button
          onClick={() => setWeekStart(addDays(weekStart, -7))}
          className="rounded-lg p-2 text-gray-600 hover:bg-white hover:shadow-sm"
        >
          <Icon name="chevron-left" className="h-5 w-5" />
        </button>
        <div className="text-center">
          <p className="text-base font-semibold text-gray-800">{weekLabel}</p>
          <button
            onClick={() => setWeekStart(startOfWeek(new Date()))}
            className="mt-0.5 text-xs text-blue-600 hover:underline"
          >
            Go to Current Week
          </button>
        </div>
        <button
          onClick={() => setWeekStart(addDays(weekStart, 7))}
          className="rounded-lg p-2 text-gray-600 hover:bg-white hover:shadow-sm"
        >
          <Icon name="chevron-right" className="h-5 w-5" />
        </button>
      </div>

      {/* Main Content */}
      {loading ? (
        <div className="mt-12 flex justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600"></div>
        </div>
      ) : error ? (
        <div className="mt-6 rounded-xl bg-red-50 p-4 text-sm text-red-700 shadow-sm border border-red-100">{error}</div>
      ) : !schedule ? (
        <div className="mt-12 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-gray-200 bg-white/50 p-12 text-center">
          <div className="rounded-full bg-blue-50 p-4">
            <Icon name="calendar" className="h-8 w-8 text-blue-600" />
          </div>
          <h3 className="mt-4 text-lg font-semibold text-gray-900">No schedule created</h3>
          <p className="mt-2 text-sm text-gray-500 max-w-md">
            There is no schedule initialized for the week of {fmtDate(weekStart)}. Initialize it to start adding shifts.
          </p>
          <button
            onClick={handleInitializeSchedule}
            disabled={actionLoading}
            className="mt-6 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
          >
            Initialize Schedule
          </button>
        </div>
      ) : (
        <div className="mt-6 flex-1 overflow-auto rounded-xl border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50 sticky top-0 z-10">
              <tr>
                <th className="sticky left-0 bg-gray-50 py-3 pl-4 pr-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 sm:pl-6 w-48 border-b border-r border-gray-200">
                  Employee
                </th>
                {Array.from({ length: 7 }, (_, i) => {
                  const dayDate = addDays(weekStart, i);
                  const dateStr = fmtDate(dayDate);
                  const isToday = dateStr === fmtDate(new Date());
                  return (
                    <th key={dateStr} className={`px-3 py-3 text-center text-xs font-medium uppercase tracking-wide border-b border-gray-200 min-w-[140px] ${isToday ? "text-blue-600 bg-blue-50/50" : "text-gray-500"}`}>
                      {DAY_LABELS[i]}
                      <div className="mt-1 text-base font-semibold">{dayDate.getDate()}</div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {employees.map((emp) => (
                <tr key={emp.id} className="hover:bg-gray-50/50 transition-colors">
                  <td className="sticky left-0 bg-white py-4 pl-4 pr-3 text-sm sm:pl-6 border-r border-gray-200 shadow-[2px_0_5px_-2px_rgba(0,0,0,0.05)]">
                    <div className="font-medium text-gray-900">{emp.full_name}</div>
                    <div className="text-gray-500 text-xs capitalize">{emp.role}</div>
                  </td>
                  {Array.from({ length: 7 }, (_, i) => {
                    const dateStr = fmtDate(addDays(weekStart, i));
                    const shift = shifts.find(s => s.user_id === emp.id && s.shift_date === dateStr);
                    return (
                      <td key={dateStr} className="p-2 text-sm">
                        {shift ? (
                          <button
                            onClick={() => openEditShiftModal(shift)}
                            className={`w-full text-left rounded-lg p-2 transition-all ${
                              schedule.status === "draft"
                                ? "bg-amber-50 border border-amber-200 text-amber-900 hover:bg-amber-100"
                                : "bg-blue-50 border border-blue-200 text-blue-900 hover:bg-blue-100"
                            }`}
                          >
                            <div className="font-semibold">{fmtTime(shift.start_time).replace(":00 ", "")} - {fmtTime(shift.end_time).replace(":00 ", "")}</div>
                            <div className="text-xs opacity-75">{shift.hours}h ({shift.break_minutes}m break)</div>
                            {shift.notes && <div className="mt-1 text-xs italic truncate">{shift.notes}</div>}
                          </button>
                        ) : (
                          <button
                            onClick={() => openNewShiftModal(emp.id, dateStr)}
                            className="w-full h-14 rounded-lg border-2 border-dashed border-gray-200 bg-transparent hover:border-blue-400 hover:bg-blue-50 flex items-center justify-center transition-colors text-gray-400 hover:text-blue-600"
                          >
                            <Icon name="plus" className="h-5 w-5" />
                          </button>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Shift Modal */}
      {showShiftModal && selectedCell && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl bg-white shadow-xl overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center bg-gray-50">
              <h3 className="text-lg font-semibold text-gray-900">
                {selectedShift ? "Edit Shift" : "Add Shift"}
              </h3>
              <button onClick={closeShiftModal} className="text-gray-400 hover:text-gray-600">
                <Icon name="x" className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleSaveShift} className="px-6 py-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">Date & Employee</label>
                <div className="mt-1 text-sm text-gray-500">
                  {selectedCell.date} • {employees.find(e => e.id === selectedCell.userId)?.full_name}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700">Start Time</label>
                  <input
                    type="time"
                    name="start_time"
                    required
                    defaultValue={selectedShift ? selectedShift.start_time.slice(0, 5) : "10:00"}
                    className="mt-1 block w-full rounded-lg border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">End Time</label>
                  <input
                    type="time"
                    name="end_time"
                    required
                    defaultValue={selectedShift ? selectedShift.end_time.slice(0, 5) : "18:00"}
                    className="mt-1 block w-full rounded-lg border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Break (Minutes)</label>
                <input
                  type="number"
                  name="break_minutes"
                  required
                  min="0"
                  step="15"
                  defaultValue={selectedShift ? selectedShift.break_minutes : 60}
                  className="mt-1 block w-full rounded-lg border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Notes (Optional)</label>
                <input
                  type="text"
                  name="notes"
                  defaultValue={selectedShift?.notes || ""}
                  className="mt-1 block w-full rounded-lg border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  placeholder="e.g. Front desk duty"
                />
              </div>
              <div className="pt-4 flex items-center justify-between gap-3">
                {selectedShift ? (
                  <button
                    type="button"
                    onClick={handleDeleteShift}
                    disabled={actionLoading}
                    className="text-red-600 hover:text-red-700 text-sm font-medium px-2 py-2"
                  >
                    Delete Shift
                  </button>
                ) : <div />}
                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={closeShiftModal}
                    className="rounded-lg px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={actionLoading}
                    className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
                  >
                    {actionLoading ? "Saving..." : "Save Shift"}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
