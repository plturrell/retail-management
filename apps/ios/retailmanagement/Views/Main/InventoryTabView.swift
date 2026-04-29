//
//  InventoryTabView.swift
//  retailmanagement
//

import SwiftUI
import UniformTypeIdentifiers

struct InventoryTabView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var inventoryVM: InventoryViewModel
    @State private var selectedSKUId: String?
    @State private var adjustmentReason = ""
    @State private var adjustmentQuantity = 1
    @FocusState private var isSearchFocused: Bool

    // CSV import state.
    @State private var showCSVImporter = false
    @State private var isCSVDropTargeted = false
    @State private var csvImportResult: InventoryViewModel.CSVImportResult?
    @State private var csvImportShowAlert = false

    @MainActor
    init() {
        _inventoryVM = State(initialValue: InventoryViewModel())
    }

    @MainActor
    init(inventoryViewModel: InventoryViewModel) {
        _inventoryVM = State(initialValue: inventoryViewModel)
    }

    private var selectedInsight: InventoryInsight? {
        inventoryVM.filteredInsights.first { $0.skuId == selectedSKUId }
            ?? inventoryVM.filteredInsights.first
    }

    private var selectedRecommendations: [ManagerRecommendation] {
        inventoryVM.recommendations(for: selectedInsight?.skuId)
    }

    private var selectedAdjustments: [InventoryAdjustmentHistory] {
        Array(inventoryVM.adjustments(for: selectedInsight?.skuId).prefix(5))
    }

    private var selectedStages: [StageInventoryPosition] {
        Array(inventoryVM.stagePositions(for: selectedInsight?.skuId).prefix(5))
    }

    private var selectedPurchaseOrders: [PurchaseOrderSummary] {
        Array(inventoryVM.purchaseOrders(for: selectedInsight?.skuId).prefix(5))
    }

    private var selectedWorkOrders: [WorkOrderSummary] {
        Array(inventoryVM.workOrders(for: selectedInsight?.skuId).prefix(5))
    }

    private var selectedTransfers: [StockTransferSummary] {
        Array(inventoryVM.transfers(for: selectedInsight?.skuId).prefix(5))
    }

    private var currentRole: UserRole {
        guard let user = authViewModel.currentUser,
              let store = storeViewModel.selectedStore else {
            return .staff
        }
        return user.role(for: store.id) ?? user.highestRole ?? .staff
    }

    private var canViewSensitiveOperations: Bool {
        currentRole.isOwnerOrAbove
    }

    var body: some View {
        NavigationStack {
            Group {
                if let storeId = storeViewModel.selectedStore?.id {
                    content(storeId: storeId)
                } else {
                    ContentUnavailableView(
                        "Choose a Store",
                        systemImage: "building.2",
                        description: Text("Pick an active store to unlock the manager inventory pilot.")
                    )
                }
            }
            .navigationTitle("Manager Inventory")
            .accessibilityIdentifier("managerInventory.root")
            .searchable(text: $inventoryVM.searchText, prompt: "Search SKU or description")
            .searchFocused($isSearchFocused)
            .toolbar {
                if canViewSensitiveOperations {
                    ToolbarItem(placement: .primaryAction) {
                        Button {
                            showCSVImporter = true
                        } label: {
                            Label("Import CSV", systemImage: "square.and.arrow.down.on.square")
                        }
                        .help("Import inventory from a CSV (sku_code, qty_on_hand, …)")
                        .disabled(storeViewModel.selectedStore == nil
                                  || inventoryVM.activeActionKey == "csv-import")
                    }
                }
            }
            .fileImporter(
                isPresented: $showCSVImporter,
                allowedContentTypes: [.commaSeparatedText, .plainText, .data]
            ) { result in
                guard case let .success(url) = result else { return }
                handleCSVDrop(url: url)
            }
            .dropDestination(for: URL.self) { urls, _ in
                guard let url = urls.first(where: { $0.pathExtension.lowercased() == "csv" }) else {
                    return false
                }
                handleCSVDrop(url: url)
                return true
            } isTargeted: { targeted in
                isCSVDropTargeted = targeted
            }
            .overlay {
                if isCSVDropTargeted {
                    csvDropOverlay
                }
            }
            .alert(
                "Import Complete",
                isPresented: $csvImportShowAlert,
                presenting: csvImportResult
            ) { _ in
                Button("OK", role: .cancel) {}
            } message: { result in
                if result.errors.isEmpty {
                    Text(result.summary)
                } else {
                    Text(result.summary + "\n\nFirst issue: " + (result.errors.first ?? ""))
                }
            }
            .task(id: storeViewModel.selectedStore?.id) {
                if let storeId = storeViewModel.selectedStore?.id {
                    await inventoryVM.loadData(
                        storeId: storeId,
                        includeOwnerData: canViewSensitiveOperations,
                        forceRefresh: true
                    )
                    if selectedSKUId == nil {
                        selectedSKUId = inventoryVM.filteredInsights.first?.skuId
                    }
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: .appRefreshRequested)) { _ in
                if let storeId = storeViewModel.selectedStore?.id {
                    Task {
                        await inventoryVM.loadData(
                            storeId: storeId,
                            includeOwnerData: canViewSensitiveOperations,
                            forceRefresh: true
                        )
                    }
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: .appFindRequested)) { _ in
                isSearchFocused = true
            }
        }
    }

    // MARK: - CSV Import

    private var csvDropOverlay: some View {
        ZStack {
            Color.blue.opacity(0.18)
            VStack(spacing: 12) {
                Image(systemName: "square.and.arrow.down.fill")
                    .font(.system(size: 48, weight: .semibold))
                Text("Drop CSV to import inventory")
                    .font(.title3.weight(.semibold))
                Text("Headers required: sku_code, qty_on_hand")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .padding(32)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .strokeBorder(Color.blue.opacity(0.6), style: StrokeStyle(lineWidth: 2, dash: [8, 6]))
            )
            .padding(40)
        }
        .transition(.opacity)
        .allowsHitTesting(false)
    }

    private func handleCSVDrop(url: URL) {
        guard let storeId = storeViewModel.selectedStore?.id else { return }
        guard canViewSensitiveOperations else {
            inventoryVM.errorMessage = "CSV import requires the owner role."
            return
        }
        Task {
            if let result = await inventoryVM.importCSV(storeId: storeId, fileURL: url) {
                csvImportResult = result
                csvImportShowAlert = true
                HapticManager.generateFeedback(style: result.errors.isEmpty ? .success : .error)
            }
        }
    }

    @ViewBuilder
    private func content(storeId: String) -> some View {
        if inventoryVM.isLoading {
            ProgressView("Loading manager inventory…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let errorMessage = inventoryVM.errorMessage {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(.red)
                            .padding()
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.red.opacity(0.08))
                            .clipShape(RoundedRectangle(cornerRadius: 18))
                    }

                    summarySection
                    filterSection
                    inventoryListSection

                    if let insight = selectedInsight {
                        detailSection(insight: insight, storeId: storeId)
                        recommendationsSection(storeId: storeId)
                        adjustmentsSection
                        if canViewSensitiveOperations {
                            stageLedgerSection
                            procurementSection(storeId: storeId)
                            workOrdersSection(storeId: storeId)
                            ManagerWorkflowStudioView(
                                inventoryVM: inventoryVM,
                                storeId: storeId,
                                selectedInsight: selectedInsight
                            )
                        } else {
                            ownerOnlyOperationsSection
                        }
                    }
                }
                .padding()
            }
            .refreshable {
                await inventoryVM.loadData(
                    storeId: storeId,
                    includeOwnerData: canViewSensitiveOperations,
                    forceRefresh: true
                )
            }
            .onChange(of: inventoryVM.filteredInsights.map(\.skuId)) { _, newValue in
                if !newValue.contains(selectedSKUId ?? "") {
                    selectedSKUId = newValue.first
                }
            }
        }
    }

    private var summarySection: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                SummaryCard(
                    title: "Low Stock",
                    value: "\(inventoryVM.summary?.lowStockCount ?? 0)",
                    color: .red
                )
                SummaryCard(
                    title: "Anomalies",
                    value: "\(inventoryVM.summary?.anomalyCount ?? 0)",
                    color: .orange
                )
                SummaryCard(
                    title: "Price Reviews",
                    value: "\(inventoryVM.summary?.pendingPriceRecommendations ?? 0)",
                    color: .indigo
                )
                SummaryCard(
                    title: "Reorders",
                    value: "\(inventoryVM.summary?.pendingReorderRecommendations ?? 0)",
                    color: .blue
                )
                SummaryCard(
                    title: "Brain Status",
                    value: (inventoryVM.summary?.analysisStatus ?? "ready").capitalized,
                    color: .green
                )
                SummaryCard(
                    title: "Finished",
                    value: "\(inventoryVM.summary?.finishedUnits ?? inventoryVM.supplySummary?.finishedUnits ?? 0)",
                    color: .green
                )
                if canViewSensitiveOperations {
                    SummaryCard(
                        title: "Open POs",
                        value: "\(inventoryVM.summary?.openPurchaseOrders ?? inventoryVM.supplySummary?.openPurchaseOrders ?? 0)",
                        color: .cyan
                    )
                    SummaryCard(
                        title: "Work Orders",
                        value: "\(inventoryVM.summary?.activeWorkOrders ?? inventoryVM.supplySummary?.activeWorkOrders ?? 0)",
                        color: .purple
                    )
                    SummaryCard(
                        title: "Transfers",
                        value: "\(inventoryVM.summary?.inTransitTransfers ?? inventoryVM.supplySummary?.inTransitTransfers ?? 0)",
                        color: .indigo
                    )
                    SummaryCard(
                        title: "Purchased",
                        value: "\(inventoryVM.summary?.purchasedUnits ?? inventoryVM.supplySummary?.purchasedUnits ?? 0)",
                        color: .gray
                    )
                    SummaryCard(
                        title: "Materials",
                        value: "\(inventoryVM.summary?.materialUnits ?? inventoryVM.supplySummary?.materialUnits ?? 0)",
                        color: .orange
                    )
                }
            }
        }
    }

    private var filterSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Toggle("Low stock", isOn: $inventoryVM.showLowStockOnly)
                    .toggleStyle(.button)
                Toggle("Anomalies", isOn: $inventoryVM.showAnomaliesOnly)
                    .toggleStyle(.button)
            }

            Button {
                guard let storeId = storeViewModel.selectedStore?.id else { return }
                Task {
                    await inventoryVM.runAnalysis(storeId: storeId)
                }
            } label: {
                Label(
                    inventoryVM.isAnalyzing ? "Running brain…" : "Run Inventory Brain",
                    systemImage: "sparkles"
                )
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
            }
            .buttonStyle(.borderedProminent)
            .disabled(inventoryVM.isAnalyzing)
            .accessibilityIdentifier("managerInventory.runBrain")
        }
    }

    private var inventoryListSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Inventory Watchlist")
                .font(.headline)
                .accessibilityIdentifier("managerInventory.watchlistTitle")

            if inventoryVM.filteredInsights.isEmpty {
                ContentUnavailableView(
                    "No Matching SKUs",
                    systemImage: "shippingbox",
                    description: Text("Try a different search or reset the current filters.")
                )
            } else {
                LazyVStack(spacing: 10) {
                    ForEach(inventoryVM.filteredInsights) { insight in
                        Button {
                            selectedSKUId = insight.skuId
                        } label: {
                            InventoryInsightRow(
                                insight: insight,
                                isSelected: insight.skuId == selectedInsight?.skuId
                            )
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("managerInventory.insight.\(insight.skuCode)")
                    }
                }
            }
        }
    }

    private func detailSection(insight: InventoryInsight, storeId: String) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("SKU Detail")
                .font(.headline)
                .accessibilityIdentifier("managerInventory.detailTitle")

            VStack(alignment: .leading, spacing: 8) {
                Text(insight.skuCode)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(insight.description)
                    .font(.title3.weight(.semibold))
                HStack(spacing: 8) {
                    Pill(label: insight.inventoryType.displayName, color: .gray)
                    Pill(label: insight.sourcingStrategy.displayName, color: .purple)
                }
                if let longDescription = insight.longDescription, !longDescription.isEmpty {
                    Text(longDescription)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                DetailMetric(title: "Current Price", value: formattedCurrency(insight.currentPrice))
                if canViewSensitiveOperations {
                    DetailMetric(title: "Cost Price", value: formattedCurrency(insight.costPrice))
                }
                DetailMetric(title: "Inventory Type", value: insight.inventoryType.displayName)
                DetailMetric(title: "Sourcing", value: insight.sourcingStrategy.displayName)
                DetailMetric(title: "Qty On Hand", value: "\(insight.qtyOnHand)")
                if canViewSensitiveOperations {
                    DetailMetric(title: "Purchased / Inbound", value: "\(insight.purchasedQty) / \(insight.purchasedIncomingQty)")
                    DetailMetric(title: "Material / Reserved", value: "\(insight.materialQty) / \(insight.materialAllocatedQty)")
                    DetailMetric(title: "Finished / In Transit", value: "\(insight.finishedQty) / \(insight.inTransitQty)")
                    DetailMetric(title: "Active WOs", value: "\(insight.activeWorkOrderCount)")
                } else {
                    DetailMetric(
                        title: "Available to Sell",
                        value: "\(max(insight.finishedQty - insight.finishedAllocatedQty, 0))"
                    )
                }
                DetailMetric(title: "Reorder", value: "\(insight.reorderLevel) / \(insight.reorderQty)")
                DetailMetric(title: "30-Day Sales", value: "\(insight.recentSalesQty) units")
                DetailMetric(
                    title: "Days of Cover",
                    value: insight.daysOfCover.map { String(format: "%.1f days", $0) } ?? "N/A"
                )
            }

            if canViewSensitiveOperations, let supplierName = insight.supplierName, !supplierName.isEmpty {
                Text("Supplier: \(supplierName)")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.gray.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 18))
            }

            if let anomalyReason = insight.anomalyReason {
                Text(anomalyReason)
                    .font(.subheadline)
                    .foregroundStyle(.orange)
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.orange.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 18))
            }

            VStack(alignment: .leading, spacing: 10) {
                Text("Manual Adjustment")
                    .font(.headline)
                if insight.inventoryId == nil {
                    Text("This SKU has no finished store-stock record yet. Receive a transfer or complete a work order first.")
                        .font(.footnote)
                        .foregroundStyle(.orange)
                }
                Stepper(value: $adjustmentQuantity, in: -100...100) {
                    Text("Quantity delta: \(adjustmentQuantity)")
                }
                TextField("Reason for the adjustment", text: $adjustmentReason, axis: .vertical)
                    .textFieldStyle(.roundedBorder)

                Button("Save Adjustment") {
                    Task {
                        await inventoryVM.adjustInventory(
                            storeId: storeId,
                            inventoryId: insight.inventoryId ?? "",
                            quantity: adjustmentQuantity,
                            reason: adjustmentReason
                        )
                        adjustmentReason = ""
                        adjustmentQuantity = 1
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled((inventoryVM.activeActionKey == "adjustment") || adjustmentReason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || insight.inventoryId == nil)
            }
            .padding()
            .background(Color.gray.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 20))
        }
        .padding()
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 24))
    }

    private func recommendationsSection(storeId: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Recommendations Inbox")
                .font(.headline)
                .accessibilityIdentifier("managerInventory.recommendationsTitle")

            if selectedRecommendations.isEmpty {
                Text("No persisted recommendations for this SKU yet.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(selectedRecommendations) { recommendation in
                    RecommendationCard(
                        recommendation: recommendation,
                        busyKey: inventoryVM.activeActionKey,
                        canViewSensitiveOperations: canViewSensitiveOperations
                    ) { action in
                        Task {
                            switch action {
                            case .approve:
                                await inventoryVM.approveRecommendation(storeId: storeId, recommendationId: recommendation.id)
                            case .reject:
                                await inventoryVM.rejectRecommendation(storeId: storeId, recommendationId: recommendation.id)
                            case .apply:
                                await inventoryVM.applyRecommendation(storeId: storeId, recommendationId: recommendation.id)
                            }
                        }
                    }
                }
            }
        }
    }

    private var ownerOnlyOperationsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Owner-Only Operations")
                .font(.headline)
            Text("Supplier, purchase-order, manufacturing, transfer, invoice-review, cost, and financial workflows are hidden from store managers.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text("This view stays focused on store stock, selling price, manual adjustments, and recommendation review for the locations assigned to you.")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 24))
    }

    private var adjustmentsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Adjustment History")
                .font(.headline)

            if selectedAdjustments.isEmpty {
                Text("No adjustment history for this SKU yet.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(selectedAdjustments) { entry in
                    HStack(alignment: .top, spacing: 12) {
                        Text(entry.quantityDelta >= 0 ? "+\(entry.quantityDelta)" : "\(entry.quantityDelta)")
                            .font(.headline)
                            .foregroundStyle(entry.quantityDelta >= 0 ? .green : .red)
                            .frame(width: 64, alignment: .leading)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(entry.reason)
                                .font(.subheadline.weight(.medium))
                            Text("Resulting qty: \(entry.resultingQty)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text(formattedDate(entry.createdAt))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.gray.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 18))
                }
            }
        }
    }

    private var stageLedgerSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Stage Ledger")
                .font(.headline)

            if selectedStages.isEmpty {
                Text("No explicit stage-ledger entries for this SKU yet.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(selectedStages) { position in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text(position.inventoryType.displayName)
                                .font(.subheadline.weight(.semibold))
                            Spacer()
                            Text("\(position.availableQuantity) available")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Text("On hand \(position.quantityOnHand) • Incoming \(position.incomingQuantity) • Reserved \(position.allocatedQuantity)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.gray.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 18))
                }
            }

            if canViewSensitiveOperations, !inventoryVM.suppliers.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Active Suppliers")
                        .font(.subheadline.weight(.semibold))
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(inventoryVM.suppliers.prefix(6)) { supplier in
                                Pill(label: supplier.name, color: .blue)
                            }
                        }
                    }
                }
                .padding()
                .background(Color.blue.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 18))
            }
        }
    }

    private func procurementSection(storeId: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Procurement & Delivery")
                .font(.headline)

            ForEach(selectedPurchaseOrders) { order in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(order.supplierName ?? "Supplier")
                                .font(.subheadline.weight(.semibold))
                            Text("\(order.totalQuantity) units • \(order.totalCost.formatted(.currency(code: "SGD")))")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(order.status.replacingOccurrences(of: "_", with: " ").capitalized)
                            .font(.caption.bold())
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(Color.cyan.opacity(0.14))
                            .foregroundStyle(.cyan)
                            .clipShape(Capsule())
                    }
                    if order.lines.contains(where: { $0.openQuantity > 0 }) {
                        Button("Receive Remaining") {
                            Task {
                                await inventoryVM.receivePurchaseOrder(storeId: storeId, order: order)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(inventoryVM.activeActionKey == "receive-\(order.id)")
                    }
                }
                .padding()
                .background(Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 18))
                .overlay(
                    RoundedRectangle(cornerRadius: 18)
                        .stroke(Color.gray.opacity(0.12), lineWidth: 1)
                )
            }

            ForEach(selectedTransfers) { transfer in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(transfer.fromInventoryType.displayName) → \(transfer.toInventoryType.displayName)")
                                .font(.subheadline.weight(.semibold))
                            Text("\(transfer.quantity) units")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(transfer.status.replacingOccurrences(of: "_", with: " ").capitalized)
                            .font(.caption.bold())
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(Color.teal.opacity(0.14))
                            .foregroundStyle(.teal)
                            .clipShape(Capsule())
                    }
                    if transfer.status == "in_transit" {
                        Button("Receive Transfer") {
                            Task {
                                await inventoryVM.receiveTransfer(storeId: storeId, transferId: transfer.id)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(inventoryVM.activeActionKey == "transfer-\(transfer.id)")
                    }
                }
                .padding()
                .background(Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 18))
                .overlay(
                    RoundedRectangle(cornerRadius: 18)
                        .stroke(Color.gray.opacity(0.12), lineWidth: 1)
                )
            }

            if selectedPurchaseOrders.isEmpty && selectedTransfers.isEmpty {
                Text("No purchase orders or transfers are linked to this SKU yet.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func workOrdersSection(storeId: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Manufacturing Queue")
                .font(.headline)

            if selectedWorkOrders.isEmpty {
                Text("No active work orders are linked to this SKU.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(selectedWorkOrders) { workOrder in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(workOrder.workOrderType.capitalized)
                                    .font(.subheadline.weight(.semibold))
                                Text("\(workOrder.completedQuantity) / \(workOrder.targetQuantity) complete")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(workOrder.status.replacingOccurrences(of: "_", with: " ").capitalized)
                                .font(.caption.bold())
                                .padding(.horizontal, 10)
                                .padding(.vertical, 6)
                                .background(Color.purple.opacity(0.14))
                                .foregroundStyle(.purple)
                                .clipShape(Capsule())
                        }

                        HStack {
                            if workOrder.status == "scheduled" {
                                Button("Start Work Order") {
                                    Task {
                                        await inventoryVM.startWorkOrder(storeId: storeId, workOrderId: workOrder.id)
                                    }
                                }
                                .buttonStyle(.borderedProminent)
                                .disabled(inventoryVM.activeActionKey == "start-\(workOrder.id)")
                            }
                            if workOrder.status != "completed" {
                                Button("Complete Remaining") {
                                    Task {
                                        await inventoryVM.completeWorkOrder(storeId: storeId, workOrder: workOrder)
                                    }
                                }
                                .buttonStyle(.bordered)
                                .disabled(inventoryVM.activeActionKey == "complete-\(workOrder.id)")
                            }
                        }
                    }
                    .padding()
                    .background(Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: 18))
                    .overlay(
                        RoundedRectangle(cornerRadius: 18)
                            .stroke(Color.gray.opacity(0.12), lineWidth: 1)
                    )
                }
            }
        }
    }

    private func formattedCurrency(_ value: Double?) -> String {
        guard let value else { return "N/A" }
        return value.formatted(.currency(code: "SGD"))
    }

    private func formattedDate(_ value: String?) -> String {
        guard
            let value,
            let date = ISO8601DateFormatter().date(from: value) ?? ISO8601DateFormatter.fractional.date(from: value)
        else {
            return value ?? "N/A"
        }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

private struct SummaryCard: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3.bold())
                .foregroundStyle(color)
        }
        .frame(width: 160, alignment: .leading)
        .padding()
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }
}

