//
//  TimesheetView.swift
//  retailmanagement
//

import SwiftUI

struct TimesheetView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var viewModel = TimesheetViewModel()
    @State private var breakMinutes: Int = 0
    @State private var showClockOutConfirm = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Clock In/Out Card
                clockCard
                    .padding()

                if let error = viewModel.errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding(.horizontal)
                }

                // History
                if viewModel.isLoading {
                    Spacer()
                    ProgressView("Loading history...")
                    Spacer()
                } else if viewModel.history.isEmpty {
                    Spacer()
                    ContentUnavailableView(
                        "No Timesheet Entries",
                        systemImage: "clock.badge.questionmark",
                        description: Text("Your timesheet history will appear here.")
                    )
                    Spacer()
                } else {
                    historyList
                }
            }
            .navigationTitle("Timesheet")
            .task { await loadData() }
            .refreshable { await loadData() }
            .alert("Clock Out", isPresented: $showClockOutConfirm) {
                TextField("Break (minutes)", value: $breakMinutes, format: .number)
                Button("Clock Out") {
                    Task { await viewModel.clockOut(breakMinutes: breakMinutes) }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Enter break time in minutes, then confirm clock out.")
            }
        }
    }

    // MARK: - Clock Card

    private var clockCard: some View {
        VStack(spacing: 16) {
            if viewModel.isClockedIn {
                // Timer display
                Text(viewModel.formattedElapsed)
                    .font(.system(size: 48, weight: .light, design: .monospaced))
                    .foregroundStyle(.green)

                Text("Clocked in at \(viewModel.activeEntry?.clockInTime ?? "")")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                Button {
                    showClockOutConfirm = true
                } label: {
                    Label("Clock Out", systemImage: "stop.circle.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.red)
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                .disabled(viewModel.isClockingOut)
            } else {
                Image(systemName: "clock.fill")
                    .font(.system(size: 48))
                    .foregroundStyle(.blue.opacity(0.6))

                Text("Ready to start your shift?")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                Button {
                    guard let storeId = storeViewModel.selectedStore?.id else { return }
                    Task { await viewModel.clockIn(storeId: storeId) }
                } label: {
                    Label("Clock In", systemImage: "play.circle.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.green)
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                .disabled(viewModel.isClockingIn || storeViewModel.selectedStore == nil)
            }
        }
        .padding()
        .background(Color.secondarySystemBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - History List

    private var historyList: some View {
        List(viewModel.history) { entry in
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(entry.formattedDate)
                        .font(.headline)
                    Text("\(entry.clockInTime) – \(entry.clockOutTime ?? "Active")")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    if let hours = entry.hoursWorked {
                        Text(String(format: "%.1fh", hours))
                            .font(.headline)
                    }
                    statusBadge(entry.status)
                }
            }
            .padding(.vertical, 4)
        }
        .listStyle(.insetGrouped)
    }

    private func statusBadge(_ status: String) -> some View {
        Text(status.capitalized)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(statusColor(status).opacity(0.15))
            .foregroundStyle(statusColor(status))
            .clipShape(Capsule())
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "approved": return .green
        case "rejected": return .red
        case "pending": return .orange
        default: return .gray
        }
    }

    private func loadData() async {
        await viewModel.checkStatus()
        guard let storeId = storeViewModel.selectedStore?.id else { return }
        await viewModel.fetchHistory(storeId: storeId)
    }
}
