//
//  ManagerScheduleViewModel.swift
//  retailmanagement
//

import Foundation
import Observation

@MainActor
@Observable
final class ManagerScheduleViewModel {
    var schedule: ScheduleRead?
    var shifts: [Shift] = []
    var employees: [Employee] = []
    var isLoading = false
    var isActionLoading = false
    var errorMessage: String?

    var weekStart: Date = Calendar.current.dateInterval(of: .weekOfYear, for: Date())?.start ?? Date()

    var weekLabel: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "d MMM"
        let end = Calendar.current.date(byAdding: .day, value: 6, to: weekStart) ?? weekStart
        let yearFmt = DateFormatter()
        yearFmt.dateFormat = "d MMM yyyy"
        return "\(formatter.string(from: weekStart)) – \(yearFmt.string(from: end))"
    }

    var dayDates: [Date] {
        (0..<7).compactMap { Calendar.current.date(byAdding: .day, value: $0, to: weekStart) }
    }

    private static let isoDateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    func dateString(_ date: Date) -> String {
        Self.isoDateFormatter.string(from: date)
    }

    func shifts(for date: Date) -> [Shift] {
        let key = dateString(date)
        return shifts.filter { $0.shiftDate == key }
    }

    func employee(for userId: String) -> Employee? {
        employees.first { $0.id == userId }
    }

    // MARK: - Week navigation

    func goToPreviousWeek() {
        weekStart = Calendar.current.date(byAdding: .weekOfYear, value: -1, to: weekStart) ?? weekStart
    }

    func goToNextWeek() {
        weekStart = Calendar.current.date(byAdding: .weekOfYear, value: 1, to: weekStart) ?? weekStart
    }

    func goToCurrentWeek() {
        weekStart = Calendar.current.dateInterval(of: .weekOfYear, for: Date())?.start ?? Date()
    }

    // MARK: - Loading

    func loadData(storeId: String) async {
        isLoading = true
        errorMessage = nil
        do {
            async let employeesTask: PaginatedResponse<Employee> = NetworkService.shared.get(
                endpoint: "/api/users/stores/\(storeId)/employees"
            )
            async let schedulesTask: PaginatedResponse<ScheduleRead> = NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/schedules",
                queryItems: [URLQueryItem(name: "week_start", value: dateString(weekStart))]
            )
            let employeesResponse = try await employeesTask
            let schedulesResponse = try await schedulesTask
            employees = employeesResponse.data

            if let first = schedulesResponse.data.first {
                let detail: DataResponse<WeeklyScheduleResponse> = try await NetworkService.shared.get(
                    endpoint: "/api/stores/\(storeId)/schedules/\(first.id)"
                )
                schedule = detail.data.schedule
                shifts = detail.data.schedule.shifts
            } else {
                schedule = nil
                shifts = []
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    // MARK: - Mutations

    func initializeSchedule(storeId: String) async {
        isActionLoading = true
        do {
            let body = ScheduleCreate(storeId: storeId, weekStart: dateString(weekStart))
            let _: DataResponse<ScheduleRead> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/schedules", body: body
            )
            await loadData(storeId: storeId)
        } catch {
            errorMessage = error.localizedDescription
        }
        isActionLoading = false
    }

    func togglePublishStatus(storeId: String) async {
        guard let sched = schedule else { return }
        isActionLoading = true
        do {
            let newStatus = sched.status == "draft" ? "published" : "draft"
            let _: DataResponse<ScheduleRead> = try await NetworkService.shared.patch(
                endpoint: "/api/stores/\(storeId)/schedules/\(sched.id)",
                body: ScheduleUpdate(status: newStatus)
            )
            await loadData(storeId: storeId)
        } catch {
            errorMessage = error.localizedDescription
        }
        isActionLoading = false
    }

    func saveShift(
        storeId: String, shiftId: String?, userId: String, date: String,
        startTime: String, endTime: String, breakMinutes: Int, notes: String?
    ) async {
        guard let sched = schedule else { return }
        isActionLoading = true
        do {
            if let shiftId {
                let body = ShiftUpdate(startTime: startTime, endTime: endTime, breakMinutes: breakMinutes, notes: notes)
                let _: DataResponse<Shift> = try await NetworkService.shared.patch(
                    endpoint: "/api/stores/\(storeId)/schedules/\(sched.id)/shifts/\(shiftId)", body: body
                )
            } else {
                let body = ShiftCreate(userId: userId, shiftDate: date, startTime: startTime, endTime: endTime, breakMinutes: breakMinutes, notes: notes)
                let _: DataResponse<Shift> = try await NetworkService.shared.post(
                    endpoint: "/api/stores/\(storeId)/schedules/\(sched.id)/shifts", body: body
                )
            }
            await loadData(storeId: storeId)
        } catch {
            errorMessage = error.localizedDescription
        }
        isActionLoading = false
    }

    func deleteShift(storeId: String, shiftId: String) async {
        guard let sched = schedule else { return }
        isActionLoading = true
        do {
            try await NetworkService.shared.deleteNoContent(
                endpoint: "/api/stores/\(storeId)/schedules/\(sched.id)/shifts/\(shiftId)"
            )
            await loadData(storeId: storeId)
        } catch {
            errorMessage = error.localizedDescription
        }
        isActionLoading = false
    }
}
