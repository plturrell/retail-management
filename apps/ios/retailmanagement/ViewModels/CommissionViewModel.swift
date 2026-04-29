//
//  CommissionViewModel.swift
//  retailmanagement
//
//  Aggregates payroll payslips into a 6-month commission timeline for the
//  current user, and resolves the active commission tier rules. Mirrors the
//  staff-portal CommissionPage data flow without re-implementing PayViewModel
//  loading paths — it makes its own narrow calls so the Pay tab and the new
//  Commission tab can refresh independently.
//

import Foundation
import Observation

nonisolated struct CommissionMonth: Identifiable, Hashable, Sendable {
    let id: String              // "yyyy-MM"
    let label: String           // "Apr"
    let sales: Double
    let commission: Double
}

@MainActor
@Observable
final class CommissionViewModel {
    var months: [CommissionMonth] = []
    var rules: [CommissionRule] = []
    var profile: EmployeeProfile?
    var totalSales: Double = 0
    var totalCommission: Double = 0
    var isLoading = false
    var errorMessage: String?

    func load(storeId: String, userId: String) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            async let runsCall: DataResponse<[PayrollRunSummary]> = NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/payroll"
            )
            async let rulesCall: DataResponse<[CommissionRule]> = NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/commission-rules?active_only=true"
            )
            let (runs, rulesResp) = try await (runsCall, rulesCall)
            rules = rulesResp.data

            // Profile is best-effort: a brand-new staff record may not have one yet.
            do {
                let profileResp: DataResponse<EmployeeProfile> = try await NetworkService.shared.get(
                    endpoint: "/api/employees/\(userId)/profile"
                )
                profile = profileResp.data
            } catch {
                profile = nil
            }

            // Pull payslips for *my* user out of every approved/calculated run.
            var slips: [(slip: PaySlip, monthKey: String, label: String)] = []
            for run in runs.data where run.status == "approved" || run.status == "calculated" {
                let detail: DataResponse<PayrollRunRead> = try await NetworkService.shared.get(
                    endpoint: "/api/stores/\(storeId)/payroll/\(run.id)"
                )
                let mine = detail.data.payslips.filter { $0.userId == userId }
                guard !mine.isEmpty else { continue }
                let key = monthKey(from: run.periodStart)
                let label = monthLabel(from: run.periodStart)
                for s in mine { slips.append((s, key, label)) }
            }

            // Aggregate by month, keep latest 6.
            var bucket: [String: (label: String, sales: Double, commission: Double)] = [:]
            for entry in slips {
                let prev = bucket[entry.monthKey] ?? (entry.label, 0, 0)
                bucket[entry.monthKey] = (
                    entry.label,
                    prev.sales + entry.slip.commissionSales,
                    prev.commission + entry.slip.commissionAmount
                )
            }
            let sortedKeys = bucket.keys.sorted()
            let last6 = Array(sortedKeys.suffix(6))
            months = last6.map { key in
                let v = bucket[key]!
                return CommissionMonth(id: key, label: v.label, sales: v.sales, commission: v.commission)
            }
            totalSales = months.reduce(0) { $0 + $1.sales }
            totalCommission = months.reduce(0) { $0 + $1.commission }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func monthKey(from periodStart: String) -> String {
        // periodStart is "yyyy-MM-dd"; key is "yyyy-MM" so sort is calendar-correct.
        String(periodStart.prefix(7))
    }

    private func monthLabel(from periodStart: String) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        if let date = formatter.date(from: periodStart) {
            let out = DateFormatter()
            out.dateFormat = "LLL"
            return out.string(from: date)
        }
        return String(periodStart.prefix(7))
    }
}
