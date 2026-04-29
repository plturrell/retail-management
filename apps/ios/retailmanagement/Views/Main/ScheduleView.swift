//
//  ScheduleView.swift
//  retailmanagement
//

import SwiftUI

struct ScheduleView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var viewModel = ScheduleViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Week navigation bar
                weekNavigationBar

                if viewModel.isLoading {
                    Spacer()
                    ProgressView("Loading shifts...")
                    Spacer()
                } else if viewModel.shifts.isEmpty {
                    Spacer()
                    ContentUnavailableView(
                        "No Shifts",
                        systemImage: "calendar.badge.exclamationmark",
                        description: Text("You have no shifts scheduled for this week.")
                    )
                    Spacer()
                } else {
                    shiftsList
                }
            }
            .navigationTitle("Schedule")
            .task { await loadShifts() }
            .refreshable { await loadShifts() }
            .onChange(of: viewModel.weekStart) { _, _ in
                Task { await loadShifts() }
            }
        }
    }

    // MARK: - Week Navigation

    private var weekNavigationBar: some View {
        HStack {
            Button { viewModel.goToPreviousWeek() } label: {
                Image(systemName: "chevron.left")
                    .fontWeight(.semibold)
            }

            Spacer()

            VStack(spacing: 2) {
                Text(viewModel.weekLabel)
                    .font(.headline)

                Button("Today") { viewModel.goToCurrentWeek() }
                    .font(.caption)
                    .foregroundStyle(.blue)
            }

            Spacer()

            Button { viewModel.goToNextWeek() } label: {
                Image(systemName: "chevron.right")
                    .fontWeight(.semibold)
            }
        }
        .padding()
        .background(Color.secondarySystemBackground)
    }

    // MARK: - Shifts List

    private var shiftsList: some View {
        List {
            ForEach(viewModel.shiftsByDate) { dayGroup in
                Section {
                    ForEach(dayGroup.shifts) { shift in
                        shiftRow(shift)
                    }
                } header: {
                    Text(formattedDayHeader(dayGroup.date))
                        .font(.subheadline.weight(.semibold))
                }
            }
        }
        .insetGroupedListStyleCompat()
    }

    private func shiftRow(_ shift: Shift) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(shift.timeRange)
                    .font(.headline)

                Text("\(String(format: "%.1f", shift.hours)) hrs")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                if shift.breakMinutes > 0 {
                    Text("\(shift.breakMinutes) min break")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            if let notes = shift.notes, !notes.isEmpty {
                Image(systemName: "note.text")
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: - Helpers

    private func loadShifts() async {
        guard let storeId = storeViewModel.selectedStore?.id else { return }
        await viewModel.fetchMyShifts(storeId: storeId)
    }

    private func formattedDayHeader(_ dateString: String) -> String {
        let inputFmt = DateFormatter()
        inputFmt.dateFormat = "yyyy-MM-dd"
        guard let date = inputFmt.date(from: dateString) else { return dateString }
        let outputFmt = DateFormatter()
        outputFmt.dateFormat = "EEEE, d MMM"
        return outputFmt.string(from: date)
    }
}

#Preview {
    ScheduleView()
        .environment(AuthViewModel())
        .environment(StoreViewModel())
}
