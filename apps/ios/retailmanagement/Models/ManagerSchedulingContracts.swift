//
//  ManagerSchedulingContracts.swift
//  retailmanagement
//

import Foundation

// MARK: - Schedule write bodies

nonisolated struct ScheduleCreate: Encodable, Sendable {
    let storeId: String
    let weekStart: String
}

nonisolated struct ScheduleUpdate: Encodable, Sendable {
    let status: String
}

// MARK: - Shift write bodies

nonisolated struct ShiftCreate: Encodable, Sendable {
    let userId: String
    let shiftDate: String
    let startTime: String
    let endTime: String
    let breakMinutes: Int
    let notes: String?
}

nonisolated struct ShiftUpdate: Encodable, Sendable {
    let startTime: String?
    let endTime: String?
    let breakMinutes: Int?
    let notes: String?
}

// MARK: - Timesheet write bodies

nonisolated struct TimeEntryUpdate: Encodable, Sendable {
    let status: String
}

// MARK: - Payroll summary

nonisolated struct TimesheetSummaryEntry: Codable, Identifiable, Sendable {
    let userId: String
    let fullName: String
    let totalHours: Double
    let totalDays: Int
    let entries: [TimeEntry]

    var id: String { userId }
}

nonisolated struct TimesheetSummaryResponse: Codable, Sendable {
    let periodStart: String
    let periodEnd: String
    let summaries: [TimesheetSummaryEntry]
}
