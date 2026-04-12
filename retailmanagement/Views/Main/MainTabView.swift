//
//  MainTabView.swift
//  retailmanagement
//

import SwiftUI

struct MainTabView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @State private var storeViewModel = StoreViewModel()

    private var currentRole: UserRole {
        guard let user = authViewModel.currentUser,
              let store = storeViewModel.selectedStore else {
            return .staff
        }
        return user.role(for: store.id) ?? user.highestRole ?? .staff
    }

    var body: some View {
        TabView {
            DashboardView()
                .tabItem {
                    Label("Dashboard", systemImage: "chart.bar.fill")
                }

            InventoryTabView()
                .tabItem {
                    Label("Inventory", systemImage: "shippingbox.fill")
                }

            OrdersTabView()
                .tabItem {
                    Label("Orders", systemImage: "cart.fill")
                }

            if currentRole.level >= UserRole.manager.level {
                EmployeesTabView()
                    .tabItem {
                        Label("Employees", systemImage: "person.3.fill")
                    }
            }

            if currentRole.level >= UserRole.owner.level {
                FinancialsTabView()
                    .tabItem {
                        Label("Financials", systemImage: "dollarsign.circle.fill")
                    }
            }

            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gearshape.fill")
                }
        }
        .environment(storeViewModel)
    }
}

#Preview {
    MainTabView()
        .environment(AuthViewModel())
}
