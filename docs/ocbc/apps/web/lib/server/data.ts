import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import type { BankStatement, Company, FinancialSummary, TaxAdjustment, Transaction } from "@tax-build/db/schema";
import { bankStatements, companies, financialSummaries, taxAdjustments, transactions } from "@tax-build/db/schema";
import type { ImportStatementSummary } from "@tax-build/parser";
import { assessFormCSEligibility, computeFormCSTax, type EligibilityResult, type TaxAdjustmentEntry, type TaxComputationResult } from "@tax-build/tax-engine";
import { unstable_noStore as noStore } from "next/cache";

import {
  buildAutoAdjustments,
  type BasisPeriod,
  getBasisPeriod,
  getTransactionAmount,
  mapUiCategoryToDb,
  normalizeYaYear,
  suggestTransactionCategory,
  type UiTransactionCategory,
  YA_OPTIONS,
  toUiTransactionCategory
} from "../tax-ui";

import { getWebDatabase } from "./db";

const DEFAULT_YA = 2025;

export interface CompanyContext {
  companies: Company[];
  selectedCompany: Company | null;
}

export interface StatementOverview extends BankStatement {
  transactionCount: number;
  dateRange: string;
}

export interface TransactionRow extends Transaction {
  uiCategory: UiTransactionCategory;
  suggestedCategory: UiTransactionCategory;
  amount: number;
  direction: "credit" | "debit";
}

/** IRAS Form C-S expense breakdown (fields 26–32) */
export interface ExpenseBreakdown {
  /** Field 26 – Directors' Fees and Remuneration */
  directorsFees: number;
  /** Field 27 – Total Remuneration excluding Directors' Fees */
  totalRemuneration: number;
  /** Field 28 – Medical Expenses */
  medicalExpenses: number;
  /** Field 29 – Transport / Travelling Expenses */
  transportExpenses: number;
  /** Field 30 – Entertainment Expenses */
  entertainmentExpenses: number;
  /** Field 31 – Inventories / COGS */
  inventories: number;
  /** Cost of Sales (inventory + stock purchases) for Gross Profit calc */
  costOfSales: number;
  /** Contractor payments */
  contractorPayments: number;
  /** Bank charges */
  bankCharges: number;
  /** IT / Software */
  itSoftware: number;
  /** Utilities */
  utilities: number;
  /** Office supplies */
  officeSupplies: number;
  /** Non-deductible expenses */
  nonDeductible: number;
}

export interface ComputationSnapshot {
  company: Company;
  yaYear: number;
  basisPeriod: BasisPeriod;
  summary: FinancialSummary;
  transactions: TransactionRow[];
  autoAdjustments: TaxAdjustmentEntry[];
  manualAdjustments: TaxAdjustment[];
  result: TaxComputationResult;
  expenseBreakdown: ExpenseBreakdown;
  eligibility: EligibilityResult;
}

