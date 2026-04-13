//
//  Timesheet.swift
//  retailmanagement
//

import Foundation

// MARK: - Request Bodies

nonisolated struct ClockInRequest: Encodable, Sendable {
    let storeId: String
    let notes: String?
}

nonisolated struct ClockOutRequest: Encodable, Sendable {
    let breakMinutes: Int
    let notes: String?
}

// MARK: - Time Entry

nonisolated struct TimeEntry: Codable, Identifiable, Sendable {
    let id: String
    let userId: String
    let storeId: String
    let clockIn: String
    let clockOut: String?
    let breakMinutes: Int
    let notes: String?
    let status: String
    let approvedBy: String?
    let hoursWorked: Double?
    let createdAt: String?
    let updatedAt: String?

    /// Parsed clock-in date
    var clockInDate: Date? {
        ISO8601DateFormatter().date(from: clockIn)
    }

    /// Parsed clock-out date
    var clockOutDate: Date? {
        guard let clockOut else { return nil }
        return ISO8601DateFormatter().date(from: clockOut)
    }

    /// Formatted clock-in time
    var clockInTime: String {
        guard let date = clockInDate else { return clockIn }
        let formatter = DateFormatter()
        formatter.dateStyle = .none
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }

    /// Formatted clock-out time
    var clockOutTime: String? {
        guard let date = clockOutDate else { return nil }
        let formatter = DateFormatter()
        formatter.dateStyle = .none
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }

    /// Formatted date
    var formattedDate: String {
        guard let date = clockInDate else { return clockIn }
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .none
        return formatter.string(from: date)
    }

    /// Whether this entry is currently active (clocked in, not out)
    var isActive: Bool { clockOut == nil }
}
