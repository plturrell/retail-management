//
//  ManagerInventoryUITestHarness.swift
//  retailmanagement
//

import SwiftUI

enum AppLaunchMode {
    static let managerInventoryUITestArgument = "--uitest-manager-inventory"

    static var isManagerInventoryUITest: Bool {
        ProcessInfo.processInfo.arguments.contains(managerInventoryUITestArgument)
    }
}

struct ManagerInventoryUITestHarnessView: View {
    @State private var authViewModel: AuthViewModel = {
        let model = AuthViewModel()
        model.authState = .authenticated
        model.currentUser = AppUser(
            id: "user-owner-1",
            firebaseUid: "fixture-owner-1",
            email: "owner@victoriaenso.test",
            fullName: "Fixture Owner",
            phone: nil,
            storeRoles: [
                UserStoreRole(
                    id: "role-owner-1",
                    userId: "user-owner-1",
                    storeId: ManagerInventoryFixtureData.managerPilot.store.id,
                    role: .owner
                )
            ]
        )
        return model
    }()
    @State private var storeViewModel = StoreViewModel(
        preloadedStores: [ManagerInventoryFixtureData.managerPilot.store],
        selectedStore: ManagerInventoryFixtureData.managerPilot.store
    )

    var body: some View {
        InventoryTabView(
            inventoryViewModel: InventoryViewModel(fixture: .managerPilot)
        )
        .environment(authViewModel)
        .environment(storeViewModel)
    }
}

struct ManagerInventoryFixtureData {
    let store: Store
    let summary: ManagerSummary
    let supplySummary: SupplyChainSummary
    let insights: [InventoryInsight]
    let recommendations: [ManagerRecommendation]
    let adjustments: [InventoryAdjustmentHistory]
    let suppliers: [SupplierSummary]
    let stagePositions: [StageInventoryPosition]
    let purchaseOrders: [PurchaseOrderSummary]
    let bomRecipes: [BOMRecipeSummary]
    let workOrders: [WorkOrderSummary]
    let transfers: [StockTransferSummary]

