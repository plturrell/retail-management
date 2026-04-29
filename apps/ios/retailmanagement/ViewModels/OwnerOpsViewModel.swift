import Foundation
import Observation

@Observable
class OwnerOpsViewModel {
    var summary: ManagerSummary?
    var recommendations: [ManagerRecommendation] = []
    var isLoading = false
    var error: String?

    private let networkService: NetworkService

    init(networkService: NetworkService) {
        self.networkService = networkService
    }

    func loadDashboard(storeId: String) async {
        isLoading = true
        error = nil

        do {
            async let summaryReq: DataResponse<ManagerSummary> = networkService.get(endpoint: "/api/stores/\(storeId)/copilot/summary")
            async let recsReq: DataResponse<[ManagerRecommendation]> = networkService.get(endpoint: "/api/stores/\(storeId)/copilot/recommendations")

            let (summaryResp, recsResp) = try await (summaryReq, recsReq)

            self.summary = summaryResp.data
            self.recommendations = recsResp.data
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func approveRecommendation(storeId: String, recommendationId: String, note: String) async {
        do {
            struct ApprovalBody: Encodable {
                let note: String
            }
            
            let _: DataResponse<ManagerRecommendation> = try await networkService.post(
                endpoint: "/api/stores/\(storeId)/copilot/recommendations/\(recommendationId)/approve",
                body: ApprovalBody(note: note)
            )
            // Refresh dashboard
            await loadDashboard(storeId: storeId)
        } catch {
            self.error = "Failed to approve: \(error.localizedDescription)"
        }
    }
}
