import { relations, sql } from "drizzle-orm";
import { integer, real, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const transactionCategories = ["revenue", "expense", "transfer", "other"] as const;
export const summaryStatuses = ["draft", "filed"] as const;
export const adjustmentTypes = ["add_back", "deduct"] as const;
export const adjustmentCategories = [
  "non_deductible",
  "non_taxable",
  "capital_allowance",
  "donation",
  "loss_brought_forward",
  "other"
] as const;

export const companies = sqliteTable(
  "companies",
  {
    companyId: text("company_id").primaryKey(),
    uen: text("uen").notNull(),
    name: text("name").notNull(),
    incorporationDate: text("incorporation_date").notNull(),
    financialYearStart: text("financial_year_start").notNull(),
    financialYearEnd: text("financial_year_end").notNull(),
    isTaxResident: integer("is_tax_resident", { mode: "boolean" }).notNull().default(true),
    shareholderCount: integer("shareholder_count").notNull(),
    functionalCurrency: text("functional_currency").notNull().default("SGD"),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`)
  },
  (table) => ({
    uenIdx: uniqueIndex("companies_uen_unique").on(table.uen)
  })
);

export const bankStatements = sqliteTable("bank_statements", {
  statementId: text("statement_id").primaryKey(),
  companyId: text("company_id")
    .notNull()
    .references(() => companies.companyId, { onDelete: "cascade" }),
  bankName: text("bank_name").notNull(),
  accountNumber: text("account_number").notNull(),
  statementDate: text("statement_date").notNull(),
  fileName: text("file_name").notNull(),
  fileHash: text("file_hash").notNull(),
  importedAt: text("imported_at").notNull().default(sql`CURRENT_TIMESTAMP`)
});

export const transactions = sqliteTable("transactions", {
  transactionId: text("transaction_id").primaryKey(),
  statementId: text("statement_id")
    .notNull()
    .references(() => bankStatements.statementId, { onDelete: "cascade" }),
  companyId: text("company_id")
    .notNull()
    .references(() => companies.companyId, { onDelete: "cascade" }),
  date: text("date").notNull(),
  description: text("description").notNull(),
  reference: text("reference"),
  debit: real("debit"),
  credit: real("credit"),
  balance: real("balance"),
  category: text("category", { enum: transactionCategories }).notNull().default("other"),
  subcategory: text("subcategory"),
  isTaxable: integer("is_taxable", { mode: "boolean" }).notNull().default(true),
  notes: text("notes"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`)
});

export const financialSummaries = sqliteTable("financial_summaries", {
  summaryId: text("summary_id").primaryKey(),
  companyId: text("company_id")
    .notNull()
    .references(() => companies.companyId, { onDelete: "cascade" }),
  yaYear: integer("ya_year").notNull(),
  totalRevenue: real("total_revenue").notNull().default(0),
  totalExpenses: real("total_expenses").notNull().default(0),
  netProfitLoss: real("net_profit_loss").notNull().default(0),
  adjustedProfitLoss: real("adjusted_profit_loss").notNull().default(0),
  chargeableIncome: real("chargeable_income").notNull().default(0),
  taxPayable: real("tax_payable").notNull().default(0),
  exemptAmount: real("exempt_amount").notNull().default(0),
  rebateAmount: real("rebate_amount").notNull().default(0),
  status: text("status", { enum: summaryStatuses }).notNull().default("draft"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`)
});

export const taxAdjustments = sqliteTable("tax_adjustments", {
  adjustmentId: text("adjustment_id").primaryKey(),
  summaryId: text("summary_id")
    .notNull()
    .references(() => financialSummaries.summaryId, { onDelete: "cascade" }),
  description: text("description").notNull(),
  amount: real("amount").notNull(),
  adjustmentType: text("adjustment_type", { enum: adjustmentTypes }).notNull(),
  category: text("category", { enum: adjustmentCategories }).notNull().default("other")
});

export const companyRelations = relations(companies, ({ many }) => ({
  bankStatements: many(bankStatements),
  transactions: many(transactions),
  financialSummaries: many(financialSummaries)
}));

export const bankStatementRelations = relations(bankStatements, ({ one, many }) => ({
  company: one(companies, {
    fields: [bankStatements.companyId],
    references: [companies.companyId]
  }),
  transactions: many(transactions)
}));

export const transactionRelations = relations(transactions, ({ one }) => ({
  bankStatement: one(bankStatements, {
    fields: [transactions.statementId],
    references: [bankStatements.statementId]
  }),
  company: one(companies, {
    fields: [transactions.companyId],
    references: [companies.companyId]
  })
}));

export const financialSummaryRelations = relations(financialSummaries, ({ one, many }) => ({
  company: one(companies, {
    fields: [financialSummaries.companyId],
    references: [companies.companyId]
  }),
  taxAdjustments: many(taxAdjustments)
}));

export const taxAdjustmentRelations = relations(taxAdjustments, ({ one }) => ({
  financialSummary: one(financialSummaries, {
    fields: [taxAdjustments.summaryId],
    references: [financialSummaries.summaryId]
  })
}));

export type Company = typeof companies.$inferSelect;
export type NewCompany = typeof companies.$inferInsert;
export type BankStatement = typeof bankStatements.$inferSelect;
export type NewBankStatement = typeof bankStatements.$inferInsert;
export type Transaction = typeof transactions.$inferSelect;
export type NewTransaction = typeof transactions.$inferInsert;
export type FinancialSummary = typeof financialSummaries.$inferSelect;
export type NewFinancialSummary = typeof financialSummaries.$inferInsert;
export type TaxAdjustment = typeof taxAdjustments.$inferSelect;
export type NewTaxAdjustment = typeof taxAdjustments.$inferInsert;
