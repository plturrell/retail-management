import { describe, expect, it } from "vitest";

import {
  assessFormCSEligibility,
  calculateTaxExemption,
  computeCorporateIncomeTaxRebate,
  computeFormCSTax,
  computeFormCSTaxFromRecords,
  CORPORATE_INCOME_TAX_RATE
} from "./index";

describe("Form C-S eligibility", () => {
  it("returns Form C-S (Lite) when all qualifying conditions are met and revenue is at most S$200,000", () => {
    expect(
      assessFormCSEligibility({
        annualRevenue: 180_000,
        isIncorporatedInSingapore: true,
        hasOnlyIncomeTaxableAt17Percent: true
      })
    ).toMatchObject({
      formType: "form-c-s-lite",
      qualifiesForFormCS: true,
      qualifiesForFormCSLite: true,
      reasons: []
    });
  });

  it("returns Form C-S when revenue exceeds the Lite threshold but not the full threshold", () => {
    expect(
      assessFormCSEligibility({
        annualRevenue: 450_000,
        isIncorporatedInSingapore: true,
        hasOnlyIncomeTaxableAt17Percent: true
      }).formType
    ).toBe("form-c-s");
  });

  it("returns Form C when any disqualifying condition is present", () => {
    const result = assessFormCSEligibility({
      annualRevenue: 5_500_000,
      isIncorporatedInSingapore: false,
      hasOnlyIncomeTaxableAt17Percent: false,
      claimsGroupRelief: true
    });

    expect(result.formType).toBe("form-c-required");
    expect(result.reasons).toEqual([
      "Company is not incorporated in Singapore.",
      "Annual revenue exceeds S$5,000,000.",
      "Company derives income that is not taxable solely at the prevailing 17% rate.",
      "Company is claiming group relief."
    ]);
  });
});

describe("tax exemption schemes", () => {
  it("matches the IRAS YA 2020 onwards SUTE maximum exemption table", () => {
    expect(calculateTaxExemption(200_000, "sute")).toEqual({
      scheme: "sute",
      exemptAmount: 125_000,
      taxableIncome: 75_000
    });
  });

  it("matches the IRAS YA 2020 onwards PTE maximum exemption table", () => {
    expect(calculateTaxExemption(200_000, "pte")).toEqual({
      scheme: "pte",
      exemptAmount: 102_500,
      taxableIncome: 97_500
    });
  });
});

describe("corporate income tax rebate", () => {
  it("computes the YA 2024 rebate without the cash grant", () => {
    expect(
      computeCorporateIncomeTaxRebate({
        yaYear: 2024,
        taxPayableBeforeRebate: 30_000,
        eligibleForCashGrant: false
      })
    ).toMatchObject({
      rebateBeforeCashGrant: 15_000,
      cashGrantAmount: 0,
      rebateAmount: 15_000
    });
  });

  it("computes the YA 2025 rebate less the S$2,000 cash grant when eligible", () => {
    expect(
      computeCorporateIncomeTaxRebate({
        yaYear: 2025,
        taxPayableBeforeRebate: 30_000,
        eligibleForCashGrant: true
      })
    ).toMatchObject({
      rebateBeforeCashGrant: 15_000,
      cashGrantAmount: 2_000,
      rebateAmount: 13_000
    });

    expect(
      computeCorporateIncomeTaxRebate({
        yaYear: 2025,
        taxPayableBeforeRebate: 100_000,
        eligibleForCashGrant: true
      }).rebateAmount
    ).toBe(38_000);
  });
});

