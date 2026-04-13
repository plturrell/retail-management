//
//  StoreViewModel.swift
//  retailmanagement
//

import Foundation
import Observation
import SwiftUI

@MainActor
@Observable
final class StoreViewModel {
    var stores: [Store] = []
    var selectedStore: Store?
    var isLoading = false
    var errorMessage: String?

    private let selectedStoreKey = "selectedStoreId"

    init() {
        Task {
            await fetchStores()
        }
    }

    /// Fetch available stores from the backend.
    func fetchStores() async {
        isLoading = true
        errorMessage = nil

        do {
            let response: PaginatedResponse<Store> = try await NetworkService.shared.get(
                endpoint: "/api/stores"
            )
            let fetchedStores = response.data
            stores = fetchedStores

            // Restore previously selected store from UserDefaults
            if let savedId = UserDefaults.standard.string(forKey: selectedStoreKey),
               let saved = fetchedStores.first(where: { $0.id == savedId }) {
                selectedStore = saved
            } else if let first = fetchedStores.first {
                selectStore(first)
            }
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    /// Select a store and persist the choice.
    func selectStore(_ store: Store) {
        selectedStore = store
        UserDefaults.standard.set(store.id, forKey: selectedStoreKey)
    }
}
