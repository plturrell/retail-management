import Foundation
import Testing
@testable import retailmanagement

private final class MockURLProtocol: URLProtocol, @unchecked Sendable {
    static var requestHandler: (@Sendable (URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.requestHandler else {
            fatalError("MockURLProtocol.requestHandler must be set before use.")
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

private struct ApprovalBody: Encodable {
    let note: String
}

private enum MockRequestError: Error {
    case invalidMethod(String?)
    case missingHeader(String)
    case invalidBody
    case invalidURL(String?)
}

struct ManagerContractsTests {
    @Test func decodesCanonicalManagerPayloads() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let summaryData = Data(
            """
            {
              "success": true,
              "message": "ok",
              "data": {
                "store_id": "store-1",
                "analysis_status": "completed",
                "last_generated_at": "2026-04-14T00:00:00Z",
                "low_stock_count": 3,
                "anomaly_count": 1,
                "pending_price_recommendations": 2,
                "pending_reorder_recommendations": 4,
                "pending_stock_anomalies": 1,
                "open_purchase_orders": 2,
                "active_work_orders": 1,
                "in_transit_transfers": 1,
                "purchased_units": 12,
                "material_units": 8,
                "finished_units": 5,
                "recent_outcomes": [
                  {
                    "recommendation_id": "rec-1",
                    "sku_id": "sku-1",
                    "title": "Reorder supplier stock",
                    "type": "reorder",
                    "status": "approved",
                    "updated_at": "2026-04-14T01:00:00Z"
                  }
                ]
              }
            }
            """.utf8
        )
        let summary = try decoder.decode(DataResponse<ManagerSummary>.self, from: summaryData)
        #expect(summary.data.pendingReorderRecommendations == 4)
        #expect(summary.data.recentOutcomes.first?.status == .approved)

        let insightData = Data(
            """
            {
              "success": true,
              "message": "ok",
              "data": {
                "inventory_id": "inv-1",
                "sku_id": "sku-1",
                "store_id": "store-1",
                "sku_code": "PRE-001",
                "description": "Supplier pendant",
                "long_description": null,
                "inventory_type": "finished",
                "sourcing_strategy": "supplier_premade",
                "supplier_name": "GemCo",
                "cost_price": 12.0,
                "current_price": 24.0,
                "current_price_valid_until": "2026-05-01",
                "purchased_qty": 2,
                "purchased_incoming_qty": 1,
                "material_qty": 0,
                "material_incoming_qty": 0,
                "material_allocated_qty": 0,
                "finished_qty": 3,
                "finished_allocated_qty": 0,
                "in_transit_qty": 1,
                "active_work_order_count": 0,
                "qty_on_hand": 3,
                "reorder_level": 4,
                "reorder_qty": 6,
                "low_stock": true,
                "anomaly_flag": false,
                "anomaly_reason": null,
                "recent_sales_qty": 7,
                "recent_sales_revenue": 168.0,
                "avg_daily_sales": 0.23,
                "days_of_cover": 13.0,
                "pending_recommendation_count": 1,
                "pending_price_recommendation_count": 0,
                "last_updated": "2026-04-14T01:30:00Z"
              }
            }
            """.utf8
        )
        let insight = try decoder.decode(DataResponse<InventoryInsight>.self, from: insightData)
        #expect(insight.data.inventoryType == .finished)
        #expect(insight.data.sourcingStrategy == .supplierPremade)
        #expect(insight.data.lowStock)

        let supplyData = Data(
            """
            {
              "success": true,
              "message": "ok",
              "data": {
                "store_id": "store-1",
                "supplier_count": 2,
                "open_purchase_orders": 3,
                "active_work_orders": 1,
                "in_transit_transfers": 2,
                "purchased_units": 9,
                "material_units": 11,
                "finished_units": 18,
                "open_recommendation_linked_orders": 2
              }
            }
            """.utf8
        )
        let supplySummary = try decoder.decode(DataResponse<SupplyChainSummary>.self, from: supplyData)
        #expect(supplySummary.data.finishedUnits == 18)
        #expect(supplySummary.data.openPurchaseOrders == 3)
    }

    @Test func networkServicePostsRecommendationApprovalWithBearerToken() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: configuration)
        let service = NetworkService(
            baseURL: "https://retailsg.example",
            session: session,
            authTokenProvider: { "firebase-token" }
        )

        MockURLProtocol.requestHandler = { request in
            guard request.httpMethod == "POST" else {
                throw MockRequestError.invalidMethod(request.httpMethod)
            }
            guard request.url?.absoluteString == "https://retailsg.example/api/stores/store-1/copilot/recommendations/rec-1/approve" else {
                throw MockRequestError.invalidURL(request.url?.absoluteString)
            }
            guard request.value(forHTTPHeaderField: "Authorization") == "Bearer firebase-token" else {
                throw MockRequestError.missingHeader("Authorization")
            }
            let body = try JSONSerialization.jsonObject(with: request.httpBody ?? Data()) as? [String: String]
            guard body?["note"] == "Approve in studio" else {
                throw MockRequestError.invalidBody
            }

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            let payload = Data(
                """
                {
                  "success": true,
                  "message": "ok",
                  "data": {
                    "id": "rec-1",
                    "store_id": "store-1",
                    "sku_id": "sku-1",
                    "inventory_id": "inv-1",
                    "inventory_type": "finished",
                    "sourcing_strategy": "supplier_premade",
                    "supplier_name": "GemCo",
                    "type": "reorder",
                    "status": "approved",
                    "title": "Reorder supplier stock",
                    "rationale": "Stock is low.",
                    "confidence": 0.82,
                    "supporting_metrics": {},
                    "source": "multica_recommendation",
                    "expected_impact": "Reduce stockout risk.",
                    "current_price": 40.0,
                    "suggested_price": null,
                    "suggested_order_qty": 6,
                    "workflow_action": "purchase_order",
                    "analysis_status": "completed",
                    "generated_at": "2026-04-14T00:00:00Z",
                    "decided_at": "2026-04-14T01:00:00Z",
                    "applied_at": null,
                    "note": "Approve in studio"
                  }
                }
                """.utf8
            )
            return (response, payload)
        }

        let response: DataResponse<ManagerRecommendation> = try await service.post(
            endpoint: "/api/stores/store-1/copilot/recommendations/rec-1/approve",
            body: ApprovalBody(note: "Approve in studio")
        )

        #expect(response.data.status == .approved)
        #expect(response.data.workflowAction == "purchase_order")
    }

    @Test func masterDataServicePostsRecommendPricesRequest() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: configuration)
        let service = MasterDataService(
            baseURL: "https://masterdata.example",
            session: session,
            authTokenProvider: { nil }
        )

