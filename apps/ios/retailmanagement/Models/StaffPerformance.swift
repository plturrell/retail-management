//
//  StaffPerformance.swift
//  retailmanagement
//

import Foundation

// MARK: - Staff Performance Overview

nonisolated struct StaffPerformanceItem: Codable, Identifiable, Sendable {
    let userId: String
    let fullName: String
    let totalSales: Double
    let orderCount: Int
    let avgOrderValue: Double
    let rank: Int

    var id: String { userId }
}

nonisolated struct StaffPerformanceOverview: Codable, Sendable {
    let generatedAt: String
    let storeId: String
    let periodFrom: String
    let periodTo: String
    let staff: [StaffPerformanceItem]
    let totalStoreSales: Double
}

// MARK: - Staff Insights

nonisolated struct StaffInsightsResponse: Codable, Sendable {
    let userId: String
    let fullName: String
    let summary: StaffInsightsSummary
    let aiInsights: String?
}

nonisolated struct StaffInsightsSummary: Codable, Sendable {
    // Dynamic summary dict from backend — use flexible decoding
    let totalSales: Double?
    let orderCount: Int?
    let avgOrderValue: Double?
    let periodDays: Int?

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: DynamicCodingKey.self)
        totalSales = try? container.decode(Double.self, forKey: DynamicCodingKey(stringValue: "totalSales")!)
        orderCount = try? container.decode(Int.self, forKey: DynamicCodingKey(stringValue: "orderCount")!)
        avgOrderValue = try? container.decode(Double.self, forKey: DynamicCodingKey(stringValue: "avgOrderValue")!)
        periodDays = try? container.decode(Int.self, forKey: DynamicCodingKey(stringValue: "periodDays")!)
    }
}

private struct DynamicCodingKey: CodingKey {
    var stringValue: String
    var intValue: Int?

    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { self.stringValue = "\(intValue)"; self.intValue = intValue }
}

// MARK: - Staff Sales Summary

nonisolated struct StaffSalesSummary: Codable, Identifiable, Sendable {
    let salespersonId: String?
    let salespersonName: String?
    let totalSales: Double
    let orderCount: Int
    let avgOrderValue: Double

    var id: String { salespersonId ?? UUID().uuidString }
}
