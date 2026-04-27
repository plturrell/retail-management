//
//  MasterDataService.swift
//  retailmanagement
//
//  HTTP client for the local master-data mini-server
//  (tools/server/master_data_api.py). Distinct from NetworkService because:
//    - The mini-server is unauthenticated (LAN-only for May 1 launch)
//    - The base URL is configurable per-device (iPad points at the Mac's LAN IP)
//
//  Track 2 will replace this with calls through the main NetworkService once
//  these endpoints land in the auth-protected backend.
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

    /// Persisted base URL — defaults to localhost. Set this on the iPad to the
    /// Mac's LAN IP (e.g. http://192.168.1.42:8765) so it can reach the
    /// mini-server running on the shop's Mac.
    private let baseUrlKey = "masterDataApiBase"
    static let defaultBase = "http://localhost:8765"

    var baseUrl: String {
        get { UserDefaults.standard.string(forKey: baseUrlKey) ?? Self.defaultBase }
        set { UserDefaults.standard.set(newValue, forKey: baseUrlKey) }
    }

    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(session: URLSession? = nil) {
        if let session {
            self.session = session
        } else {
            let cfg = URLSessionConfiguration.default
            cfg.timeoutIntervalForRequest = 120
            cfg.timeoutIntervalForResource = 600  // OCR runs can take a minute+
            cfg.waitsForConnectivity = false
            self.session = URLSession(configuration: cfg)
        }
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    // MARK: - URL building

    private func url(_ path: String, query: [URLQueryItem] = []) -> URL? {
        let trimmed = baseUrl.hasSuffix("/") ? String(baseUrl.dropLast()) : baseUrl
        guard var comps = URLComponents(string: trimmed + path) else { return nil }
        if !query.isEmpty { comps.queryItems = query }
        return comps.url
    }

    private func send<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw MasterDataServiceError.badStatus(0, body: "no response")
            }
            guard (200..<300).contains(http.statusCode) else {
                let body = String(data: data, encoding: .utf8) ?? ""
                throw MasterDataServiceError.badStatus(http.statusCode, body: body)
            }
            do {
                return try decoder.decode(T.self, from: data)
            } catch {
                throw MasterDataServiceError.decoding(error)
            }
        } catch let error as MasterDataServiceError {
            throw error
        } catch {
            throw MasterDataServiceError.transport(error)
        }
    }

    // MARK: - Endpoints

    func health() async throws -> [String: AnyCodable] {
        guard let u = url("/api/health") else { throw MasterDataServiceError.transport(URLError(.badURL)) }
        return try await send(URLRequest(url: u), as: [String: AnyCodable].self)
    }

    func stats() async throws -> MasterDataStats {
        guard let u = url("/api/stats") else { throw MasterDataServiceError.transport(URLError(.badURL)) }
        return try await send(URLRequest(url: u), as: MasterDataStats.self)
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
        guard let u = url("/api/products", query: q) else { throw MasterDataServiceError.transport(URLError(.badURL)) }
        return try await send(URLRequest(url: u), as: MasterDataProductsResponse.self)
    }

    func patchProduct(sku: String, patch: MasterDataProductPatch) async throws -> MasterDataProductRow {
        let escaped = sku.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sku
        guard let u = url("/api/products/\(escaped)") else { throw MasterDataServiceError.transport(URLError(.badURL)) }
        var req = URLRequest(url: u)
        req.httpMethod = "PATCH"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(patch)
        return try await send(req, as: MasterDataProductRow.self)
    }

    func exportNecJewel() async throws -> MasterDataExportResult {
        guard let u = url("/api/export/nec_jewel") else { throw MasterDataServiceError.transport(URLError(.badURL)) }
        var req = URLRequest(url: u)
        req.httpMethod = "POST"
        return try await send(req, as: MasterDataExportResult.self)
    }

    /// Upload a supplier PDF/image and run DeepSeek OCR. Returns a preview the
    /// user reviews before committing to master_product_list.json.
    func ingestInvoice(fileURL: URL, mimeType: String) async throws -> IngestPreview {
        guard let u = url("/api/ingest/invoice") else { throw MasterDataServiceError.transport(URLError(.badURL)) }
        let data: Data
        do {
            data = try Data(contentsOf: fileURL)
        } catch {
            throw MasterDataServiceError.missingFile
        }

        let boundary = "Boundary-\(UUID().uuidString)"
        var req = URLRequest(url: u)
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        let filename = fileURL.lastPathComponent
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body

        return try await send(req, as: IngestPreview.self)
    }

    func commitInvoice(_ payload: IngestCommitRequest) async throws -> IngestCommitResult {
        guard let u = url("/api/ingest/invoice/commit") else { throw MasterDataServiceError.transport(URLError(.badURL)) }
        var req = URLRequest(url: u)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(payload)
        return try await send(req, as: IngestCommitResult.self)
    }

    func recommendPrices(targetSkus: [String]? = nil, maxTargets: Int = 80) async throws -> PriceRecommendationsResponse {
        guard let u = url("/api/ai/recommend_prices") else { throw MasterDataServiceError.transport(URLError(.badURL)) }
        var req = URLRequest(url: u)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(
            RecommendPricesRequest(
                targetSkus: targetSkus,
                maxTargets: maxTargets
            )
        )
        return try await send(req, as: PriceRecommendationsResponse.self)
    }
}

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
