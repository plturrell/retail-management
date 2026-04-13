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
                                Text(user.email)
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

                // Sign Out
                Section {
                    Button(role: .destructive) {
                        authViewModel.signOut()
                    } label: {
                        Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Profile")
            .task { await loadProfile() }
            .refreshable { await loadProfile() }
        }
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
