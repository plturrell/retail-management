//
//  MasterData.swift
//  retailmanagement
//
//  Codable mirrors of the shared auth-protected backend master-data API.
//

import Foundation

struct MasterDataProductRow: Codable, Identifiable, Hashable, Sendable {
    var id: String { skuCode }

    let skuCode: String
    let internalCode: String?
    let supplierId: String?
    let supplierName: String?
    let description: String?
    let longDescription: String?
    let productType: String?
    let material: String?
    let category: String?
    let size: String?
    let qtyOnHand: Double?
    let costPrice: Double?
    let costCurrency: String?
    let retailPrice: Double?
    let retailPriceNote: String?
    let retailPriceSetAt: String?
    let saleReady: Bool?
    let blockSales: Bool?
    let needsRetailPrice: Bool?
    let needsReview: Bool?
    let stockingLocation: String?
    let necPlu: String?

    enum CodingKeys: String, CodingKey {
        case skuCode = "sku_code"
        case internalCode = "internal_code"
        case supplierId = "supplier_id"
        case supplierName = "supplier_name"
        case description
        case longDescription = "long_description"
        case productType = "product_type"
        case material
        case category
        case size
        case qtyOnHand = "qty_on_hand"
        case costPrice = "cost_price"
        case costCurrency = "cost_currency"
        case retailPrice = "retail_price"
        case retailPriceNote = "retail_price_note"
        case retailPriceSetAt = "retail_price_set_at"
        case saleReady = "sale_ready"
        case blockSales = "block_sales"
        case needsRetailPrice = "needs_retail_price"
        case needsReview = "needs_review"
        case stockingLocation = "stocking_location"
        case necPlu = "nec_plu"
    }
}

struct MasterDataProductPatch: Codable, Sendable {
    var retailPrice: Double?
    var saleReady: Bool?
    var blockSales: Bool?
    var notes: String?

    enum CodingKeys: String, CodingKey {
        case retailPrice = "retail_price"
        case saleReady = "sale_ready"
        case blockSales = "block_sales"
        case notes
    }
}

struct MasterDataStats: Codable, Sendable {
    let total: Int
    let saleReady: Int
    let needsPriceFlag: Int
    let needsReviewFlag: Int
    let saleReadyMissingPrice: Int
    let bySupplier: [String: Int]

    enum CodingKeys: String, CodingKey {
        case total
        case saleReady = "sale_ready"
        case needsPriceFlag = "needs_price_flag"
        case needsReviewFlag = "needs_review_flag"
        case saleReadyMissingPrice = "sale_ready_missing_price"
        case bySupplier = "by_supplier"
    }
}

struct MasterDataExportResult: Codable, Sendable {
    let ok: Bool
    let exitCode: Int
    let outputPath: String?
    let downloadUrl: String?
    let stdout: String
    let stderr: String

    enum CodingKeys: String, CodingKey {
        case ok
        case exitCode = "exit_code"
        case outputPath = "output_path"
        case downloadUrl = "download_url"
        case stdout
        case stderr
    }
}

struct MasterDataProductsResponse: Codable, Sendable {
    let count: Int
    let products: [MasterDataProductRow]
}

// MARK: - Publish price to POS (Firestore prices/* doc)

struct MasterDataPublishPriceRequest: Codable, Sendable {
    let retailPrice: Double
    let storeCode: String
    let currency: String
    let taxCode: String
    let expectedActivePriceId: String?

    init(
        retailPrice: Double,
        storeCode: String = "JEWEL-01",
        currency: String = "SGD",
        taxCode: String = "G",
        expectedActivePriceId: String? = nil
    ) {
        self.retailPrice = retailPrice
        self.storeCode = storeCode
        self.currency = currency
        self.taxCode = taxCode
        self.expectedActivePriceId = expectedActivePriceId
    }

    enum CodingKeys: String, CodingKey {
        case retailPrice = "retail_price"
        case storeCode = "store_code"
        case currency
        case taxCode = "tax_code"
        case expectedActivePriceId = "expected_active_price_id"
    }
}

struct MasterDataPublishResult: Codable, Sendable {
    let ok: Bool
    let sku: String
    let pluCode: String
    let priceId: String
    let retailPrice: Double
    let validFrom: String
    let validTo: String
    let supersededPriceIds: [String]?
    let product: MasterDataProductRow?

    enum CodingKeys: String, CodingKey {
        case ok
        case sku
        case pluCode = "plu_code"
        case priceId = "price_id"
        case retailPrice = "retail_price"
        case validFrom = "valid_from"
        case validTo = "valid_to"
        case supersededPriceIds = "superseded_price_ids"
        case product
    }
}

