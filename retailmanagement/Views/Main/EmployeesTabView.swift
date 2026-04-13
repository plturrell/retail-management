//
//  EmployeesTabView.swift
//  retailmanagement
//

import SwiftUI

nonisolated struct Employee: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let roleId: String
    let fullName: String
    let email: String
    let phone: String?
    let role: UserRole
}

private struct SearchedUser: Codable, Identifiable, Sendable {
    let id: String
    let email: String
    let fullName: String
    let firebaseUid: String
}

private struct AssignRoleBody: Encodable {
    let userId: String
    let storeId: String
    let role: String
}

private struct UpdateRoleBody: Encodable {
    let role: String
}

@MainActor
@Observable
final class EmployeesViewModel {
    var employees: [Employee] = []
    var isLoading = false
    var errorMessage: String?

    func loadEmployees(storeId: String) async {
        isLoading = true
        errorMessage = nil

        do {
            let response: PaginatedResponse<Employee> = try await NetworkService.shared.get(
                endpoint: "/api/users/stores/\(storeId)/employees"
            )
            employees = response.data
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }
}

struct EmployeesTabView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var employeesVM = EmployeesViewModel()
    @State private var selectedEmployee: Employee?
    @State private var showInviteSheet = false

    private var isOwner: Bool {
        guard let user = authViewModel.currentUser,
              let store = storeViewModel.selectedStore else { return false }
        return user.role(for: store.id) == .owner
    }

    var body: some View {
        NavigationStack {
            Group {
                if employeesVM.isLoading {
                    ProgressView("Loading employees...")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if employeesVM.employees.isEmpty {
                    ContentUnavailableView(
                        "No Employees",
                        systemImage: "person.3",
                        description: Text("Add team members to manage your store.")
                    )
                } else {
                    List {
                        Section("\(employeesVM.employees.count) Team Members") {
                            ForEach(employeesVM.employees) { emp in
                                Button {
                                    selectedEmployee = emp
                                } label: {
                                    EmployeeRow(employee: emp)
                                }
                                .foregroundStyle(.primary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Employees")
            .toolbar {
                if isOwner {
                    ToolbarItem(placement: .primaryAction) {
                        Button {
                            showInviteSheet = true
                        } label: {
                            Label("Add", systemImage: "person.badge.plus")
                        }
                    }
                }
            }
            .task {
                if let storeId = storeViewModel.selectedStore?.id {
                    await employeesVM.loadEmployees(storeId: storeId)
                }
            }
            .sheet(item: $selectedEmployee) { emp in
                EmployeeDetailView(employee: emp, onChanged: {
                    Task {
                        if let storeId = storeViewModel.selectedStore?.id {
                            await employeesVM.loadEmployees(storeId: storeId)
                        }
                    }
                })
            }
            .sheet(isPresented: $showInviteSheet) {
                InviteEmployeeView(onInvited: {
                    Task {
                        if let storeId = storeViewModel.selectedStore?.id {
                            await employeesVM.loadEmployees(storeId: storeId)
                        }
                    }
                })
            }
        }
    }
}

struct EmployeeRow: View {
    let employee: Employee

    var roleColor: Color {
        switch employee.role {
        case .owner: return .purple
        case .manager: return .blue
        case .staff: return .gray
        }
    }

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "person.circle.fill")
                .font(.title2)
                .foregroundStyle(roleColor)

            VStack(alignment: .leading, spacing: 3) {
                Text(employee.fullName)
                    .font(.subheadline.weight(.medium))
                Text(employee.email)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Text(employee.role.displayName)
                .font(.caption.weight(.semibold))
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(roleColor.opacity(0.12))
                .foregroundStyle(roleColor)
                .clipShape(Capsule())
        }
        .padding(.vertical, 2)
    }
}

struct EmployeeDetailView: View {
    let employee: Employee
    var onChanged: (() -> Void)? = nil
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var showRolePicker = false
    @State private var showRemoveConfirm = false
    @State private var isProcessing = false
    @State private var actionError: String?

    private var isOwner: Bool {
        guard let user = authViewModel.currentUser,
              let store = storeViewModel.selectedStore else { return false }
        return user.role(for: store.id) == .owner
    }

    private var isSelf: Bool {
        authViewModel.currentUser?.id == employee.id
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        Spacer()
                        VStack(spacing: 8) {
                            Image(systemName: "person.circle.fill")
                                .font(.system(size: 60))
                                .foregroundStyle(.blue)
                            Text(employee.fullName)
                                .font(.title3.bold())
                            Text(employee.role.displayName)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                    }
                    .padding(.vertical, 8)
                }

                Section("Contact") {
                    LabeledContent("Email", value: employee.email)
                    if let phone = employee.phone {
                        LabeledContent("Phone", value: phone)
                    }
                }

                Section("Assignment") {
                    LabeledContent("Store", value: storeViewModel.selectedStore?.name ?? "—")
                    LabeledContent("Role", value: employee.role.displayName)
                }

                if isOwner && !isSelf {
                    Section("Actions") {
                        Button {
                            showRolePicker = true
                        } label: {
                            Label("Change Role", systemImage: "person.badge.key")
                        }
                        .disabled(isProcessing)

                        Button(role: .destructive) {
                            showRemoveConfirm = true
                        } label: {
                            Label("Remove from Store", systemImage: "person.badge.minus")
                        }
                        .disabled(isProcessing)
                    }
                }

                if let error = actionError {
                    Section {
                        Text(error).foregroundStyle(.red).font(.caption)
                    }
                }
            }
            .navigationTitle("Employee")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .confirmationDialog("Change Role", isPresented: $showRolePicker) {
                ForEach(UserRole.allCases.filter { $0 != employee.role }, id: \.self) { role in
                    Button(role.displayName) {
                        Task { await changeRole(to: role) }
                    }
                }
                Button("Cancel", role: .cancel) {}
            }
            .alert("Remove Employee", isPresented: $showRemoveConfirm) {
                Button("Remove", role: .destructive) {
                    Task { await removeEmployee() }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Are you sure you want to remove \(employee.fullName) from this store?")
            }
        }
    }

    private func changeRole(to newRole: UserRole) async {
        isProcessing = true
        actionError = nil
        do {
            let body = UpdateRoleBody(role: newRole.rawValue)
            let _: DataResponse<UserStoreRole> = try await NetworkService.shared.patch(
                endpoint: "/api/users/roles/\(employee.roleId)",
                body: body
            )
            onChanged?()
            dismiss()
        } catch {
            actionError = error.localizedDescription
        }
        isProcessing = false
    }

    private func removeEmployee() async {
        isProcessing = true
        actionError = nil
        do {
            try await NetworkService.shared.deleteNoContent(
                endpoint: "/api/users/roles/\(employee.roleId)"
            )
            onChanged?()
            dismiss()
        } catch {
            actionError = error.localizedDescription
        }
        isProcessing = false
    }
}

// MARK: - Invite Employee

struct InviteEmployeeView: View {
    var onInvited: (() -> Void)? = nil
    @Environment(StoreViewModel.self) var storeViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var searchEmail = ""
    @State private var searchResults: [SearchedUser] = []
    @State private var selectedRole: UserRole = .staff
    @State private var isSearching = false
    @State private var isInviting = false
    @State private var errorMessage: String?
    @State private var successMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Find User") {
                    HStack {
                        TextField("Search by email", text: $searchEmail)
                            .textContentType(.emailAddress)
                            .keyboardType(.emailAddress)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                        Button {
                            Task { await search() }
                        } label: {
                            if isSearching {
                                ProgressView()
                            } else {
                                Image(systemName: "magnifyingglass")
                            }
                        }
                        .disabled(searchEmail.count < 3 || isSearching)
                    }
                }

                if !searchResults.isEmpty {
                    Section("Results") {
                        ForEach(searchResults) { user in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(user.fullName)
                                        .font(.subheadline.weight(.medium))
                                    Text(user.email)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("Invite") {
                                    Task { await invite(user: user) }
                                }
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)
                                .disabled(isInviting)
                            }
                        }
                    }
                }

