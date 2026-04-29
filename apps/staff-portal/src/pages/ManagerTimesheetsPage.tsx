import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../lib/api";
import { Icon } from "../components/Icon";
import type { TimeEntryRead, TimesheetSummaryResponse } from "../lib/scheduling-contracts";

function fmtDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function endOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0);
}

export default function ManagerTimesheetsPage() {
  const { selectedStore, loading: authLoading } = useAuth();
  const storeId = selectedStore?.id ?? null;

  const [activeTab, setActiveTab] = useState<"pending" | "summary">("pending");
  
  // Pending Tab State
  const [pendingEntries, setPendingEntries] = useState<TimeEntryRead[]>([]);
  const [pendingLoading, setPendingLoading] = useState(false);
  
  // Summary Tab State
  const [periodStart, setPeriodStart] = useState(() => startOfMonth(new Date()));
  const [periodEnd, setPeriodEnd] = useState(() => endOfMonth(new Date()));
  const [summary, setSummary] = useState<TimesheetSummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPending = useCallback(async () => {
    if (!storeId) return;
    setPendingLoading(true);
    try {
      const res = await api.get<{ data: TimeEntryRead[] }>(
        `/stores/${storeId}/timesheets?status=pending&page_size=100`
      );
      // Filter out those still clocked in
      const closedOnly = res.data.filter(e => e.clock_out !== null);
      setPendingEntries(closedOnly);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load pending timesheets");
    } finally {
      setPendingLoading(false);
    }
  }, [storeId]);

  const loadSummary = useCallback(async () => {
    if (!storeId) return;
    setSummaryLoading(true);
    try {
      const startIso = periodStart.toISOString();
      const endIso = periodEnd.toISOString();
      const res = await api.get<{ data: TimesheetSummaryResponse }>(
        `/stores/${storeId}/timesheets/summary?date_from=${startIso}&date_to=${endIso}`
      );
      setSummary(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary");
    } finally {
      setSummaryLoading(false);
    }
  }, [storeId, periodStart, periodEnd]);

  useEffect(() => {
    if (authLoading || !storeId) return;
    if (activeTab === "pending") void loadPending();
    else void loadSummary();
  }, [authLoading, storeId, activeTab, loadPending, loadSummary]);

  const handleUpdateStatus = async (entryId: string, status: "approved" | "rejected") => {
    if (!storeId) return;
    setActionLoading(true);
    try {
      await api.patch(`/stores/${storeId}/timesheets/${entryId}`, { status });
      await loadPending();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to update status");
    } finally {
      setActionLoading(false);
    }
  };

  const formatDateTime = (iso: string) => {
    return new Date(iso).toLocaleString("en-SG", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
    });
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Timesheet Approvals</h1>
          <p className="mt-1 text-sm text-gray-500">Review staff timesheets and prepare for payroll.</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="mt-6 border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab("pending")}
            className={`whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === "pending"
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
            }`}
          >
            Pending Reviews
            {pendingEntries.length > 0 && (
              <span className="ml-2 rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-600">
                {pendingEntries.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab("summary")}
            className={`whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === "summary"
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
            }`}
          >
            Payroll Summary
          </button>
        </nav>
      </div>

      {error && (
        <div className="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-700 shadow-sm border border-red-100">{error}</div>
      )}

      {/* Pending Tab Content */}
      {activeTab === "pending" && (
        <div className="mt-6">
          {pendingLoading ? (
            <div className="flex justify-center py-12">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600"></div>
            </div>
          ) : pendingEntries.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-gray-200 bg-white/50 p-12 text-center">
              <div className="rounded-full bg-green-50 p-4">
                <Icon name="check-circle" className="h-8 w-8 text-green-600" />
              </div>
              <h3 className="mt-4 text-lg font-semibold text-gray-900">All caught up!</h3>
              <p className="mt-2 text-sm text-gray-500 max-w-md">
                There are no pending timesheets awaiting your approval.
              </p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {pendingEntries.map(entry => (
                <div key={entry.id} className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden flex flex-col transition-all hover:shadow-md">
                  <div className="p-5 flex-1">
                    <div className="flex items-center justify-between mb-4">
                      <div className="text-sm font-semibold text-gray-900 truncate">User ID: {entry.user_id.slice(0, 8)}...</div>
                      <span className="inline-flex items-center rounded-md bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700 ring-1 ring-inset ring-amber-600/20">
                        Pending
                      </span>
                    </div>
                    
                    <div className="space-y-3">
                      <div>
                        <div className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Clock In</div>
                        <div className="mt-1 text-sm text-gray-900">{formatDateTime(entry.clock_in)}</div>
                      </div>
                      <div>
                        <div className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Clock Out</div>
                        <div className="mt-1 text-sm text-gray-900">{entry.clock_out ? formatDateTime(entry.clock_out) : "Active"}</div>
                      </div>
                    </div>

                    <div className="mt-4 grid grid-cols-2 gap-4 border-t border-gray-100 pt-4">
                      <div>
                        <div className="text-xs text-gray-500">Duration</div>
                        <div className="mt-0.5 text-sm font-semibold text-gray-900">{entry.hours_worked ? `${entry.hours_worked.toFixed(2)} hrs` : "-"}</div>
                      </div>
                      <div>
                        <div className="text-xs text-gray-500">Break</div>
                        <div className="mt-0.5 text-sm font-medium text-gray-900">{entry.break_minutes} min</div>
                      </div>
                    </div>
                    {entry.notes && (
                      <div className="mt-3 text-sm text-gray-600 bg-gray-50 p-2 rounded border border-gray-100 italic">
                        "{entry.notes}"
                      </div>
                    )}
                  </div>
                  <div className="flex border-t border-gray-200 bg-gray-50">
                    <button
                      onClick={() => handleUpdateStatus(entry.id, "rejected")}
                      disabled={actionLoading}
                      className="flex-1 py-3 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 disabled:opacity-50 transition-colors border-r border-gray-200"
                    >
                      Reject
                    </button>
                    <button
                      onClick={() => handleUpdateStatus(entry.id, "approved")}
                      disabled={actionLoading}
                      className="flex-1 py-3 text-sm font-semibold text-blue-600 hover:text-blue-700 hover:bg-blue-50 disabled:opacity-50 transition-colors"
                    >
                      Approve
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Summary Tab Content */}
      {activeTab === "summary" && (
        <div className="mt-6">
          <div className="flex items-center gap-4 mb-6 bg-white p-4 rounded-xl border border-gray-200 shadow-sm">
            <div>
              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Period Start</label>
              <input
                type="date"
                value={fmtDate(periodStart)}
                onChange={(e) => setPeriodStart(new Date(e.target.value))}
                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Period End</label>
              <input
                type="date"
                value={fmtDate(periodEnd)}
                onChange={(e) => setPeriodEnd(new Date(e.target.value))}
                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              />
            </div>
            <div className="self-end pb-[1px]">
              <button
                onClick={loadSummary}
                className="rounded-md bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50"
              >
                Apply Range
              </button>
            </div>
          </div>

          {summaryLoading ? (
             <div className="flex justify-center py-12">
               <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600"></div>
             </div>
          ) : !summary || summary.summaries.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-gray-200 bg-white/50 p-12 text-center">
              <div className="rounded-full bg-gray-50 p-4">
                <Icon name="document-text" className="h-8 w-8 text-gray-400" />
              </div>
              <h3 className="mt-4 text-lg font-semibold text-gray-900">No data available</h3>
              <p className="mt-2 text-sm text-gray-500 max-w-md">
                No timesheets were recorded in the selected period.
              </p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="py-3 pl-4 pr-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 sm:pl-6">
                      Employee
                    </th>
                    <th className="px-3 py-3 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Days Worked
                    </th>
                    <th className="px-3 py-3 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Total Hours
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {summary.summaries.map((s) => (
                    <tr key={s.user_id} className="hover:bg-gray-50 transition-colors">
                      <td className="whitespace-nowrap py-4 pl-4 pr-3 text-sm font-medium text-gray-900 sm:pl-6">
                        {s.full_name}
                      </td>
                      <td className="whitespace-nowrap px-3 py-4 text-right text-sm text-gray-500">
                        {s.total_days}
                      </td>
                      <td className="whitespace-nowrap px-3 py-4 text-right text-sm font-semibold text-gray-900">
                        {s.total_hours.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                  <tr className="bg-gray-50 border-t-2 border-gray-200">
                    <td className="whitespace-nowrap py-4 pl-4 pr-3 text-sm font-bold text-gray-900 sm:pl-6">
                      Total
                    </td>
                    <td className="whitespace-nowrap px-3 py-4 text-right text-sm font-bold text-gray-900">
                      {summary.summaries.reduce((acc, s) => acc + s.total_days, 0)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-4 text-right text-sm font-bold text-blue-600">
                      {summary.summaries.reduce((acc, s) => acc + s.total_hours, 0).toFixed(2)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
