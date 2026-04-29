//
//  ManagerTimesheetsViewModel.swift
//  retailmanagement
//

import Foundation
import Observation

@MainActor
@Observable
final class ManagerTimesheetsViewModel {
    var pendingEntries: [TimeEntry] = []
    var summary: TimesheetSummaryResponse?
    var isLoading = false
    var isActionLoading = false
    var summaryLoading = false
    var errorMessage: String?

    var periodStart: Date
    var periodEnd: Date

    init() {
        let cal = Calendar.current
        let now = Date()
        let comps = cal.dateComponents([.year, .month], from: now)
        let start = cal.date(from: comps) ?? now
        let nextMonth = cal.date(byAdding: .month, value: 1, to: start) ?? now
        let end = cal.date(byAdding: .second, value: -1, to: nextMonth) ?? now
        self.periodStart = start
        self.periodEnd = end
    }

    func loadPending(storeId: String) async {
        isLoading = true
        errorMessage = nil
        do {
            let response: PaginatedResponse<TimeEntry> = try await NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/timesheets",
                queryItems: [
                    URLQueryItem(name: "status", value: "pending"),
                    URLQueryItem(name: "page_size", value: "100"),
                ]
            )
            pendingEntries = response.data.filter { $0.clockOut != nil }
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    func loadSummary(storeId: String) async {
        summaryLoading = true
        errorMessage = nil
        let iso = ISO8601DateFormatter()
        do {
            let response: DataResponse<TimesheetSummaryResponse> = try await NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/timesheets/summary",
                queryItems: [
                    URLQueryItem(name: "date_from", value: iso.string(from: periodStart)),
                    URLQueryItem(name: "date_to", value: iso.string(from: periodEnd)),
                ]
            )
            summary = response.data
        } catch {
            errorMessage = error.localizedDescription
        }
        summaryLoading = false
    }

    func updateStatus(storeId: String, entryId: String, status: String) async {
        isActionLoading = true
        do {
            let body = TimeEntryUpdate(status: status)
            let _: DataResponse<TimeEntry> = try await NetworkService.shared.patch(
                endpoint: "/api/stores/\(storeId)/timesheets/\(entryId)", body: body
            )
            await loadPending(storeId: storeId)
        } catch {
            errorMessage = error.localizedDescription
        }
        isActionLoading = false
    }
}
