import Foundation
import Testing
@testable import retailmanagement

private final class PublishMockURLProtocol: URLProtocol, @unchecked Sendable {
    static var requestHandler: (@Sendable (URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.requestHandler else {
            fatalError("PublishMockURLProtocol.requestHandler must be set before use.")
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

private enum PublishMockError: Error {
    case invalidMethod(String?)
    case invalidURL(String?)
    case invalidBody
}

struct MasterDataPublishPriceTests {
    @Test func publishPricePostsExpectedBodyAndDecodesResult() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [PublishMockURLProtocol.self]
        let session = URLSession(configuration: configuration)
        let service = MasterDataService(
            baseURL: "https://masterdata.example",
            session: session,
            authTokenProvider: { nil }
        )

        PublishMockURLProtocol.requestHandler = { request in
            guard request.httpMethod == "POST" else {
                throw PublishMockError.invalidMethod(request.httpMethod)
            }
            guard request.url?.absoluteString == "https://masterdata.example/api/master-data/products/SKU-XYZ/publish_price" else {
                throw PublishMockError.invalidURL(request.url?.absoluteString)
            }
            // URLProtocol strips the body off the request — read it from the input stream.
            let bodyData = request.httpBody ?? request.httpBodyStream.flatMap { stream -> Data? in
                stream.open()
                defer { stream.close() }
                var data = Data()
                let buf = UnsafeMutablePointer<UInt8>.allocate(capacity: 4096)
                defer { buf.deallocate() }
                while stream.hasBytesAvailable {
                    let n = stream.read(buf, maxLength: 4096)
                    if n <= 0 { break }
                    data.append(buf, count: n)
                }
                return data
            } ?? Data()
            let body = try JSONSerialization.jsonObject(with: bodyData) as? [String: Any]
            guard (body?["retail_price"] as? Double) == 88.0 else { throw PublishMockError.invalidBody }
            guard (body?["store_code"] as? String) == "JEWEL-01" else { throw PublishMockError.invalidBody }
            guard (body?["currency"] as? String) == "SGD" else { throw PublishMockError.invalidBody }
            guard (body?["tax_code"] as? String) == "G" else { throw PublishMockError.invalidBody }

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            let payload = Data(
                """
                {
                  "ok": true,
                  "sku": "SKU-XYZ",
                  "plu_code": "00012345",
                  "price_id": "price-abc",
                  "retail_price": 88.0,
                  "valid_from": "2026-04-29T00:00:00Z",
                  "valid_to": "2099-12-31T23:59:59Z",
                  "superseded_price_ids": ["price-old"]
                }
                """.utf8
            )
            return (response, payload)
        }

        let result = try await service.publishPrice(
            sku: "SKU-XYZ",
            request: MasterDataPublishPriceRequest(retailPrice: 88.0)
        )

        #expect(result.ok)
        #expect(result.sku == "SKU-XYZ")
        #expect(result.pluCode == "00012345")
        #expect(result.priceId == "price-abc")
        #expect(result.retailPrice == 88.0)
        #expect(result.supersededPriceIds == ["price-old"])
    }

    @Test func publishPriceSurfacesServer403AsBadStatus() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [PublishMockURLProtocol.self]
        let session = URLSession(configuration: configuration)
        let service = MasterDataService(
            baseURL: "https://masterdata.example",
            session: session,
            authTokenProvider: { nil }
        )

        PublishMockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 403,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(#"{"detail":"not on publisher allowlist"}"#.utf8))
        }

        do {
            _ = try await service.publishPrice(
                sku: "SKU-XYZ",
                request: MasterDataPublishPriceRequest(retailPrice: 88.0)
            )
            Issue.record("Expected publishPrice to throw on 403")
        } catch let MasterDataServiceError.badStatus(code, _) {
            #expect(code == 403)
        } catch {
            Issue.record("Expected MasterDataServiceError.badStatus, got \(error)")
        }
    }
}
