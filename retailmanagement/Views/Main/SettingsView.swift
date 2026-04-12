//
//  SettingsView.swift
//  retailmanagement
//

import SwiftUI

struct SettingsView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var showStorePicker = false

    var body: some View {
        NavigationStack {
            List {
                // Profile section
                if let user = authViewModel.currentUser {
                    Section("Profile") {
                        HStack {
                            Image(systemName: "person.circle.fill")
                                .font(.system(size: 40))
                                .foregroundStyle(.blue)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(user.fullName)
                                    .font(.headline)
                                Text(user.email)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }

                // Store section
                Section("Store") {
                    Button {
                        showStorePicker = true
                    } label: {
                        HStack {
                            Label(
                                storeViewModel.selectedStore?.name ?? "Select Store",
                                systemImage: "storefront"
                            )
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .foregroundStyle(.primary)

                    if let store = storeViewModel.selectedStore {
                        LabeledContent("Location", value: store.location)
                        if let start = store.businessHoursStart, let end = store.businessHoursEnd {
                            LabeledContent("Hours", value: "\(start) - \(end)")
                        }
                    }
                }

                // Account section
                Section {
                    Button(role: .destructive) {
                        authViewModel.signOut()
                    } label: {
                        Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
                    }
                }
            }
            .navigationTitle("Settings")
            .sheet(isPresented: $showStorePicker) {
                StorePickerView()
            }
        }
    }
}

#Preview {
    SettingsView()
        .environment(AuthViewModel())
        .environment(StoreViewModel())
}
