import { eq } from "drizzle-orm";

import type { TaxDatabase } from "./client";
import { transactions, type Transaction } from "./schema";

type TransactionCategorisationInput = Pick<Transaction, "description" | "debit" | "credit" | "isTaxable">;
type StoredTransactionForCategorisation = Pick<
  Transaction,
  "transactionId" | "statementId" | "companyId" | "description" | "debit" | "credit" | "isTaxable" | "category" | "subcategory"
>;

export interface AutoCategorisationFilters {
  statementId?: string;
  companyId?: string;
  onlyUncategorised?: boolean;
}

const BANK_FEE_PATTERN = /(service charge|agent fee|bank charge|annual fee|late fee|finance charge|conversion fee|ccy conversion fee)/;
const TRANSFER_PATTERN = /(cash withdrawal|cash satm|cash wdl visa\/mcard|internal transfer|inter-account|own account|debit transfer case id)/;
const CAPITAL_PATTERN = /(laptop|computer|equipment|printer|renovation|furniture|server)/;
const NON_DEDUCTIBLE_PATTERN = /(fine|penalty|private|club|personal)/;

// Fine-grained expense patterns
const SALARY_PATTERN = /(salary|payroll|fast payment|fast transfer)/;
const INVENTORY_PATTERN = /(inventory|supplier|raw material|stock|purchase order|wholesale|wholesal|trading|handicraf|crystal|etsy|ebay|fabric|bhg|rachael|ji xiang|newecon|mix & match)/;
const TRANSPORT_PATTERN = /(taxi|grab|gojek|tada|comfort|citycab|bus\/mrt|mrt |jetstar|kiwi\.com|scoot|airasia)/;
const MEALS_PATTERN = /(restaurant|cafe|coffee|ramen|bakery|burger|mcdonald|kfc|subway|starbucks|butter studio|juice bar|bar & kitche|7-eleven|cheers|food|dining|sanpoutei|bk - |sergeant chick|honglu mi|costa choice)/;
const MEDICAL_PATTERN = /(clinic charges|medical|watsons|guardian|pharmacy)/;
const IT_SOFTWARE_PATTERN = /(software|canva|google cloud|paypal \*canva|saas|digital ocean|aws|heroku)/;
const UTILITIES_PATTERN = /(singtel|starhub|m1 |utility|electricity|water|gas|sp group)/;
const INSURANCE_PATTERN = /(insurance|prudential|aia |great eastern|aviva|ntuc income)/;
const OFFICE_PATTERN = /(office|stationery|printing|singpost|pos purchase|debit purchase)/;
const SUBSCRIPTION_PATTERN = /(subscription|membership|netflix|spotify)/;
const PROFESSIONAL_PATTERN = /(accounting|legal|audit|consultant|advisory)/;
const CREDIT_REVENUE_PATTERN = /(invoice|payment received|customer|sale|sales|stripe|shopify|receipt|paynow|fast payment|giro|ibg giro|interest|rebate|cash deposit|fund transfer)/;

function hasPositiveAmount(value?: number | null): value is number {
  return typeof value === "number" && value > 0;
}