describe("tax computation pipeline", () => {
  it("computes chargeable income from accounting profit with adjustments, allowances, and brought-forward balances", () => {
    const result = computeFormCSTax({
      yaYear: 2024,
      revenue: 1_500_000,
      netProfitLoss: 100_000,
      taxAdjustments: [
        { description: "Entertainment", amount: 12_000, adjustmentType: "add_back", category: "non_deductible" },
        { description: "Exempt dividends", amount: 8_000, adjustmentType: "deduct", category: "non_taxable" },
        { description: "Capital gains", amount: 2_000, adjustmentType: "deduct", category: "other" }
      ],
      capitalAllowancesCurrentYear: 20_000,
      priorYearBalances: {
        losses: 10_000,
        capitalAllowances: 5_000,
        donations: 2_000
      }
    });

    expect(result.adjustedProfitLoss).toBe(102_000);
    expect(result.chargeableIncome).toBe(65_000);
    expect(result.formCsOutput).toMatchObject({
      totalAddBacks: 12_000,
      totalDeductions: 10_000,
      capitalAllowancesClaimed: 20_000,
      lossesBroughtForwardUsed: 10_000,
      capitalAllowancesBroughtForwardUsed: 5_000,
      donationsBroughtForwardUsed: 2_000,
      exemptionScheme: "pte",
      exemptAmount: 35_000,
      taxableIncomeAfterExemptions: 30_000,
      grossTaxPayable: 5_100,
      citRebateAmount: 2_550,
      taxPayable: 2_550
    });
  });

  it("returns zero tax for zero income", () => {
    const result = computeFormCSTax({
      yaYear: 2024,
      revenue: 0,
      netProfitLoss: 0
    });

    expect(result.chargeableIncome).toBe(0);
    expect(result.exemptAmount).toBe(0);
    expect(result.taxPayable).toBe(0);
  });

  it("preserves remaining losses when brought-forward losses exceed adjusted profit, matching the IRAS FAQ example values", () => {
    const result = computeFormCSTax({
      yaYear: 2024,
      revenue: 100_000,
      netProfitLoss: 100_000,
      priorYearBalances: {
        losses: 150_000
      },
      exemption: {
        qualifiesForSute: true,
        firstYaYear: 2022
      }
    });

    expect(result.lossesBroughtForwardUsed).toBe(100_000);
    expect(result.remainingBalances.losses).toBe(50_000);
    expect(result.chargeableIncome).toBe(0);
    expect(result.exemptAmount).toBe(0);
    expect(result.taxPayable).toBe(0);
  });

  it("carries forward the current-year loss into remaining balances for scenario 4", () => {
    const result = computeFormCSTax({
      yaYear: 2024,
      revenue: 50_000,
      netProfitLoss: -12_000,
      priorYearBalances: {
        losses: 8_000,
        capitalAllowances: 5_000
      }
    });

    expect(result.chargeableIncome).toBe(0);
    expect(result.lossesBroughtForwardUsed).toBe(0);
    expect(result.remainingBalances.losses).toBe(20_000);
    expect(result.remainingBalances.capitalAllowances).toBe(5_000);
    expect(result.taxPayable).toBe(0);
  });

  it("uses SUTE automatically within the first three YAs and computes tax at 17%", () => {
    const result = computeFormCSTax({
      yaYear: 2024,
      revenue: 200_000,
      netProfitLoss: 200_000,
      exemption: {
        qualifiesForSute: true,
        firstYaYear: 2022
      }
    });

    expect(result.exemptionScheme).toBe("sute");
    expect(result.exemptAmount).toBe(125_000);
    expect(result.taxableIncomeAfterExemptions).toBe(75_000);
    expect(result.grossTaxPayable).toBe(12_750);
    expect(result.grossTaxPayable).toBe(Math.round(75_000 * CORPORATE_INCOME_TAX_RATE * 100) / 100);
  });
});

describe("record-based helper", () => {
  it("maps DB-shaped records into the computation pipeline", () => {
    const result = computeFormCSTaxFromRecords({
      company: {
        companyId: "company_001",
        incorporationDate: "2022-01-01",
        isTaxResident: true,
        shareholderCount: 2
      },
      summary: {
        companyId: "company_001",
        yaYear: 2025,
        totalRevenue: 300_000,
        netProfitLoss: 80_000
      },
      adjustments: [{ description: "Private car", amount: 5_000, adjustmentType: "add_back", category: "non_deductible" }],
      citRebate: {
        eligibleForCashGrant: true
      }
    });

    expect(result.formCsOutput.revenue).toBe(300_000);
    expect(result.formCsOutput.totalAddBacks).toBe(5_000);
    expect(result.citRebateCashGrant).toBe(2_000);
  });
});