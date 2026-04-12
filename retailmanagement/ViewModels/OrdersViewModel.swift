//
//  OrdersViewModel.swift
//  retailmanagement
//

import Foundation
import Observation

@MainActor
@Observable
final class OrdersViewModel {
    var orders: [Order] = []
    var totalOrders: Int = 0
    var isLoading = false
    var errorMessage: String?
    var filterStatus: OrderStatus?
    var searchText: String = ""

    private var currentStoreId: String?

    func loadOrders(storeId: String) async {
        guard currentStoreId != storeId || orders.isEmpty else { return }
        currentStoreId = storeId
        isLoading = true
        errorMessage = nil

        do {
            let response: PaginatedResponse<Order> = try await NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/orders?page_size=100"
            )
            orders = response.data
            totalOrders = response.total
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    var filteredOrders: [Order] {
        var result = orders
        if let status = filterStatus {
            result = result.filter { $0.status == status }
        }
        if !searchText.isEmpty {
            result = result.filter {
                $0.orderNumber.localizedCaseInsensitiveContains(searchText) ||
                $0.paymentMethod.localizedCaseInsensitiveContains(searchText)
            }
        }
        return result
    }

    var todayRevenue: Double {
        orders.filter { $0.status == .completed }.reduce(0) { $0 + $1.grandTotal }
    }

    var openOrdersCount: Int {
        orders.filter { $0.status == .open }.count
    }

}
