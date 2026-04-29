//
//  ManagerScheduleTabView.swift
//  retailmanagement
//

import SwiftUI

struct ManagerScheduleTabView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var viewModel = ManagerScheduleViewModel()
    @State private var editorTarget: ShiftEditorTarget?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                weekNavigationBar

                if viewModel.isLoading {
                    Spacer()
                    ProgressView("Loading schedule...")
                    Spacer()
                } else if viewModel.schedule == nil {
                    emptyState
                } else {
                    daysList
                }
            }
            .navigationTitle("Team Schedule")
            .toolbar { toolbarContent }
            .task { await load() }
            .refreshable { await load() }
            .onChange(of: viewModel.weekStart) { _, _ in Task { await load() } }
            .sheet(item: $editorTarget) { target in
                ShiftEditorSheet(target: target, viewModel: viewModel, storeId: storeId)
            }
        }
    }

    private var storeId: String { storeViewModel.selectedStore?.id ?? "" }

    private func load() async {
        guard let id = storeViewModel.selectedStore?.id else { return }
        await viewModel.loadData(storeId: id)
    }

    // MARK: - Toolbar

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        if let sched = viewModel.schedule {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await viewModel.togglePublishStatus(storeId: storeId) }
                } label: {
                    Text(sched.status == "published" ? "Revert to Draft" : "Publish")
                }
                .disabled(viewModel.isActionLoading)
            }
        }
    }

    // MARK: - Week Navigation

    private var weekNavigationBar: some View {
        HStack {
            Button { viewModel.goToPreviousWeek() } label: {
                Image(systemName: "chevron.left").fontWeight(.semibold)
            }
            Spacer()
            VStack(spacing: 2) {
                Text(viewModel.weekLabel).font(.headline)
                Button("Current Week") { viewModel.goToCurrentWeek() }
                    .font(.caption).foregroundStyle(.blue)
            }
            Spacer()
            Button { viewModel.goToNextWeek() } label: {
                Image(systemName: "chevron.right").fontWeight(.semibold)
            }
        }
        .padding()
        .background(Color.secondarySystemBackground)
    }

    // MARK: - Empty / Days

    private var emptyState: some View {
        VStack(spacing: 16) {
            Spacer()
            ContentUnavailableView(
                "No Schedule",
                systemImage: "calendar.badge.plus",
                description: Text("Initialize a schedule to start assigning shifts for this week.")
            )
            Button {
                Task { await viewModel.initializeSchedule(storeId: storeId) }
            } label: {
                Label("Initialize Schedule", systemImage: "plus.circle.fill")
                    .padding(.horizontal)
            }
            .buttonStyle(.borderedProminent)
            .disabled(viewModel.isActionLoading)
            Spacer()
        }
    }

    private var daysList: some View {
        List {
            ForEach(viewModel.dayDates, id: \.self) { day in
                daySection(for: day)
            }
        }
        .insetGroupedListStyleCompat()
    }

    @ViewBuilder
    private func daySection(for day: Date) -> some View {
        let dateStr = viewModel.dateString(day)
        let dayShifts = viewModel.shifts(for: day)
        Section {
            ForEach(dayShifts) { shift in
                shiftRow(shift)
                    .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                        Button(role: .destructive) {
                            Task { await viewModel.deleteShift(storeId: storeId, shiftId: shift.id) }
                        } label: { Label("Delete", systemImage: "trash") }
                        Button {
                            editorTarget = .edit(shift)
                        } label: { Label("Edit", systemImage: "pencil") }
                        .tint(.blue)
                    }
            }
            Button {
                editorTarget = .new(dateStr)
            } label: {
                Label("Add Shift", systemImage: "plus.circle")
                    .font(.subheadline)
            }
        } header: {
            Text(formattedDayHeader(day)).font(.subheadline.weight(.semibold))
        }
    }

    private func shiftRow(_ shift: Shift) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(viewModel.employee(for: shift.userId)?.fullName ?? shift.userId)
                .font(.headline)
            HStack(spacing: 12) {
                Text(shift.timeRange).font(.subheadline)
                Text("\(String(format: "%.1f", shift.hours)) hrs")
                    .font(.caption).foregroundStyle(.secondary)
                if shift.breakMinutes > 0 {
                    Text("\(shift.breakMinutes)m break")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 2)
    }

    private func formattedDayHeader(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "EEEE, d MMM"
        return f.string(from: date)
    }
}
