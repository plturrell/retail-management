//
//  PerformanceViewModel.swift
//  retailmanagement
//

import Foundation
import Observation

@MainActor
@Observable
final class PerformanceViewModel {
    var overview: StaffPerformanceOverview?
    var myPerformance: StaffPerformanceItem?
    var insights: StaffInsightsResponse?
    var salesByStaff: [StaffSalesSummary] = []
    var isLoading = false
    var errorMessage: String?

    /// Period for performance data (default: last 30 days)
    var periodDays: Int = 30

    var periodFromDate: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let from = Calendar.current.date(byAdding: .day, value: -periodDays, to: Date()) ?? Date()
        return formatter.string(from: from)
    }

    var periodToDate: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: Date())
    }

    func fetchPerformance(storeId: String, userId: String) async {
        isLoading = true
        errorMessage = nil

        do {
            // Fetch staff performance overview
            let perfResponse: StaffPerformanceOverview = try await NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/analytics/staff-performance",
                queryItems: [
                    URLQueryItem(name: "from", value: periodFromDate),
                    URLQueryItem(name: "to", value: periodToDate),
                ]
            )
            overview = perfResponse
            myPerformance = perfResponse.staff.first { $0.userId == userId }

            // Fetch sales by staff
            let salesResponse: DataResponse<[StaffSalesSummary]> = try await NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/sales/by-staff",
                queryItems: [
                    URLQueryItem(name: "from", value: periodFromDate),
                    URLQueryItem(name: "to", value: periodToDate),
                ]
            )
            salesByStaff = salesResponse.data
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func fetchInsights(storeId: String, userId: String) async {
        do {
            let response: StaffInsightsResponse = try await NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/analytics/staff/\(userId)/insights"
            )
            insights = response
        } catch {
            // AI insights may not be available
        }
    }
}
