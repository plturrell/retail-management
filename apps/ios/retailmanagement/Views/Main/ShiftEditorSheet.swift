//
//  ShiftEditorSheet.swift
//  retailmanagement
//

import SwiftUI

enum ShiftEditorTarget: Identifiable {
    case new(String)
    case edit(Shift)

    var id: String {
        switch self {
        case .new(let date): return "new-\(date)"
        case .edit(let shift): return "edit-\(shift.id)"
        }
    }
}

struct ShiftEditorSheet: View {
    let target: ShiftEditorTarget
    @Bindable var viewModel: ManagerScheduleViewModel
    let storeId: String

    @Environment(\.dismiss) private var dismiss

    @State private var selectedUserId: String = ""
    @State private var date: String = ""
    @State private var startTime: String = "09:00"
    @State private var endTime: String = "17:00"
    @State private var breakMinutes: Int = 60
    @State private var notes: String = ""

    private var isEdit: Bool {
        if case .edit = target { return true }
        return false
    }

    var body: some View {
        NavigationStack {
            Form {
                if isEdit {
                    Section("Employee") {
                        Text(viewModel.employee(for: selectedUserId)?.fullName ?? selectedUserId)
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Section("Employee") {
                        Picker("Employee", selection: $selectedUserId) {
                            Text("Select…").tag("")
                            ForEach(viewModel.employees) { emp in
                                Text(emp.fullName).tag(emp.id)
                            }
                        }
                    }
                }

                Section("Date") {
                    Text(date).foregroundStyle(.secondary)
                }

                Section("Time") {
                    HStack {
                        Text("Start")
                        Spacer()
                        TextField("HH:MM", text: $startTime)
                            .multilineTextAlignment(.trailing)
                            .frame(maxWidth: 80)
                    }
                    HStack {
                        Text("End")
                        Spacer()
                        TextField("HH:MM", text: $endTime)
                            .multilineTextAlignment(.trailing)
                            .frame(maxWidth: 80)
                    }
                    Stepper("Break: \(breakMinutes) min", value: $breakMinutes, in: 0...240, step: 15)
                }

                Section("Notes") {
                    TextField("Optional", text: $notes, axis: .vertical)
                        .lineLimit(2...4)
                }
            }
            .navigationTitle(isEdit ? "Edit Shift" : "New Shift")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task {
                            await save()
                            dismiss()
                        }
                    }
                    .disabled(saveDisabled)
                }
            }
            .onAppear(perform: prefill)
        }
    }

    private var saveDisabled: Bool {
        viewModel.isActionLoading
            || (!isEdit && selectedUserId.isEmpty)
            || startTime.isEmpty
            || endTime.isEmpty
    }

    private func prefill() {
        switch target {
        case .new(let dateStr):
            date = dateStr
        case .edit(let shift):
            selectedUserId = shift.userId
            date = shift.shiftDate
            startTime = String(shift.startTime.prefix(5))
            endTime = String(shift.endTime.prefix(5))
            breakMinutes = shift.breakMinutes
            notes = shift.notes ?? ""
        }
    }

    private func save() async {
        let shiftId: String? = {
            if case .edit(let shift) = target { return shift.id }
            return nil
        }()
        await viewModel.saveShift(
            storeId: storeId,
            shiftId: shiftId,
            userId: selectedUserId,
            date: date,
            startTime: normalizeTime(startTime),
            endTime: normalizeTime(endTime),
            breakMinutes: breakMinutes,
            notes: notes.isEmpty ? nil : notes
        )
    }

    private func normalizeTime(_ t: String) -> String {
        // Backend expects HH:MM:SS; accept HH:MM and append :00
        t.contains(":") && t.count == 5 ? "\(t):00" : t
    }
}
