import type { Company, FinancialSummary, TaxAdjustment } from "@tax-build/db";

export const CORPORATE_INCOME_TAX_RATE = 0.17;
export const SUPPORTED_YA_YEARS = [2024, 2025, 2026] as const;

export type SupportedYaYear = (typeof SUPPORTED_YA_YEARS)[number];
export type FormType = "form-c-s-lite" | "form-c-s" | "form-c-required";
export type ExemptionScheme = "sute" | "pte";

export interface EligibilityInput {
  annualRevenue: number;
  isIncorporatedInSingapore: boolean;
  hasOnlyIncomeTaxableAt17Percent: boolean;
  claimsCarryBackRelief?: boolean;
  claimsGroupRelief?: boolean;
  claimsInvestmentAllowance?: boolean;
  claimsForeignTaxCredit?: boolean;
  hasTaxDeductedAtSource?: boolean;
}

export interface EligibilityResult {
  formType: FormType;
  qualifiesForFormCS: boolean;
  qualifiesForFormCSLite: boolean;
  reasons: string[];
}

export interface TaxAdjustmentEntry {
  description: string;
  amount: number;
  adjustmentType: "add_back" | "deduct";
  category?: "non_deductible" | "non_taxable" | "capital_allowance" | "donation" | "loss_brought_forward" | "other";
}

export interface PriorYearBalances {
  losses: number;
  capitalAllowances: number;
  donations: number;
}

export interface ExemptionSelection {
  scheme?: "auto" | ExemptionScheme;
  qualifiesForSute?: boolean;
  firstYaYear?: number;
}

export interface TaxComputationInput {
  yaYear: SupportedYaYear;
  revenue: number;
  netProfitLoss: number;
  otherIncome?: number;
  taxAdjustments?: TaxAdjustmentEntry[];
  capitalAllowancesCurrentYear?: number;
  priorYearBalances?: Partial<PriorYearBalances>;
  exemption?: ExemptionSelection;
  citRebate?: {
    eligibleForCashGrant?: boolean;
  };
}

export interface TaxExemptionResult {
  scheme: ExemptionScheme;
  exemptAmount: number;
  taxableIncome: number;
}

export interface CorporateIncomeTaxRebateResult {
  yaYear: SupportedYaYear;
  rebateRate: number;
  rebateCap: number;
  taxPayableBeforeRebate: number;
  rebateBeforeCashGrant: number;
  cashGrantAmount: number;
  rebateAmount: number;
}

export interface FormCSOutput {
  revenue: number;
  otherIncome: number;
  netProfitLoss: number;
  totalAddBacks: number;
  totalDeductions: number;
  adjustedProfitLoss: number;
  capitalAllowancesClaimed: number;
  lossesBroughtForwardUsed: number;
  capitalAllowancesBroughtForwardUsed: number;
  donationsBroughtForwardUsed: number;
  chargeableIncome: number;
  exemptionScheme: ExemptionScheme;
  exemptAmount: number;
  taxableIncomeAfterExemptions: number;
  corporateIncomeTaxRate: number;
  grossTaxPayable: number;
  citRebateAmount: number;
  taxPayable: number;
}

export interface TaxComputationResult {
  chargeableIncome: number;
  taxPayable: number;
  adjustedProfitLoss: number;
  exemptionScheme: ExemptionScheme;
  exemptAmount: number;
  taxableIncomeAfterExemptions: number;
  grossTaxPayable: number;
  citRebateAmount: number;
  citRebateCashGrant: number;
  currentYearCapitalAllowancesClaimed: number;
  lossesBroughtForwardUsed: number;
  capitalAllowancesBroughtForwardUsed: number;
  donationsBroughtForwardUsed: number;
  remainingBalances: PriorYearBalances;
  formCsOutput: FormCSOutput;
}

export interface TaxComputationRecords {
  company: Pick<Company, "companyId" | "incorporationDate" | "isTaxResident" | "shareholderCount">;
  summary: Pick<FinancialSummary, "companyId" | "yaYear" | "totalRevenue" | "netProfitLoss">;
  adjustments?: Array<Pick<TaxAdjustment, "description" | "amount" | "adjustmentType" | "category">>;
  otherIncome?: number;
  capitalAllowancesCurrentYear?: number;
  priorYearBalances?: Partial<PriorYearBalances>;
  exemption?: ExemptionSelection;
  citRebate?: {
    eligibleForCashGrant?: boolean;
  };
}

