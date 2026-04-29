//
//  DashboardView.swift
//  retailmanagement
//

import SwiftUI

struct DashboardView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var inventoryVM = InventoryViewModel()
    @State private var ordersVM = OrdersViewModel()
    
    @State private var animateSymbols = false

    private var storeName: String {
        storeViewModel.selectedStore?.name ?? "Your Store"
    }

    private var lowStockInsights: [InventoryInsight] {
        inventoryVM.insights.filter(\.lowStock)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                // Background Depth - Defines the spatial environment
                LinearGradient(
                    colors: [Color.blue.opacity(0.15), Color.purple.opacity(0.05), Color.systemBackground],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
                .ignoresSafeArea()
                
                ScrollView {
                    VStack(spacing: 24) {
                        // Greeting - High Typographic Precision
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Welcome back,")
                                    .font(.system(.subheadline, design: .rounded))
                                    .foregroundStyle(.secondary)
                                Text(authViewModel.currentUser?.fullName ?? "User")
                                    .font(.system(.title, design: .rounded).bold())
                            }
                            Spacer()
                            Image(systemName: "storefront.fill")
                                .font(.title)
                                .foregroundStyle(LinearGradient(colors: [.cyan, .blue], startPoint: .top, endPoint: .bottom))
                                .symbolEffect(.bounce, value: animateSymbols)
                        }
                        .padding(.horizontal)

                        // KPI Cards - Glassmorphism & Numeric Transitions
                        LazyVGrid(columns: AdaptiveLayout.kpiGridColumns(), spacing: 16) {
                            KPICard(
                                title: "Today's Revenue",
                                value: String(format: "$%.2f", ordersVM.todayRevenue),
                                icon: "dollarsign.circle.fill",
                                color: .green,
                                animate: animateSymbols
                            )
                            KPICard(
                                title: "Open Orders",
                                value: "\(ordersVM.openOrdersCount)",
                                icon: "cart.fill",
                                color: .orange,
                                animate: animateSymbols
                            )
                            KPICard(
                                title: "Total SKUs",
                                value: "\(inventoryVM.insights.count)",
                                icon: "shippingbox.fill",
                                color: .blue,
                                animate: animateSymbols
                            )
                            KPICard(
                                title: "Low Stock",
                                value: "\(lowStockInsights.count)",
                                icon: "exclamationmark.triangle.fill",
                                color: lowStockInsights.isEmpty ? .gray : .red,
                                animate: animateSymbols
                            )
                        }
                        .padding(.horizontal)

                        // Recent Orders - Fluid Spatial Rendering
                        VStack(alignment: .leading, spacing: 16) {
                            HStack {
                                Text("Recent Orders")
                                    .font(.system(.title3, design: .rounded).weight(.semibold))
                                Spacer()
                            }

                            if ordersVM.orders.isEmpty {
                                Text("No orders yet")
                                    .font(.system(.subheadline, design: .rounded))
                                    .foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity, alignment: .center)
                                    .padding(.vertical, 32)
                                    .background(.ultraThinMaterial)
                                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                            } else {
                                ForEach(ordersVM.orders.prefix(3)) { order in
                                    OrderRowCard(order: order)
                                        .transition(.asymmetric(insertion: .scale.combined(with: .opacity), removal: .opacity))
                                }
                            }
                        }
                        .padding(.horizontal)

                        // Low Stock Alerts - High urgency tactile feedback
                        if !lowStockInsights.isEmpty {
                            VStack(alignment: .leading, spacing: 16) {
                                HStack {
                                    Image(systemName: "exclamationmark.triangle.fill")
                                        .symbolEffect(.pulse.byLayer, options: .repeating)
                                        .foregroundStyle(.red)
                                    Text("Low Stock Alerts")
                                        .font(.system(.title3, design: .rounded).weight(.semibold))
                                    Spacer()
                                }

                                ForEach(lowStockInsights) { item in
                                    HStack {
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(item.description)
                                                .font(.system(.subheadline, design: .rounded).weight(.medium))
                                            Text(item.skuCode)
                                                .font(.system(.caption, design: .rounded))
                                                .foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                        Text("\(item.qtyOnHand) left")
                                            .font(.system(.subheadline, design: .rounded).weight(.semibold))
                                            .foregroundStyle(.red)
                                            .contentTransition(.numericText())
                                    }
                                    .padding()
                                    .background(.ultraThinMaterial)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                                            .strokeBorder(Color.red.opacity(0.3), lineWidth: 0.5)
                                    )
                                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                                }
                            }
                            .padding(.horizontal)
                        }
                    }
                    .padding(.vertical)
                }
            }
            .navigationTitle("Dashboard")
            .onAppear {
                animateSymbols.toggle()
            }
            .task {
                withAnimation(.spring(response: 0.5, dampingFraction: 0.8)) {
                    if let storeId = storeViewModel.selectedStore?.id {
                        Task { await inventoryVM.loadData(storeId: storeId) }
                        Task { await ordersVM.loadOrders(storeId: storeId) }
                    }
                }
            }
        }
    }
}

// MARK: - Supporting Views

struct KPICard: View {
    let title: String
    let value: String
    let icon: String
    let color: Color
    let animate: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: icon)
                    .font(.title2)
                    .foregroundStyle(LinearGradient(colors: [color.opacity(0.7), color], startPoint: .topLeading, endPoint: .bottomTrailing))
                    .symbolEffect(.bounce, value: animate)
                Spacer()
            }
            
            VStack(alignment: .leading, spacing: 2) {
                Text(value)
                    .font(.system(.title2, design: .rounded).weight(.bold))
                    .contentTransition(.numericText())
                Text(title)
                    .font(.system(.caption, design: .rounded).weight(.medium))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .modifier(LiquidGlassUI(cornerRadius: 20))
    }
}

struct OrderRowCard: View {
    let order: Order

    var statusColor: Color {
        switch order.status {
        case .open: return .blue
        case .completed: return .green
        case .voided: return .red
        }
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 6) {
                Text(order.orderNumber)
                    .font(.system(.subheadline, design: .rounded).weight(.semibold))
                HStack(spacing: 8) {
                    Text(order.source.displayName)
                        .font(.system(.caption, design: .rounded))
                        .foregroundStyle(.secondary)
                    Text("·")
                        .foregroundStyle(.secondary)
                    Text("\(order.itemCount) items")
                        .font(.system(.caption, design: .rounded))
                        .foregroundStyle(.secondary)
                        .contentTransition(.numericText())
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 6) {
                Text(order.formattedTotal)
                    .font(.system(.subheadline, design: .rounded).weight(.bold))
                    .contentTransition(.numericText())
                Text(order.status.displayName)
                    .font(.system(.caption, design: .rounded).weight(.bold))
                    .foregroundStyle(statusColor)
            }
        }
        .padding(16)
        .modifier(LiquidGlassUI(cornerRadius: 16))
    }
}

#Preview {
    DashboardView()
        .environment(AuthViewModel())
        .environment(StoreViewModel())
}
