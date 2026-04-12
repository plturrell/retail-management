//
//  OrdersTabView.swift
//  retailmanagement
//

import SwiftUI

struct OrdersTabView: View {
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var ordersVM = OrdersViewModel()
    @State private var selectedOrder: Order?

    var body: some View {
        NavigationStack {
            Group {
                if ordersVM.isLoading {
                    ProgressView("Loading orders...")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if ordersVM.orders.isEmpty {
                    ContentUnavailableView(
                        "No Orders",
                        systemImage: "cart",
                        description: Text("Orders will appear here once placed.")
                    )
                } else {
                    List {
                        // Filter chips
                        Section {
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 8) {
                                    FilterChip(label: "All", isSelected: ordersVM.filterStatus == nil) {
                                        ordersVM.filterStatus = nil
                                    }
                                    ForEach(OrderStatus.allCases, id: \.self) { status in
                                        FilterChip(label: status.displayName, isSelected: ordersVM.filterStatus == status) {
                                            ordersVM.filterStatus = status
                                        }
                                    }
                                }
                            }
                        }

                        // Order list
                        Section("\(ordersVM.filteredOrders.count) Orders") {
                            ForEach(ordersVM.filteredOrders) { order in
                                Button {
                                    selectedOrder = order
                                } label: {
                                    OrderListRow(order: order)
                                }
                                .foregroundStyle(.primary)
                            }
                        }
                    }
                    .searchable(text: $ordersVM.searchText, prompt: "Search orders")
                }
            }
            .navigationTitle("Orders")
            .task {
                if let storeId = storeViewModel.selectedStore?.id {
                    await ordersVM.loadOrders(storeId: storeId)
                }
            }
            .sheet(item: $selectedOrder) { order in
                OrderDetailView(order: order)
            }
        }
    }
}

// MARK: - Supporting Views

struct FilterChip: View {
    let label: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.subheadline.weight(isSelected ? .semibold : .regular))
                .padding(.horizontal, 14)
                .padding(.vertical, 7)
                .background(isSelected ? Color.blue : Color.clear)
                .foregroundStyle(isSelected ? .white : .primary)
                .clipShape(Capsule())
                .overlay(
                    Capsule()
                        .strokeBorder(isSelected ? Color.clear : Color.secondary.opacity(0.3), lineWidth: 1)
                )
        }
    }
}

struct OrderListRow: View {
    let order: Order

    var statusColor: Color {
        switch order.status {
        case .open: return .blue
        case .completed: return .green
        case .voided: return .red
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(order.orderNumber)
                    .font(.subheadline.weight(.medium).monospaced())
                Spacer()
                Text(order.status.displayName)
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(statusColor.opacity(0.12))
                    .foregroundStyle(statusColor)
                    .clipShape(Capsule())
            }

            HStack {
                Label(order.source.displayName, systemImage: "arrow.right.circle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(order.paymentMethod)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack {
                Text("\(order.itemCount) items")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(order.formattedTotal)
                    .font(.subheadline.weight(.bold))
            }
        }
        .padding(.vertical, 4)
    }
}

struct OrderDetailView: View {
    let order: Order
    @Environment(\.dismiss) private var dismiss

    var statusColor: Color {
        switch order.status {
        case .open: return .blue
        case .completed: return .green
        case .voided: return .red
        }
    }

    var body: some View {
        NavigationStack {
            List {
                Section("Order Info") {
                    LabeledContent("Order #", value: order.orderNumber)
                    HStack {
                        Text("Status")
                        Spacer()
                        Text(order.status.displayName)
                            .fontWeight(.semibold)
                            .foregroundStyle(statusColor)
                    }
                    LabeledContent("Source", value: order.source.displayName)
                    LabeledContent("Date", value: order.orderDate)
                    LabeledContent("Payment", value: order.paymentMethod)
                    if let ref = order.paymentRef {
                        LabeledContent("Reference", value: ref)
                    }
                }

                Section("Items (\(order.items.count))") {
                    ForEach(order.items) { item in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("SKU: \(item.skuId)")
                                    .font(.subheadline)
                                Text("Qty: \(item.qty) × \(String(format: "$%.2f", item.unitPrice))")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(item.formattedPrice)
                                    .font(.subheadline.weight(.medium))
                                if item.discount > 0 {
                                    Text("-\(String(format: "$%.2f", item.discount))")
                                        .font(.caption)
                                        .foregroundStyle(.green)
                                }
                            }
                        }
                    }
                }

                Section("Totals") {
                    LabeledContent("Subtotal", value: String(format: "$%.2f", order.subtotal))
                    if order.discountTotal > 0 {
                        LabeledContent("Discount", value: String(format: "-$%.2f", order.discountTotal))
                    }
                    LabeledContent("Tax", value: String(format: "$%.2f", order.taxTotal))
                    HStack {
                        Text("Grand Total")
                            .fontWeight(.bold)
                        Spacer()
                        Text(order.formattedTotal)
                            .fontWeight(.bold)
                    }
                }
            }
            .navigationTitle("Order Details")
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
    OrdersTabView()
        .environment(StoreViewModel())
}
