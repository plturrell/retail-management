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
            .navigationTitle("Select Store")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

#Preview {
    StorePickerView()
        .environment(StoreViewModel())
}
