//
//  ScheduleViewModel.swift
//  retailmanagement
//

import Foundation
import Observation

nonisolated struct ShiftDayGroup: Identifiable, Sendable {
    let date: String
    let shifts: [Shift]

    var id: String { date }
}

@MainActor
@Observable
final class ScheduleViewModel {
    var shifts: [Shift] = []
    var isLoading = false
    var errorMessage: String?

    /// The current week's Monday date
    var weekStart: Date = Calendar.current.dateInterval(of: .weekOfYear, for: Date())?.start ?? Date()

    /// Formatted week label
    var weekLabel: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "d MMM"
        let end = Calendar.current.date(byAdding: .day, value: 6, to: weekStart) ?? weekStart
        let yearFmt = DateFormatter()
        yearFmt.dateFormat = "d MMM yyyy"
        return "\(formatter.string(from: weekStart)) – \(yearFmt.string(from: end))"
    }

    /// Shifts grouped by date
    var shiftsByDate: [ShiftDayGroup] {
        let grouped = Dictionary(grouping: shifts, by: { $0.shiftDate })
        return grouped.sorted { $0.key < $1.key }.map { ShiftDayGroup(date: $0.key, shifts: $0.value) }
    }

    func fetchMyShifts(storeId: String) async {
        isLoading = true
        errorMessage = nil

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let from = formatter.string(from: weekStart)
        let to = formatter.string(from: Calendar.current.date(byAdding: .day, value: 6, to: weekStart) ?? weekStart)

        do {
            let response: DataResponse<[Shift]> = try await NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/schedules/my-shifts",
                queryItems: [
                    URLQueryItem(name: "from", value: from),
                    URLQueryItem(name: "to", value: to),
                ]
            )
            shifts = response.data
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func goToPreviousWeek() {
        weekStart = Calendar.current.date(byAdding: .weekOfYear, value: -1, to: weekStart) ?? weekStart
    }

    func goToNextWeek() {
        weekStart = Calendar.current.date(byAdding: .weekOfYear, value: 1, to: weekStart) ?? weekStart
    }

    func goToCurrentWeek() {
        weekStart = Calendar.current.dateInterval(of: .weekOfYear, for: Date())?.start ?? Date()
    }
}
