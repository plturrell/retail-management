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

    func loadMockData() async {
        isLoading = true
        // Simulate network delay
        try? await Task.sleep(nanoseconds: 500_000_000)

        // Hardcoded mock of docs/suppliers/hengweicraft/orders/364-365.json
        // In production, this comes from an authenticated FastAPI /api/supplier-review endpoint
        let mockJSON = """
        {
          "order_number": "364-365",
          "order_date": "2026-03-26",
          "supplier_id": "CN-001",
          "supplier_name": "Hengwei Craft",
          "currency": "CNY",
          "source_document_total_amount": 11046,
          "document_payment_status": "cash_paid",
          "item_reconciliation_status": "needs_follow_up",
          "line_items": [
            {
              "source_line_number": 1,
              "supplier_item_code": "A339A",
              "unit_cost_cny": 120,
              "quantity": 5,
              "line_total_cny": 600,
              "size": "8*8*10",
              "material_description": "Copper, Natural mineral stone"
            },
            {
              "source_line_number": 2,
              "supplier_item_code": "A339B",
              "unit_cost_cny": 105,
              "quantity": 5,
              "line_total_cny": 525,
              "size": "11.5*11.5*6",
              "material_description": "Copper, Natural mineral stone"
            },
            {
              "source_line_number": 3,
              "supplier_item_code": "H1444A",
              "unit_cost_cny": 360,
              "quantity": 2,
              "line_total_cny": 720,
              "size": "18*18*14",
              "material_description": "Copper, Natural brown crystal marble"
            },
            {
              "source_line_number": 10,
              "supplier_item_code": null,
              "display_name": "Guardian artwork",
              "unit_cost_cny": 2000,
              "quantity": 1,
              "line_total_cny": 2000,
              "material_description": "Malachite Tin"
            }
          ]
        }
        """

        do {
            let decoder = JSONDecoder()
            let record = try decoder.decode(VendorReviewOrderRecord.self, from: Data(mockJSON.utf8))
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
            self.error = error.localizedDescription
        }
        isLoading = false
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
