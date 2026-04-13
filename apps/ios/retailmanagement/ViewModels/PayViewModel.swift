//
//  PayViewModel.swift
//  retailmanagement
//

import Foundation
import Observation

@MainActor
@Observable
final class PayViewModel {
    var payslips: [PaySlip] = []
    var payrollRuns: [PayrollRunSummary] = []
    var selectedPayslip: PaySlip?
    var employeeProfile: EmployeeProfile?
    var isLoading = false
    var errorMessage: String?

    /// Fetch payroll runs for the store, then extract the current user's payslips
    func fetchPayslips(storeId: String, userId: String) async {
        isLoading = true
        errorMessage = nil

        do {
            // Fetch payroll runs
            let runsResponse: DataResponse<[PayrollRunSummary]> = try await NetworkService.shared.get(
                endpoint: "/api/stores/\(storeId)/payroll"
            )
            payrollRuns = runsResponse.data

            // For each approved/calculated run, fetch the detail to get payslips
            var allPayslips: [PaySlip] = []
            for run in payrollRuns where run.status == "approved" || run.status == "calculated" {
                let runDetail: DataResponse<PayrollRunRead> = try await NetworkService.shared.get(
                    endpoint: "/api/stores/\(storeId)/payroll/\(run.id)"
                )
                let mySlips = runDetail.data.payslips.filter { $0.userId == userId }
                allPayslips.append(contentsOf: mySlips)
            }
            payslips = allPayslips.sorted { ($0.createdAt ?? "") > ($1.createdAt ?? "") }
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    /// Fetch the employee profile
    func fetchProfile(userId: String) async {
        do {
            let response: DataResponse<EmployeeProfile> = try await NetworkService.shared.get(
                endpoint: "/api/employees/\(userId)/profile"
            )
            employeeProfile = response.data
        } catch {
            // Profile may not exist for all users
        }
    }

    /// Find the payroll run that owns a given payslip
    func payrollRun(for payslip: PaySlip) -> PayrollRunSummary? {
        payrollRuns.first { $0.id == payslip.payrollRunId }
    }
}
