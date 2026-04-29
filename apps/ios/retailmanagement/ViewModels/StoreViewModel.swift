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

    /// When non-nil, the model is "pinned" to a particular store (used for
    /// per-store windows). In pinned mode, selection is fixed to that id and
    /// is never persisted to `UserDefaults`, so multiple windows can show
    /// different stores without fighting over the saved selection.
    let pinnedStoreId: String?

    var isPinned: Bool { pinnedStoreId != nil }

    init(preloadedStores: [Store]? = nil, selectedStore: Store? = nil) {
        self.pinnedStoreId = nil
        if let preloadedStores {
            stores = preloadedStores
            self.selectedStore = selectedStore ?? preloadedStores.first
        } else {
            Task {
                await fetchStores()
            }
        }
    }

    /// Initialise a per-window model pinned to a specific store id. Selection
    /// will resolve to that store once the catalog is fetched, and changes
    /// are not written to `UserDefaults`.
    init(pinnedStoreId: String) {
        self.pinnedStoreId = pinnedStoreId
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

            if let pinnedStoreId,
               let pinned = fetchedStores.first(where: { $0.id == pinnedStoreId }) {
                // Pinned mode — never read/write the shared UserDefaults key.
                selectedStore = pinned
            } else if let savedId = UserDefaults.standard.string(forKey: selectedStoreKey),
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

    /// Select a store. In pinned mode the call is ignored to prevent multiple
    /// per-store windows from cross-mutating each other's state.
    func selectStore(_ store: Store) {
        if isPinned { return }
        selectedStore = store
        UserDefaults.standard.set(store.id, forKey: selectedStoreKey)
    }
}
