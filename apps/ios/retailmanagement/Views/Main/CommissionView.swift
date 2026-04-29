//
//  CommissionView.swift
//  retailmanagement
//
//  Mirrors the staff-portal CommissionPage on mobile: a 6-month sales +
//  commission chart for the current user, plus the active commission tier
//  rules. Skips the recharts bar chart used on web — uses a Swift Charts
//  stacked bar (iOS 16+) which is the native equivalent and gives free
//  accessibility/dark-mode support.
//

import Charts
import SwiftUI

struct CommissionView: View {
    @Environment(AuthViewModel.self) private var authViewModel
    @Environment(StoreViewModel.self) private var storeViewModel
    @State private var vm = CommissionViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading {
                    ProgressView("Loading commission\u2026")
                } else if let err = vm.errorMessage {
                    ContentUnavailableView("Couldn\u2019t load commission",
                                           systemImage: "exclamationmark.triangle",
                                           description: Text(err))
                } else if vm.months.isEmpty && vm.rules.isEmpty {
                    ContentUnavailableView("No commission yet",
                                           systemImage: "percent",
                                           description: Text("Once your store posts a payroll run, your sales and commission appear here."))
                } else {
                    body(.padding)
                }
            }
            .navigationTitle("Commission")
            .task { await load() }
            .refreshable { await load() }
        }
    }

    private func body(_ pad: Edge.Set) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                summaryCard
                if !vm.months.isEmpty { chartSection }
                if !vm.rules.isEmpty { rulesSection }
            }
            .padding()
        }
    }

    private var summaryCard: some View {
        HStack(spacing: 12) {
            metric(title: "6-mo sales", value: currency(vm.totalSales))
            Divider().frame(height: 30)
            metric(title: "6-mo commission", value: currency(vm.totalCommission), tint: .green)
            if let profile = vm.profile {
                Divider().frame(height: 30)
                metric(title: "Default rate",
                       value: profile.commissionRate.map { String(format: "%.1f%%", $0 * 100) } ?? "—")
            }
        }
        .padding()
        .background(.ultraThinMaterial)
        .cornerRadius(12)
    }

    @ViewBuilder
    private var chartSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Monthly").font(.headline)
            Chart(vm.months) { m in
                BarMark(
                    x: .value("Month", m.label),
                    y: .value("Commission", m.commission)
                )
                .foregroundStyle(.green)
                .annotation(position: .top, alignment: .center) {
                    Text(currency(m.commission))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(height: 180)
        }
    }

    @ViewBuilder
    private var rulesSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Tier rules").font(.headline)
            ForEach(vm.rules) { rule in
                VStack(alignment: .leading, spacing: 6) {
                    Text(rule.name).font(.subheadline.bold())
                    ForEach(Array(rule.tiers.enumerated()), id: \.offset) { _, tier in
                        HStack(spacing: 6) {
                            Text(tierBoundary(tier))
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text(String(format: "%.1f%%", tier.rate * 100))
                                .font(.caption.bold())
                                .foregroundStyle(.green)
                        }
                    }
                }
                .padding()
                .background(.ultraThinMaterial)
                .cornerRadius(10)
            }
        }
    }

    private func metric(title: String, value: String, tint: Color = .primary) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title3.bold()).foregroundStyle(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func tierBoundary(_ tier: CommissionTier) -> String {
        if let max = tier.max {
            return "\(currency(tier.min)) \u2013 \(currency(max))"
        }
        return "\(currency(tier.min)) +"
    }

    private func currency(_ v: Double) -> String { String(format: "$%.0f", v) }

    private func load() async {
        guard let storeId = storeViewModel.selectedStore?.id,
              let userId = authViewModel.currentUser?.id else { return }
        await vm.load(storeId: storeId, userId: userId)
    }
}

#Preview {
    CommissionView()
        .environment(AuthViewModel())
        .environment(StoreViewModel())
}
