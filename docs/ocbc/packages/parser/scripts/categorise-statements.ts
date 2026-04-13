import { PDFParse } from "pdf-parse";
import fs from "node:fs";
import path from "node:path";

// ── Types ───────────────────────────────────────────────────────────────────

type TaxCategory =
  | "revenue"
  | "salary_wages"
  | "contractor_payments"
  | "rent_property"
  | "utilities"
  | "professional_fees"
  | "bank_charges"
  | "insurance"
  | "transport_travel"
  | "meals_entertainment"
  | "office_supplies"
  | "inventory_cogs"
  | "it_software"
  | "marketing_advertising"
  | "subscriptions"
  | "repairs_maintenance"
  | "training_development"
  | "medical_benefits"
  | "cpf_contributions"
  | "donations"
  | "capital_expenditure"
  | "loan_repayment"
  | "cash_withdrawal"
  | "transfer_internal"
  | "personal_non_deductible"
  | "uncategorised";

interface TaxCategoryMeta {
  label: string;
  deductible: boolean | "partial";
  deductionRate: number; // 1.0 = 100%, 0.5 = 50%, 0 = not deductible
  section: string;
  note: string;
}

interface Transaction {
  date: string;
  valueDate: string;
  description: string;
  withdrawal?: number;
  deposit?: number;
  balance: number;
  category: TaxCategory;
  categoryLabel: string;
  deductible: boolean | "partial";
  deductionAmount: number;
  month: string;
  year: number;
  source: string;
}

// ── Singapore Tax Category Definitions ──────────────────────────────────────

const CATEGORY_META: Record<TaxCategory, TaxCategoryMeta> = {
  revenue: {
    label: "Revenue / Income",
    deductible: false,
    deductionRate: 0,
    section: "S10(1)(a)",
    note: "Taxable business income",
  },
  salary_wages: {
    label: "Salary & Wages",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Fully deductible employee remuneration",
  },
  contractor_payments: {
    label: "Contractor / Freelancer Payments",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Deductible if incurred in producing income",
  },
  rent_property: {
    label: "Rent & Property",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Deductible business premises rent",
  },
  utilities: {
    label: "Utilities",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Electricity, water, internet for business",
  },
  professional_fees: {
    label: "Professional Fees (Legal/Accounting/Audit)",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Deductible revenue-nature professional fees",
  },
  bank_charges: {
    label: "Bank Charges & Fees",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Deductible business banking costs",
  },
  insurance: {
    label: "Insurance",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Business insurance premiums",
  },
  transport_travel: {
    label: "Transport & Business Travel",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Deductible if wholly for business purposes",
  },
  meals_entertainment: {
    label: "Staff Entertainment & Meals",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "100% deductible — confirmed as staff welfare/entertainment",
  },
  office_supplies: {
    label: "Office Supplies & General Expenses",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Fully deductible consumables",
  },
  it_software: {
    label: "IT, Software & Digital Services",
    deductible: true,
    deductionRate: 1.0,
    section: "S14/S19A",
    note: "Software as expense or capital allowance over 1 year",
  },
  marketing_advertising: {
    label: "Marketing & Advertising",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Deductible business promotion costs",
  },
  subscriptions: {
    label: "Subscriptions & Memberships",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Trade/professional subscriptions deductible",
  },
  repairs_maintenance: {
    label: "Repairs & Maintenance",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)(d)",
    note: "Revenue-nature repairs fully deductible",
  },
  training_development: {
    label: "Training & Development",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Staff training deductible",
  },
  medical_benefits: {
    label: "Medical & Health Benefits",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Staff medical deductible up to 2% of remuneration (1% if no approved scheme)",
  },
  cpf_contributions: {
    label: "CPF Contributions",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Employer CPF contributions are fully deductible",
  },
  donations: {
    label: "Donations (Approved IPCs)",
    deductible: true,
    deductionRate: 2.5,
    section: "S37",
    note: "250% deduction for approved IPC donations (until YA2026)",
  },
  inventory_cogs: {
    label: "Inventory / Cost of Goods Sold",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Raw materials and inventory for resale — fully deductible",
  },
  capital_expenditure: {
    label: "Capital Expenditure",
    deductible: "partial",
    deductionRate: 0,
    section: "S19/S19A",
    note: "Not directly deductible; claim capital allowance separately",
  },
  loan_repayment: {
    label: "Loan Repayment",
    deductible: false,
    deductionRate: 0,
    section: "N/A",
    note: "Principal repayments are not deductible (interest may be)",
  },
  cash_withdrawal: {
    label: "Cash Withdrawal (Stock Purchases)",
    deductible: true,
    deductionRate: 1.0,
    section: "S14(1)",
    note: "Cash used for stock/inventory purchases — fully deductible with petty cash log",
  },
  transfer_internal: {
    label: "Internal Transfer",
    deductible: false,
    deductionRate: 0,
    section: "N/A",
    note: "Transfers between own accounts — neutral",
  },
  personal_non_deductible: {
    label: "Personal / Non-Deductible",
    deductible: false,
    deductionRate: 0,
    section: "S15",
    note: "Private expenditure; not deductible under S15",
  },
  uncategorised: {
    label: "Uncategorised",
    deductible: false,
    deductionRate: 0,
    section: "—",
    note: "Needs manual review",
  },
};

