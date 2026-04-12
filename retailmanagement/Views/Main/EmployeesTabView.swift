//
//  EmployeesTabView.swift
//  retailmanagement
//

import SwiftUI

nonisolated struct Employee: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let fullName: String
    let email: String
    let phone: String?
    let role: UserRole
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
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var employeesVM = EmployeesViewModel()
    @State private var selectedEmployee: Employee?

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
            .task {
                if let storeId = storeViewModel.selectedStore?.id {
                    await employeesVM.loadEmployees(storeId: storeId)
                }
            }
            .sheet(item: $selectedEmployee) { emp in
                EmployeeDetailView(employee: emp)
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
    @Environment(StoreViewModel.self) var storeViewModel
    @Environment(\.dismiss) private var dismiss

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
            }
            .navigationTitle("Employee")
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
    EmployeesTabView()
        .environment(StoreViewModel())
}
