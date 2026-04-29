//
//  MasterDataService.swift
//  retailmanagement
//
//  HTTP client for the auth-protected backend master-data API.
//

import Foundation

enum MasterDataServiceError: LocalizedError {
    case badStatus(Int, body: String)
    case decoding(Error)
    case transport(Error)
    case missingFile

    var errorDescription: String? {
        switch self {
        case .badStatus(let code, let body):
            return "Master-data API responded \(code): \(body.prefix(200))"
        case .decoding(let err):
            return "Couldn't decode master-data response: \(err.localizedDescription)"
        case .transport(let err):
            return "Couldn't reach master-data API: \(err.localizedDescription)"
        case .missingFile:
            return "Couldn't read the file you picked."
        }
    }
}

final class MasterDataService: @unchecked Sendable {
    static let shared = MasterDataService()

    private let network: NetworkService

    init(
        baseURL: String? = nil,
        session: URLSession = .shared,
        authTokenProvider: (@Sendable () async throws -> String?)? = nil
    ) {
        self.network = NetworkService(
            baseURL: baseURL,
            session: session,
            authTokenProvider: authTokenProvider
        )
    }

    // MARK: - Endpoints

    func health() async throws -> [String: AnyCodable] {
        try await network.get(endpoint: "/api/master-data/health")
    }

    func stats() async throws -> MasterDataStats {
        try await network.get(endpoint: "/api/master-data/stats")
    }

    func listProducts(
        launchOnly: Bool = true,
        needsPrice: Bool = false,
        purchasedOnly: Bool = true,
        supplier: String? = nil
    ) async throws -> MasterDataProductsResponse {
        var q: [URLQueryItem] = [
            URLQueryItem(name: "launch_only", value: String(launchOnly)),
            URLQueryItem(name: "needs_price", value: String(needsPrice)),
            URLQueryItem(name: "purchased_only", value: String(purchasedOnly)),
        ]
        if let supplier { q.append(URLQueryItem(name: "supplier", value: supplier)) }
        return try await network.get(endpoint: "/api/master-data/products", queryItems: q)
    }

    func patchProduct(sku: String, patch: MasterDataProductPatch) async throws -> MasterDataProductRow {
        let escaped = sku.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sku
        return try await network.patch(endpoint: "/api/master-data/products/\(escaped)", body: patch)
    }

    /// Publish *sku*'s retail price to Firestore so the POS barcode lookup
    /// can ring it up. Restricted on the server to the publisher email
    /// allowlist (settings.MASTER_DATA_PUBLISHER_EMAILS); non-allowlisted
    /// callers get a 403 surfaced as MasterDataServiceError.badStatus.
    func publishPrice(sku: String, request: MasterDataPublishPriceRequest) async throws -> MasterDataPublishResult {
        let escaped = sku.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sku
        return try await network.post(endpoint: "/api/master-data/products/\(escaped)/publish_price", body: request)
    }

    func exportNecJewel() async throws -> MasterDataExportResult {
        return try await network.post(endpoint: "/api/master-data/export/nec_jewel", body: EmptyBody())
    }

    /// Upload a supplier PDF/image and run DeepSeek OCR. Returns a preview the
    /// user reviews before committing to master_product_list.json.
    func ingestInvoice(fileURL: URL, mimeType: String) async throws -> IngestPreview {
        return try await network.upload(
            endpoint: "/api/master-data/ingest/invoice",
            fileURL: fileURL,
            mimeType: mimeType
        )
    }

    func commitInvoice(_ payload: IngestCommitRequest) async throws -> IngestCommitResult {
        return try await network.post(endpoint: "/api/master-data/ingest/invoice/commit", body: payload)
    }

    func recommendPrices(targetSkus: [String]? = nil, maxTargets: Int = 80) async throws -> PriceRecommendationsResponse {
        return try await network.post(
            endpoint: "/api/master-data/ai/recommend_prices",
            body: RecommendPricesRequest(
                targetSkus: targetSkus,
                maxTargets: maxTargets
            )
        )
    }
}

private struct EmptyBody: Encodable {}

/// Loose-typed JSON value for endpoints whose shape isn't worth a Codable
/// (e.g. /api/health). Avoids dragging in a third-party JSON-any helper.
struct AnyCodable: Codable, Sendable {
    let value: Any

    init(_ value: Any) { self.value = value }

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { value = NSNull() }
        else if let b = try? c.decode(Bool.self) { value = b }
        else if let i = try? c.decode(Int.self) { value = i }
        else if let d = try? c.decode(Double.self) { value = d }
        else if let s = try? c.decode(String.self) { value = s }
        else if let arr = try? c.decode([AnyCodable].self) { value = arr.map(\.value) }
        else if let obj = try? c.decode([String: AnyCodable].self) {
            value = obj.mapValues { $0.value }
        } else { value = NSNull() }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch value {
        case is NSNull: try c.encodeNil()
        case let b as Bool: try c.encode(b)
        case let i as Int: try c.encode(i)
        case let d as Double: try c.encode(d)
        case let s as String: try c.encode(s)
        default: try c.encodeNil()
        }
    }
}
