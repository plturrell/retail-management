//
//  SettingsView.swift
//  retailmanagement
//

import SwiftUI

struct SettingsView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var showStorePicker = false
    @State private var showProfileEdit = false

    #if os(macOS)
    @AppStorage("menuBarExtraEnabled") private var menuBarExtraEnabled: Bool = true
    #endif

    private var isOwner: Bool {
        guard let user = authViewModel.currentUser else { return false }
        if let store = storeViewModel.selectedStore, user.role(for: store.id) == .owner { return true }
        return user.highestRole == .owner
    }

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
                                Text(user.username)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                if let phone = user.phone, !phone.isEmpty {
                                    Text(phone)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                        .padding(.vertical, 4)

                        Button {
                            showProfileEdit = true
                        } label: {
                            Label("Edit Profile", systemImage: "pencil")
                        }
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
                        if !storeDescriptor(for: store).isEmpty {
                            LabeledContent("Type", value: storeDescriptor(for: store))
                        }
                        if let start = store.businessHoursStart, let end = store.businessHoursEnd {
                            LabeledContent("Hours", value: "\(start) - \(end)")
                        }
                        if let notes = store.notes, !notes.isEmpty {
                            Text(notes)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                #if os(macOS)
                // macOS-only preferences.
                Section("Mac Preferences") {
                    Toggle(isOn: $menuBarExtraEnabled) {
                        Label("Show Menu Bar Icon", systemImage: "menubar.rectangle")
                    }
                }
                #endif

                if isOwner {
                    Section("Integrations") {
                        NavigationLink {
                            CagSettingsView()
                        } label: {
                            Label("NEC CAG Integration", systemImage: "antenna.radiowaves.left.and.right")
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
            .sheet(isPresented: $showProfileEdit) {
                ProfileEditView()
            }
        }
    }

    private func storeDescriptor(for store: Store) -> String {
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
    SettingsView()
        .environment(AuthViewModel())
        .environment(StoreViewModel())
}
