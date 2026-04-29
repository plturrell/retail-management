//
//  InventoryViewModel.swift
//  retailmanagement
//

import Foundation
import Observation

@MainActor
@Observable
final class InventoryViewModel {
    var summary: ManagerSummary?
    var supplySummary: SupplyChainSummary?
    var insights: [InventoryInsight] = []
    var recommendations: [ManagerRecommendation] = []
    var adjustments: [InventoryAdjustmentHistory] = []
    var suppliers: [SupplierSummary] = []
    var stagePositions: [StageInventoryPosition] = []
    var purchaseOrders: [PurchaseOrderSummary] = []
    var bomRecipes: [BOMRecipeSummary] = []
    var workOrders: [WorkOrderSummary] = []
    var transfers: [StockTransferSummary] = []
    var isLoading = false
    var isAnalyzing = false
    var errorMessage: String?
    var searchText: String = ""
    var showLowStockOnly = false
    var showAnomaliesOnly = false
    var activeActionKey: String?

    private var currentStoreId: String?
    private let usesFixtureData: Bool

    init(usesFixtureData: Bool = false) {
        self.usesFixtureData = usesFixtureData
    }

    convenience init(fixture: ManagerInventoryFixtureData) {
        self.init(usesFixtureData: true)
        summary = fixture.summary
        supplySummary = fixture.supplySummary
        insights = fixture.insights
        recommendations = fixture.recommendations
        adjustments = fixture.adjustments
        suppliers = fixture.suppliers
        stagePositions = fixture.stagePositions
        purchaseOrders = fixture.purchaseOrders
        bomRecipes = fixture.bomRecipes
        workOrders = fixture.workOrders
        transfers = fixture.transfers
    }