        MockURLProtocol.requestHandler = { request in
            guard request.httpMethod == "POST" else {
                throw MockRequestError.invalidMethod(request.httpMethod)
            }
            guard request.url?.absoluteString == "https://masterdata.example/api/master-data/ai/recommend_prices" else {
                throw MockRequestError.invalidURL(request.url?.absoluteString)
            }
            guard request.value(forHTTPHeaderField: "Content-Type") == "application/json" else {
                throw MockRequestError.missingHeader("Content-Type")
            }
            let body = try JSONSerialization.jsonObject(with: request.httpBody ?? Data()) as? [String: Any]
            guard (body?["max_targets"] as? Int) == 25 else {
                throw MockRequestError.invalidBody
            }
            guard (body?["target_skus"] as? [String]) == ["SKU-1", "SKU-2"] else {
                throw MockRequestError.invalidBody
            }

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            let payload = Data(
                """
                {
                  "rules_inferred": ["Round to nearest S$5"],
                  "recommendations": [
                    {
                      "sku_code": "SKU-1",
                      "recommended_retail_sgd": 55,
                      "implied_margin_pct": 64,
                      "confidence": "medium",
                      "comparable_skus": ["SKU-A"],
                      "rationale": "Similar crystal decor items land around this bracket."
                    }
                  ],
                  "notes": "Use owner review before publish.",
                  "n_priced_examples": 12,
                  "n_targets": 2
                }
                """.utf8
            )
            return (response, payload)
        }

        let response = try await service.recommendPrices(targetSkus: ["SKU-1", "SKU-2"], maxTargets: 25)

        #expect(response.recommendations.count == 1)
        #expect(response.recommendations.first?.skuCode == "SKU-1")
        #expect(response.recommendations.first?.confidence == .medium)
        #expect(response.targetCount == 2)
    }
}