function roundToCents(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function sumBySubcategory(transactions: TransactionRow[], ...subcategories: string[]): number {
  return roundToCents(
    transactions
      .filter((t) => t.category === "expense" && subcategories.includes(t.subcategory ?? ""))
      .reduce((sum, t) => sum + Math.abs(t.debit ?? 0), 0)
  );
}

function buildExpenseBreakdown(transactions: TransactionRow[]): ExpenseBreakdown {
  return {
    directorsFees: 0, // Would need director flag on transactions — not yet available
    totalRemuneration: sumBySubcategory(transactions, "salary_wages"),
    medicalExpenses: sumBySubcategory(transactions, "medical_benefits"),
    transportExpenses: sumBySubcategory(transactions, "transport_travel"),
    entertainmentExpenses: sumBySubcategory(transactions, "meals_entertainment"),
    inventories: sumBySubcategory(transactions, "inventory_cogs"),
    costOfSales: sumBySubcategory(transactions, "inventory_cogs", "cost_of_sales"),
    contractorPayments: sumBySubcategory(transactions, "contractor_payments"),
    bankCharges: sumBySubcategory(transactions, "bank_charges"),
    itSoftware: sumBySubcategory(transactions, "it_software"),
    utilities: sumBySubcategory(transactions, "utilities"),
    officeSupplies: sumBySubcategory(transactions, "office_supplies"),
    nonDeductible: sumBySubcategory(transactions, "non_deductible")
  };
}

function byName(a: Company, b: Company) {
  return a.name.localeCompare(b.name);
}

function getAllCompanies(): Company[] {
  return [...(getWebDatabase().db.select().from(companies).all() as Company[])].sort(byName);
}

function getCompanyRecord(companyId?: string | null): Company | null {
  const records = getAllCompanies();
  return records.find((company) => company.companyId === companyId) ?? records[0] ?? null;
}

function toTransactionRow(transaction: Transaction): TransactionRow {
  return {
    ...transaction,
    uiCategory: toUiTransactionCategory(transaction),
    suggestedCategory: suggestTransactionCategory(transaction.description, transaction.debit, transaction.credit),
    amount: getTransactionAmount(transaction),
    direction: transaction.credit ? "credit" : "debit"
  };
}

function getTransactionsForPeriod(companyId: string, basisPeriod: BasisPeriod): TransactionRow[] {
  const rows = getWebDatabase().db.select().from(transactions).all() as Transaction[];

  return rows
    .filter((transaction) => {
      return transaction.companyId === companyId && transaction.date >= basisPeriod.start && transaction.date <= basisPeriod.end;
    })
    .sort((a, b) => (a.date === b.date ? a.description.localeCompare(b.description) : b.date.localeCompare(a.date)))
    .map(toTransactionRow);
}

function buildEligibility(company: Company, annualRevenue: number): EligibilityResult {
  return assessFormCSEligibility({
    annualRevenue,
    isIncorporatedInSingapore: true,
    hasOnlyIncomeTaxableAt17Percent: true
  });
}

function upsertSummary(summary: FinancialSummary) {
  getWebDatabase().db.insert(financialSummaries)
    .values(summary)
    .onConflictDoUpdate({
      target: financialSummaries.summaryId,
      set: {
        totalRevenue: summary.totalRevenue,
        totalExpenses: summary.totalExpenses,
        netProfitLoss: summary.netProfitLoss,
        adjustedProfitLoss: summary.adjustedProfitLoss,
        chargeableIncome: summary.chargeableIncome,
        taxPayable: summary.taxPayable,
        exemptAmount: summary.exemptAmount,
        rebateAmount: summary.rebateAmount,
        updatedAt: summary.updatedAt
      }
    })
    .run();
}

function getAdjustments(summaryId: string) {
  return (getWebDatabase().db.select().from(taxAdjustments).all() as TaxAdjustment[])
    .filter((adjustment) => adjustment.summaryId === summaryId)
    .sort((a, b) => a.description.localeCompare(b.description));
}

function makeSummaryId(companyId: string, yaYear: number) {
  return `summary_${companyId}_${yaYear}`;
}

export function getCompanyContext(companyId?: string | null): CompanyContext {
  noStore();
  const companies = getAllCompanies();
  return {
    companies,
    selectedCompany: companies.find((company) => company.companyId === companyId) ?? companies[0] ?? null
  };
}

export function getStatementsOverview(companyId: string): StatementOverview[] {
  noStore();
  const statementRows = (getWebDatabase().db.select().from(bankStatements).all() as BankStatement[])
    .filter((statement) => statement.companyId === companyId)
    .sort((a, b) => b.importedAt.localeCompare(a.importedAt));
  const txRows = (getWebDatabase().db.select().from(transactions).all() as Transaction[]).filter(
    (transaction) => transaction.companyId === companyId
  );

  return statementRows.map((statement) => {
    const statementTransactions = txRows.filter((transaction) => transaction.statementId === statement.statementId);
    const dates = statementTransactions.map((transaction) => transaction.date).sort();
    return {
      ...statement,
      transactionCount: statementTransactions.length,
      dateRange: dates.length > 0 ? `${dates[0]} → ${dates[dates.length - 1]}` : statement.statementDate
    };
  });
}

export function getFilteredTransactions(input: {
  companyId: string;
  yaYear?: number;
  search?: string | null;
  category?: string | null;
  taxability?: string | null;
}) {
  noStore();
  const company = getCompanyRecord(input.companyId);

  if (!company) {
    return { basisPeriod: null, transactions: [] as TransactionRow[] };
  }

  const basisPeriod = getBasisPeriod(company, normalizeYaYear(input.yaYear ?? DEFAULT_YA));
  const search = input.search?.trim().toLowerCase();
  const category = input.category?.trim();
  const taxability = input.taxability?.trim();

  return {
    basisPeriod,
    transactions: getTransactionsForPeriod(company.companyId, basisPeriod).filter((transaction) => {
      if (search && !`${transaction.description} ${transaction.reference ?? ""}`.toLowerCase().includes(search)) {
        return false;
      }

      if (category && category !== "all" && transaction.uiCategory !== category) {
        return false;
      }

      if (taxability === "taxable" && !transaction.isTaxable) {
        return false;
      }

      if (taxability === "non-taxable" && transaction.isTaxable) {
        return false;
      }

      return true;
    })
  };
}

export function getComputationSnapshot(companyId: string, yaYear?: number): ComputationSnapshot | null {
  const company = getCompanyRecord(companyId);

  if (!company) {
    return null;
  }

  const normalizedYa = normalizeYaYear(yaYear ?? DEFAULT_YA);
  const basisPeriod = getBasisPeriod(company, normalizedYa);
  const periodTransactions = getTransactionsForPeriod(company.companyId, basisPeriod);

  const revenue = roundToCents(
    periodTransactions.filter((transaction) => transaction.uiCategory === "revenue").reduce((sum, transaction) => sum + Math.abs(transaction.credit ?? 0), 0)
  );
  const expenses = roundToCents(
    periodTransactions.filter((transaction) => ["cost_of_sales", "operating_expense", "non_deductible", "capital"].includes(transaction.uiCategory))
      .reduce((sum, transaction) => sum + Math.abs(transaction.debit ?? 0), 0)
  );
  const netProfitLoss = roundToCents(revenue - expenses);

  // Build IRAS Form C-S expense breakdown by fine-grained subcategory
  const expenseBreakdown = buildExpenseBreakdown(periodTransactions);
  const now = new Date().toISOString();
  const summaryId = makeSummaryId(company.companyId, normalizedYa);
  const existing = (getWebDatabase().db.select().from(financialSummaries).all() as FinancialSummary[]).find(
    (summary) => summary.summaryId === summaryId
  );
  const baseSummary: FinancialSummary = {
    summaryId,
    companyId: company.companyId,
    yaYear: normalizedYa,
    totalRevenue: revenue,
    totalExpenses: expenses,
    netProfitLoss,
    adjustedProfitLoss: existing?.adjustedProfitLoss ?? netProfitLoss,
    chargeableIncome: existing?.chargeableIncome ?? 0,
    taxPayable: existing?.taxPayable ?? 0,
    exemptAmount: existing?.exemptAmount ?? 0,
    rebateAmount: existing?.rebateAmount ?? 0,
    status: existing?.status ?? "draft",
    createdAt: existing?.createdAt ?? now,
    updatedAt: now
  };

  upsertSummary(baseSummary);

  const manualAdjustments = getAdjustments(summaryId);
  const autoAdjustments = buildAutoAdjustments(periodTransactions);
  const result = computeFormCSTax({
    yaYear: normalizedYa,
    revenue,
    netProfitLoss,
    taxAdjustments: [
      ...autoAdjustments,
      ...manualAdjustments.map((adjustment) => ({
        description: adjustment.description,
        amount: adjustment.amount,
        adjustmentType: adjustment.adjustmentType,
        category: adjustment.category
      }))
    ],
    exemption: {
      qualifiesForSute: company.isTaxResident && company.shareholderCount <= 20,
      firstYaYear: Number(company.incorporationDate.slice(0, 4)) + 1
    }
  });

  const updatedSummary: FinancialSummary = {
    ...baseSummary,
    adjustedProfitLoss: result.adjustedProfitLoss,
    chargeableIncome: result.chargeableIncome,
    taxPayable: result.taxPayable,
    exemptAmount: result.exemptAmount,
    rebateAmount: result.citRebateAmount,
    updatedAt: new Date().toISOString()
  };

  upsertSummary(updatedSummary);

  return {
    company,
    yaYear: normalizedYa,
    basisPeriod,
    summary: updatedSummary,
    transactions: periodTransactions,
    autoAdjustments,
    manualAdjustments,
    result,
    expenseBreakdown,
    eligibility: buildEligibility(company, revenue)
  };
}

export function getDashboardData(companyId?: string | null, yaYear?: number) {
  noStore();
  const context = getCompanyContext(companyId);

  if (!context.selectedCompany) {
    return { ...context, yaYear: normalizeYaYear(yaYear), snapshot: null };
  }

  return {
    ...context,
    yaYear: normalizeYaYear(yaYear),
    snapshot: getComputationSnapshot(context.selectedCompany.companyId, yaYear)
  };
}

export async function saveCompanyRecord(input: {
  companyId?: string | null;
  uen: string;
  name: string;
  incorporationDate: string;
  financialYearStart: string;
  financialYearEnd: string;
  shareholderCount: number;
  isTaxResident: boolean;
}) {
  const records = getAllCompanies();
  const existing = records.find((company) => company.companyId === input.companyId) ?? records.find((company) => company.uen === input.uen);
  const now = new Date().toISOString();
  const companyId = existing?.companyId ?? input.companyId ?? `company_${crypto.randomUUID()}`;

  getWebDatabase().db.insert(companies)
    .values({
      companyId,
      uen: input.uen,
      name: input.name,
      incorporationDate: input.incorporationDate,
      financialYearStart: input.financialYearStart,
      financialYearEnd: input.financialYearEnd,
      shareholderCount: input.shareholderCount,
      isTaxResident: input.isTaxResident,
      functionalCurrency: "SGD",
      createdAt: existing?.createdAt ?? now,
      updatedAt: now
    })
    .onConflictDoUpdate({
      target: companies.companyId,
      set: {
        uen: input.uen,
        name: input.name,
        incorporationDate: input.incorporationDate,
        financialYearStart: input.financialYearStart,
        financialYearEnd: input.financialYearEnd,
        shareholderCount: input.shareholderCount,
        isTaxResident: input.isTaxResident,
        functionalCurrency: "SGD",
        updatedAt: now
      }
    })
    .run();

  return companyId;
}

export async function importStatementUpload(input: {
  companyId: string;
  file: File;
  bankName?: string | null;
}): Promise<ImportStatementSummary> {
  const { importStatement } = await import("@tax-build/parser");
  const tempPath = path.join(os.tmpdir(), `${crypto.randomUUID()}-${input.file.name}`);

  try {
    const bytes = Buffer.from(await input.file.arrayBuffer());
    await fs.writeFile(tempPath, bytes);

    const summary = await importStatement(
      getWebDatabase().db,
      input.companyId,
      tempPath,
      input.bankName && input.bankName !== "Auto" ? input.bankName : undefined
    );

    return summary;
  } finally {
    await fs.rm(tempPath, { force: true });
  }
}

export async function bulkUpdateTransactions(input: {
  transactionIds: string[];
  uiCategory: UiTransactionCategory;
  taxability: "keep" | "taxable" | "non-taxable";
}) {
  if (input.transactionIds.length === 0) {
    return 0;
  }

  const mapped = mapUiCategoryToDb(input.uiCategory);
  const withTaxability = getWebDatabase().sqlite.prepare(
    "UPDATE transactions SET category = ?, subcategory = ?, is_taxable = ? WHERE transaction_id = ?"
  );
  const withoutTaxability = getWebDatabase().sqlite.prepare(
    "UPDATE transactions SET category = ?, subcategory = ? WHERE transaction_id = ?"
  );

  for (const transactionId of input.transactionIds) {
    if (input.taxability === "keep") {
      withoutTaxability.run(mapped.category, mapped.subcategory, transactionId);
      continue;
    }

    withTaxability.run(mapped.category, mapped.subcategory, input.taxability === "taxable" ? 1 : 0, transactionId);
  }

  return input.transactionIds.length;
}

export async function addManualAdjustment(input: {
  companyId: string;
  yaYear: number;
  description: string;
  amount: number;
  adjustmentType: TaxAdjustment["adjustmentType"];
  category: TaxAdjustment["category"];
}) {
  const snapshot = getComputationSnapshot(input.companyId, input.yaYear);

  if (!snapshot) {
    throw new Error("Company not found.");
  }

  getWebDatabase().db.insert(taxAdjustments)
    .values({
      adjustmentId: `adj_${crypto.randomUUID()}`,
      summaryId: snapshot.summary.summaryId,
      description: input.description,
      amount: Math.abs(input.amount),
      adjustmentType: input.adjustmentType,
      category: input.category
    })
    .run();
}

export async function deleteManualAdjustment(adjustmentId: string) {
  getWebDatabase().sqlite.prepare("DELETE FROM tax_adjustments WHERE adjustment_id = ?").run(adjustmentId);
}

export async function setSummaryStatus(input: { companyId: string; yaYear: number; status: FinancialSummary["status"] }) {
  const snapshot = getComputationSnapshot(input.companyId, input.yaYear);

  if (!snapshot) {
    throw new Error("Company not found.");
  }

  getWebDatabase().sqlite.prepare(
    "UPDATE financial_summaries SET status = ?, updated_at = ? WHERE summary_id = ?"
  ).run(input.status, new Date().toISOString(), snapshot.summary.summaryId);
}

export function getFilingExportData(companyId: string, yaYear?: number) {
  noStore();
  const snapshot = getComputationSnapshot(companyId, yaYear);

  if (!snapshot) {
    return null;
  }

  return {
    generatedAt: new Date().toISOString(),
    company: {
      companyId: snapshot.company.companyId,
      name: snapshot.company.name,
      uen: snapshot.company.uen,
      incorporationDate: snapshot.company.incorporationDate,
      financialYearStart: snapshot.company.financialYearStart,
      financialYearEnd: snapshot.company.financialYearEnd,
      shareholderCount: snapshot.company.shareholderCount,
      isTaxResident: snapshot.company.isTaxResident
    },
    yaYear: snapshot.yaYear,
    basisPeriod: snapshot.basisPeriod,
    filingStatus: snapshot.summary.status,
    formType: snapshot.eligibility.formType,
    formCsOutput: snapshot.result.formCsOutput,
    summary: {
      revenue: snapshot.summary.totalRevenue,
      expenses: snapshot.summary.totalExpenses,
      netProfitLoss: snapshot.summary.netProfitLoss,
      chargeableIncome: snapshot.summary.chargeableIncome,
      taxPayable: snapshot.summary.taxPayable
    },
    adjustments: {
      auto: snapshot.autoAdjustments,
      manual: snapshot.manualAdjustments
    }
  };
}

export { DEFAULT_YA, YA_OPTIONS };