//
//  Commission.swift
//  retailmanagement
//
//  Mirrors the staff-portal CommissionPage's view of a CommissionRule.
//  Backend source of truth: app/schemas/payroll.py CommissionRuleRead.
//

import Foundation

nonisolated struct CommissionTier: Codable, Sendable, Hashable {
    let min: Double
    let max: Double?
    let rate: Double
}

nonisolated struct CommissionRule: Codable, Identifiable, Sendable, Hashable {
    let id: String
    let storeId: String
    let name: String
    let tiers: [CommissionTier]
    let isActive: Bool
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case storeId = "store_id"
        case name
        case tiers
        case isActive = "is_active"
        case createdAt = "created_at"
    }
}
