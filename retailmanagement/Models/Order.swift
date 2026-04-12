//
//  Order.swift
//  retailmanagement
//

import Foundation

nonisolated enum OrderStatus: String, Codable, CaseIterable, Sendable {
    case open, completed, voided

    var displayName: String { rawValue.capitalized }

    var color: String {
        switch self {
        case .open: return "blue"
        case .completed: return "green"
        case .voided: return "red"
        }
    }
}

nonisolated enum OrderSource: String, Codable, CaseIterable, Sendable {
    case necPos = "nec_pos"
    case hipay
    case airwallex
    case shopify
    case manual

    var displayName: String {
        switch self {
        case .necPos: return "NEC POS"
        case .hipay: return "HiPay"
        case .airwallex: return "Airwallex"
        case .shopify: return "Shopify"
        case .manual: return "Manual"
        }
    }
}

nonisolated struct OrderItem: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let orderId: String
    let skuId: String
    let qty: Int
    let unitPrice: Double
    let discount: Double
    let lineTotal: Double
    let createdAt: String?

    var formattedPrice: String {
        String(format: "$%.2f", lineTotal)
    }
}

nonisolated struct Order: Codable, Identifiable, Hashable, Sendable {
    static func == (lhs: Order, rhs: Order) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }

    let id: String
    let orderNumber: String
    let storeId: String
    let staffId: String?
    let orderDate: String
    let subtotal: Double
    let discountTotal: Double
    let taxTotal: Double
    let grandTotal: Double
    let paymentMethod: String
    let paymentRef: String?
    let status: OrderStatus
    let source: OrderSource
    let items: [OrderItem]
    let createdAt: String?
    let updatedAt: String?

    var formattedTotal: String {
        String(format: "$%.2f", grandTotal)
    }

    var itemCount: Int {
        items.reduce(0) { $0 + $1.qty }
    }
}