private struct InventoryInsightRow: View {
    let insight: InventoryInsight
    let isSelected: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text(insight.skuCode)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                Text(insight.description)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)

                HStack(spacing: 6) {
                    Pill(label: insight.inventoryType.displayName, color: .gray)
                    Pill(label: insight.sourcingStrategy.displayName, color: .purple)
                    if insight.lowStock {
                        Pill(label: "Low stock", color: .red)
                    }
                    if insight.anomalyFlag {
                        Pill(label: "Anomaly", color: .orange)
                    }
                    if insight.pendingRecommendationCount > 0 {
                        Pill(label: "\(insight.pendingRecommendationCount) open", color: .blue)
                    }
                }
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 6) {
                Text("Qty \(insight.qtyOnHand)")
                    .font(.subheadline.weight(.semibold))
                Text(insight.currentPrice.map { $0.formatted(.currency(code: "SGD")) } ?? "N/A")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text("Upstream \(insight.purchasedQty + insight.materialQty + insight.inTransitQty)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(isSelected ? Color.blue.opacity(0.08) : Color.white)
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .stroke(isSelected ? Color.blue.opacity(0.25) : Color.gray.opacity(0.12), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }
}

private struct Pill: View {
    let label: String
    let color: Color

    var body: some View {
        Text(label)
            .font(.caption2.bold())
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(color.opacity(0.14))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
}

private struct DetailMetric: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.headline)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color.gray.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 18))
    }
}

