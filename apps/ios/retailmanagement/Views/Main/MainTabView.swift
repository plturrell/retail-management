//
//  MainTabView.swift
//  retailmanagement
//

import SwiftUI

struct MainTabView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel

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
        #else
        iOSTabs
        #endif
    }

    // MARK: - macOS: Sidebar Navigation

    #if os(macOS)
    @SceneStorage("mainSidebarTab") private var selectedTabRaw: String = SidebarTab.dashboard.rawValue

    private var selectedTabBinding: Binding<SidebarTab?> {
        Binding(
            get: { SidebarTab(rawValue: selectedTabRaw) ?? .dashboard },
            set: { selectedTabRaw = ($0 ?? .dashboard).rawValue }
        )
    }

    private enum SidebarTab: String, CaseIterable, Identifiable {
        case dashboard = "Dashboard"
        case schedule = "Schedule"
        case timesheet = "Timesheet"
        case pay = "Pay"
        case commission = "Commission"
        case performance = "Performance"
        case inventory = "Inventory"
        case masterData = "Master Data"
        case orders = "Orders"
        case workflows = "Workflows"
        case employees = "Employees"
        case financials = "Financials"
        case profile = "Profile"
        case settings = "Settings"
        case vendorReview = "Vendor Review"
        case teamSchedule = "Team Schedule"
        case timesheetApprovals = "Timesheet Approvals"

        var id: String { rawValue }

        var icon: String {
            switch self {
            case .dashboard: return "chart.bar.fill"
            case .schedule: return "calendar"
            case .timesheet: return "clock.fill"
            case .pay: return "banknote.fill"
            case .commission: return "percent"
            case .performance: return "trophy.fill"
            case .inventory: return "shippingbox.fill"
            case .masterData: return "list.bullet.rectangle.portrait"
            case .orders: return "cart.fill"
            case .workflows: return "wand.and.stars"
            case .employees: return "person.3.fill"
            case .financials: return "dollarsign.circle.fill"
            case .profile: return "person.crop.circle.fill"
            case .settings: return "gearshape.fill"
            case .vendorReview: return "doc.text.magnifyingglass"
            case .teamSchedule: return "calendar.badge.clock"
            case .timesheetApprovals: return "checkmark.seal.fill"
            }
        }

        /// Minimum role level required to see this tab.
        var minimumRoleLevel: Int {
            switch self {
            case .employees, .teamSchedule, .timesheetApprovals: return UserRole.manager.level
            case .financials: return UserRole.owner.level
            case .inventory, .orders, .workflows: return UserRole.manager.level
            case .masterData, .vendorReview: return UserRole.owner.level
            default: return 0
            }
        }
    }

    private var visibleTabs: [SidebarTab] {
        SidebarTab.allCases.filter { $0.minimumRoleLevel <= currentRole.level }
    }

    private var macOSSidebar: some View {
        NavigationSplitView {
            List(visibleTabs, selection: selectedTabBinding) { tab in
                Label(tab.rawValue, systemImage: tab.icon)
                    .tag(tab)
            }
            .navigationTitle("RetailSG")
            .listStyle(.sidebar)
            .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 280)
        } detail: {
            switch selectedTabBinding.wrappedValue {
            case .dashboard:
                DashboardView()
            case .schedule:
                ScheduleView()
            case .timesheet:
                TimesheetView()
            case .pay:
                PayView()
            case .commission:
                CommissionView()
            case .performance:
                PerformanceView()
            case .inventory:
                InventoryTabView()
            case .masterData:
                MasterDataView(canEdit: currentRole == .owner)
            case .vendorReview:
                VendorReviewTabView()
            case .orders:
                OrdersTabView()
            case .workflows:
                WorkflowsRoute()
            case .employees:
                EmployeesTabView()
            case .financials:
                FinancialsTabView()
            case .profile:
                StaffProfileView()
            case .settings:
                SettingsView()
            case .teamSchedule:
                ManagerScheduleTabView()
            case .timesheetApprovals:
                ManagerTimesheetsTabView()
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

            CommissionView()
                .tabItem {
                    Label("Commission", systemImage: "percent")
                }

            PerformanceView()
                .tabItem {
                    Label("Performance", systemImage: "trophy.fill")
                }

            if currentRole.level >= UserRole.manager.level {
                ManagerScheduleTabView()
                    .tabItem {
                        Label("Team Sched", systemImage: "calendar.badge.clock")
                    }
                ManagerTimesheetsTabView()
                    .tabItem {
                        Label("Approvals", systemImage: "checkmark.seal.fill")
                    }
                InventoryTabView()
                    .tabItem {
                        Label("Inventory", systemImage: "shippingbox.fill")
                    }
            }
            if currentRole == .owner {
                MasterDataView(canEdit: currentRole == .owner)
                    .tabItem {
                        Label("Master Data", systemImage: "list.bullet.rectangle.portrait")
                    }
                VendorReviewTabView()
                    .tabItem {
                        Label("Vendor Review", systemImage: "doc.text.magnifyingglass")
                    }
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
        .environment(StoreViewModel())
}

// MARK: - macOS Workflows Route

#if os(macOS)
/// Sidebar route for the Workflow Studio. Owns its own `InventoryViewModel`
/// (loaded for the currently selected store) so the view can be navigated to
/// directly from the sidebar without requiring a parent SKU selection.
private struct WorkflowsRoute: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var inventoryVM = InventoryViewModel()

    private var canViewSensitiveOperations: Bool {
        guard let user = authViewModel.currentUser,
              let store = storeViewModel.selectedStore else { return false }
        return (user.role(for: store.id) ?? user.highestRole ?? .staff) == .owner
    }

    var body: some View {
        NavigationStack {
            Group {
                if let storeId = storeViewModel.selectedStore?.id {
                    ScrollView {
                        ManagerWorkflowStudioView(
                            inventoryVM: inventoryVM,
                            storeId: storeId,
                            selectedInsight: inventoryVM.filteredInsights.first
                        )
                        .padding()
                    }
                    .task(id: storeId) {
                        await inventoryVM.loadData(
                            storeId: storeId,
                            includeOwnerData: canViewSensitiveOperations,
                            forceRefresh: true
                        )
                    }
                } else {
                    ContentUnavailableView(
                        "Choose a Store",
                        systemImage: "building.2",
                        description: Text("Pick an active store to use the Workflow Studio.")
                    )
                }
            }
            .navigationTitle("Workflow Studio")
        }
    }
}
#endif