// ── Categorisation Rules ────────────────────────────────────────────────────
// Order matters: first match wins. More specific patterns come first.

interface CategorisationRule {
  patterns: RegExp[];
  category: TaxCategory;
  direction?: "withdrawal" | "deposit" | "any";
}

const RULES: CategorisationRule[] = [
  // ─ Revenue / Inflows ─
  {
    patterns: [/IBG GIRO/i, /GIRO.*ISETAN/i, /GIRO.*TAKASHIMAYA/i],
    category: "revenue",
    direction: "deposit",
  },
  {
    patterns: [/PAYMENT\/TRANSFER/i],
    category: "revenue",
    direction: "deposit",
  },
  {
    patterns: [/FUND TRANSFER/i],
    category: "revenue",
    direction: "deposit",
  },
  {
    patterns: [/FAST PAYMENT/i, /FAST TRANSFER/i],
    category: "revenue",
    direction: "deposit",
  },
  {
    patterns: [/INTEREST\s*CREDIT/i, /INT\s*EARNED/i, /CASH REBATE/i],
    category: "revenue",
    direction: "deposit",
  },

  // ─ CPF ─
  {
    patterns: [/CPF\s*BOARD/i, /CPF\s*CONTRIBUTION/i, /CPF\s*PAYMENT/i],
    category: "cpf_contributions",
  },

  // ─ IRAS / Corporate Tax ─
  {
    patterns: [/IRAS/i, /INLAND\s*REVENUE/i, /TAX\s*PAYMENT/i, /GST\s*PAYMENT/i, /CASE\s*ID\s*\d+/i],
    category: "personal_non_deductible",
  },

  // ─ Medical (before bank charges to catch CLINIC CHARGES) ─
  {
    patterns: [
      /MED\s*CONSULT/i, /CLINIC/i, /HOSPITAL/i, /PHARMACY/i,
      /DOCTOR/i, /DENTAL/i, /MEDICAL/i,
      /GUARDIAN/i, /WATSONS/i,
    ],
    category: "medical_benefits",
  },

  // ─ Cash Withdrawals (before salary to avoid matching) ─
  {
    patterns: [/CASH\s*WITHDRAWAL/i, /ATM\s*W\/D/i],
    category: "cash_withdrawal",
  },

  // ─ Inventory / Cost of Goods Sold (business sells via dept stores) ─
  {
    patterns: [
      /ETSY\.COM/i,
      /TOP FABRIC/i, /FABRIC/i,
      /RACHAEL\s*CRYSTAL/i, /CRYSTAL\s*TRADING/i,
      /STERLING\s*SIL/i, /CRYSTALIDEA/i,
      /MIX\s*&\s*MATCH\s*MERCHANDIS/i,
      /NEWECON/i,
      /JI\s*XIANG\s*WHOLESAL/i,
    ],
    category: "inventory_cogs",
  },

  // ─ Bank Charges & Fees ─
  {
    patterns: [
      /^CHARGES\b/i, /Txn\s*Charges/i, /Billing\s*Statement/i,
      /BANK\s*FEE/i, /SERVICE\s*CHARGE/i, /SER\s*CHARGE/i,
      /CCY\s*CONVERSION\s*FEE/i, /TRAN\s*CHARGE/i,
      /ANNUAL\s*FEE/i, /ACCOUNT\s*FEE/i,
    ],
    category: "bank_charges",
  },

  // ─ Travel & Transport (before meals — GRAB can be transport) ─
  {
    patterns: [
      /EDREAMS/i, /BOOKING\.COM/i, /Partners on Booki/i,
      /AIRBNB/i, /AGODA/i, /EXPEDIA/i, /KLOOK/i, /Kiwi\.com/i,
      /AIRLINES?/i, /SCOOT/i, /JETSTAR/i, /CATHAY/i, /\bSIA\b/i,
      /TAXI\b/i, /\bGRAB\b(?!\s*FOOD)/i, /GOJEK/i, /COMFORT/i,
      /\bTADA\b/i, /WWW\.TADA/i,
      /BUS\/MRT/i, /\bSMRT\b/i, /TRANSIT/i, /EZ-?LINK/i,
      /CHANGI\s*T/i,
      /CC\s*S\s*HIDEAWAY/i,
    ],
    category: "transport_travel",
  },

  // ─ Meals & Entertainment ─
  {
    patterns: [
      /COFFEE/i, /CAFE/i, /RESTAURANT/i, /\bFOOD\b/i,
      /COMMON\s*MAN/i, /STARBUCKS/i, /TOAST\s*BOX/i,
      /GRAB\s*FOOD/i, /DELIVEROO/i, /FOODPANDA/i,
      /HAWKER/i, /EATING\s*HOUSE/i, /BISTRO/i,
      /\bBAR\b/i, /TESS\s*BAR/i,
      /\bPUB\b/i, /\bWINE\b/i, /\bBEER\b/i,
      /\bKFC\b/i, /MCDONALD/i, /SUBWAY/i, /PIZZA/i,
      /BURGER\s*KING/i, /\bBK\s*-/i,
      /RAMEN/i, /SANPOUTEI/i, /YUGOSLAVIA/i,
      /BUTTER\s*STUDIO/i,
      /7-?ELEVEN/i, /7\s*ELEVEN/i, /CHEERS/i,
      /CRUST\s*C/i, /SNP\*CRUST/i,
    ],
    category: "meals_entertainment",
  },

  // ─ Supermarket / Groceries ─
  {
    patterns: [
      /SUPERMARKET/i, /SUPERMART/i,
      /NTUC/i, /FAIRPRICE/i, /FP\s*XTRA/i,
      /COLD\s*STORAGE/i, /SHENG\s*SIONG/i, /\bGIANT\b/i,
      /DON\s*DON\s*DONKI/i,
      /TOP\s*CHOICE/i,
      /AVM\s*SUPERMART/i,
    ],
    category: "meals_entertainment",
  },

  // ─ Salary / Payroll (FAST PAYMENT outflows to named individuals) ─
  {
    patterns: [
      /SALARY/i, /PAYROLL/i, /WAGES/i,
      /FAST PAYMENT/i, /FAST TRANSFER/i,
    ],
    category: "salary_wages",
    direction: "withdrawal",
  },

  // ─ Insurance ─
  {
    patterns: [/INSURANCE/i, /INSUR/i, /\bAIA\b/i, /PRUDENTIAL/i, /GREAT EASTERN/i, /NTUC INCOME/i],
    category: "insurance",
  },

  // ─ IT / Software ─
  {
    patterns: [
      /GOOGLE/i, /APPLE/i, /MICROSOFT/i, /AMAZON\s*WEB/i, /\bAWS\b/i,
      /ADOBE/i, /GITHUB/i, /ATLASSIAN/i, /SLACK/i, /ZOOM/i,
      /DIGITAL\s*OCEAN/i, /HEROKU/i, /VERCEL/i, /NETLIFY/i,
      /SHOPIFY/i, /STRIPE/i, /PAYPAL/i, /CANVA/i,
    ],
    category: "it_software",
  },

  // ─ Professional Fees ─
  {
    patterns: [
      /ACRA/i, /ACCOUNTING/i, /AUDIT/i, /LEGAL/i,
      /LAW\s*FIRM/i, /SOLICITOR/i, /NOTARY/i,
      /XERO/i, /QUICKBOOKS/i,
    ],
    category: "professional_fees",
  },

  // ─ Utilities ─
  {
    patterns: [/SP\s*GROUP/i, /SP\s*SERVICES/i, /SINGTEL/i, /STARHUB/i, /\bM1\b/i],
    category: "utilities",
  },

  // ─ Rent ─
  {
    patterns: [/RENT/i, /LEASE/i, /TENANCY/i, /LANDLORD/i],
    category: "rent_property",
  },

  // ─ Marketing ─
  {
    patterns: [/FACEBOOK\s*ADS/i, /GOOGLE\s*ADS/i, /LINKEDIN/i, /TIKTOK/i, /ADVERTISING/i],
    category: "marketing_advertising",
  },

  // ─ Donations ─
  {
    patterns: [/DONATION/i, /CHARITY/i, /RED\s*CROSS/i, /COMMUNITY\s*CHEST/i],
    category: "donations",
  },

  // ─ Subscriptions ─
  {
    patterns: [/SUBSCRIPTION/i, /MEMBERSHIP/i],
    category: "subscriptions",
  },

  // ─ Staff Uniforms (deductible) ─
  {
    patterns: [
      /ZARA\b/i,
      /\bH&M\b/i,
    ],
    category: "office_supplies",
  },

  // ─ Clothing/dept store purchases (could be business inventory or personal) ─
  {
    patterns: [
      /\bBHG\b/i, /\bM\s*&\s*S\b/i,
    ],
    category: "inventory_cogs",
  },

  // ─ Debit Purchase catch-all → office supplies ─
  {
    patterns: [/DEBIT\s*PURCHASE/i],
    category: "office_supplies",
    direction: "withdrawal",
  },

  // ─ Debit Transfer catch-all ─
  {
    patterns: [/DEBIT\s*TRANSFER/i],
    category: "uncategorised",
    direction: "withdrawal",
  },

  // ─ POS Purchase catch-all ─
  {
    patterns: [/POS\s*PURCHASE/i],
    category: "office_supplies",
    direction: "withdrawal",
  },
];