private enum RecommendationAction {
    case approve
    case reject
    case apply
}

private struct RecommendationCard: View {
    let recommendation: ManagerRecommendation
    let busyKey: String?
    let canViewSensitiveOperations: Bool
    let onAction: (RecommendationAction) -> Void

    private var workflowLabel: String {
        switch recommendation.workflowAction {
        case "purchase_order": return "Create PO"
        case "work_order": return "Start Work Order"
        case "transfer": return "Receive Transfer"
        case "price_review": return "Price Review"
        default: return "Review"
        }
    }

    private var statusColor: Color {
        switch recommendation.status {
        case .approved, .applied: return .green
        case .rejected, .expired: return .gray
        case .queued, .unavailable: return .orange
        default: return .blue
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(recommendation.type.displayName)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(recommendation.title)
                        .font(.headline)
                    HStack(spacing: 8) {
                        Pill(label: recommendation.inventoryType.displayName, color: .gray)
                        Pill(label: recommendation.sourcingStrategy.displayName, color: .purple)
                        if canViewSensitiveOperations, let supplierName = recommendation.supplierName, !supplierName.isEmpty {
                            Pill(label: supplierName, color: .green)
                        }
                    }
                }
                Spacer()
                Text(recommendation.status.displayName)
                    .font(.caption.bold())
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(statusColor.opacity(0.14))
                    .foregroundStyle(statusColor)
                    .clipShape(Capsule())
            }