                Section("Role") {
                    Picker("Assign Role", selection: $selectedRole) {
                        ForEach(UserRole.allCases, id: \.self) { role in
                            Text(role.displayName).tag(role)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                if let error = errorMessage {
                    Section { Text(error).foregroundStyle(.red).font(.caption) }
                }
                if let success = successMessage {
                    Section { Text(success).foregroundStyle(.green).font(.caption) }
                }
            }
            .navigationTitle("Invite Employee")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }

    private func search() async {
        isSearching = true
        errorMessage = nil
        do {
            let response: DataResponse<[SearchedUser]> = try await NetworkService.shared.get(
                endpoint: "/api/users/search",
                queryItems: [URLQueryItem(name: "email", value: searchEmail)]
            )
            searchResults = response.data
            if searchResults.isEmpty {
                errorMessage = "No users found with that email."
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        isSearching = false
    }

    private func invite(user: SearchedUser) async {
        guard let storeId = storeViewModel.selectedStore?.id else { return }
        isInviting = true
        errorMessage = nil
        successMessage = nil
        do {
            let body = AssignRoleBody(
                userId: user.id,
                storeId: storeId,
                role: selectedRole.rawValue
            )
            let _: DataResponse<UserStoreRole> = try await NetworkService.shared.post(
                endpoint: "/api/users/roles",
                body: body
            )
            successMessage = "\(user.fullName) added as \(selectedRole.displayName)."
            searchResults.removeAll { $0.id == user.id }
            onInvited?()
        } catch {
            errorMessage = error.localizedDescription
        }
        isInviting = false
    }
}

#Preview {
    EmployeesTabView()
        .environment(AuthViewModel())
        .environment(StoreViewModel())
}