    static let managerPilot = ManagerInventoryFixtureData(
        store: Store(
            id: "store-pilot-1",
            name: "Orchard Pilot Store",
            location: "Orchard",
            address: "391 Orchard Road, Singapore"
        ),
        summary: ManagerSummary(
            storeId: "store-pilot-1",
            analysisStatus: "completed",
            lastGeneratedAt: "2026-04-14T08:00:00Z",
            lowStockCount: 1,
            anomalyCount: 1,
            pendingPriceRecommendations: 1,
            pendingReorderRecommendations: 1,
            pendingStockAnomalies: 1,
            openPurchaseOrders: 1,
            activeWorkOrders: 1,
            inTransitTransfers: 1,
            purchasedUnits: 7,
            materialUnits: 18,
            finishedUnits: 9,
            recentOutcomes: [
                RecommendationOutcome(
                    recommendationId: "rec-outcome-1",
                    skuId: "sku-pre-001",
                    title: "Reorder supplier stock",
                    type: .reorder,
                    status: .approved,
                    updatedAt: "2026-04-14T08:30:00Z"
                )
            ]
        ),
        supplySummary: SupplyChainSummary(
            storeId: "store-pilot-1",
            supplierCount: 2,
            openPurchaseOrders: 1,
            activeWorkOrders: 1,
            inTransitTransfers: 1,
            purchasedUnits: 7,
            materialUnits: 18,
            finishedUnits: 9
        ),
        insights: [
            InventoryInsight(
                inventoryId: "inv-pre-001",
                skuId: "sku-pre-001",
                storeId: "store-pilot-1",
                skuCode: "PRE-001",
                description: "Supplier Pendant",
                longDescription: "Best-selling pendant sourced from GemCo.",
                inventoryType: .finished,
                sourcingStrategy: .supplierPremade,
                supplierName: "GemCo",
                costPrice: 12,
                currentPrice: 24,
                currentPriceValidUntil: "2026-05-01",
                purchasedQty: 4,
                purchasedIncomingQty: 3,
                materialQty: 0,
                materialIncomingQty: 0,
                materialAllocatedQty: 0,
                finishedQty: 3,
                finishedAllocatedQty: 0,
                inTransitQty: 1,
                activeWorkOrderCount: 0,
                qtyOnHand: 3,
                reorderLevel: 4,
                reorderQty: 6,
                lowStock: true,
                anomalyFlag: false,
                anomalyReason: nil,
                recentSalesQty: 7,
                recentSalesRevenue: 168,
                avgDailySales: 0.23,
                daysOfCover: 13,
                pendingRecommendationCount: 1,
                pendingPriceRecommendationCount: 0,
                lastUpdated: "2026-04-14T08:00:00Z"
            ),
            InventoryInsight(
                inventoryId: nil,
                skuId: "sku-mat-101",
                storeId: "store-pilot-1",
                skuCode: "MAT-101",
                description: "Silver Casting Grain",
                longDescription: "Core material held for standard and custom bridal runs.",
                inventoryType: .material,
                sourcingStrategy: .manufacturedStandard,
                supplierName: "Alloy Source",
                costPrice: 8.5,
                currentPrice: nil,
                currentPriceValidUntil: nil,
                purchasedQty: 3,
                purchasedIncomingQty: 2,
                materialQty: 18,
                materialIncomingQty: 5,
                materialAllocatedQty: 6,
                finishedQty: 0,
                finishedAllocatedQty: 0,
                inTransitQty: 0,
                activeWorkOrderCount: 1,
                qtyOnHand: 18,
                reorderLevel: 10,
                reorderQty: 15,
                lowStock: false,
                anomalyFlag: false,
                anomalyReason: nil,
                recentSalesQty: 0,
                recentSalesRevenue: 0,
                avgDailySales: 0,
                daysOfCover: nil,
                pendingRecommendationCount: 0,
                pendingPriceRecommendationCount: 0,
                lastUpdated: "2026-04-14T07:45:00Z"
            ),
            InventoryInsight(
                inventoryId: "inv-cus-900",
                skuId: "sku-cus-900",
                storeId: "store-pilot-1",
                skuCode: "CUS-900",
                description: "Custom Bridal Halo",
                longDescription: "Low-volume custom ring still in active production review.",
                inventoryType: .finished,
                sourcingStrategy: .manufacturedCustom,
                supplierName: nil,
                costPrice: 45,
                currentPrice: 149,
                currentPriceValidUntil: "2026-04-30",
                purchasedQty: 0,
                purchasedIncomingQty: 0,
                materialQty: 4,
                materialIncomingQty: 0,
                materialAllocatedQty: 2,
                finishedQty: 1,
                finishedAllocatedQty: 1,
                inTransitQty: 0,
                activeWorkOrderCount: 1,
                qtyOnHand: 1,
                reorderLevel: 1,
                reorderQty: 1,
                lowStock: false,
                anomalyFlag: true,
                anomalyReason: "Demand spiked after a bridal expo appointment.",
                recentSalesQty: 2,
                recentSalesRevenue: 298,
                avgDailySales: 0.07,
                daysOfCover: 14,
                pendingRecommendationCount: 1,
                pendingPriceRecommendationCount: 1,
                lastUpdated: "2026-04-14T07:30:00Z"
            )
        ],
        recommendations: [
            ManagerRecommendation(
                id: "rec-pre-001",
                storeId: "store-pilot-1",
                skuId: "sku-pre-001",
                inventoryId: "inv-pre-001",
                inventoryType: .finished,
                sourcingStrategy: .supplierPremade,
                supplierName: "GemCo",
                type: .reorder,
                status: .pending,
                title: "Reorder supplier stock",
                rationale: "Finished stock is below the reorder level and supplier lead time is 7 days.",
                confidence: 0.82,
                supportingMetrics: [
                    "days_of_cover": .number(13),
                    "open_purchase_orders": .number(1)
                ],
                source: "multica_recommendation",
                expectedImpact: "Reduce stockout risk on the pendant line.",
                currentPrice: 24,
                suggestedPrice: nil,
                suggestedOrderQty: 6,
                workflowAction: "purchase_order",
                analysisStatus: "completed",
                generatedAt: "2026-04-14T08:00:00Z",
                decidedAt: nil,
                appliedAt: nil,
                note: "Waiting for manager approval."
            ),
            ManagerRecommendation(
                id: "rec-cus-900",
                storeId: "store-pilot-1",
                skuId: "sku-cus-900",
                inventoryId: "inv-cus-900",
                inventoryType: .finished,
                sourcingStrategy: .manufacturedCustom,
                supplierName: nil,
                type: .priceChange,
                status: .pending,
                title: "Review custom halo pricing",
                rationale: "Recent bridal demand supports a modest premium while stock is constrained.",
                confidence: 0.74,
                supportingMetrics: [
                    "recent_sales_qty": .number(2),
                    "avg_margin_delta": .number(0.12)
                ],
                source: "multica_recommendation",
                expectedImpact: "Protect margin while the custom queue remains tight.",
                currentPrice: 149,
                suggestedPrice: 159,
                suggestedOrderQty: nil,
                workflowAction: "price_review",
                analysisStatus: "completed",
                generatedAt: "2026-04-14T08:05:00Z",
                decidedAt: nil,
                appliedAt: nil,
                note: "Escalate if bridal demand remains elevated."
            )
        ],
        adjustments: [
            InventoryAdjustmentHistory(
                id: "adj-1",
                inventoryId: "inv-pre-001",
                skuId: "sku-pre-001",
                storeId: "store-pilot-1",
                quantityDelta: -1,
                resultingQty: 3,
                reason: "Display unit moved to bridal window set.",
                source: "manual",
                note: "Approved by store manager.",
                createdAt: "2026-04-14T07:00:00Z"
            )
        ],
        suppliers: [
            SupplierSummary(
                id: "sup-gemco",
                name: "GemCo",
                contactName: "Amelia Tan",
                email: "amelia@gemco.example",
                phone: "+65 6123 1111",
                leadTimeDays: 7,
                currency: "SGD",
                notes: "Primary pendant vendor.",
                isActive: true
            ),
            SupplierSummary(
                id: "sup-alloy",
                name: "Alloy Source",
                contactName: "Marcus Lim",
                email: "marcus@alloysource.example",
                phone: "+65 6123 2222",
                leadTimeDays: 5,
                currency: "SGD",
                notes: "Casting materials and alloy top-ups.",
                isActive: true
            )
        ],
        stagePositions: [
            StageInventoryPosition(
                id: "stage-pre-001-purchased",
                storeId: "store-pilot-1",
                skuId: "sku-pre-001",
                skuCode: "PRE-001",
                description: "Supplier Pendant",
                inventoryType: .purchased,
                sourcingStrategy: .supplierPremade,
                supplierName: "GemCo",
                quantityOnHand: 4,
                incomingQuantity: 3,
                allocatedQuantity: 0,
                availableQuantity: 7
            ),
            StageInventoryPosition(
                id: "stage-mat-101-material",
                storeId: "store-pilot-1",
                skuId: "sku-mat-101",
                skuCode: "MAT-101",
                description: "Silver Casting Grain",
                inventoryType: .material,
                sourcingStrategy: .manufacturedStandard,
                supplierName: "Alloy Source",
                quantityOnHand: 18,
                incomingQuantity: 5,
                allocatedQuantity: 6,
                availableQuantity: 17
            ),
            StageInventoryPosition(
                id: "stage-cus-900-finished",
                storeId: "store-pilot-1",
                skuId: "sku-cus-900",
                skuCode: "CUS-900",
                description: "Custom Bridal Halo",
                inventoryType: .finished,
                sourcingStrategy: .manufacturedCustom,
                supplierName: nil,
                quantityOnHand: 1,
                incomingQuantity: 0,
                allocatedQuantity: 1,
                availableQuantity: 0
            )
        ],
        purchaseOrders: [
            PurchaseOrderSummary(
                id: "po-1",
                supplierId: "sup-gemco",
                supplierName: "GemCo",
                status: "open",
                lines: [
                    PurchaseOrderLine(
                        lineId: "po-line-1",
                        skuId: "sku-pre-001",
                        skuCode: "PRE-001",
                        description: "Supplier Pendant",
                        stageInventoryType: .purchased,
                        quantity: 6,
                        unitCost: 12,
                        receivedQuantity: 0,
                        openQuantity: 6,
                        note: "Restock for weekend bridal traffic."
                    )
                ],
                totalQuantity: 6,
                totalCost: 72,
                expectedDeliveryDate: "2026-04-18",
                note: "Linked to reorder recommendation.",
                recommendationId: "rec-pre-001"
            )
        ],
        bomRecipes: [
            BOMRecipeSummary(
                id: "bom-cus-900",
                storeId: "store-pilot-1",
                finishedSkuId: "sku-cus-900",
                finishedSkuCode: "CUS-900",
                finishedDescription: "Custom Bridal Halo",
                name: "Halo Bridal Assembly",
                yieldQuantity: 1,
                components: [
                    BOMRecipeComponent(
                        skuId: "sku-mat-101",
                        skuCode: "MAT-101",
                        description: "Silver Casting Grain",
                        quantityRequired: 2,
                        note: "Base casting input."
                    )
                ],
                notes: "Default custom halo bill of materials."
            )
        ],
        workOrders: [
            WorkOrderSummary(
                id: "wo-1",
                finishedSkuId: "sku-cus-900",
                finishedSkuCode: "CUS-900",
                finishedDescription: "Custom Bridal Halo",
                workOrderType: "custom",
                status: "in_progress",
                targetQuantity: 1,
                completedQuantity: 0,
                components: [
                    WorkOrderComponent(
                        skuId: "sku-mat-101",
                        skuCode: "MAT-101",
                        description: "Silver Casting Grain",
                        quantityRequired: 2,
                        note: "Reserved for benchsmith run."
                    )
                ],
                dueDate: "2026-04-16",
                note: "Client fitting scheduled Friday.",
                recommendationId: nil
            )
        ],
        transfers: [
            StockTransferSummary(
                id: "transfer-1",
                skuId: "sku-pre-001",
                skuCode: "PRE-001",
                description: "Supplier Pendant",
                quantity: 1,
                fromInventoryType: .purchased,
                toInventoryType: .finished,
                status: "in_transit",
                note: "Warehouse dispatch to Orchard floor.",
                recommendationId: nil,
                dispatchedAt: "2026-04-14T06:30:00Z",
                receivedAt: nil
            )
        ]
    )
}
