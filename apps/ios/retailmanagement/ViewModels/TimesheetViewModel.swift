//
//  TimesheetViewModel.swift
//  retailmanagement
//

import Foundation
import Observation

@MainActor
@Observable
final class TimesheetViewModel {
    var activeEntry: TimeEntry?
    var history: [TimeEntry] = []
    var isLoading = false
    var isClockingIn = false
    var isClockingOut = false
    var errorMessage: String?

    /// Elapsed seconds since clock-in
    var elapsedSeconds: Int = 0
    private var timerTask: Task<Void, Never>?

    var isClockedIn: Bool { activeEntry != nil }

    var formattedElapsed: String {
        let hours = elapsedSeconds / 3600
        let minutes = (elapsedSeconds % 3600) / 60
        let seconds = elapsedSeconds % 60
        return String(format: "%02d:%02d:%02d", hours, minutes, seconds)
    }

    func checkStatus() async {
        do {
            let response: DataResponse<TimeEntry?> = try await NetworkService.shared.get(
                endpoint: "/api/timesheets/status"
            )
            activeEntry = response.data
            if activeEntry != nil {
                startTimer()
            }
        } catch {
            // Silently handle — status check is non-critical
        }
    }

    func clockIn(storeId: String, notes: String? = nil) async {
        isClockingIn = true
        errorMessage = nil

        do {
            let body = ClockInRequest(storeId: storeId, notes: notes)
            let response: DataResponse<TimeEntry> = try await NetworkService.shared.post(
                endpoint: "/api/timesheets/clock-in", body: body
            )
            activeEntry = response.data
            startTimer()
        } catch {
            errorMessage = error.localizedDescription
        }

        isClockingIn = false
    }

    func clockOut(breakMinutes: Int = 0, notes: String? = nil) async {
        isClockingOut = true
        errorMessage = nil

        do {
            let body = ClockOutRequest(breakMinutes: breakMinutes, notes: notes)
            let response: DataResponse<TimeEntry> = try await NetworkService.shared.post(
                endpoint: "/api/timesheets/clock-out", body: body
            )
            activeEntry = nil
            stopTimer()
            // Prepend to history
            history.insert(response.data, at: 0)
        } catch {
            errorMessage = error.localizedDescription
        }

        isClockingOut = false
    }

    func fetchHistory(storeId: String) async {
        isLoading = true
        errorMessage = nil

        do {
            let response: PaginatedResponse<TimeEntry> = try await NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/timesheets",
                queryItems: [
                    URLQueryItem(name: "page_size", value: "50"),
                ]
            )
            history = response.data
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    // MARK: - Timer

    private func startTimer() {
        stopTimer()
        guard let entry = activeEntry, let clockIn = entry.clockInDate else { return }
        elapsedSeconds = Int(Date().timeIntervalSince(clockIn))

        timerTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                guard let self, let clockIn = self.activeEntry?.clockInDate else { break }
                self.elapsedSeconds = Int(Date().timeIntervalSince(clockIn))
            }
        }
    }

    private func stopTimer() {
        timerTask?.cancel()
        timerTask = nil
        elapsedSeconds = 0
    }
}