// ── OCBC PDF Parser ─────────────────────────────────────────────────────────

const MONTH_MAP: Record<string, string> = {
  JAN: "01", FEB: "02", MAR: "03", APR: "04", MAY: "05", JUN: "06",
  JUL: "07", AUG: "08", SEP: "09", OCT: "10", NOV: "11", DEC: "12",
};

function parseOcbcDate(dayStr: string, monthStr: string, year: number): string {
  const month = MONTH_MAP[monthStr.toUpperCase()];
  if (!month) return "";
  return `${year}-${month}-${dayStr.padStart(2, "0")}`;
}

function parseAmount(s: string): number | undefined {
  if (!s) return undefined;
  const cleaned = s.replace(/,/g, "").trim();
  if (!cleaned || cleaned === "-") return undefined;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : undefined;
}

interface RawTransaction {
  txnDate: string;
  valueDate: string;
  description: string;
  amount: number;
  balance: number;
  isDeposit: boolean;
}

function extractTransactionBlocks(fullText: string, year: number): RawTransaction[] {
  const results: RawTransaction[] = [];

  const pages = fullText.split(/-- \d+ of \d+ --/i);

  for (const page of pages) {
    // Skip pages that are the transaction code reference
    if (page.includes("TRANSACTION CODE DESCRIPTION")) continue;

    const lines = page.split("\n");
    let prevBalance: number | undefined;
    let inTransactionSection = false;
    let currentTxn: {
      txnDateStr: string;
      valueDateStr: string;
      amount: number;
      balance: number;
      descriptionLines: string[];
    } | null = null;

    // Find the period line to determine the year context
    let stmtYear = year;
    for (const line of lines) {
      const periodMatch = line.match(
        /\d+\s+[A-Z]{3}\s+(\d{4})\s+TO\s+\d+\s+[A-Z]{3}\s+(\d{4})/
      );
      if (periodMatch) {
        stmtYear = parseInt(periodMatch[2]);
        break;
      }
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Detect start of transaction table
      if (line.includes("BALANCE B/F")) {
        inTransactionSection = true;
        const bfMatch = line.match(/([\d,]+\.\d{2})\s*BALANCE B\/F/);
        if (bfMatch) {
          prevBalance = parseAmount(bfMatch[1]);
        }
        continue;
      }

      if (!inTransactionSection) continue;

      // Skip header repetitions and noise
      if (
        line.includes("STATEMENT OF ACCOUNT") ||
        line.includes("BUSINESS GROWTH ACCOUNT") ||
        line.includes("Account No.") ||
        line.match(/^\d+\s+[A-Z]{3}\s+\d{4}\s+TO/) ||
        line.includes("Page ") ||
        line.includes("Please turn over") ||
        line.includes("CRAELL PTE") ||
        line.includes("RNB0") ||
        line.includes("Transaction") ||
        line.match(/^Date\s+Date\s+Description/) ||
        line.match(/^Value$/) ||
        !line.trim()
      ) {
        continue;
      }

      // Check for a new transaction line: "DD MMM <amount> <balance>\tDD MMM <description>"
      // The tab character is key - it separates the value-date/amount/balance block from the txn-date/description
      const txnMatch = line.match(
        /^(\d{2}\s+[A-Z]{3})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\t(\d{2}\s+[A-Z]{3})\s+(.+)$/
      );

      if (txnMatch) {
        // Flush previous transaction
        if (currentTxn) {
          const desc = currentTxn.descriptionLines.join(" ").trim();
          const isDeposit = prevBalance !== undefined
            ? currentTxn.balance > (prevBalance ?? 0)
            : false;
          results.push({
            txnDate: currentTxn.txnDateStr,
            valueDate: currentTxn.valueDateStr,
            description: desc,
            amount: currentTxn.amount,
            balance: currentTxn.balance,
            isDeposit,
          });
          prevBalance = currentTxn.balance;
        }

        const [, valueDateRaw, amountStr, balanceStr, txnDateRaw, descFirstLine] = txnMatch;
        const amount = parseAmount(amountStr)!;
        const balance = parseAmount(balanceStr)!;

        const vdParts = valueDateRaw.split(/\s+/);
        const tdParts = txnDateRaw.split(/\s+/);

        currentTxn = {
          valueDateStr: parseOcbcDate(vdParts[0], vdParts[1], stmtYear),
          txnDateStr: parseOcbcDate(tdParts[0], tdParts[1], stmtYear),
          amount,
          balance,
          descriptionLines: [descFirstLine],
        };
        continue;
      }

      // Continuation line for current transaction description
      if (currentTxn && line.trim()) {
        currentTxn.descriptionLines.push(line.trim());
      }
    }

    // Flush last transaction on this page
    if (currentTxn) {
      const desc = currentTxn.descriptionLines.join(" ").trim();
      const isDeposit = prevBalance !== undefined
        ? currentTxn.balance > (prevBalance ?? 0)
        : false;
      results.push({
        txnDate: currentTxn.txnDateStr,
        valueDate: currentTxn.valueDateStr,
        description: desc,
        amount: currentTxn.amount,
        balance: currentTxn.balance,
        isDeposit,
      });
      prevBalance = currentTxn.balance;
    }
  }

  return results;
}