export function assessFormCSEligibility(input: EligibilityInput): EligibilityResult {
  const reasons: string[] = [];

  if (!input.isIncorporatedInSingapore) {
    reasons.push("Company is not incorporated in Singapore.");
  }

  if (roundToCents(input.annualRevenue) > 5_000_000) {
    reasons.push("Annual revenue exceeds S$5,000,000.");
  }

  if (!input.hasOnlyIncomeTaxableAt17Percent) {
    reasons.push("Company derives income that is not taxable solely at the prevailing 17% rate.");
  }

  if (input.claimsCarryBackRelief) {
    reasons.push("Company is claiming carry-back of current year capital allowances or losses.");
  }

  if (input.claimsGroupRelief) {
    reasons.push("Company is claiming group relief.");
  }

  if (input.claimsInvestmentAllowance) {
    reasons.push("Company is claiming investment allowance.");
  }

  if (input.claimsForeignTaxCredit) {
    reasons.push("Company is claiming foreign tax credit.");
  }

  if (input.hasTaxDeductedAtSource) {
    reasons.push("Company has tax deducted at source.");
  }

  const qualifiesForFormCS = reasons.length === 0;
  const qualifiesForFormCSLite = qualifiesForFormCS && roundToCents(input.annualRevenue) <= 200_000;

  return {
    formType: qualifiesForFormCSLite ? "form-c-s-lite" : qualifiesForFormCS ? "form-c-s" : "form-c-required",
    qualifiesForFormCS,
    qualifiesForFormCSLite,
    reasons
  };
}

export function calculateTaxExemption(chargeableIncome: number, scheme: ExemptionScheme): TaxExemptionResult {
  const income = clampNonNegative(chargeableIncome);
  const exemptAmount = scheme === "sute"
    ? roundToCents(Math.min(income, 100_000) * 0.75 + Math.min(Math.max(income - 100_000, 0), 100_000) * 0.5)
    : roundToCents(Math.min(income, 10_000) * 0.75 + Math.min(Math.max(income - 10_000, 0), 190_000) * 0.5);

  return {
    scheme,
    exemptAmount,
    taxableIncome: roundToCents(Math.max(income - exemptAmount, 0))
  };
}

export function computeCorporateIncomeTaxRebate(input: {
  yaYear: SupportedYaYear;
  taxPayableBeforeRebate: number;
  eligibleForCashGrant?: boolean;
}): CorporateIncomeTaxRebateResult {
  assertSupportedYaYear(input.yaYear);

  const taxPayableBeforeRebate = clampNonNegative(input.taxPayableBeforeRebate);
  const rebateBeforeCashGrant = roundToCents(Math.min(taxPayableBeforeRebate * 0.5, 40_000));
  const cashGrantAmount = input.eligibleForCashGrant ? 2_000 : 0;
  const rebateAmount = roundToCents(Math.max(rebateBeforeCashGrant - cashGrantAmount, 0));

  return {
    yaYear: input.yaYear,
    rebateRate: 0.5,
    rebateCap: 40_000,
    taxPayableBeforeRebate,
    rebateBeforeCashGrant,
    cashGrantAmount,
    rebateAmount
  };
}

