//
//  PerformanceView.swift
//  retailmanagement
//

import Charts
import SwiftUI

struct PerformanceView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var viewModel = PerformanceViewModel()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    if viewModel.isLoading {
                        ProgressView("Loading performance data...")
                            .padding(.top, 40)
                    } else if let error = viewModel.errorMessage {
                        ContentUnavailableView(
                            "Error",
                            systemImage: "exclamationmark.triangle",
                            description: Text(error)
                        )
                    } else {
                        if let my = viewModel.myPerformance {
                            myPerformanceCard(my)
                        }
                        if !viewModel.salesByStaff.isEmpty {
                            salesChart
                        }
                        if let overview = viewModel.overview, !overview.staff.isEmpty {
                            peerRankingSection(overview)
                        }
                        if let insights = viewModel.insights, let ai = insights.aiInsights {
                            aiInsightsCard(ai)
                        }
                    }
                }
                .padding()
            }
            .navigationTitle("Performance")
            .task { await loadData() }
            .refreshable { await loadData() }
        }
    }

    private func myPerformanceCard(_ item: StaffPerformanceItem) -> some View {
        VStack(spacing: 12) {
            HStack {
                Text("Your Performance")
                    .font(.headline)
                Spacer()
                Text("Rank #\(item.rank)")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.blue)
            }
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                kpiTile(title: "Total Sales", value: "$\(String(format: "%.0f", item.totalSales))", icon: "dollarsign.circle.fill", color: .green)
                kpiTile(title: "Orders", value: "\(item.orderCount)", icon: "bag.fill", color: .blue)
                kpiTile(title: "Avg Order", value: "$\(String(format: "%.0f", item.avgOrderValue))", icon: "chart.bar.fill", color: .orange)
                kpiTile(title: "Period", value: "\(viewModel.periodDays)d", icon: "calendar", color: .purple)
            }
        }
        .padding()
        .background(Color.secondarySystemBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private func kpiTile(title: String, value: String, icon: String, color: Color) -> some View {
        VStack(spacing: 6) {
            Image(systemName: icon).font(.title2).foregroundStyle(color)
            Text(value).font(.title3.weight(.semibold))
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
        .background(color.opacity(0.1))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private var salesChart: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Sales by Staff").font(.headline)
            Chart(viewModel.salesByStaff) { staff in
                BarMark(
                    x: .value("Sales", staff.totalSales),
                    y: .value("Staff", staff.salespersonName ?? "Unknown")
                )
                .foregroundStyle(.blue.gradient)
            }
            .chartYAxis { AxisMarks { _ in AxisValueLabel() } }
            .frame(height: CGFloat(max(viewModel.salesByStaff.count * 44, 120)))
        }
        .padding()
        .background(Color.secondarySystemBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private func peerRankingSection(_ overview: StaffPerformanceOverview) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Peer Ranking").font(.headline)
            ForEach(overview.staff) { staff in
                HStack {
                    Text("#\(staff.rank)").font(.headline)
                        .foregroundStyle(staff.rank <= 3 ? .orange : .secondary)
                        .frame(width: 36)
                    Text(staff.fullName).font(.subheadline)
                        .fontWeight(staff.userId == authViewModel.currentUser?.id ? .bold : .regular)
                    if staff.userId == authViewModel.currentUser?.id {
                        Text("You").font(.caption2.weight(.semibold))
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(Color.blue.opacity(0.15))
                            .foregroundStyle(.blue).clipShape(Capsule())
                    }
                    Spacer()
                    Text("$\(String(format: "%.0f", staff.totalSales))")
                        .font(.subheadline.weight(.semibold))
                }
                .padding(.vertical, 4)
            }
        }
        .padding()
        .background(Color.secondarySystemBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private func aiInsightsCard(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "sparkles").foregroundStyle(.purple)
                Text("AI Insights").font(.headline)
            }
            Text(text).font(.body).foregroundStyle(.secondary)
        }
        .padding()
        .background(Color.secondarySystemBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private func loadData() async {
        guard let storeId = storeViewModel.selectedStore?.id,
              let userId = authViewModel.currentUser?.id else { return }
        await viewModel.fetchPerformance(storeId: storeId, userId: userId)
        await viewModel.fetchInsights(storeId: storeId, userId: userId)
    }
}

#Preview {
    PerformanceView()
        .environment(AuthViewModel())
        .environment(StoreViewModel())
}
