//
//  MasterDataViewModel.swift
//  retailmanagement
//
//  Drives the MasterDataView — the iPad/macOS twin of the React price-entry
//  page. Talks to the LAN-bound mini-server via MasterDataService.
//

import Foundation
import Observation

enum MasterDataSaveState: Equatable, Sendable {
    case idle
    case saving
    case saved
    case error(String)
}

struct MasterDataRowDraft: Identifiable, Sendable {
    let id: String          // sku_code
    var product: MasterDataProductRow
    var draftPrice: String
    var draftNotes: String
    var saleReady: Bool
    var save: MasterDataSaveState

    init(product: MasterDataProductRow) {
        self.id = product.skuCode
        self.product = product
        if let price = product.retailPrice { self.draftPrice = String(format: "%g", price) }
        else { self.draftPrice = "" }
        self.draftNotes = product.retailPriceNote ?? ""
        self.saleReady = product.saleReady ?? false
        self.save = .idle
    }
}

enum MasterDataIngestState: Sendable {
    case idle
    case uploading(filename: String)
    case preview(IngestPreview, selected: Set<String>)
    case committing
    case error(String)
}

enum MasterDataRecommendationState: Sendable {
    case idle
    case generating
    case preview(PriceRecommendationsResponse, selected: Set<String>)
    case applying
    case error(String)
}

enum MasterDataVisualSearchState: Sendable {
    case idle
    case searching(filename: String)
    case result(VisualSearchResponse)
    case error(String)
}

enum MasterDataBulkState: Sendable {
    case idle
    case running
    case done(BulkSaleReadyResult)
    case error(String)
}

@MainActor
@Observable
final class MasterDataViewModel {
    var stats: MasterDataStats?
    var rows: [MasterDataRowDraft] = []
    var isLoading = false
    var globalError: String?

    // Filter state
    var search = ""
    var supplierFilter: String = "all"
    var purchasedOnly: Bool = true
    var needsPriceOnly: Bool = true

    // Export panel state
    var isExporting = false
    var lastExport: MasterDataExportResult?

    // Invoice ingest state
    var ingest: MasterDataIngestState = .idle
    var recommendations: MasterDataRecommendationState = .idle
    var visualSearch: MasterDataVisualSearchState = .idle
    var bulk: MasterDataBulkState = .idle

    private let service: MasterDataService

    init(service: MasterDataService? = nil) {
        self.service = service ?? MasterDataService.shared
    }

    // MARK: - Loading

    func load() async {
        isLoading = true
        globalError = nil
        do {
            async let statsCall = service.stats(purchasedOnly: purchasedOnly)
            async let productsCall = service.listProducts(
                launchOnly: true,
                needsPrice: needsPriceOnly,
                purchasedOnly: purchasedOnly
            )
            let (s, p) = try await (statsCall, productsCall)
            stats = s
            rows = p.products.map(MasterDataRowDraft.init(product:))
        } catch {
            globalError = error.localizedDescription
        }
        isLoading = false
    }

    var filteredRows: [MasterDataRowDraft] {
        let q = search.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return rows.filter { r in
            if supplierFilter != "all" {
                let sup = r.product.supplierId ?? "(none)"
                if sup != supplierFilter { return false }
            }
            if !q.isEmpty {
                let hay = [
                    r.product.skuCode,
                    r.product.internalCode ?? "",
                    r.product.description ?? "",
                    r.product.material ?? "",
                    r.product.productType ?? "",
                    r.product.necPlu ?? "",
                ].joined(separator: " ").lowercased()
                if !hay.contains(q) { return false }
            }
            return true
        }
    }

    var supplierOptions: [String] {
        let codes = Set(rows.map { $0.product.supplierId ?? "(none)" })
        return Array(codes).sorted()
    }

    // MARK: - Mutations

    func updateRow(_ id: String, transform: (inout MasterDataRowDraft) -> Void) {
        guard let idx = rows.firstIndex(where: { $0.id == id }) else { return }
        transform(&rows[idx])
    }

    func saveRow(id sku: String) async {
        guard let idx = rows.firstIndex(where: { $0.id == sku }) else { return }
        let row = rows[idx]
        guard let price = Double(row.draftPrice), price > 0 else {
            rows[idx].save = .error("Enter a positive price")
            return
        }
        rows[idx].save = .saving
        do {
            let updated = try await service.patchProduct(
                sku: sku,
                patch: MasterDataProductPatch(
                    retailPrice: price,
                    saleReady: row.saleReady,
                    blockSales: nil,
                    notes: row.draftNotes.isEmpty ? nil : row.draftNotes
                )
            )
            if let i = rows.firstIndex(where: { $0.id == sku }) {
                rows[i].product = updated
                rows[i].save = .saved
            }
        } catch {
            if let i = rows.firstIndex(where: { $0.id == sku }) {
                rows[i].save = .error(error.localizedDescription)
            }
        }
    }

