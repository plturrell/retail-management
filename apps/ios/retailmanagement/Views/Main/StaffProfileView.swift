//
//  StaffProfileView.swift
//  retailmanagement
//

import SwiftUI

struct StaffProfileView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var employeeProfile: EmployeeProfile?
    @State private var isLoading = false
    @State private var sessions: [SessionRead] = []
    @State private var sessionsBusy = false
    @State private var sessionsMessage: String?
    @State private var sessionsError: String?
    @State private var confirmSignOutOthers = false

    private var isOwner: Bool {
        guard let user = authViewModel.currentUser else { return false }
        if let store = storeViewModel.selectedStore, user.role(for: store.id) == .owner { return true }
        return user.highestRole == .owner
    }

    var body: some View {
        NavigationStack {
            List {
                // Personal Info
                if let user = authViewModel.currentUser {
                    Section("Personal Information") {
                        HStack {
                            Image(systemName: "person.circle.fill")
                                .font(.system(size: 48))
                                .foregroundStyle(.blue)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(user.fullName)
                                    .font(.title3.weight(.semibold))
                                Text(user.username)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                if let phone = user.phone, !phone.isEmpty {
                                    Text(phone)
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                        .padding(.vertical, 4)
                    }

                    // Store Role
                    if let store = storeViewModel.selectedStore {
                        Section("Store") {
                            LabeledContent("Store", value: store.name)
                            LabeledContent("Location", value: store.location)
                            if let role = user.role(for: store.id) {
                                LabeledContent("Role", value: role.displayName)
                            }
                        }
                    }
                }

                // Employment Details
                if let profile = employeeProfile {
                    Section("Employment Details") {
                        LabeledContent("Start Date", value: formatDate(profile.startDate))
                        if let end = profile.endDate {
                            LabeledContent("End Date", value: formatDate(end))
                        }
                        LabeledContent("Nationality", value: profile.nationality.capitalized)
                        LabeledContent("Status", value: profile.isActive ? "Active" : "Inactive")
                    }

                    Section("Compensation") {
                        LabeledContent("Basic Salary", value: "$\(String(format: "%.2f", profile.basicSalary))")
                        if let rate = profile.hourlyRate {
                            LabeledContent("Hourly Rate", value: "$\(String(format: "%.2f", rate))")
                        }
                        if let commission = profile.commissionRate, commission > 0 {
                            LabeledContent("Commission Rate", value: "\(String(format: "%.1f", commission))%")
                        }
                    }

                    Section("Banking") {
                        LabeledContent("Bank", value: profile.bankName)
                        if let account = profile.bankAccount {
                            LabeledContent("Account", value: account)
                        }
                        if let cpf = profile.cpfAccountNumber {
                            LabeledContent("CPF Account", value: cpf)
                        }
                    }
                } else if isLoading {
                    Section("Employment Details") {
                        HStack {
                            Spacer()
                            ProgressView()
                            Spacer()
                        }
                    }
                }

                sessionsSection

                if isOwner {
                    Section("Owner Tools") {
                        NavigationLink {
                            CagSettingsView()
                        } label: {
                            Label("NEC CAG Integration", systemImage: "antenna.radiowaves.left.and.right")
                        }
                    }
                }

                // Sign Out
                Section {
                    Button(role: .destructive) {
                        authViewModel.signOut()
                    } label: {
                        Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
                    }
                }
            }
            .insetGroupedListStyleCompat()
            .navigationTitle("Profile")
            .task {
                await loadProfile()
                await loadSessions()
            }
            .refreshable {
                await loadProfile()
                await loadSessions()
            }
            .alert("Sign out other devices?", isPresented: $confirmSignOutOthers) {
                Button("Sign out", role: .destructive) { Task { await signOutOthers() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This revokes refresh tokens on every device. You may also need to sign in again within the hour.")
            }
        }
    }

    @ViewBuilder
    private var sessionsSection: some View {
        Section("Active devices") {
            if let msg = sessionsMessage {
                Text(msg).font(.caption).foregroundStyle(.green)
            }
            if let err = sessionsError {
                Text(err).font(.caption).foregroundStyle(.red)
            }
            if sessions.isEmpty {
                Text("No recorded sessions yet.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(sessions) { s in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(prettyUserAgent(s.userAgent))
                            .font(.subheadline.bold())
                        Text("\(s.ip ?? "unknown network") · seen \(s.count)\u{00d7}")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        Text("Last \(s.lastSeen ?? "—")")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 2)
                }
            }
            Button(role: .destructive) {
                confirmSignOutOthers = true
            } label: {
                if sessionsBusy {
                    ProgressView()
                } else {
                    Label("Sign out other devices", systemImage: "iphone.slash")
                }
            }
            .disabled(sessionsBusy)
        }
    }

    private func loadSessions() async {
        do {
            let resp: DataResponse<[SessionRead]> = try await NetworkService.shared.get(
                endpoint: "/api/users/me/sessions"
            )
            await MainActor.run { sessions = resp.data; sessionsError = nil }
        } catch {
            await MainActor.run { sessionsError = error.localizedDescription }
        }
    }

    private func signOutOthers() async {
        sessionsBusy = true
        sessionsMessage = nil
        sessionsError = nil
        defer { sessionsBusy = false }
        do {
            let resp: SignOutResponse = try await NetworkService.shared.post(
                endpoint: "/api/users/me/sign-out-other-devices",
                body: EmptyBody()
            )
            sessionsMessage = resp.message ?? "Other devices signed out."
        } catch {
            sessionsError = error.localizedDescription
        }
    }

    private func prettyUserAgent(_ ua: String?) -> String {
        guard let ua, !ua.isEmpty else { return "Unknown device" }
        if ua.contains("iPhone") { return "iPhone" }
        if ua.contains("iPad") { return "iPad" }
        if ua.contains("Macintosh") { return "Mac" }
        if ua.contains("Android") { return "Android" }
        if ua.contains("Chrome") { return "Chrome browser" }
        if ua.contains("Safari") { return "Safari browser" }
        return String(ua.prefix(40))
    }

    private func loadProfile() async {
        guard let userId = authViewModel.currentUser?.id else { return }
        isLoading = true
        do {
            let response: DataResponse<EmployeeProfile> = try await NetworkService.shared.get(
                endpoint: "/api/employees/\(userId)/profile"
            )
            employeeProfile = response.data
        } catch {
            // Profile may not exist
        }
        isLoading = false
    }

    private func formatDate(_ dateString: String) -> String {
        let inputFmt = DateFormatter()
        inputFmt.dateFormat = "yyyy-MM-dd"
        guard let date = inputFmt.date(from: dateString) else { return dateString }
        let outputFmt = DateFormatter()
        outputFmt.dateStyle = .medium
        return outputFmt.string(from: date)
    }
}

#Preview {
    StaffProfileView()
        .environment(AuthViewModel())
        .environment(StoreViewModel())
}