// MARK: - Invoice ingest (DeepSeek OCR preview / commit)

struct IngestPreviewItem: Codable, Hashable, Sendable, Identifiable {
    var id: String { (supplierItemCode ?? "") + "::" + String(lineNumber ?? -1) }

    let lineNumber: Int?
    let supplierItemCode: String?
    let productNameEn: String?
    let material: String?
    let productType: String?
    let size: String?
    let quantity: Int?
    let unitPriceCny: Double?
    let proposedSku: String?
    let proposedPlu: String?
    let proposedCostSgd: Double?
    let alreadyExists: Bool?
    let existingSku: String?
    let skipReason: String?

    enum CodingKeys: String, CodingKey {
        case lineNumber = "line_number"
        case supplierItemCode = "supplier_item_code"
        case productNameEn = "product_name_en"
        case material
        case productType = "product_type"
        case size
        case quantity
        case unitPriceCny = "unit_price_cny"
        case proposedSku = "proposed_sku"
        case proposedPlu = "proposed_plu"
        case proposedCostSgd = "proposed_cost_sgd"
        case alreadyExists = "already_exists"
        case existingSku = "existing_sku"
        case skipReason = "skip_reason"
    }
}

struct IngestPreviewSummary: Codable, Sendable {
    let totalLines: Int
    let newSkus: Int
    let alreadyExists: Int
    let skipped: Int

    enum CodingKeys: String, CodingKey {
        case totalLines = "total_lines"
        case newSkus = "new_skus"
        case alreadyExists = "already_exists"
        case skipped
    }
}

struct IngestPreview: Codable, Sendable {
    let uploadId: String
    let documentType: String?
    let documentNumber: String?
    let documentDate: String?
    let supplierName: String?
    let currency: String?
    let documentTotal: Double?
    let items: [IngestPreviewItem]
    let summary: IngestPreviewSummary

    enum CodingKeys: String, CodingKey {
        case uploadId = "upload_id"
        case documentType = "document_type"
        case documentNumber = "document_number"
        case documentDate = "document_date"
        case supplierName = "supplier_name"
        case currency
        case documentTotal = "document_total"
        case items
        case summary
    }
}

struct IngestCommitRequest: Codable, Sendable {
    let uploadId: String
    let items: [IngestPreviewItem]
    let supplierId: String
    let supplierName: String
    let orderNumber: String?

    enum CodingKeys: String, CodingKey {
        case uploadId = "upload_id"
        case items
        case supplierId = "supplier_id"
        case supplierName = "supplier_name"
        case orderNumber = "order_number"
    }
}

struct IngestCommitResult: Codable, Sendable {
    let added: Int
    let skipped: Int
    let addedEntries: [MasterDataProductRow]

    enum CodingKeys: String, CodingKey {
        case added
        case skipped
        case addedEntries = "added_entries"
    }
}

// MARK: - AI price recommender

enum PriceRecommendationConfidence: String, Codable, Sendable {
    case low
    case medium
    case high

    var label: String { rawValue.capitalized }
}

struct PriceRecommendation: Codable, Hashable, Sendable, Identifiable {
    let skuCode: String
    let recommendedRetailSgd: Double
    let impliedMarginPct: Int?
    let confidence: PriceRecommendationConfidence
    let comparableSkus: [String]?
    let rationale: String

    var id: String { skuCode }

    enum CodingKeys: String, CodingKey {
        case skuCode = "sku_code"
        case recommendedRetailSgd = "recommended_retail_sgd"
        case impliedMarginPct = "implied_margin_pct"
        case confidence
        case comparableSkus = "comparable_skus"
        case rationale
    }
}

struct PriceRecommendationsResponse: Codable, Sendable {
    let rulesInferred: [String]?
    let recommendations: [PriceRecommendation]
    let notes: String?
    let pricedExamplesCount: Int?
    let targetCount: Int?

    enum CodingKeys: String, CodingKey {
        case rulesInferred = "rules_inferred"
        case recommendations
        case notes
        case pricedExamplesCount = "n_priced_examples"
        case targetCount = "n_targets"
    }
}

struct RecommendPricesRequest: Codable, Sendable {
    let targetSkus: [String]?
    let maxTargets: Int?

    enum CodingKeys: String, CodingKey {
        case targetSkus = "target_skus"
        case maxTargets = "max_targets"
    }
}
