//
//  VendorReviewContracts.swift
//  retailmanagement
//
//  Data models for Supplier Invoice/OCR Review.
//

import Foundation

struct VendorReviewOrderRecord: Codable, Identifiable {
    var id: String { orderNumber }
    let orderNumber: String
    let orderDate: String
    let supplierId: String
    let supplierName: String
    let currency: String
    let sourceDocumentTotalAmount: Double
    let documentPaymentStatus: String
    let itemReconciliationStatus: String?
    let lineItems: [VendorReviewLineItem]

    enum CodingKeys: String, CodingKey {
        case orderNumber = "order_number"
        case orderDate = "order_date"
        case supplierId = "supplier_id"
        case supplierName = "supplier_name"
        case currency
        case sourceDocumentTotalAmount = "source_document_total_amount"
        case documentPaymentStatus = "document_payment_status"
        case itemReconciliationStatus = "item_reconciliation_status"
        case lineItems = "line_items"
    }
}

struct VendorReviewLineItem: Codable, Identifiable {
    var id: String { "\(sourceLineNumber)" }
    let sourceLineNumber: Int
    let supplierItemCode: String?
    let unitCostCny: Double?
    let quantity: Int?
    let lineTotalCny: Double?
    let size: String?
    let materialDescription: String?
    let displayName: String?

    enum CodingKeys: String, CodingKey {
        case sourceLineNumber = "source_line_number"
        case supplierItemCode = "supplier_item_code"
        case unitCostCny = "unit_cost_cny"
        case quantity
        case lineTotalCny = "line_total_cny"
        case size
        case materialDescription = "material_description"
        case displayName = "display_name"
    }
}

// MARK: - Local Workspace State (Persisted)

enum ReviewLineStatus: String, Codable {
    case unreviewed
    case verified
    case needsFollowUp = "needs_follow_up"
}

struct ReviewLineState: Codable {
    var status: ReviewLineStatus
    var note: String
    var targetSkuId: String
    var updatedAt: Date?
}

struct ReviewOrderState: Codable {
    var lines: [String: ReviewLineState]
}

struct SupplierReviewWorkspaceState: Codable {
    var schemaVersion: Int
    var supplierId: String
    var savedAt: Date?
    var orders: [String: ReviewOrderState]
}
