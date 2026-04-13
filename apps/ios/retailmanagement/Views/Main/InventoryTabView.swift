//
//  InventoryTabView.swift
//  retailmanagement
//

import SwiftUI

struct InventoryTabView: View {
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var inventoryVM = InventoryViewModel()
    @State private var selectedSKU: SKU?

    var body: some View {
        NavigationStack {
            Group {
                if inventoryVM.isLoading {
                    ProgressView("Loading inventory...")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if inventoryVM.skus.isEmpty {
                    ContentUnavailableView(
                        "No Products",
                        systemImage: "shippingbox",
                        description: Text("Add products to get started.")
                    )
                } else {
                    List {
                        // Summary section
                        Section {
                            HStack(spacing: 24) {
                                StatBadge(label: "SKUs", value: "\(inventoryVM.totalSKUs)", color: .blue)
                                StatBadge(label: "Low Stock", value: "\(inventoryVM.lowStockItems.count)", color: .red)
                                StatBadge(label: "Categories", value: "\(inventoryVM.categories.count)", color: .purple)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 4)
                        }

                        // Product list
                        Section("Products") {
                            ForEach(inventoryVM.filteredSKUs) { sku in
                                Button {
                                    selectedSKU = sku
                                } label: {
                                    SKURowView(
                                        sku: sku,
                                        inventory: inventoryVM.inventoryFor(skuId: sku.id)
                                    )
                                }
                                .foregroundStyle(.primary)
                            }
                        }
                    }
                    .searchable(text: $inventoryVM.searchText, prompt: "Search by SKU or name")
                }
            }
            .navigationTitle("Inventory")
            .task {
                if let storeId = storeViewModel.selectedStore?.id {
                    await inventoryVM.loadData(storeId: storeId)
                }
            }
            .sheet(item: $selectedSKU) { sku in
                SKUDetailView(sku: sku, inventory: inventoryVM.inventoryFor(skuId: sku.id))
            }
        }
    }
}

// MARK: - Supporting Views

struct StatBadge: View {
    let label: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.title3.bold())
                .foregroundStyle(color)
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

struct SKURowView: View {
    let sku: SKU
    let inventory: InventoryItem?

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(sku.description)
                    .font(.subheadline.weight(.medium))
                HStack(spacing: 8) {
                    Text(sku.skuCode)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                    if sku.isUniquePiece {
                        Text("UNIQUE")
                            .font(.system(size: 9, weight: .bold))
                            .padding(.horizontal, 5)
                            .padding(.vertical, 2)
                            .background(.purple.opacity(0.15))
                            .foregroundStyle(.purple)
                            .clipShape(Capsule())
                    }
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text(sku.displayPrice)
                    .font(.subheadline.weight(.semibold))
                if let inv = inventory {
                    Text("Qty: \(inv.qtyOnHand)")
                        .font(.caption)
                        .foregroundStyle(inv.isLowStock ? .red : .secondary)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

struct SKUDetailView: View {
    let sku: SKU
    let inventory: InventoryItem?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section("Product Info") {
                    LabeledContent("SKU Code", value: sku.skuCode)
                    LabeledContent("Description", value: sku.description)
                    if let longDesc = sku.longDescription {
                        LabeledContent("Details", value: longDesc)
                    }
                    LabeledContent("Cost Price", value: sku.displayPrice)
                    LabeledContent("Tax Code", value: sku.taxCode)
                    if let gender = sku.gender {
                        LabeledContent("Gender", value: gender)
                    }
                    if let age = sku.ageGroup {
                        LabeledContent("Age Group", value: age)
                    }
                }

                Section("Flags") {
                    LabeledContent("Unique Piece", value: sku.isUniquePiece ? "Yes" : "No")
                    LabeledContent("Uses Stock", value: sku.useStock ? "Yes" : "No")
                    LabeledContent("Block Sales", value: sku.blockSales ? "Yes" : "No")
                }

                if let inv = inventory {
                    Section("Stock") {
                        LabeledContent("On Hand", value: "\(inv.qtyOnHand)")
                        LabeledContent("Reorder Level", value: "\(inv.reorderLevel)")
                        LabeledContent("Reorder Qty", value: "\(inv.reorderQty)")
                        if let serial = inv.serialNumber {
                            LabeledContent("Serial #", value: serial)
                        }
                        if inv.isLowStock {
                            HStack {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .foregroundStyle(.red)
                                Text("Low stock — reorder needed")
                                    .foregroundStyle(.red)
                            }
                        }
                    }
                }
            }
            .navigationTitle(sku.description)
            #if canImport(UIKit)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

#Preview {
    InventoryTabView()
        .environment(StoreViewModel())
}
