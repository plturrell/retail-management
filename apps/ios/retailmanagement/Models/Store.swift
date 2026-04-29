//
//  Store.swift
//  retailmanagement
//

import Foundation

nonisolated struct Store: Codable, Identifiable, Hashable, Sendable {
    enum StoreType: String, Codable, Sendable {
        case retail
        case warehouse
        case hybrid
    }

    enum OperationalStatus: String, Codable, Sendable {
        case active
        case staging
        case planned
        case inactive
    }

    let id: String
    let name: String
    let location: String
    let address: String
    let businessHoursStart: String?
    let businessHoursEnd: String?
    let storeType: StoreType
    let operationalStatus: OperationalStatus
    let isHomeBase: Bool
    let isTempWarehouse: Bool
    let plannedOpenDate: String?
    let notes: String?
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
        storeType: StoreType = .retail,
        operationalStatus: OperationalStatus = .active,
        isHomeBase: Bool = false,
        isTempWarehouse: Bool = false,
        plannedOpenDate: String? = nil,
        notes: String? = nil,
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
        self.storeType = storeType
        self.operationalStatus = operationalStatus
        self.isHomeBase = isHomeBase
        self.isTempWarehouse = isTempWarehouse
        self.plannedOpenDate = plannedOpenDate
        self.notes = notes
        self.isActive = isActive
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }
}