export function computeFormCSTax(input: TaxComputationInput): TaxComputationResult {
  assertSupportedYaYear(input.yaYear);

  const revenue = clampNonNegative(input.revenue);
  const otherIncome = clampNonNegative(input.otherIncome ?? 0);
  const netProfitLoss = roundToCents(input.netProfitLoss);
  const adjustments = input.taxAdjustments ?? [];

  const totalAddBacks = sumAmounts(adjustments.filter((adjustment) => adjustment.adjustmentType === "add_back"));
  const totalDeductions = sumAmounts(
    adjustments.filter(
      (adjustment) => adjustment.adjustmentType === "deduct" && adjustment.category !== "capital_allowance" && adjustment.category !== "loss_brought_forward"
    )
  );
  const currentYearCapitalAllowancesClaimed = roundToCents(
    clampNonNegative(input.capitalAllowancesCurrentYear ?? 0)
      + sumAmounts(adjustments.filter((adjustment) => adjustment.adjustmentType === "deduct" && adjustment.category === "capital_allowance"))
  );

  const priorYearBalances: PriorYearBalances = {
    losses: roundToCents(
      clampNonNegative(input.priorYearBalances?.losses ?? 0)
        + sumAmounts(adjustments.filter((adjustment) => adjustment.adjustmentType === "deduct" && adjustment.category === "loss_brought_forward"))
    ),
    capitalAllowances: clampNonNegative(input.priorYearBalances?.capitalAllowances ?? 0),
    donations: clampNonNegative(input.priorYearBalances?.donations ?? 0)
  };

  const adjustedProfitLoss = roundToCents(netProfitLoss + totalAddBacks - totalDeductions + otherIncome);
  const afterCurrentYearCapitalAllowances = roundToCents(adjustedProfitLoss - currentYearCapitalAllowancesClaimed);
  const lossesBroughtForwardUsed = roundToCents(Math.min(priorYearBalances.losses, Math.max(afterCurrentYearCapitalAllowances, 0)));
  const afterLosses = roundToCents(afterCurrentYearCapitalAllowances - lossesBroughtForwardUsed);
  const capitalAllowancesBroughtForwardUsed = roundToCents(
    Math.min(priorYearBalances.capitalAllowances, Math.max(afterLosses, 0))
  );
  const afterCapitalAllowancesBf = roundToCents(afterLosses - capitalAllowancesBroughtForwardUsed);
  const donationsBroughtForwardUsed = roundToCents(Math.min(priorYearBalances.donations, Math.max(afterCapitalAllowancesBf, 0)));
  const afterDonations = roundToCents(afterCapitalAllowancesBf - donationsBroughtForwardUsed);
  const currentYearLoss = roundToCents(Math.max(-afterDonations, 0));
  const chargeableIncome = roundToCents(Math.max(afterDonations, 0));

  const exemptionScheme = resolveExemptionScheme(input.yaYear, input.exemption);
  const exemption = calculateTaxExemption(chargeableIncome, exemptionScheme);
  const grossTaxPayable = roundToCents(exemption.taxableIncome * CORPORATE_INCOME_TAX_RATE);
  const rebate = computeCorporateIncomeTaxRebate({
    yaYear: input.yaYear,
    taxPayableBeforeRebate: grossTaxPayable,
    eligibleForCashGrant: input.citRebate?.eligibleForCashGrant
  });
  const taxPayable = roundToCents(Math.max(grossTaxPayable - rebate.rebateAmount, 0));

  const remainingBalances: PriorYearBalances = {
    losses: roundToCents(priorYearBalances.losses - lossesBroughtForwardUsed + currentYearLoss),
    capitalAllowances: roundToCents(priorYearBalances.capitalAllowances - capitalAllowancesBroughtForwardUsed),
    donations: roundToCents(priorYearBalances.donations - donationsBroughtForwardUsed)
  };

  const formCsOutput: FormCSOutput = {
    revenue,
    otherIncome,
    netProfitLoss,
    totalAddBacks,
    totalDeductions,
    adjustedProfitLoss,
    capitalAllowancesClaimed: currentYearCapitalAllowancesClaimed,
    lossesBroughtForwardUsed,
    capitalAllowancesBroughtForwardUsed,
    donationsBroughtForwardUsed,
    chargeableIncome,
    exemptionScheme,
    exemptAmount: exemption.exemptAmount,
    taxableIncomeAfterExemptions: exemption.taxableIncome,
    corporateIncomeTaxRate: CORPORATE_INCOME_TAX_RATE,
    grossTaxPayable,
    citRebateAmount: rebate.rebateAmount,
    taxPayable
  };

  return {
    chargeableIncome,
    taxPayable,
    adjustedProfitLoss,
    exemptionScheme,
    exemptAmount: exemption.exemptAmount,
    taxableIncomeAfterExemptions: exemption.taxableIncome,
    grossTaxPayable,
    citRebateAmount: rebate.rebateAmount,
    citRebateCashGrant: rebate.cashGrantAmount,
    currentYearCapitalAllowancesClaimed,
    lossesBroughtForwardUsed,
    capitalAllowancesBroughtForwardUsed,
    donationsBroughtForwardUsed,
    remainingBalances,
    formCsOutput
  };
}

export function computeFormCSTaxFromRecords(records: TaxComputationRecords): TaxComputationResult {
  assertSupportedYaYear(records.summary.yaYear);

  return computeFormCSTax({
    yaYear: records.summary.yaYear,
    revenue: records.summary.totalRevenue,
    netProfitLoss: records.summary.netProfitLoss,
    otherIncome: records.otherIncome,
    taxAdjustments: records.adjustments,
    capitalAllowancesCurrentYear: records.capitalAllowancesCurrentYear,
    priorYearBalances: records.priorYearBalances,
    exemption: records.exemption,
    citRebate: records.citRebate
  });
}

function resolveExemptionScheme(yaYear: SupportedYaYear, exemption?: ExemptionSelection): ExemptionScheme {
  if (exemption?.scheme === "sute" || exemption?.scheme === "pte") {
    return exemption.scheme;
  }

  const qualifiesForSute = exemption?.qualifiesForSute === true
    && (exemption.firstYaYear === undefined || (yaYear >= exemption.firstYaYear && yaYear <= exemption.firstYaYear + 2));

  return qualifiesForSute ? "sute" : "pte";
}

function assertSupportedYaYear(yaYear: number): asserts yaYear is SupportedYaYear {
  if (!SUPPORTED_YA_YEARS.includes(yaYear as SupportedYaYear)) {
    throw new Error(`Unsupported YA year: ${yaYear}. Supported years are ${SUPPORTED_YA_YEARS.join(", ")}.`);
  }
}

function sumAmounts(entries: Array<Pick<TaxAdjustmentEntry, "amount">>): number {
  return roundToCents(entries.reduce((sum, entry) => sum + Math.abs(entry.amount), 0));
}

function clampNonNegative(value: number): number {
  return roundToCents(Math.max(value, 0));
}

function roundToCents(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

export type {
  Company,
  FinancialSummary,
  TaxAdjustment
};
