//
//  InventoryViewModel.swift
//  retailmanagement
//

import Foundation
import Observation

@MainActor
@Observable
final class InventoryViewModel {
    var skus: [SKU] = []
    var categories: [Category] = []
    var brands: [Brand] = []
    var inventoryItems: [InventoryItem] = []
    var totalSKUs: Int = 0
    var isLoading = false
    var errorMessage: String?
    var searchText: String = ""

    private var currentStoreId: String?

    func loadData(storeId: String) async {
        guard currentStoreId != storeId || skus.isEmpty else { return }
        currentStoreId = storeId
        isLoading = true
        errorMessage = nil

        do {
            async let skuResp: PaginatedResponse<SKU> = NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/skus?page_size=500"
            )
            async let catResp: PaginatedResponse<Category> = NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/categories?page_size=500"
            )
            async let brandResp: PaginatedResponse<Brand> = NetworkService.shared.get(
                endpoint: "/api/brands?page_size=500"
            )
            async let invResp: PaginatedResponse<InventoryItem> = NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/inventory?page_size=500"
            )

            let (skuResult, catResult, brandResult, invResult) = try await (skuResp, catResp, brandResp, invResp)
            skus = skuResult.data
            categories = catResult.data
            brands = brandResult.data
            inventoryItems = invResult.data
            totalSKUs = skuResult.total
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    var filteredSKUs: [SKU] {
        guard !searchText.isEmpty else { return skus }
        return skus.filter {
            $0.skuCode.localizedCaseInsensitiveContains(searchText) ||
            $0.description.localizedCaseInsensitiveContains(searchText)
        }
    }

    var lowStockItems: [InventoryItem] {
        inventoryItems.filter { $0.isLowStock }
    }

    func inventoryFor(skuId: String) -> InventoryItem? {
        inventoryItems.first { $0.skuId == skuId }
    }

}
