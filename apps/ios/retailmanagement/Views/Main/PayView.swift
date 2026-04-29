//
//  PayView.swift
//  retailmanagement
//

import SwiftUI

struct PayView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(StoreViewModel.self) var storeViewModel
    @State private var viewModel = PayViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if viewModel.isLoading {
                    ProgressView("Loading payslips...")
                } else if viewModel.payslips.isEmpty {
                    ContentUnavailableView(
                        "No Payslips",
                        systemImage: "dollarsign.circle",
                        description: Text("Your payslips will appear here once payroll is processed.")
                    )
                } else {
                    payslipList
                }
            }
            .navigationTitle("Pay")
            .task { await loadPayslips() }
            .refreshable { await loadPayslips() }
        }
    }

    // MARK: - Payslip List

    private var payslipList: some View {
        List(viewModel.payslips) { slip in
            NavigationLink {
                PaySlipDetailView(payslip: slip, payrollRun: viewModel.payrollRun(for: slip))
            } label: {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        if let run = viewModel.payrollRun(for: slip) {
                            Text(run.periodLabel)
                                .font(.headline)
                        }
                        Text("Gross: $\(String(format: "%.2f", slip.grossPay))")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 4) {
                        Text("$\(String(format: "%.2f", slip.netPay))")
                            .font(.title3.weight(.semibold))
                            .foregroundStyle(.green)
                        Text("Net")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 4)
            }
        }
        .insetGroupedListStyleCompat()
    }

    private func loadPayslips() async {
        guard let storeId = storeViewModel.selectedStore?.id,
              let userId = authViewModel.currentUser?.id else { return }
        await viewModel.fetchPayslips(storeId: storeId, userId: userId)
    }
}

// MARK: - PaySlip Detail View

struct PaySlipDetailView: View {
    let payslip: PaySlip
    let payrollRun: PayrollRunSummary?

    var body: some View {
        List {
            // Period header
            if let run = payrollRun {
                Section("Period") {
                    LabeledContent("Period", value: run.periodLabel)
                    LabeledContent("Status", value: run.status.capitalized)
                }
            }

            // Earnings
            Section("Earnings") {
                LabeledContent("Basic Salary", value: currency(payslip.basicSalary))
                if let hours = payslip.hoursWorked {
                    LabeledContent("Hours Worked", value: String(format: "%.1f", hours))
                }
                if payslip.overtimeHours > 0 {
                    LabeledContent("Overtime Hours", value: String(format: "%.1f", payslip.overtimeHours))
                    LabeledContent("Overtime Pay", value: currency(payslip.overtimePay))
                }
                if payslip.commissionAmount > 0 {
                    LabeledContent("Commission Sales", value: currency(payslip.commissionSales))
                    LabeledContent("Commission", value: currency(payslip.commissionAmount))
                }
                if payslip.allowances > 0 {
                    LabeledContent("Allowances", value: currency(payslip.allowances))
                }
            }

            // Deductions
            Section("Deductions") {
                LabeledContent("CPF (Employee)", value: currency(payslip.cpfEmployee))
                LabeledContent("CPF (Employer)", value: currency(payslip.cpfEmployer))
                if payslip.deductions > 0 {
                    LabeledContent("Other Deductions", value: currency(payslip.deductions))
                }
            }

            // Totals
            Section("Summary") {
                LabeledContent("Gross Pay", value: currency(payslip.grossPay))
                    .font(.headline)
                LabeledContent("Net Pay", value: currency(payslip.netPay))
                    .font(.headline)
                    .foregroundStyle(.green)
            }

            if let notes = payslip.notes, !notes.isEmpty {
                Section("Notes") {
                    Text(notes)
                        .font(.body)
                }
            }
        }
        .insetGroupedListStyleCompat()
        .navigationTitle("Payslip")
    }

    private func currency(_ value: Double) -> String {
        String(format: "$%.2f", value)
    }
}