    func loadData(storeId: String, includeOwnerData: Bool = false, forceRefresh: Bool = false) async {
        if usesFixtureData {
            currentStoreId = storeId
            isLoading = false
            errorMessage = nil
            return
        }
        guard forceRefresh || currentStoreId != storeId || insights.isEmpty else { return }
        currentStoreId = storeId
        isLoading = true
        errorMessage = nil

        do {
            async let summaryResp: DataResponse<ManagerSummary> = NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/copilot/summary"
            )
            async let inventoryResp: DataResponse<[InventoryInsight]> = NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/copilot/inventory"
            )
            async let recommendationsResp: DataResponse<[ManagerRecommendation]> = NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/copilot/recommendations"
            )
            async let adjustmentsResp: DataResponse<[InventoryAdjustmentHistory]> = NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/copilot/adjustments"
            )

            let (
                summaryResult,
                inventoryResult,
                recommendationResult,
                adjustmentResult
            ) = try await (
                summaryResp,
                inventoryResp,
                recommendationsResp,
                adjustmentsResp
            )

            summary = summaryResult.data
            insights = inventoryResult.data
            recommendations = recommendationResult.data
            adjustments = adjustmentResult.data
            if includeOwnerData {
                async let supplySummaryResp: DataResponse<SupplyChainSummary> = NetworkService.shared.get(
                    endpoint: "/api/stores/\(storeId)/supply-chain/summary"
                )
                async let suppliersResp: DataResponse<[SupplierSummary]> = NetworkService.shared.get(
                    endpoint: "/api/stores/\(storeId)/supply-chain/suppliers?active_only=true"
                )
                async let stageResp: DataResponse<[StageInventoryPosition]> = NetworkService.shared.get(
                    endpoint: "/api/stores/\(storeId)/supply-chain/stages"
                )
                async let purchaseOrdersResp: DataResponse<[PurchaseOrderSummary]> = NetworkService.shared.get(
                    endpoint: "/api/stores/\(storeId)/supply-chain/purchase-orders"
                )
                async let bomRecipesResp: DataResponse<[BOMRecipeSummary]> = NetworkService.shared.get(
                    endpoint: "/api/stores/\(storeId)/supply-chain/bom-recipes"
                )
                async let workOrdersResp: DataResponse<[WorkOrderSummary]> = NetworkService.shared.get(
                    endpoint: "/api/stores/\(storeId)/supply-chain/work-orders"
                )
                async let transfersResp: DataResponse<[StockTransferSummary]> = NetworkService.shared.get(
                    endpoint: "/api/stores/\(storeId)/supply-chain/transfers"
                )

                let (
                    supplySummaryResult,
                    suppliersResult,
                    stageResult,
                    purchaseOrdersResult,
                    bomRecipesResult,
                    workOrdersResult,
                    transfersResult
                ) = try await (
                    supplySummaryResp,
                    suppliersResp,
                    stageResp,
                    purchaseOrdersResp,
                    bomRecipesResp,
                    workOrdersResp,
                    transfersResp
                )

                supplySummary = supplySummaryResult.data
                suppliers = suppliersResult.data
                stagePositions = stageResult.data
                purchaseOrders = purchaseOrdersResult.data
                bomRecipes = bomRecipesResult.data
                workOrders = workOrdersResult.data
                transfers = transfersResult.data
            } else {
                supplySummary = nil
                suppliers = []
                stagePositions = []
                purchaseOrders = []
                bomRecipes = []
                workOrders = []
                transfers = []
            }
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    var filteredInsights: [InventoryInsight] {
        let normalizedSearch = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return insights.filter { item in
            if showLowStockOnly && !item.lowStock { return false }
            if showAnomaliesOnly && !item.anomalyFlag { return false }
            if normalizedSearch.isEmpty { return true }
            return item.skuCode.lowercased().contains(normalizedSearch)
                || item.description.lowercased().contains(normalizedSearch)
        }
    }

    func recommendations(for skuId: String?) -> [ManagerRecommendation] {
        guard let skuId else { return recommendations }
        let scoped = recommendations.filter { $0.skuId == skuId }
        return scoped.isEmpty ? recommendations : scoped
    }

    func adjustments(for skuId: String?) -> [InventoryAdjustmentHistory] {
        guard let skuId else { return adjustments }
        return adjustments.filter { $0.skuId == skuId }
    }

    func stagePositions(for skuId: String?) -> [StageInventoryPosition] {
        guard let skuId else { return stagePositions }
        return stagePositions.filter { $0.skuId == skuId }
    }

    func purchaseOrders(for skuId: String?) -> [PurchaseOrderSummary] {
        guard let skuId else { return purchaseOrders }
        return purchaseOrders.filter { order in
            order.lines.contains { $0.skuId == skuId }
        }
    }

    func bomRecipes(for skuId: String?) -> [BOMRecipeSummary] {
        guard let skuId else { return bomRecipes }
        return bomRecipes.filter { $0.finishedSkuId == skuId }
    }

    func workOrders(for skuId: String?) -> [WorkOrderSummary] {
        guard let skuId else { return workOrders }
        return workOrders.filter { $0.finishedSkuId == skuId }
    }

    func transfers(for skuId: String?) -> [StockTransferSummary] {
        guard let skuId else { return transfers }
        return transfers.filter { $0.skuId == skuId }
    }

    func runAnalysis(storeId: String) async {
        activeActionKey = "analysis"
        isAnalyzing = true
        errorMessage = nil

        do {
            let _: DataResponse<ManagerAnalysisTriggerResponse> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/copilot/recommendations/analyze",
                body: AnalysisTriggerBody(forceRefresh: true, lookbackDays: 30, lowStockThreshold: 5)
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
        isAnalyzing = false
    }

    func approveRecommendation(storeId: String, recommendationId: String) async {
        await updateRecommendation(storeId: storeId, recommendationId: recommendationId, action: "approve")
    }

    func rejectRecommendation(storeId: String, recommendationId: String) async {
        await updateRecommendation(storeId: storeId, recommendationId: recommendationId, action: "reject")
    }

    func applyRecommendation(storeId: String, recommendationId: String) async {
        await updateRecommendation(storeId: storeId, recommendationId: recommendationId, action: "apply")
    }

    /// Result of a CSV inventory import. Mirrors the backend's `CSVImportResult`.
    struct CSVImportResult: Decodable, Sendable {
        let imported: Int
        let updated: Int
        let skipped: Int
        let errors: [String]

        var summary: String {
            "Imported \(imported), updated \(updated), skipped \(skipped)"
                + (errors.isEmpty ? "." : " — \(errors.count) issue(s).")
        }
    }

    /// Upload a CSV file and create / update inventory records on the backend.
    /// Validates the file extension client-side; the backend re-validates
    /// headers and rows.
    func importCSV(storeId: String, fileURL: URL) async -> CSVImportResult? {
        guard fileURL.pathExtension.lowercased() == "csv" else {
            errorMessage = "Only .csv files are supported."
            return nil
        }
        activeActionKey = "csv-import"
        errorMessage = nil
        defer { activeActionKey = nil }

        do {
            let result: CSVImportResult = try await NetworkService.shared.upload(
                endpoint: "/api/stores/\(storeId)/inventory/import-csv",
                fileURL: fileURL,
                fieldName: "file",
                mimeType: "text/csv"
            )
            await loadData(storeId: storeId, forceRefresh: true)
            return result
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func adjustInventory(storeId: String, inventoryId: String, quantity: Int, reason: String) async {
        guard !reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            errorMessage = "A reason is required for inventory adjustments."
            return
        }

        activeActionKey = "adjustment"
        errorMessage = nil

        do {
            let _: DataResponse<InventoryItem> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/inventory/\(inventoryId)/adjust",
                body: InventoryAdjustmentBody(quantity: quantity, reason: reason, source: "manual")
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    func receivePurchaseOrder(storeId: String, order: PurchaseOrderSummary) async {
        let remainingLines = order.lines
            .filter { $0.openQuantity > 0 }
            .map { ReceivePurchaseOrderLine(lineId: $0.lineId, quantityReceived: $0.openQuantity) }
        guard !remainingLines.isEmpty else { return }

        activeActionKey = "receive-\(order.id)"
        errorMessage = nil

        do {
            let _: DataResponse<EmptyEnvelope> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/supply-chain/purchase-orders/\(order.id)/receive",
                body: ReceivePurchaseOrderBody(lines: remainingLines, note: "Received from the iOS manager console.")
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    func startWorkOrder(storeId: String, workOrderId: String) async {
        activeActionKey = "start-\(workOrderId)"
        errorMessage = nil

        do {
            let _: DataResponse<WorkOrderSummary> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/supply-chain/work-orders/\(workOrderId)/start",
                body: EmptyBody()
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    func completeWorkOrder(storeId: String, workOrder: WorkOrderSummary) async {
        activeActionKey = "complete-\(workOrder.id)"
        errorMessage = nil

        do {
            let _: DataResponse<EmptyEnvelope> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/supply-chain/work-orders/\(workOrder.id)/complete",
                body: CompleteWorkOrderBody(
                    completedQuantity: max(workOrder.targetQuantity - workOrder.completedQuantity, 1),
                    note: "Completed from the iOS manager console."
                )
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    func receiveTransfer(storeId: String, transferId: String) async {
        activeActionKey = "transfer-\(transferId)"
        errorMessage = nil

        do {
            let _: DataResponse<StockTransferSummary> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/supply-chain/transfers/\(transferId)/receive",
                body: SimpleNoteBody(note: "Received from the iOS manager console.")
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    func saveSupplier(
        storeId: String,
        supplierId: String?,
        name: String,
        contactName: String,
        email: String,
        phone: String,
        leadTimeDays: Int,
        currency: String,
        notes: String,
        isActive: Bool
    ) async {
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            errorMessage = "Supplier name is required."
            return
        }

        activeActionKey = "supplier-save"
        errorMessage = nil

        let body = SupplierBody(
            name: name.trimmingCharacters(in: .whitespacesAndNewlines),
            contactName: contactName.nilIfBlank,
            email: email.nilIfBlank,
            phone: phone.nilIfBlank,
            leadTimeDays: max(leadTimeDays, 0),
            currency: currency.trimmingCharacters(in: .whitespacesAndNewlines).uppercased().isEmpty ? "SGD" : currency.trimmingCharacters(in: .whitespacesAndNewlines).uppercased(),
            notes: notes.nilIfBlank,
            isActive: isActive
        )

        do {
            if let supplierId {
                let _: DataResponse<SupplierSummary> = try await NetworkService.shared.patch(
                    endpoint: "/api/stores/\(storeId)/supply-chain/suppliers/\(supplierId)",
                    body: body
                )
            } else {
                let _: DataResponse<SupplierSummary> = try await NetworkService.shared.post(
                    endpoint: "/api/stores/\(storeId)/supply-chain/suppliers",
                    body: body
                )
            }
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    func createPurchaseOrder(
        storeId: String,
        supplierId: String,
        skuId: String,
        quantity: Int,
        unitCost: Double,
        expectedDeliveryDate: String?,
        note: String
    ) async {
        activeActionKey = "purchase-order-create"
        errorMessage = nil

        do {
            let _: DataResponse<PurchaseOrderSummary> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/supply-chain/purchase-orders",
                body: PurchaseOrderCreateBody(
                    supplierId: supplierId,
                    lines: [
                        PurchaseOrderLineBody(
                            skuId: skuId,
                            quantity: max(quantity, 1),
                            unitCost: max(unitCost, 0),
                            note: note.nilIfBlank
                        )
                    ],
                    expectedDeliveryDate: expectedDeliveryDate?.nilIfBlank,
                    note: note.nilIfBlank,
                    source: "manual"
                )
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    func createBOMRecipe(
        storeId: String,
        finishedSkuId: String,
        name: String,
        yieldQuantity: Int,
        components: [ComponentDraftPayload],
        notes: String
    ) async {
        let filtered = components.filter { !$0.skuId.isEmpty && $0.quantityRequired > 0 }
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !filtered.isEmpty else {
            errorMessage = "Recipe name and at least one component are required."
            return
        }

        activeActionKey = "bom-create"
        errorMessage = nil

        do {
            let _: DataResponse<BOMRecipeSummary> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/supply-chain/bom-recipes",
                body: BOMRecipeCreateBody(
                    finishedSkuId: finishedSkuId,
                    name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                    yieldQuantity: max(yieldQuantity, 1),
                    components: filtered.map {
                        BOMComponentBody(
                            skuId: $0.skuId,
                            quantityRequired: $0.quantityRequired,
                            note: $0.note.nilIfBlank
                        )
                    },
                    notes: notes.nilIfBlank
                )
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    func createWorkOrder(
        storeId: String,
        finishedSkuId: String,
        targetQuantity: Int,
        bomId: String?,
        workOrderType: String,
        customComponents: [ComponentDraftPayload],
        dueDate: String?,
        note: String
    ) async {
        let filtered = customComponents.filter { !$0.skuId.isEmpty && $0.quantityRequired > 0 }
        if bomId == nil && filtered.isEmpty {
            errorMessage = "Select a BOM or add at least one custom component."
            return
        }

        activeActionKey = "work-order-create"
        errorMessage = nil

        do {
            let _: DataResponse<WorkOrderSummary> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/supply-chain/work-orders",
                body: WorkOrderCreateBody(
                    finishedSkuId: finishedSkuId,
                    targetQuantity: max(targetQuantity, 1),
                    bomId: bomId?.nilIfBlank,
                    workOrderType: workOrderType,
                    customComponents: bomId == nil
                        ? filtered.map {
                            BOMComponentBody(
                                skuId: $0.skuId,
                                quantityRequired: $0.quantityRequired,
                                note: $0.note.nilIfBlank
                            )
                        }
                        : [],
                    dueDate: dueDate?.nilIfBlank,
                    note: note.nilIfBlank,
                    source: "manual"
                )
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    func createTransfer(
        storeId: String,
        skuId: String,
        quantity: Int,
        fromInventoryType: String,
        toInventoryType: String,
        note: String
    ) async {
        activeActionKey = "transfer-create"
        errorMessage = nil

        do {
            let _: DataResponse<StockTransferSummary> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/supply-chain/transfers",
                body: StockTransferCreateBody(
                    skuId: skuId,
                    quantity: max(quantity, 1),
                    fromInventoryType: fromInventoryType,
                    toInventoryType: toInventoryType,
                    note: note.nilIfBlank,
                    source: "manual"
                )
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    private func updateRecommendation(storeId: String, recommendationId: String, action: String) async {
        activeActionKey = recommendationId + action
        errorMessage = nil

        do {
            let _: DataResponse<ManagerRecommendation> = try await NetworkService.shared.post(
                endpoint: "/api/stores/\(storeId)/copilot/recommendations/\(recommendationId)/\(action)",
                body: RecommendationDecisionBody(note: defaultNote(for: action))
            )
            await loadData(storeId: storeId, forceRefresh: true)
        } catch {
            errorMessage = error.localizedDescription
        }

        activeActionKey = nil
    }

    private func defaultNote(for action: String) -> String {
        switch action {
        case "approve":
            return "Approved from the iOS manager console."
        case "reject":
            return "Rejected from the iOS manager console."
        case "apply":
            return "Applied from the iOS manager console."
        default:
            return "Updated from the iOS manager console."
        }
    }
}

private struct AnalysisTriggerBody: Encodable {
    let forceRefresh: Bool
    let lookbackDays: Int
    let lowStockThreshold: Int
}

private struct RecommendationDecisionBody: Encodable {
    let note: String
}

nonisolated struct ComponentDraftPayload: Sendable {
    let skuId: String
    let quantityRequired: Int
    let note: String
}

private struct InventoryAdjustmentBody: Encodable {
    let quantity: Int
    let reason: String
    let source: String
}

private struct ReceivePurchaseOrderLine: Encodable {
    let lineId: String
    let quantityReceived: Int
}

private struct ReceivePurchaseOrderBody: Encodable {
    let lines: [ReceivePurchaseOrderLine]
    let note: String
}

private struct CompleteWorkOrderBody: Encodable {
    let completedQuantity: Int
    let note: String
}

private struct SimpleNoteBody: Encodable {
    let note: String
}

private struct EmptyBody: Encodable {}

private struct SupplierBody: Encodable {
    let name: String
    let contactName: String?
    let email: String?
    let phone: String?
    let leadTimeDays: Int
    let currency: String
    let notes: String?
    let isActive: Bool
}

private struct PurchaseOrderLineBody: Encodable {
    let skuId: String
    let quantity: Int
    let unitCost: Double
    let note: String?
}

private struct PurchaseOrderCreateBody: Encodable {
    let supplierId: String
    let lines: [PurchaseOrderLineBody]
    let expectedDeliveryDate: String?
    let note: String?
    let source: String
}

private struct BOMComponentBody: Encodable {
    let skuId: String
    let quantityRequired: Int
    let note: String?
}

private struct BOMRecipeCreateBody: Encodable {
    let finishedSkuId: String
    let name: String
    let yieldQuantity: Int
    let components: [BOMComponentBody]
    let notes: String?
}

private struct WorkOrderCreateBody: Encodable {
    let finishedSkuId: String
    let targetQuantity: Int
    let bomId: String?
    let workOrderType: String
    let customComponents: [BOMComponentBody]
    let dueDate: String?
    let note: String?
    let source: String
}

private struct StockTransferCreateBody: Encodable {
    let skuId: String
    let quantity: Int
    let fromInventoryType: String
    let toInventoryType: String
    let note: String?
    let source: String
}

private nonisolated struct EmptyEnvelope: Codable, Sendable {}

private extension String {
    var nilIfBlank: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