            Text(recommendation.rationale)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            HStack(spacing: 12) {
                Label("\(Int(recommendation.confidence * 100))%", systemImage: "target")
                if let suggestedPrice = recommendation.suggestedPrice {
                    Label(suggestedPrice.formatted(.currency(code: "SGD")), systemImage: "tag")
                } else if let suggestedQty = recommendation.suggestedOrderQty {
                    Label("\(suggestedQty) units", systemImage: "cart")
                }
                Label(workflowLabel, systemImage: "arrow.triangle.branch")
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            if let expectedImpact = recommendation.expectedImpact {
                Text(expectedImpact)
                    .font(.caption)
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.blue.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 16))
            }

            HStack {
                if recommendation.status == .pending {
                    Button("Approve") { onAction(.approve) }
                        .buttonStyle(.borderedProminent)
                        .disabled(busyKey == recommendation.id + "approve")
                    Button("Reject") { onAction(.reject) }
                        .buttonStyle(.bordered)
                        .disabled(busyKey == recommendation.id + "reject")
                } else if recommendation.status == .approved {
                    if canViewSensitiveOperations || recommendation.workflowAction == "price_review" {
                        Button("Mark Applied") { onAction(.apply) }
                            .buttonStyle(.borderedProminent)
                            .disabled(busyKey == recommendation.id + "apply")
                    } else {
                        Text("Owner director applies procurement actions.")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            }
        }
        .padding()
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 20))
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .stroke(Color.gray.opacity(0.12), lineWidth: 1)
        )
    }
}

private extension ISO8601DateFormatter {
    static let fractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
}

#Preview {
    InventoryTabView()
        .environment(StoreViewModel())
}
