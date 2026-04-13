//
//  Schedule.swift
//  retailmanagement
//

import Foundation

nonisolated struct Shift: Codable, Identifiable, Sendable {
    let id: String
    let scheduleId: String
    let userId: String
    let shiftDate: String
    let startTime: String
    let endTime: String
    let breakMinutes: Int
    let notes: String?
    let hours: Double
    let createdAt: String?
    let updatedAt: String?

    /// Formatted time range, e.g. "10:00 - 18:00"
    var timeRange: String {
        let start = String(startTime.prefix(5))
        let end = String(endTime.prefix(5))
        return "\(start) – \(end)"
    }

    /// Parsed shift date
    var date: Date? {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: shiftDate)
    }
}

nonisolated struct ScheduleRead: Codable, Identifiable, Sendable {
    let id: String
    let storeId: String
    let weekStart: String
    let status: String
    let createdBy: String
    let publishedAt: String?
    let shifts: [Shift]
    let createdAt: String?
    let updatedAt: String?
}

nonisolated struct DayShifts: Codable, Sendable {
    let date: String
    let shifts: [Shift]
}

nonisolated struct WeeklyScheduleResponse: Codable, Sendable {
    let schedule: ScheduleRead
    let days: [DayShifts]
}
