//
//  VendorReviewTabView.swift
//  retailmanagement
//
//  Native implementation of the SupplierReviewPage.
//

import SwiftUI

struct VendorReviewTabView: View {
    @State private var vm = VendorReviewViewModel()
    @State private var selectedLineKey: String? = "1"

    // Based on hengweiInvoiceAssets for order 364-365
    let imageWidth: CGFloat = 1056
    let imageHeight: CGFloat = 4026
    let cropRegions: [String: CGRect] = [
        "1": CGRect(x: 92, y: 488, width: 192, height: 116),
        "2": CGRect(x: 92, y: 610, width: 192, height: 116),
        "3": CGRect(x: 92, y: 732, width: 192, height: 116),
        "10": CGRect(x: 92, y: 1760, width: 192, height: 198)
    ]

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading {
                    ProgressView("Loading vendor data...")
                } else if let err = vm.error {
                    ContentUnavailableView("Error loading data", systemImage: "exclamationmark.triangle", description: Text(err))
                } else if let order = vm.order {
                    #if os(macOS) || targetEnvironment(macCatalyst)
                    HStack(spacing: 0) {
                        imageViewer
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                        Divider()
                        reconciliationList(order: order)
                            .frame(width: 400)
                    }
                    #else
                    // On iPhone/iPad, use a VStack or SplitView
                    VStack(spacing: 0) {
                        imageViewer
                            .frame(height: 300)
                            .clipShape(Rectangle())
                        Divider()
                        reconciliationList(order: order)
                    }
                    #endif
                } else {
                    ContentUnavailableView("No Data", systemImage: "doc.text.magnifyingglass")
                }
            }
            .navigationTitle("Vendor Review")
            .task {
                await vm.loadOrder()
            }
        }
    }

    // MARK: - Image Viewer
    private var imageViewer: some View {
        ZStack {
            Color(white: 0.1).edgesIgnoringSafeArea(.all)
            
            GeometryReader { geo in
                ScrollView([.horizontal, .vertical], showsIndicators: true) {
                    ZStack(alignment: .topLeading) {
                        // The raw invoice image
                        // Note: In production this would be downloaded/cached. Here we point to the local Vite dev server or use a placeholder if unavailable.
                        AsyncImage(url: URL(string: "http://localhost:5173/docs/suppliers/hengweicraft/orders/order-364-365-2026-03-26-source.PNG")) { phase in
                            switch phase {
                            case .empty:
                                ProgressView().frame(width: imageWidth, height: imageHeight)
                            case .success(let image):
                                image.resizable().scaledToFit()
                            case .failure:
                                Rectangle()
                                    .fill(Color.gray.opacity(0.3))
                                    .overlay(Text("Invoice Image Unreachable").foregroundStyle(.white))
                            @unknown default:
                                EmptyView()
                            }
                        }
                        .frame(width: imageWidth, height: imageHeight)

                        // Overlays
                        ForEach(Array(cropRegions.keys), id: \.self) { key in
                            if let rect = cropRegions[key] {
                                let isSelected = selectedLineKey == key
                                Rectangle()
                                    .fill(isSelected ? Color.blue.opacity(0.3) : Color.clear)
                                    .border(isSelected ? Color.blue : Color.yellow.opacity(0.5), width: isSelected ? 3 : 1)
                                    .frame(width: rect.width, height: rect.height)
                                    .position(x: rect.midX, y: rect.midY)
                                    .onTapGesture {
                                        selectedLineKey = key
                                    }
                            }
                        }
                    }
                }
            }
        }
    }

    // MARK: - Reconciliation List
    private func reconciliationList(order: VendorReviewOrderRecord) -> some View {
        List(order.lineItems, selection: $selectedLineKey) { line in
            let key = String(line.sourceLineNumber)
            let state = vm.workspace.orders[order.orderNumber]?.lines[key] ?? ReviewLineState(status: .unreviewed, note: "", targetSkuId: "", updatedAt: nil)
            
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Line \(line.sourceLineNumber)")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                        
                        Text(line.displayName ?? line.materialDescription ?? "Unknown Item")
                            .font(.headline)
                            .lineLimit(2)
                        
                        if let size = line.size {
                            Text(size).font(.caption2).padding(4).background(Color.secondary.opacity(0.1)).cornerRadius(4)
                        }
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 4) {
                        if let qty = line.quantity, let cost = line.unitCostCny, let total = line.lineTotalCny {
                            Text("¥\(String(format: "%.0f", total))")
                                .font(.headline.monospaced())
                            Text("\(qty) × ¥\(String(format: "%.0f", cost))")
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                
                HStack {
                    Text("Target SKU: \(line.supplierItemCode ?? "UNMAPPED")")
                        .font(.caption.monospaced())
                        .foregroundStyle(line.supplierItemCode == nil ? .red : .green)
                    
                    Spacer()
                    
                    Picker("Status", selection: Binding(
                        get: { state.status },
                        set: { newStatus in
                            vm.updateLineStatus(orderNumber: order.orderNumber, lineKey: key, status: newStatus, note: state.note)
                        }
                    )) {
                        Text("Unreviewed").tag(ReviewLineStatus.unreviewed)
                        Text("Verified").tag(ReviewLineStatus.verified)
                        Text("Needs Follow-up").tag(ReviewLineStatus.needsFollowUp)
                    }
                    .pickerStyle(.menu)
                    .tint(statusColor(state.status))
                }
            }
            .padding(.vertical, 4)
            .contentShape(Rectangle())
            .onTapGesture {
                selectedLineKey = key
            }
            .listRowBackground(selectedLineKey == key ? Color.blue.opacity(0.1) : nil)
            .tag(key)
        }
        .listStyle(.plain)
    }
    
    private func statusColor(_ status: ReviewLineStatus) -> Color {
        switch status {
        case .unreviewed: return .secondary
        case .verified: return .green
        case .needsFollowUp: return .orange
        }
    }
}
