//
//  FinancialsTabView.swift
//  retailmanagement
//

import SwiftUI

struct FinancialSummary {
    let totalRevenue: Double
    let totalOrders: Int
    let averageOrderValue: Double
    let topPaymentMethod: String
    let completedOrders: Int
    let voidedOrders: Int
    let discountsGiven: Double
    let taxCollected: Double
}

@MainActor
@Observable
final class FinancialsViewModel {
    var summary: FinancialSummary?
    var dailyRevenue: [(day: String, amount: Double)] = []
    var isLoading = false
    var errorMessage: String?

    func loadFinancials(storeId: String) async {
        isLoading = true
        errorMessage = nil

        do {
            let response: PaginatedResponse<Order> = try await NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/orders?page_size=500"
            )
            let orders = response.data

            let completed = orders.filter { $0.status == .completed }
            let totalRevenue = completed.reduce(0.0) { $0 + $1.grandTotal }
            let totalOrders = orders.count
            let avg = totalOrders > 0 ? totalRevenue / Double(completed.count.nonZero ?? 1) : 0

            // Count payment methods to find top
            var paymentCounts: [String: Int] = [:]
            for order in completed {
                paymentCounts[order.paymentMethod, default: 0] += 1
            }
            let topPayment = paymentCounts.max(by: { $0.value < $1.value })?.key ?? "—"

            summary = FinancialSummary(
                totalRevenue: totalRevenue,
                totalOrders: totalOrders,
                averageOrderValue: avg,
                topPaymentMethod: topPayment,
                completedOrders: completed.count,
                voidedOrders: orders.filter { $0.status == .voided }.count,
                discountsGiven: orders.reduce(0.0) { $0 + $1.discountTotal },
                taxCollected: completed.reduce(0.0) { $0 + $1.taxTotal }
            )

            // Build daily revenue from order dates (last 5 unique days)
            let dateFormatter = DateFormatter()
            dateFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            let displayFormatter = DateFormatter()
            displayFormatter.dateFormat = "MMM d"

            var daily: [String: Double] = [:]
            for order in completed {
                if let date = dateFormatter.date(from: order.orderDate) {
                    let key = displayFormatter.string(from: date)
                    daily[key, default: 0] += order.grandTotal
                }
            }
            dailyRevenue = daily.sorted(by: { $0.key < $1.key }).suffix(5).map { ($0.key, $0.value) }

        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }
}

private extension Int {
    var nonZero: Int? { self == 0 ? nil : self }
}

struct FinancialsTabView: View {
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var financialsVM = FinancialsViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if financialsVM.isLoading {
                    ProgressView("Loading financials...")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if let summary = financialsVM.summary {
                    ScrollView {
                        VStack(spacing: 20) {
                            // Revenue highlight
                            VStack(spacing: 4) {
                                Text("Total Revenue")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                Text(String(format: "$%.2f", summary.totalRevenue))
                                    .font(.system(size: 36, weight: .bold))
                                    .foregroundStyle(.green)
                                Text("\(summary.totalOrders) orders · Avg \(String(format: "$%.2f", summary.averageOrderValue))")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 20)
                            .background(.green.opacity(0.06))
                            .clipShape(RoundedRectangle(cornerRadius: 16))
                            .padding(.horizontal)

                            // Revenue chart (simple bar representation)
                            VStack(alignment: .leading, spacing: 12) {
                                Text("Daily Revenue (Last 5 Days)")
                                    .font(.headline)
                                    .padding(.horizontal)

                                let maxRevenue = financialsVM.dailyRevenue.map(\.amount).max() ?? 1

                                ForEach(Array(financialsVM.dailyRevenue.enumerated()), id: \.offset) { _, entry in
                                    HStack(spacing: 12) {
                                        Text(entry.day)
                                            .font(.caption)
                                            .frame(width: 44, alignment: .leading)
                                        GeometryReader { geo in
                                            RoundedRectangle(cornerRadius: 4)
                                                .fill(.blue.gradient)
                                                .frame(width: max(4, geo.size.width * CGFloat(entry.amount / maxRevenue)))
                                        }
                                        .frame(height: 20)
                                        Text(String(format: "$%.0f", entry.amount))
                                            .font(.caption.weight(.medium))
                                            .frame(width: 60, alignment: .trailing)
                                    }
                                    .padding(.horizontal)
                                }
                            }

                            // Breakdown cards
                            LazyVGrid(columns: [
                                GridItem(.flexible()),
                                GridItem(.flexible()),
                            ], spacing: 12) {
                                FinancialCard(title: "Completed", value: "\(summary.completedOrders)", icon: "checkmark.circle.fill", color: .green)
                                FinancialCard(title: "Voided", value: "\(summary.voidedOrders)", icon: "xmark.circle.fill", color: .red)
                                FinancialCard(title: "Discounts", value: String(format: "$%.2f", summary.discountsGiven), icon: "tag.fill", color: .orange)
                                FinancialCard(title: "Tax Collected", value: String(format: "$%.2f", summary.taxCollected), icon: "building.columns.fill", color: .blue)
                            }
                            .padding(.horizontal)

                            // Payment breakdown
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Top Payment Method")
                                    .font(.headline)
                                HStack {
                                    Image(systemName: "creditcard.fill")
                                        .foregroundStyle(.blue)
                                    Text(summary.topPaymentMethod)
                                        .font(.subheadline)
                                }
                                .padding()
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(.quaternary.opacity(0.5))
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                            }
                            .padding(.horizontal)
                        }
                        .padding(.vertical)
                    }
                } else {
                    ContentUnavailableView(
                        "No Financial Data",
                        systemImage: "dollarsign.circle",
                        description: Text("Financial data will appear once orders are processed.")
                    )
                }
            }
            .navigationTitle("Financials")
            .task {
                if let storeId = storeViewModel.selectedStore?.id {
                    await financialsVM.loadFinancials(storeId: storeId)
                }
            }
        }
    }
}

struct FinancialCard: View {
    let title: String
    let value: String
    let icon: String
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(color)
            Text(value)
                .font(.headline)
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(color.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

#Preview {
    FinancialsTabView()
        .environment(StoreViewModel())
}
