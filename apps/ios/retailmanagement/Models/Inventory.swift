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
    let inventoryType: InventoryType
    let sourcingStrategy: SourcingStrategy
    let supplierName: String?
    let supplierSkuCode: String?
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

nonisolated enum InventoryType: String, Codable, Sendable {
    case purchased
    case material
    case finished

    var displayName: String {
        switch self {
        case .purchased: return "Purchased"
        case .material: return "Material"
        case .finished: return "Finished"
        }
    }
}

nonisolated enum SourcingStrategy: String, Codable, Sendable {
    case supplierPremade = "supplier_premade"
    case manufacturedStandard = "manufactured_standard"
    case manufacturedCustom = "manufactured_custom"

    var displayName: String {
        switch self {
        case .supplierPremade: return "Supplier pre-made"
        case .manufacturedStandard: return "Manufactured standard"
        case .manufacturedCustom: return "Manufactured custom"
        }
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

nonisolated enum JSONValue: Codable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON value")
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .number(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }
}

nonisolated enum RecommendationType: String, Codable, Sendable {
    case reorder
    case priceChange = "price_change"
    case stockAnomaly = "stock_anomaly"

    var displayName: String {
        switch self {
        case .reorder: return "Reorder"
        case .priceChange: return "Price Review"
        case .stockAnomaly: return "Stock Anomaly"
        }
    }
}

nonisolated enum RecommendationStatus: String, Codable, Sendable {
    case pending
    case approved
    case rejected
    case applied
    case expired
    case queued
    case unavailable

    var displayName: String { rawValue.capitalized }
}

nonisolated struct RecommendationOutcome: Codable, Identifiable, Sendable {
    let recommendationId: String
    let skuId: String?
    let title: String
    let type: RecommendationType
    let status: RecommendationStatus
    let updatedAt: String?

    var id: String { recommendationId }
}

nonisolated struct ManagerSummary: Codable, Sendable {
    let storeId: String
    let analysisStatus: String
    let lastGeneratedAt: String?
    let lowStockCount: Int
    let anomalyCount: Int
    let pendingPriceRecommendations: Int
    let pendingReorderRecommendations: Int
    let pendingStockAnomalies: Int
    let openPurchaseOrders: Int
    let activeWorkOrders: Int
    let inTransitTransfers: Int
    let purchasedUnits: Int
    let materialUnits: Int
    let finishedUnits: Int
    let recentOutcomes: [RecommendationOutcome]
}

nonisolated struct InventoryInsight: Codable, Identifiable, Hashable, Sendable {
    let inventoryId: String?
    let skuId: String
    let storeId: String
    let skuCode: String
    let description: String
    let longDescription: String?
    let inventoryType: InventoryType
    let sourcingStrategy: SourcingStrategy
    let supplierName: String?
    let costPrice: Double?
    let currentPrice: Double?
    let currentPriceValidUntil: String?
    let purchasedQty: Int
    let purchasedIncomingQty: Int
    let materialQty: Int
    let materialIncomingQty: Int
    let materialAllocatedQty: Int
    let finishedQty: Int
    let finishedAllocatedQty: Int
    let inTransitQty: Int
    let activeWorkOrderCount: Int
    let qtyOnHand: Int
    let reorderLevel: Int
    let reorderQty: Int
    let lowStock: Bool
    let anomalyFlag: Bool
    let anomalyReason: String?
    let recentSalesQty: Int
    let recentSalesRevenue: Double
    let avgDailySales: Double
    let daysOfCover: Double?
    let pendingRecommendationCount: Int
    let pendingPriceRecommendationCount: Int
    let lastUpdated: String?

    var id: String { skuId }
}

nonisolated struct ManagerRecommendation: Codable, Identifiable, Sendable {
    let id: String
    let storeId: String
    let skuId: String?
    let inventoryId: String?
    let inventoryType: InventoryType
    let sourcingStrategy: SourcingStrategy
    let supplierName: String?
    let type: RecommendationType
    let status: RecommendationStatus
    let title: String
    let rationale: String
    let confidence: Double
    let supportingMetrics: [String: JSONValue]
    let source: String
    let expectedImpact: String?
    let currentPrice: Double?
    let suggestedPrice: Double?
    let suggestedOrderQty: Int?
    let workflowAction: String?
    let analysisStatus: String
    let generatedAt: String
    let decidedAt: String?
    let appliedAt: String?
    let note: String?
}

nonisolated struct InventoryAdjustmentHistory: Codable, Identifiable, Sendable {
    let id: String
    let inventoryId: String
    let skuId: String
    let storeId: String
    let quantityDelta: Int
    let resultingQty: Int
    let reason: String
    let source: String
    let note: String?
    let createdAt: String
}

nonisolated struct ManagerAnalysisTriggerResponse: Codable, Sendable {
    let analysisStatus: String
    let multicaStatus: String
    let recommendationsCreated: Int
    let recommendationsReused: Int
    let recommendations: [ManagerRecommendation]
}

nonisolated struct SupplyChainSummary: Codable, Sendable {
    let storeId: String
    let supplierCount: Int
    let openPurchaseOrders: Int
    let activeWorkOrders: Int
    let inTransitTransfers: Int
    let purchasedUnits: Int
    let materialUnits: Int
    let finishedUnits: Int
}

nonisolated struct SupplierSummary: Codable, Identifiable, Sendable {
    let id: String
    let name: String
    let contactName: String?
    let email: String?
    let phone: String?
    let leadTimeDays: Int
    let currency: String
    let notes: String?
    let isActive: Bool
}

nonisolated struct StageInventoryPosition: Codable, Identifiable, Sendable {
    let id: String
    let storeId: String
    let skuId: String
    let skuCode: String
    let description: String
    let inventoryType: InventoryType
    let sourcingStrategy: SourcingStrategy
    let supplierName: String?
    let quantityOnHand: Int
    let incomingQuantity: Int
    let allocatedQuantity: Int
    let availableQuantity: Int
}

nonisolated struct PurchaseOrderLine: Codable, Identifiable, Sendable {
    let lineId: String
    let skuId: String
    let skuCode: String
    let description: String
    let stageInventoryType: InventoryType
    let quantity: Int
    let unitCost: Double
    let receivedQuantity: Int
    let openQuantity: Int
    let note: String?

    var id: String { lineId }
}

nonisolated struct PurchaseOrderSummary: Codable, Identifiable, Sendable {
    let id: String
    let supplierId: String
    let supplierName: String?
    let status: String
    let lines: [PurchaseOrderLine]
    let totalQuantity: Int
    let totalCost: Double
    let expectedDeliveryDate: String?
    let note: String?
    let recommendationId: String?
}

nonisolated struct WorkOrderComponent: Codable, Identifiable, Sendable {
    let skuId: String
    let skuCode: String
    let description: String
    let quantityRequired: Int
    let note: String?

    var id: String { "\(skuId)-\(quantityRequired)" }
}

nonisolated struct WorkOrderSummary: Codable, Identifiable, Sendable {
    let id: String
    let finishedSkuId: String
    let finishedSkuCode: String
    let finishedDescription: String
    let workOrderType: String
    let status: String
    let targetQuantity: Int
    let completedQuantity: Int
    let components: [WorkOrderComponent]
    let dueDate: String?
    let note: String?
    let recommendationId: String?
}

nonisolated struct StockTransferSummary: Codable, Identifiable, Sendable {
    let id: String
    let skuId: String
    let skuCode: String
    let description: String
    let quantity: Int
    let fromInventoryType: InventoryType
    let toInventoryType: InventoryType
    let status: String
    let note: String?
    let recommendationId: String?
    let dispatchedAt: String?
    let receivedAt: String?
}

nonisolated struct BOMRecipeComponent: Codable, Identifiable, Sendable {
    let skuId: String
    let skuCode: String
    let description: String
    let quantityRequired: Int
    let note: String?

    var id: String { "\(skuId)-\(quantityRequired)-\(note ?? "")" }
}

nonisolated struct BOMRecipeSummary: Codable, Identifiable, Sendable {
    let id: String
    let storeId: String
    let finishedSkuId: String
    let finishedSkuCode: String
    let finishedDescription: String
    let name: String
    let yieldQuantity: Int
    let components: [BOMRecipeComponent]
    let notes: String?
}
