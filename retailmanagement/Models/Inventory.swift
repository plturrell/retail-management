//
//  Inventory.swift
//  retailmanagement
//

import Foundation

nonisolated struct Category: Codable, Identifiable, Sendable {
    let id: String
    let catgCode: String
    let cagCatgCode: String?
    let description: String
    let parentId: String?
    let storeId: String
    let createdAt: String?
    let updatedAt: String?
}

nonisolated struct Brand: Codable, Identifiable, Sendable {
    let id: String
    let name: String
    let categoryType: String?
    let createdAt: String?
}

nonisolated struct SKU: Codable, Identifiable, Hashable, Sendable {
    static func == (lhs: SKU, rhs: SKU) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }

    let id: String
    let skuCode: String
    let description: String
    let longDescription: String?
    let costPrice: Double?
    let categoryId: String?
    let brandId: String?
    let taxCode: String
    let gender: String?
    let ageGroup: String?
    let isUniquePiece: Bool
    let useStock: Bool
    let blockSales: Bool
    let storeId: String
    let createdAt: String?
    let updatedAt: String?

    var displayPrice: String {
        if let cost = costPrice {
            return String(format: "$%.2f", cost)
        }
        return "N/A"
    }
}

nonisolated struct InventoryItem: Codable, Identifiable, Sendable {
    let id: String
    let skuId: String
    let storeId: String
    let qtyOnHand: Int
    let reorderLevel: Int
    let reorderQty: Int
    let serialNumber: String?
    let lastUpdated: String
    let createdAt: String?
    let updatedAt: String?

    var isLowStock: Bool {
        qtyOnHand <= reorderLevel
    }
}

nonisolated struct Price: Codable, Identifiable, Sendable {
    let id: String
    let skuId: String
    let storeId: String?
    let priceInclTax: Double
    let priceExclTax: Double
    let priceUnit: Int
    let validFrom: String
    let validTo: String
    let createdAt: String?
    let updatedAt: String?

    var formattedPrice: String {
        String(format: "$%.2f", priceInclTax)
    }
}

nonisolated struct Promotion: Codable, Identifiable, Sendable {
    let id: String
    let discId: String
    let skuId: String?
    let categoryId: String?
    let lineType: String
    let discMethod: String
    let discValue: Double
    let lineGroup: String?
    let createdAt: String?
    let updatedAt: String?
}
