//
//  Payroll.swift
//  retailmanagement
//

import Foundation

nonisolated struct PaySlip: Codable, Identifiable, Sendable {
    let id: String
    let payrollRunId: String
    let userId: String
    let basicSalary: Double
    let hoursWorked: Double?
    let overtimeHours: Double
    let overtimePay: Double
    let allowances: Double
    let deductions: Double
    let commissionSales: Double
    let commissionAmount: Double
    let grossPay: Double
    let cpfEmployee: Double
    let cpfEmployer: Double
    let netPay: Double
    let notes: String?
    let createdAt: String?
    let updatedAt: String?
}

nonisolated struct PayrollRunSummary: Codable, Identifiable, Sendable {
    let id: String
    let storeId: String
    let periodStart: String
    let periodEnd: String
    let status: String
    let createdBy: String
    let totalGross: Double
    let totalCpfEmployee: Double
    let totalCpfEmployer: Double
    let totalNet: Double
    let createdAt: String?
    let updatedAt: String?

    /// Formatted period label
    var periodLabel: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        guard let start = formatter.date(from: periodStart),
              let end = formatter.date(from: periodEnd) else {
            return "\(periodStart) – \(periodEnd)"
        }
        let display = DateFormatter()
        display.dateFormat = "d MMM"
        let yearFmt = DateFormatter()
        yearFmt.dateFormat = "d MMM yyyy"
        return "\(display.string(from: start)) – \(yearFmt.string(from: end))"
    }
}

nonisolated struct PayrollRunRead: Codable, Identifiable, Sendable {
    let id: String
    let storeId: String
    let periodStart: String
    let periodEnd: String
    let status: String
    let createdBy: String
    let approvedBy: String?
    let totalGross: Double
    let totalCpfEmployee: Double
    let totalCpfEmployer: Double
    let totalNet: Double
    let payslips: [PaySlip]
    let createdAt: String?
    let updatedAt: String?
}

nonisolated struct EmployeeProfile: Codable, Identifiable, Sendable {
    let id: String
    let userId: String
    let dateOfBirth: String
    let nationality: String
    let basicSalary: Double
    let hourlyRate: Double?
    let commissionRate: Double?
    let bankAccount: String?
    let bankName: String
    let cpfAccountNumber: String?
    let startDate: String
    let endDate: String?
    let isActive: Bool
    let createdAt: String?
    let updatedAt: String?
}
