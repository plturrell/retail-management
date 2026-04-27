//
//  MasterData.swift
//  retailmanagement
//
//  Codable mirrors of the local master-data API
//  (tools/server/master_data_api.py). The mini-server is unauthenticated and
//  LAN-bound for the May 1 Jewel Changi launch — Track 2 will fold these
//  endpoints into the main backend.
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
    let missingCost: Int?
    let bySupplier: [String: Int]
    let purchasedOnly: Bool?

    enum CodingKeys: String, CodingKey {
        case total
        case saleReady = "sale_ready"
        case needsPriceFlag = "needs_price_flag"
        case needsReviewFlag = "needs_review_flag"
        case saleReadyMissingPrice = "sale_ready_missing_price"
        case missingCost = "missing_cost"
        case bySupplier = "by_supplier"
        case purchasedOnly = "purchased_only"
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
    let imageUrl: String?
    let imageMatchConfidence: String?

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
        case imageUrl = "image_url"
        case imageMatchConfidence = "image_match_confidence"
    }
}

struct IngestPreviewPageImage: Codable, Hashable, Sendable, Identifiable {
    var id: Int { pageNumber }
    let pageNumber: Int
    let url: String

    enum CodingKeys: String, CodingKey {
        case pageNumber = "page_number"
        case url
    }
}

struct IngestPreviewSummary: Codable, Sendable {
    let totalLines: Int
    let newSkus: Int
    let alreadyExists: Int
    let skipped: Int
    let imagesExtracted: Int?
    let itemsWithImage: Int?

    enum CodingKeys: String, CodingKey {
        case totalLines = "total_lines"
        case newSkus = "new_skus"
        case alreadyExists = "already_exists"
        case skipped
        case imagesExtracted = "images_extracted"
        case itemsWithImage = "items_with_image"
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
    let pageImages: [IngestPreviewPageImage]?
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
        case pageImages = "page_images"
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

struct BulkSaleReadyRequest: Codable, Sendable {
    let purchasedOnly: Bool
    let requirePrice: Bool
    let requireCost: Bool

    enum CodingKeys: String, CodingKey {
        case purchasedOnly = "purchased_only"
        case requirePrice = "require_price"
        case requireCost = "require_cost"
    }
}

struct BulkSaleReadySkipped: Codable, Sendable {
    let alreadyReady: Int
    let noPrice: Int
    let noCost: Int
    let notPurchased: Int
    let blocked: Int

    enum CodingKeys: String, CodingKey {
        case alreadyReady = "already_ready"
        case noPrice = "no_price"
        case noCost = "no_cost"
        case notPurchased = "not_purchased"
        case blocked
    }
}

struct BulkSaleReadyResult: Codable, Sendable {
    let updated: Int
    let updatedSkus: [String]
    let skipped: BulkSaleReadySkipped

    enum CodingKeys: String, CodingKey {
        case updated
        case updatedSkus = "updated_skus"
        case skipped
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

// MARK: - Visual search (find SKU by photo)

struct VisualSearchMatch: Codable, Hashable, Sendable, Identifiable {
    var id: String { (sku ?? code ?? file ?? "") + "::" + String(rank) }

    let rank: Int
    let code: String?
    let file: String?
    let imageUrl: String?
    let similarity: Double
    let catalogText: String?
    let sku: String?
    let necPlu: String?
    let description: String?
    let retailPrice: Double?
    let qtyOnHand: Double?

    enum CodingKeys: String, CodingKey {
        case rank
        case code
        case file
        case imageUrl = "image_url"
        case similarity
        case catalogText = "catalog_text"
        case sku
        case necPlu = "nec_plu"
        case description
        case retailPrice = "retail_price"
        case qtyOnHand = "qty_on_hand"
    }
}

struct VisualSearchResponse: Codable, Sendable {
    let queryText: String
    let matches: [VisualSearchMatch]
    let catalogSize: Int

    enum CodingKeys: String, CodingKey {
        case queryText = "query_text"
        case matches
        case catalogSize = "catalog_size"
    }
}