// ── Categorise a single transaction ─────────────────────────────────────────

function categorise(desc: string, isDeposit: boolean): TaxCategory {
  const direction = isDeposit ? "deposit" : "withdrawal";

  for (const rule of RULES) {
    if (rule.direction && rule.direction !== "any" && rule.direction !== direction) continue;
    for (const pattern of rule.patterns) {
      if (pattern.test(desc)) {
        return rule.category;
      }
    }
  }

  // Fallback: deposits are likely revenue, withdrawals uncategorised
  if (isDeposit) return "revenue";

  return "uncategorised";
}

// ── Main ────────────────────────────────────────────────────────────────────

async function main() {
  const dirs = [
    { dir: "/Users/user/Downloads/c-s/2024", year: 2024 },
    { dir: "/Users/user/Downloads/c-s/2025", year: 2025 },
  ];

  const allTransactions: Transaction[] = [];

  for (const { dir, year } of dirs) {
    const files = fs.readdirSync(dir)
      .filter((f) => f.endsWith(".pdf"))
      .sort((a, b) => {
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const mA = months.findIndex((m) => a.includes(m));
        const mB = months.findIndex((m) => b.includes(m));
        return mA - mB;
      });

    for (const file of files) {
      const filePath = path.join(dir, file);
      const data = fs.readFileSync(filePath);
      const parser = new PDFParse({ data: new Uint8Array(data) });

      try {
        const result = await parser.getText();
        const rawTxns = extractTransactionBlocks(result.text, year);

        for (const raw of rawTxns) {
          const cat = categorise(raw.description, raw.isDeposit);
          const meta = CATEGORY_META[cat];
          const amount = raw.isDeposit ? raw.amount : raw.amount;
          const deductionAmount = raw.isDeposit
            ? 0
            : amount * meta.deductionRate;

          const monthMatch = file.match(/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/);

          allTransactions.push({
            date: raw.txnDate,
            valueDate: raw.valueDate,
            description: raw.description,
            withdrawal: raw.isDeposit ? undefined : raw.amount,
            deposit: raw.isDeposit ? raw.amount : undefined,
            balance: raw.balance,
            category: cat,
            categoryLabel: meta.label,
            deductible: meta.deductible,
            deductionAmount,
            month: monthMatch?.[1] ?? "",
            year,
            source: file,
          });
        }
      } finally {
        await parser.destroy();
      }
    }
  }

  // ── Generate Report ─────────────────────────────────────────────────────

  console.log("═".repeat(100));
  console.log("  CRAELL PTE. LTD. — TAX CATEGORISATION REPORT");
  console.log("  OCBC Business Growth Account 601483548001");
  console.log("  Period: January 2024 – December 2025");
  console.log("═".repeat(100));
  console.log();

  // Summary by year
  for (const year of [2024, 2025]) {
    const yearTxns = allTransactions.filter((t) => t.year === year);
    const totalDeposits = yearTxns.reduce((s, t) => s + (t.deposit ?? 0), 0);
    const totalWithdrawals = yearTxns.reduce((s, t) => s + (t.withdrawal ?? 0), 0);
    const totalDeductions = yearTxns.reduce((s, t) => s + t.deductionAmount, 0);

    console.log(`\n${"─".repeat(100)}`);
    console.log(`  YA${year + 1} (Financial Year ${year}) — SUMMARY`);
    console.log(`${"─".repeat(100)}`);
    console.log(`  Total transactions:  ${yearTxns.length}`);
    console.log(`  Total deposits:      S$${totalDeposits.toLocaleString("en-SG", { minimumFractionDigits: 2 })}`);
    console.log(`  Total withdrawals:   S$${totalWithdrawals.toLocaleString("en-SG", { minimumFractionDigits: 2 })}`);
    console.log(`  Total deductions:    S$${totalDeductions.toLocaleString("en-SG", { minimumFractionDigits: 2 })}`);

    // Category breakdown
    const catTotals: Record<string, { withdrawal: number; deposit: number; deduction: number; count: number }> = {};

    for (const t of yearTxns) {
      if (!catTotals[t.category]) {
        catTotals[t.category] = { withdrawal: 0, deposit: 0, deduction: 0, count: 0 };
      }
      catTotals[t.category].withdrawal += t.withdrawal ?? 0;
      catTotals[t.category].deposit += t.deposit ?? 0;
      catTotals[t.category].deduction += t.deductionAmount;
      catTotals[t.category].count++;
    }

    console.log(`\n  Category Breakdown:`);
    console.log(`  ${"Category".padEnd(40)} ${"Count".padStart(6)} ${"Withdrawals".padStart(14)} ${"Deposits".padStart(14)} ${"Deduction".padStart(14)} ${"Rate".padStart(6)}`);
    console.log(`  ${"─".repeat(96)}`);

    const sortedCats = Object.entries(catTotals).sort((a, b) => b[1].withdrawal - a[1].withdrawal);

    for (const [cat, totals] of sortedCats) {
      const meta = CATEGORY_META[cat as TaxCategory];
      const rateStr = meta.deductionRate === 0 ? "  0%" :
        meta.deductionRate === 1 ? "100%" :
        meta.deductionRate === 0.5 ? " 50%" :
        `${(meta.deductionRate * 100).toFixed(0)}%`;
      console.log(
        `  ${meta.label.padEnd(40)} ${String(totals.count).padStart(6)} ${("S$" + totals.withdrawal.toLocaleString("en-SG", { minimumFractionDigits: 2 })).padStart(14)} ${("S$" + totals.deposit.toLocaleString("en-SG", { minimumFractionDigits: 2 })).padStart(14)} ${("S$" + totals.deduction.toLocaleString("en-SG", { minimumFractionDigits: 2 })).padStart(14)} ${rateStr.padStart(6)}`
      );
    }
  }

  // ── Detailed Transaction Listing ────────────────────────────────────────

  console.log(`\n\n${"═".repeat(100)}`);
  console.log("  DETAILED TRANSACTION LISTING");
  console.log(`${"═".repeat(100)}`);

  for (const year of [2024, 2025]) {
    const yearTxns = allTransactions.filter((t) => t.year === year);
    console.log(`\n${"─".repeat(100)}`);
    console.log(`  ${year}`);
    console.log(`${"─".repeat(100)}`);
    console.log(
      `  ${"Date".padEnd(12)} ${"Description".padEnd(45)} ${"W/D".padStart(12)} ${"Dep".padStart(12)} ${"Category".padEnd(20)}`
    );
    console.log(`  ${"─".repeat(96)}`);

    for (const t of yearTxns) {
      const descShort = t.description.length > 43 ? t.description.slice(0, 43) + ".." : t.description;
      const wdStr = t.withdrawal ? `S$${t.withdrawal.toLocaleString("en-SG", { minimumFractionDigits: 2 })}` : "";
      const depStr = t.deposit ? `S$${t.deposit.toLocaleString("en-SG", { minimumFractionDigits: 2 })}` : "";
      console.log(
        `  ${t.date.padEnd(12)} ${descShort.padEnd(45)} ${wdStr.padStart(12)} ${depStr.padStart(12)} ${t.categoryLabel.slice(0, 20).padEnd(20)}`
      );
    }
  }

  // ── Deduction Optimisation Recommendations ──────────────────────────────

  console.log(`\n\n${"═".repeat(100)}`);
  console.log("  DEDUCTION OPTIMISATION RECOMMENDATIONS");
  console.log(`${"═".repeat(100)}`);

  const uncategorised = allTransactions.filter((t) => t.category === "uncategorised");
  const personalItems = allTransactions.filter((t) => t.category === "personal_non_deductible");
  const cashWithdrawals = allTransactions.filter((t) => t.category === "cash_withdrawal");
  const mealsItems = allTransactions.filter((t) => t.category === "meals_entertainment");

  console.log(`
  DEDUCTIONS ALREADY MAXIMISED:`);

  console.log(`
  ✓ Cash Withdrawals → Stock Purchases (${cashWithdrawals.length} items, S$${cashWithdrawals.reduce((s, t) => s + (t.withdrawal ?? 0), 0).toLocaleString("en-SG", { minimumFractionDigits: 2 })})
    Claimed at 100%. Maintain a petty cash log with receipts as supporting evidence.`);

  console.log(`
  ✓ Meals → Staff Entertainment (${mealsItems.length} items, S$${mealsItems.reduce((s, t) => s + (t.withdrawal ?? 0), 0).toLocaleString("en-SG", { minimumFractionDigits: 2 })})
    Claimed at 100% as staff welfare. Keep attendance records for each event.`);

  console.log(`
  ✓ ZARA → Staff Uniforms
    Reclassified as deductible office supplies / uniforms.`);

  if (personalItems.length > 0) {
    console.log(`
  NON-DEDUCTIBLE (${personalItems.length} items, S$${personalItems.reduce((s, t) => s + (t.withdrawal ?? 0), 0).toLocaleString("en-SG", { minimumFractionDigits: 2 })}):
    Corporate income tax payment — correctly non-deductible under S15(1)(d).`);
  }

  if (uncategorised.length > 0) {
    console.log(`
  STILL UNCATEGORISED (${uncategorised.length} items, S$${uncategorised.reduce((s, t) => s + (t.withdrawal ?? 0), 0).toLocaleString("en-SG", { minimumFractionDigits: 2 })}):
    Review and assign a category to claim any eligible deductions.`);
  }

  // Final totals
  const totalDeductions2024 = allTransactions.filter((t) => t.year === 2024).reduce((s, t) => s + t.deductionAmount, 0);
  const totalDeductions2025 = allTransactions.filter((t) => t.year === 2025).reduce((s, t) => s + t.deductionAmount, 0);
  console.log(`
  TOTAL DEDUCTIONS CLAIMED:
    YA2025 (FY2024):  S$${totalDeductions2024.toLocaleString("en-SG", { minimumFractionDigits: 2 })}
    YA2026 (FY2025):  S$${totalDeductions2025.toLocaleString("en-SG", { minimumFractionDigits: 2 })}
    Combined:         S$${(totalDeductions2024 + totalDeductions2025).toLocaleString("en-SG", { minimumFractionDigits: 2 })}`);

  // Write JSON output
  const outputPath = "/Users/user/Downloads/c-s/tax-categorisation-output.json";
  fs.writeFileSync(outputPath, JSON.stringify({
    company: "CRAELL PTE. LTD.",
    account: "601483548001",
    generatedAt: new Date().toISOString(),
    transactions: allTransactions,
    summary: {
      2024: buildYearSummary(allTransactions, 2024),
      2025: buildYearSummary(allTransactions, 2025),
    },
  }, null, 2));

  console.log(`\n  Full data written to: ${outputPath}`);
  console.log(`  Total transactions processed: ${allTransactions.length}`);
  console.log();
}

function buildYearSummary(txns: Transaction[], year: number) {
  const yearTxns = txns.filter((t) => t.year === year);
  const totalDeposits = yearTxns.reduce((s, t) => s + (t.deposit ?? 0), 0);
  const totalWithdrawals = yearTxns.reduce((s, t) => s + (t.withdrawal ?? 0), 0);
  const totalDeductions = yearTxns.reduce((s, t) => s + t.deductionAmount, 0);

  const byCategory: Record<string, { count: number; withdrawal: number; deposit: number; deduction: number }> = {};
  for (const t of yearTxns) {
    if (!byCategory[t.category]) byCategory[t.category] = { count: 0, withdrawal: 0, deposit: 0, deduction: 0 };
    byCategory[t.category].count++;
    byCategory[t.category].withdrawal += t.withdrawal ?? 0;
    byCategory[t.category].deposit += t.deposit ?? 0;
    byCategory[t.category].deduction += t.deductionAmount;
  }

  return { totalDeposits, totalWithdrawals, totalDeductions, transactionCount: yearTxns.length, byCategory };
}

main().catch(console.error);
