import { describe, expect, it } from "vitest";

import { buildAutoAdjustments, getBasisPeriod, mapUiCategoryToDb, suggestTransactionCategory } from "./tax-ui";

describe("tax-ui helpers", () => {
  it("maps UI categories to DB categories", () => {
    expect(mapUiCategoryToDb("cost_of_sales")).toEqual({ category: "expense", subcategory: "cost_of_sales" });
    expect(mapUiCategoryToDb("transfer")).toEqual({ category: "transfer", subcategory: null });
  });

  it("derives YA basis periods from stored FY dates", () => {
    expect(
      getBasisPeriod(
        { financialYearStart: "2024-04-01", financialYearEnd: "2025-03-31" },
        2025
      )
    ).toEqual({ start: "2023-04-01", end: "2024-03-31", label: "2023-04-01 → 2024-03-31" });
  });

  it("suggests categories from description patterns", () => {
    expect(suggestTransactionCategory("Stripe customer payment", null, 200)).toBe("revenue");
    expect(suggestTransactionCategory("Office rent expense", 1000, null)).toBe("operating_expense");
    expect(suggestTransactionCategory("SERVICE CHARGE", 15, null)).toBe("non_deductible");
    expect(suggestTransactionCategory("CASH WITHDRAWAL ATM xx-9618", 300, null)).toBe("transfer");
  });

  it("builds auto tax adjustments from transaction tags", () => {
    expect(
      buildAutoAdjustments([
        { category: "expense", subcategory: "non_deductible", debit: 200, credit: null, isTaxable: true, description: "Private expense" },
        { category: "expense", subcategory: "capital", debit: 3000, credit: null, isTaxable: true, description: "Laptop" },
        { category: "revenue", subcategory: null, debit: null, credit: 500, isTaxable: false, description: "Grant" }
      ])
    ).toEqual([
      { description: "Auto add-back: non-deductible expenses", amount: 200, adjustmentType: "add_back", category: "non_deductible" },
      { description: "Auto add-back: capital expenditure", amount: 3000, adjustmentType: "add_back", category: "other" },
      { description: "Auto deduction: non-taxable income", amount: 500, adjustmentType: "deduct", category: "non_taxable" }
    ]);
  });
});