    // MARK: - Excel export

    func regenerateExcel() async {
        isExporting = true
        lastExport = nil
        do {
            lastExport = try await service.exportNecJewel()
        } catch {
            lastExport = MasterDataExportResult(
                ok: false,
                exitCode: -1,
                outputPath: nil,
                downloadUrl: nil,
                stdout: "",
                stderr: error.localizedDescription
            )
        }
        isExporting = false
    }

    // MARK: - Invoice ingest

    func uploadInvoice(fileURL: URL, mimeType: String) async {
        ingest = .uploading(filename: fileURL.lastPathComponent)
        do {
            let preview = try await service.ingestInvoice(fileURL: fileURL, mimeType: mimeType)
            let initialSelection = Set(
                preview.items
                    .filter { $0.proposedSku != nil && !($0.alreadyExists ?? false) && $0.skipReason == nil }
                    .compactMap { $0.supplierItemCode }
            )
            ingest = .preview(preview, selected: initialSelection)
        } catch {
            ingest = .error(error.localizedDescription)
        }
    }

    func togglePreviewItem(code: String) {
        guard case .preview(let preview, var sel) = ingest else { return }
        if sel.contains(code) { sel.remove(code) } else { sel.insert(code) }
        ingest = .preview(preview, selected: sel)
    }

    func cancelIngest() { ingest = .idle }

    func commitIngest() async {
        guard case .preview(let preview, let sel) = ingest else { return }
        let items = preview.items.filter { item in
            guard let code = item.supplierItemCode else { return false }
            return sel.contains(code)
        }
        guard !items.isEmpty else { return }
        ingest = .committing
        do {
            _ = try await service.commitInvoice(
                IngestCommitRequest(
                    uploadId: preview.uploadId,
                    items: items,
                    supplierId: "CN-001",
                    supplierName: "Hengwei Craft",
                    orderNumber: preview.documentNumber
                )
            )
            ingest = .idle
            await load()
        } catch {
            ingest = .error(error.localizedDescription)
        }
    }

    // MARK: - AI price recommender

    func generatePriceRecommendations() async {
        recommendations = .generating
        do {
            let response = try await service.recommendPrices()
            let selected = Set(response.recommendations.map(\.skuCode))
            recommendations = .preview(response, selected: selected)
        } catch {
            recommendations = .error(error.localizedDescription)
        }
    }

    func toggleRecommendation(sku: String) {
        guard case .preview(let response, var selected) = recommendations else { return }
        if selected.contains(sku) { selected.remove(sku) } else { selected.insert(sku) }
        recommendations = .preview(response, selected: selected)
    }

    func cancelRecommendations() {
        recommendations = .idle
    }

    func applyRecommendations() async -> Int {
        guard case .preview(let response, let selected) = recommendations else { return 0 }
        let items = response.recommendations.filter { selected.contains($0.skuCode) }
        guard !items.isEmpty else { return 0 }

        recommendations = .applying
        do {
            for recommendation in items {
                guard let row = rows.first(where: { $0.id == recommendation.skuCode }) else { continue }
                let note = recommendationNote(
                    existing: row.draftNotes,
                    recommendation: recommendation
                )
                _ = try await service.patchProduct(
                    sku: recommendation.skuCode,
                    patch: MasterDataProductPatch(
                        retailPrice: recommendation.recommendedRetailSgd,
                        saleReady: row.saleReady,
                        blockSales: nil,
                        notes: note
                    )
                )
            }
            recommendations = .idle
            await load()
            return items.count
        } catch {
            recommendations = .error(error.localizedDescription)
            return 0
        }
    }

    // MARK: - Visual search

    func runVisualSearch(fileURL: URL, mimeType: String, topK: Int = 8) async {
        visualSearch = .searching(filename: fileURL.lastPathComponent)
        do {
            let response = try await service.visualSearch(fileURL: fileURL, mimeType: mimeType, topK: topK)
            visualSearch = .result(response)
        } catch {
            visualSearch = .error(error.localizedDescription)
        }
    }

    func cancelVisualSearch() { visualSearch = .idle }

    // MARK: - Bulk sale-ready

    func bulkMarkSaleReady() async {
        bulk = .running
        do {
            let result = try await service.bulkSaleReady(
                purchasedOnly: true,
                requirePrice: true
            )
            bulk = .done(result)
            await load()
        } catch {
            bulk = .error(error.localizedDescription)
        }
    }

    func dismissBulk() { bulk = .idle }

    private func recommendationNote(existing: String, recommendation: PriceRecommendation) -> String {
        let comparableList = recommendation.comparableSkus ?? []
        let comparable = comparableList.isEmpty ? "" : " comps: \(comparableList.joined(separator: ", "))"
        let aiNote = "AI \(recommendation.confidence.rawValue): \(recommendation.rationale)\(comparable)"
        if existing.isEmpty { return aiNote }
        return "\(existing) | \(aiNote)"
    }
}
