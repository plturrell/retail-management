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

    private var storeName: String {
        storeViewModel.selectedStore?.name ?? "Your Store"
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Greeting
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Welcome back,")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                            Text(authViewModel.currentUser?.fullName ?? "User")
                                .font(.title2.bold())
                        }
                        Spacer()
                        Image(systemName: "storefront.fill")
                            .font(.title)
                            .foregroundStyle(.blue)
                    }
                    .padding(.horizontal)

                    // KPI Cards
                    LazyVGrid(columns: [
                        GridItem(.flexible()),
                        GridItem(.flexible()),
                    ], spacing: 16) {
                        KPICard(
                            title: "Today's Revenue",
                            value: String(format: "$%.2f", ordersVM.todayRevenue),
                            icon: "dollarsign.circle.fill",
                            color: .green
                        )
                        KPICard(
                            title: "Open Orders",
                            value: "\(ordersVM.openOrdersCount)",
                            icon: "cart.fill",
                            color: .orange
                        )
                        KPICard(
                            title: "Total SKUs",
                            value: "\(inventoryVM.totalSKUs)",
                            icon: "shippingbox.fill",
                            color: .blue
                        )
                        KPICard(
                            title: "Low Stock",
                            value: "\(inventoryVM.lowStockItems.count)",
                            icon: "exclamationmark.triangle.fill",
                            color: inventoryVM.lowStockItems.isEmpty ? .gray : .red
                        )
                    }
                    .padding(.horizontal)

                    // Recent Orders
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Text("Recent Orders")
                                .font(.headline)
                            Spacer()
                        }

                        if ordersVM.orders.isEmpty {
                            Text("No orders yet")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .center)
                                .padding(.vertical, 24)
                        } else {
                            ForEach(ordersVM.orders.prefix(3)) { order in
                                OrderRowCard(order: order)
                            }
                        }
                    }
                    .padding(.horizontal)

                    // Low Stock Alerts
                    if !inventoryVM.lowStockItems.isEmpty {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .foregroundStyle(.red)
                                Text("Low Stock Alerts")
                                    .font(.headline)
                                Spacer()
                            }

                            ForEach(inventoryVM.lowStockItems) { item in
                                if let sku = inventoryVM.skus.first(where: { $0.id == item.skuId }) {
                                    HStack {
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(sku.description)
                                                .font(.subheadline.weight(.medium))
                                            Text(sku.skuCode)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                        Text("\(item.qtyOnHand) left")
                                            .font(.subheadline.weight(.semibold))
                                            .foregroundStyle(.red)
                                    }
                                    .padding(12)
                                    .background(.red.opacity(0.08))
                                    .clipShape(RoundedRectangle(cornerRadius: 10))
                                }
                            }
                        }
                        .padding(.horizontal)
                    }
                }
                .padding(.vertical)
            }
            .navigationTitle("Dashboard")
            .task {
                if let storeId = storeViewModel.selectedStore?.id {
                    await inventoryVM.loadData(storeId: storeId)
                    await ordersVM.loadOrders(storeId: storeId)
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

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: icon)
                    .font(.title3)
                    .foregroundStyle(color)
                Spacer()
            }
            Text(value)
                .font(.title2.bold())
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(color.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 14))
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
            VStack(alignment: .leading, spacing: 4) {
                Text(order.orderNumber)
                    .font(.subheadline.weight(.medium))
                HStack(spacing: 8) {
                    Text(order.source.displayName)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("·")
                        .foregroundStyle(.secondary)
                    Text("\(order.itemCount) items")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text(order.formattedTotal)
                    .font(.subheadline.weight(.semibold))
                Text(order.status.displayName)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(statusColor)
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
}

#Preview {
    DashboardView()
        .environment(AuthViewModel())
        .environment(StoreViewModel())
}