export function suggestTransactionCategorisation(input: TransactionCategorisationInput): Pick<Transaction, "category" | "subcategory" | "isTaxable"> {
  const text = input.description.toLowerCase().replace(/\s+/g, " ").trim();
  const isDebit = hasPositiveAmount(input.debit);
  const isCredit = hasPositiveAmount(input.credit);

  if (BANK_FEE_PATTERN.test(text)) {
    return { category: "expense", subcategory: "bank_charges", isTaxable: input.isTaxable };
  }

  if (TRANSFER_PATTERN.test(text)) {
    return { category: "transfer", subcategory: null, isTaxable: false };
  }

  if (isDebit && CAPITAL_PATTERN.test(text)) {
    return { category: "expense", subcategory: "capital", isTaxable: input.isTaxable };
  }

  if (isDebit && NON_DEDUCTIBLE_PATTERN.test(text)) {
    return { category: "expense", subcategory: "non_deductible", isTaxable: input.isTaxable };
  }

  // Fine-grained expense matching (order matters — more specific first)
  if (isDebit && INVENTORY_PATTERN.test(text)) {
    return { category: "expense", subcategory: "inventory_cogs", isTaxable: input.isTaxable };
  }
  if (isDebit && SALARY_PATTERN.test(text)) {
    return { category: "expense", subcategory: "salary_wages", isTaxable: input.isTaxable };
  }
  if (isDebit && MEDICAL_PATTERN.test(text)) {
    return { category: "expense", subcategory: "medical_benefits", isTaxable: input.isTaxable };
  }
  if (isDebit && TRANSPORT_PATTERN.test(text)) {
    return { category: "expense", subcategory: "transport_travel", isTaxable: input.isTaxable };
  }
  if (isDebit && MEALS_PATTERN.test(text)) {
    return { category: "expense", subcategory: "meals_entertainment", isTaxable: input.isTaxable };
  }
  if (isDebit && IT_SOFTWARE_PATTERN.test(text)) {
    return { category: "expense", subcategory: "it_software", isTaxable: input.isTaxable };
  }
  if (isDebit && UTILITIES_PATTERN.test(text)) {
    return { category: "expense", subcategory: "utilities", isTaxable: input.isTaxable };
  }
  if (isDebit && INSURANCE_PATTERN.test(text)) {
    return { category: "expense", subcategory: "insurance", isTaxable: input.isTaxable };
  }
  if (isDebit && PROFESSIONAL_PATTERN.test(text)) {
    return { category: "expense", subcategory: "professional_fees", isTaxable: input.isTaxable };
  }
  if (isDebit && SUBSCRIPTION_PATTERN.test(text)) {
    return { category: "expense", subcategory: "subscriptions", isTaxable: input.isTaxable };
  }
  if (isDebit && OFFICE_PATTERN.test(text)) {
    return { category: "expense", subcategory: "office_supplies", isTaxable: input.isTaxable };
  }

  if (isCredit && CREDIT_REVENUE_PATTERN.test(text)) {
    return { category: "revenue", subcategory: null, isTaxable: input.isTaxable };
  }

  if (isCredit) {
    return { category: "revenue", subcategory: null, isTaxable: input.isTaxable };
  }

  if (isDebit) {
    return { category: "expense", subcategory: "office_supplies", isTaxable: input.isTaxable };
  }

  return { category: "other", subcategory: null, isTaxable: input.isTaxable };
}

export function autoCategoriseTransactions(db: TaxDatabase, filters: AutoCategorisationFilters = {}): number {
  const candidates = db
    .select({
      transactionId: transactions.transactionId,
      statementId: transactions.statementId,
      companyId: transactions.companyId,
      description: transactions.description,
      debit: transactions.debit,
      credit: transactions.credit,
      isTaxable: transactions.isTaxable,
      category: transactions.category,
      subcategory: transactions.subcategory
    })
    .from(transactions)
    .all() as StoredTransactionForCategorisation[];

  let updatedCount = 0;

  for (const transaction of candidates) {
    if (filters.statementId && transaction.statementId !== filters.statementId) {
      continue;
    }

    if (filters.companyId && transaction.companyId !== filters.companyId) {
      continue;
    }

    if (filters.onlyUncategorised && transaction.category !== "other") {
      continue;
    }

    const suggestion = suggestTransactionCategorisation(transaction);

    if (
      transaction.category === suggestion.category
      && (transaction.subcategory ?? null) === suggestion.subcategory
      && transaction.isTaxable === suggestion.isTaxable
    ) {
      continue;
    }

    db.update(transactions).set(suggestion).where(eq(transactions.transactionId, transaction.transactionId)).run();
    updatedCount += 1;
  }

  return updatedCount;
}