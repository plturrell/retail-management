import { suggestTransactionCategorisation } from "@tax-build/db";
import type { Company, Transaction } from "@tax-build/db/schema";
import type { TaxAdjustmentEntry } from "@tax-build/tax-engine";

export const YA_OPTIONS = [2024, 2025, 2026] as const;

export type YaOption = (typeof YA_OPTIONS)[number];

export type UiTransactionCategory =
  | "revenue"
  | "cost_of_sales"
  | "operating_expense"
  | "non_deductible"
  | "capital"
  | "transfer"
  | "other";

export const UI_TRANSACTION_CATEGORIES: Array<{ value: UiTransactionCategory; label: string }> = [
  { value: "revenue", label: "Revenue" },
  { value: "cost_of_sales", label: "Cost of Sales" },
  { value: "operating_expense", label: "Operating Expense" },
  { value: "non_deductible", label: "Non-deductible" },
  { value: "capital", label: "Capital" },
  { value: "transfer", label: "Transfer" },
  { value: "other", label: "Other" }
];

export interface BasisPeriod {
  start: string;
  end: string;
  label: string;
}

export interface TransactionLike extends Pick<Transaction, "category" | "subcategory" | "debit" | "credit" | "isTaxable"> {
  description: string;
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-SG", {
    style: "currency",
    currency: "SGD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(Number.isFinite(value) ? value : 0);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-SG", { maximumFractionDigits: 0 }).format(value);
}

export function normalizeYaYear(value?: string | number | null): YaOption {
  const parsed = Number(value);
  return YA_OPTIONS.includes(parsed as YaOption) ? (parsed as YaOption) : 2025;
}

export function mapUiCategoryToDb(value: UiTransactionCategory): { category: Transaction["category"]; subcategory: string | null } {
  switch (value) {
    case "revenue":
      return { category: "revenue", subcategory: null };
    case "cost_of_sales":
      return { category: "expense", subcategory: "cost_of_sales" };
    case "operating_expense":
      return { category: "expense", subcategory: "operating_expense" };
    case "non_deductible":
      return { category: "expense", subcategory: "non_deductible" };
    case "capital":
      return { category: "expense", subcategory: "capital" };
    case "transfer":
      return { category: "transfer", subcategory: null };
    default:
      return { category: "other", subcategory: null };
  }
}

/** Subcategories that map to cost_of_sales in the UI */
const COST_OF_SALES_SUBCATEGORIES = new Set([
  "cost_of_sales",
  "inventory_cogs",
  "cash_withdrawal"
]);

export function toUiTransactionCategory(transaction: Pick<Transaction, "category" | "subcategory">): UiTransactionCategory {
  if (transaction.category === "revenue") {
    return "revenue";
  }

  if (transaction.category === "transfer") {
    return "transfer";
  }

  if (transaction.category === "expense") {
    if (COST_OF_SALES_SUBCATEGORIES.has(transaction.subcategory ?? "")) {
      return "cost_of_sales";
    }
    if (transaction.subcategory === "non_deductible") {
      return "non_deductible";
    }
    if (transaction.subcategory === "capital") {
      return "capital";
    }
    return "operating_expense";
  }

  return "other";
}

export function getCategoryLabel(value: UiTransactionCategory): string {
  return UI_TRANSACTION_CATEGORIES.find((category) => category.value === value)?.label ?? "Other";
}

export function getBasisPeriod(company: Pick<Company, "financialYearStart" | "financialYearEnd">, yaYear: number): BasisPeriod {
  const startParts = company.financialYearStart.split("-");
  const endParts = company.financialYearEnd.split("-");
  const wrapsYear = `${startParts[1]}-${startParts[2]}` > `${endParts[1]}-${endParts[2]}`;
  const endYear = yaYear - 1;
  const startYear = wrapsYear ? endYear - 1 : endYear;
  const start = `${startYear}-${startParts[1]}-${startParts[2]}`;
  const end = `${endYear}-${endParts[1]}-${endParts[2]}`;

  return {
    start,
    end,
    label: `${start} → ${end}`
  };
}

export function getTransactionAmount(transaction: Pick<Transaction, "credit" | "debit">): number {
  return Math.abs(transaction.credit ?? transaction.debit ?? 0);
}

export function suggestTransactionCategory(description: string, debit?: number | null, credit?: number | null): UiTransactionCategory {
  return toUiTransactionCategory(
    suggestTransactionCategorisation({ description, debit: debit ?? null, credit: credit ?? null, isTaxable: true })
  );
}

export function buildAutoAdjustments(transactions: TransactionLike[]): TaxAdjustmentEntry[] {
  let nonDeductible = 0;
  let capital = 0;
  let nonTaxableIncome = 0;

  for (const transaction of transactions) {
    const amount = getTransactionAmount(transaction);
    const category = toUiTransactionCategory(transaction);

    if (category === "non_deductible") {
      nonDeductible += amount;
    }

    if (category === "capital") {
      capital += amount;
    }

    if (category === "revenue" && transaction.isTaxable === false) {
      nonTaxableIncome += amount;
    }
  }

  const adjustments: TaxAdjustmentEntry[] = [];

  if (nonDeductible > 0) {
    adjustments.push({
      description: "Auto add-back: non-deductible expenses",
      amount: nonDeductible,
      adjustmentType: "add_back",
      category: "non_deductible"
    });
  }

  if (capital > 0) {
    adjustments.push({
      description: "Auto add-back: capital expenditure",
      amount: capital,
      adjustmentType: "add_back",
      category: "other"
    });
  }

  if (nonTaxableIncome > 0) {
    adjustments.push({
      description: "Auto deduction: non-taxable income",
      amount: nonTaxableIncome,
      adjustmentType: "deduct",
      category: "non_taxable"
    });
  }

  return adjustments;
}