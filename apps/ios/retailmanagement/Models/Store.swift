//
//  Store.swift
//  retailmanagement
//

import Foundation

nonisolated struct Store: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let name: String
    let location: String
    let address: String
    let businessHoursStart: String?
    let businessHoursEnd: String?
    let isActive: Bool
    let createdAt: String?
    let updatedAt: String?

    init(
        id: String,
        name: String,
        location: String,
        address: String,
        businessHoursStart: String? = nil,
        businessHoursEnd: String? = nil,
        isActive: Bool = true,
        createdAt: String? = nil,
        updatedAt: String? = nil
    ) {
        self.id = id
        self.name = name
        self.location = location
        self.address = address
        self.businessHoursStart = businessHoursStart
        self.businessHoursEnd = businessHoursEnd
        self.isActive = isActive
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }
}
