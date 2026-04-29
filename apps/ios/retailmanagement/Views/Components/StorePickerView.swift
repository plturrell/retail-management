//
//  StorePickerView.swift
//  retailmanagement
//

import SwiftUI

struct StorePickerView: View {
    @Environment(StoreViewModel.self) var storeViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List(storeViewModel.stores) { store in
                Button {
                    storeViewModel.selectStore(store)
                    dismiss()
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(store.name)
                                .font(.headline)
                            Text(store.location)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                            if !descriptor(for: store).isEmpty {
                                Text(descriptor(for: store))
                                    .font(.caption)
                                    .foregroundStyle(.blue)
                            }
                            Text(store.address)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        if storeViewModel.selectedStore?.id == store.id {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(.blue)
                        }
                    }
                    .padding(.vertical, 4)
                }
                .foregroundStyle(.primary)
            }
            .macOSFormWidth(560)
            .navigationTitle("Select Store")
            #if canImport(UIKit)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func descriptor(for store: Store) -> String {
        var parts: [String] = []
        if store.storeType != .retail {
            parts.append(store.storeType.rawValue)
        }
        if store.isHomeBase {
            parts.append("home base")
        }
        if store.isTempWarehouse {
            parts.append("temp warehouse")
        }
        if store.operationalStatus != .active {
            parts.append(store.operationalStatus.rawValue)
        }
        if let plannedOpenDate = store.plannedOpenDate, !plannedOpenDate.isEmpty {
            parts.append("opens \(plannedOpenDate)")
        }
        return parts.joined(separator: " • ")
    }
}

#Preview {
    StorePickerView()
        .environment(StoreViewModel())
}
