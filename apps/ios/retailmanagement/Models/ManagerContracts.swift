import Foundation

// MARK: - Enums

enum RecommendationType: String, Codable, Sendable {
    case reorder
    case priceChange = "price_change"
    case stockAnomaly = "stock_anomaly"
}

enum RecommendationStatus: String, Codable, Sendable {
    case pending
    case approved
    case dismissed
}

enum InventoryType: String, Codable, Sendable {
    case finished
    case material
    case purchased
}

enum SourcingStrategy: String, Codable, Sendable {
    case supplierPremade = "supplier_premade"
    case manufacturedStandard = "manufactured_standard"
    case manufacturedCustom = "manufactured_custom"
}

// Support for arbitrary metrics mapping in Recommendation
enum MetricValue: Codable, Sendable {
    case string(String)
    case number(Double)
    case boolean(Bool)
    
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let x = try? container.decode(String.self) {
            self = .string(x)
            return
        }
        if let x = try? container.decode(Double.self) {
            self = .number(x)
            return
        }
        if let x = try? container.decode(Bool.self) {
            self = .boolean(x)
            return
        }
        throw DecodingError.typeMismatch(MetricValue.self, DecodingError.Context(codingPath: decoder.codingPath, debugDescription: "Wrong type for MetricValue"))
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let x): try container.encode(x)
        case .number(let x): try container.encode(x)
        case .boolean(let x): try container.encode(x)
        }
    }
}

// MARK: - Manager Summary

struct RecommendationOutcome: Codable, Sendable, Identifiable {
    var id: String { recommendationId }
    
    let recommendationId: String
    let skuId: String
    let title: String
    let type: RecommendationType
    let status: RecommendationStatus
    let updatedAt: String
}

struct ManagerSummary: Codable, Sendable {
    let storeId: String
    let analysisStatus: String
    let lastGeneratedAt: String
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

struct SupplyChainSummary: Codable, Sendable {
    let storeId: String
    let supplierCount: Int
    let openPurchaseOrders: Int
    let activeWorkOrders: Int
    let inTransitTransfers: Int
    let purchasedUnits: Int
    let materialUnits: Int
    let finishedUnits: Int
    let openRecommendationLinkedOrders: Int?
}

// MARK: - Detailed Insights

struct InventoryInsight: Codable, Sendable, Identifiable {
    var id: String { skuId }
    
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
    let lastUpdated: String
}

struct ManagerRecommendation: Codable, Sendable, Identifiable {
    let id: String
    let storeId: String
    let skuId: String
    let inventoryId: String?
    let inventoryType: InventoryType
    let sourcingStrategy: SourcingStrategy
    let supplierName: String?
    let type: RecommendationType
    let status: RecommendationStatus
    let title: String
    let rationale: String
    let confidence: Double
    let supportingMetrics: [String: MetricValue]
    let source: String
    let expectedImpact: String
    let currentPrice: Double?
    let suggestedPrice: Double?
    let suggestedOrderQty: Int?
    let workflowAction: String
    let analysisStatus: String
    let generatedAt: String
    let decidedAt: String?
    let appliedAt: String?
    let note: String?
}

// MARK: - Tracking Entities

struct InventoryAdjustmentHistory: Codable, Sendable, Identifiable {
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

struct SupplierSummary: Codable, Sendable, Identifiable {
    let id: String
    let name: String
    let contactName: String?
    let email: String?
    let phone: String?
    let leadTimeDays: Int?
    let currency: String?
    let notes: String?
    let isActive: Bool
}

struct StageInventoryPosition: Codable, Sendable, Identifiable {
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

struct PurchaseOrderLine: Codable, Sendable, Identifiable {
    var id: String { lineId }
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
}

struct PurchaseOrderSummary: Codable, Sendable, Identifiable {
    let id: String
    let supplierId: String
    let supplierName: String
    let status: String
    let lines: [PurchaseOrderLine]
    let totalQuantity: Int
    let totalCost: Double
    let expectedDeliveryDate: String?
    let note: String?
    let recommendationId: String?
}

struct BOMRecipeComponent: Codable, Sendable {
    let skuId: String
    let skuCode: String
    let description: String
    let quantityRequired: Double
    let note: String?
}

struct BOMRecipeSummary: Codable, Sendable, Identifiable {
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

struct WorkOrderComponent: Codable, Sendable {
    let skuId: String
    let skuCode: String
    let description: String
    let quantityRequired: Double
    let note: String?
}

struct WorkOrderSummary: Codable, Sendable, Identifiable {
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

struct StockTransferSummary: Codable, Sendable, Identifiable {
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
