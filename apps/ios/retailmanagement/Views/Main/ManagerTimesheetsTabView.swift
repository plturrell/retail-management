//
//  ManagerTimesheetsTabView.swift
//  retailmanagement
//

import SwiftUI

struct ManagerTimesheetsTabView: View {
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var viewModel = ManagerTimesheetsViewModel()
    @State private var selectedTab: Tab = .pending

    enum Tab: String, CaseIterable, Identifiable {
        case pending = "Pending"
        case summary = "Payroll Summary"
        var id: String { rawValue }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Picker("Tab", selection: $selectedTab) {
                    ForEach(Tab.allCases) { tab in
                        Text(tabLabel(tab)).tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .padding()

                if let error = viewModel.errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding(.horizontal)
                }

                switch selectedTab {
                case .pending: pendingTab
                case .summary: summaryTab
                }
            }
            .navigationTitle("Timesheet Approvals")
            .task { await viewModel.loadPending(storeId: storeId) }
            .refreshable { await reload() }
            .onChange(of: selectedTab) { _, newValue in
                Task {
                    if newValue == .pending {
                        await viewModel.loadPending(storeId: storeId)
                    } else {
                        await viewModel.loadSummary(storeId: storeId)
                    }
                }
            }
        }
    }

    private var storeId: String { storeViewModel.selectedStore?.id ?? "" }

    private func reload() async {
        if selectedTab == .pending {
            await viewModel.loadPending(storeId: storeId)
        } else {
            await viewModel.loadSummary(storeId: storeId)
        }
    }

    private func tabLabel(_ tab: Tab) -> String {
        switch tab {
        case .pending:
            return viewModel.pendingEntries.isEmpty
                ? "Pending"
                : "Pending (\(viewModel.pendingEntries.count))"
        case .summary:
            return "Payroll Summary"
        }
    }

    // MARK: - Pending

    private var pendingTab: some View {
        Group {
            if viewModel.isLoading {
                Spacer(); ProgressView("Loading…"); Spacer()
            } else if viewModel.pendingEntries.isEmpty {
                Spacer()
                ContentUnavailableView(
                    "No Pending Reviews",
                    systemImage: "checkmark.seal",
                    description: Text("All timesheet entries have been reviewed.")
                )
                Spacer()
            } else {
                List(viewModel.pendingEntries) { entry in
                    pendingRow(entry)
                }
                .insetGroupedListStyleCompat()
            }
        }
    }

    private func pendingRow(_ entry: TimeEntry) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(entry.formattedDate).font(.headline)
            Text("\(entry.clockInTime) – \(entry.clockOutTime ?? "—")")
                .font(.subheadline).foregroundStyle(.secondary)
            if let hours = entry.hoursWorked {
                Text(String(format: "%.2f hours", hours))
                    .font(.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: 12) {
                Button {
                    Task { await viewModel.updateStatus(storeId: storeId, entryId: entry.id, status: "approved") }
                } label: {
                    Label("Approve", systemImage: "checkmark.circle.fill")
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)

                Button {
                    Task { await viewModel.updateStatus(storeId: storeId, entryId: entry.id, status: "rejected") }
                } label: {
                    Label("Reject", systemImage: "xmark.circle.fill")
                }
                .buttonStyle(.bordered)
                .tint(.red)
            }
            .disabled(viewModel.isActionLoading)
        }
        .padding(.vertical, 4)
    }

    // MARK: - Summary

    private var summaryTab: some View {
        Group {
            if viewModel.summaryLoading {
                Spacer(); ProgressView("Loading…"); Spacer()
            } else if let summary = viewModel.summary, !summary.summaries.isEmpty {
                List(summary.summaries) { entry in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(entry.fullName).font(.headline)
                            Text("\(entry.totalDays) days worked")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(String(format: "%.1f hrs", entry.totalHours))
                            .font(.headline.weight(.semibold))
                    }
                }
                .insetGroupedListStyleCompat()
            } else {
                Spacer()
                ContentUnavailableView(
                    "No Summary Yet",
                    systemImage: "chart.bar",
                    description: Text("Pull to load the current period's payroll summary.")
                )
                Spacer()
            }
        }
    }
}
