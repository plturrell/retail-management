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
        #if os(macOS)
        macOSSidebar
            .environment(storeViewModel)
        #else
        iOSTabs
            .environment(storeViewModel)
        #endif
    }

    // MARK: - macOS: Sidebar Navigation

    #if os(macOS)
    @State private var selectedTab: SidebarTab? = .dashboard

    private enum SidebarTab: String, CaseIterable, Identifiable {
        case dashboard = "Dashboard"
        case schedule = "Schedule"
        case timesheet = "Timesheet"
        case pay = "Pay"
        case performance = "Performance"
        case inventory = "Inventory"
        case orders = "Orders"
        case employees = "Employees"
        case financials = "Financials"
        case profile = "Profile"

        var id: String { rawValue }

        var icon: String {
            switch self {
            case .dashboard: return "chart.bar.fill"
            case .schedule: return "calendar"
            case .timesheet: return "clock.fill"
            case .pay: return "banknote.fill"
            case .performance: return "trophy.fill"
            case .inventory: return "shippingbox.fill"
            case .orders: return "cart.fill"
            case .employees: return "person.3.fill"
            case .financials: return "dollarsign.circle.fill"
            case .profile: return "person.crop.circle.fill"
            }
        }

        /// Minimum role level required to see this tab.
        var minimumRoleLevel: Int {
            switch self {
            case .employees: return UserRole.manager.level
            case .financials: return UserRole.owner.level
            case .inventory, .orders: return UserRole.manager.level
            default: return 0
            }
        }
    }

    private var visibleTabs: [SidebarTab] {
        SidebarTab.allCases.filter { $0.minimumRoleLevel <= currentRole.level }
    }

    private var macOSSidebar: some View {
        NavigationSplitView {
            List(visibleTabs, selection: $selectedTab) { tab in
                Label(tab.rawValue, systemImage: tab.icon)
                    .tag(tab)
            }
            .navigationTitle("RetailSG")
            .listStyle(.sidebar)
        } detail: {
            switch selectedTab {
            case .dashboard:
                DashboardView()
            case .schedule:
                ScheduleView()
            case .timesheet:
                TimesheetView()
            case .pay:
                PayView()
            case .performance:
                PerformanceView()
            case .inventory:
                InventoryTabView()
            case .orders:
                OrdersTabView()
            case .employees:
                EmployeesTabView()
            case .financials:
                FinancialsTabView()
            case .profile:
                StaffProfileView()
            case .none:
                Text("Select an item from the sidebar.")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
        }
    }
    #endif

    // MARK: - iOS: Tab Bar Navigation

    #if !os(macOS)
    private var iOSTabs: some View {
        TabView {
            ScheduleView()
                .tabItem {
                    Label("Schedule", systemImage: "calendar")
                }

            TimesheetView()
                .tabItem {
                    Label("Timesheet", systemImage: "clock.fill")
                }

            PayView()
                .tabItem {
                    Label("Pay", systemImage: "banknote.fill")
                }

            PerformanceView()
                .tabItem {
                    Label("Performance", systemImage: "trophy.fill")
                }

            StaffProfileView()
                .tabItem {
                    Label("Profile", systemImage: "person.crop.circle.fill")
                }
        }
    }
    #endif
}

#Preview {
    MainTabView()
        .environment(AuthViewModel())
}
