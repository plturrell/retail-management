//
//  VendorReviewViewModel.swift
//  retailmanagement
//
//  Manages the state for Supplier Invoice OCR reconciliation.
//

import Foundation
import Observation
import SwiftUI

@MainActor
@Observable
final class VendorReviewViewModel {
    var order: VendorReviewOrderRecord?
    var workspace: SupplierReviewWorkspaceState
    var isLoading = false
    var error: String?

    let supplierId = "CN-001"

    init() {
        // Load persisted state from UserDefaults
        if let data = UserDefaults.standard.data(forKey: "vendor_review_\(supplierId)"),
           let saved = try? JSONDecoder().decode(SupplierReviewWorkspaceState.self, from: data) {
            self.workspace = saved
        } else {
            self.workspace = SupplierReviewWorkspaceState(
                schemaVersion: 2,
                supplierId: supplierId,
                savedAt: nil,
                orders: [:]
            )
        }
    }

    /// Default order to fetch when the view first appears. In a fuller build
    /// this would come from a list endpoint or user selection.
    static let defaultOrderNumber = "364-365"

    /// Fetch a single supplier order from the live FastAPI endpoint.
    func loadOrder(orderNumber: String = defaultOrderNumber) async {
        isLoading = true
        error = nil
        defer { isLoading = false }

        do {
            let endpoint = "/api/supplier-review/\(supplierId)/orders/\(orderNumber)"
            let record: VendorReviewOrderRecord = try await NetworkService.shared.get(endpoint: endpoint)
            self.order = record

            // Initialize workspace state for this order if missing
            if workspace.orders[record.orderNumber] == nil {
                workspace.orders[record.orderNumber] = ReviewOrderState(lines: [:])
                for line in record.lineItems {
                    let key = String(line.sourceLineNumber)
                    workspace.orders[record.orderNumber]?.lines[key] = ReviewLineState(
                        status: .unreviewed,
                        note: "",
                        targetSkuId: line.supplierItemCode ?? "",
                        updatedAt: nil
                    )
                }
            }
        } catch {
            self.error = "Failed to load supplier order \(orderNumber): \(error.localizedDescription)"
        }
    }

    func updateLineStatus(orderNumber: String, lineKey: String, status: ReviewLineStatus, note: String) {
        guard var orderState = workspace.orders[orderNumber],
              var lineState = orderState.lines[lineKey] else { return }

        lineState.status = status
        lineState.note = note
        lineState.updatedAt = Date()
        orderState.lines[lineKey] = lineState
        workspace.orders[orderNumber] = orderState

        saveWorkspace()
    }

    private func saveWorkspace() {
        workspace.savedAt = Date()
        if let encoded = try? JSONEncoder().encode(workspace) {
            UserDefaults.standard.set(encoded, forKey: "vendor_review_\\(supplierId)")
        }
    }
}
