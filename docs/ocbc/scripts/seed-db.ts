import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import BetterSqlite3 from "better-sqlite3";

import { bankStatements, companies, transactions, type NewBankStatement, type NewCompany, type NewTransaction } from "@tax-build/db/schema";

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

interface CategorisedTransaction {
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

interface CategorisationFile {
  company: string;
  account: string;
  generatedAt: string;
  transactions: CategorisedTransaction[];
}

function loadCategorisation(filePath: string): CategorisationFile {
  const raw = fs.readFileSync(filePath, "utf8");
  return JSON.parse(raw) as CategorisationFile;
}

function mapTaxCategoryToDb(category: TaxCategory): { dbCategory: "revenue" | "expense" | "transfer" | "other"; subcategory: string | null } {
  switch (category) {
    case "revenue":
      return { dbCategory: "revenue", subcategory: null };
    case "salary_wages":
      return { dbCategory: "expense", subcategory: "salary_wages" };
    case "contractor_payments":
      return { dbCategory: "expense", subcategory: "contractor_payments" };
    case "inventory_cogs":
      return { dbCategory: "expense", subcategory: "inventory_cogs" };
    case "cash_withdrawal":
      return { dbCategory: "expense", subcategory: "cash_withdrawal" };
    case "bank_charges":
      return { dbCategory: "expense", subcategory: "bank_charges" };
    case "transport_travel":
      return { dbCategory: "expense", subcategory: "transport_travel" };
    case "meals_entertainment":
      return { dbCategory: "expense", subcategory: "meals_entertainment" };
    case "office_supplies":
      return { dbCategory: "expense", subcategory: "office_supplies" };
    case "it_software":
      return { dbCategory: "expense", subcategory: "it_software" };
    case "utilities":
      return { dbCategory: "expense", subcategory: "utilities" };
    case "medical_benefits":
      return { dbCategory: "expense", subcategory: "medical_benefits" };
    case "insurance":
      return { dbCategory: "expense", subcategory: "insurance" };
    case "professional_fees":
      return { dbCategory: "expense", subcategory: "professional_fees" };
    case "subscriptions":
      return { dbCategory: "expense", subcategory: "subscriptions" };
    case "repairs_maintenance":
      return { dbCategory: "expense", subcategory: "repairs_maintenance" };
    case "training_development":
      return { dbCategory: "expense", subcategory: "training_development" };
    case "cpf_contributions":
      return { dbCategory: "expense", subcategory: "cpf_contributions" };
    case "personal_non_deductible":
      return { dbCategory: "expense", subcategory: "non_deductible" };
    case "capital_expenditure":
      return { dbCategory: "expense", subcategory: "capital" };
    case "transfer_internal":
    case "loan_repayment":
      return { dbCategory: "transfer", subcategory: null };
    default:
      return { dbCategory: "other", subcategory: null };
  }
}

function getDatabasePath(): string {
  const currentFile = fileURLToPath(import.meta.url);
  const currentDir = path.dirname(currentFile);
  const repoRoot = path.resolve(currentDir, "..");
  const defaultDatabasePath = path.resolve(repoRoot, "packages/db/dev.sqlite");
  const configuredPath = process.env.TAX_BUILD_DB_PATH;

  if (!configuredPath) {
    return defaultDatabasePath;
  }

  return path.isAbsolute(configuredPath) ? configuredPath : path.resolve(repoRoot, configuredPath);
}

async function main() {
  const currentFile = fileURLToPath(import.meta.url);
  const currentDir = path.dirname(currentFile);
  const repoRoot = path.resolve(currentDir, "..");
  const jsonPath = path.resolve(repoRoot, "tax-categorisation-output.json");

  if (!fs.existsSync(jsonPath)) {
    throw new Error(`Cannot find categorisation output at ${jsonPath}`);
  }

  const data = loadCategorisation(jsonPath);
  const databasePath = getDatabasePath();

  console.log(`Using database at: ${databasePath}`);

  fs.mkdirSync(path.dirname(databasePath), { recursive: true });

  const sqlite = new BetterSqlite3(databasePath);

  try {
    sqlite.pragma("foreign_keys = ON");
    sqlite.pragma("journal_mode = WAL");

    const tx = sqlite.transaction(() => {
      // Upsert company
      const now = new Date().toISOString();
      const companyId = "company_craell";

      const upsertCompany = sqlite.prepare(
        "INSERT INTO companies (company_id, uen, name, incorporation_date, financial_year_start, financial_year_end, is_tax_resident, shareholder_count, functional_currency, created_at, updated_at) " +
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) " +
          "ON CONFLICT(company_id) DO UPDATE SET uen = excluded.uen, name = excluded.name, incorporation_date = excluded.incorporation_date, financial_year_start = excluded.financial_year_start, financial_year_end = excluded.financial_year_end, is_tax_resident = excluded.is_tax_resident, shareholder_count = excluded.shareholder_count, functional_currency = excluded.functional_currency, updated_at = excluded.updated_at"
      );

      const incorporationYear = 2016;

      upsertCompany.run(
        companyId,
        "201620817G",
        "CRAELL PTE. LTD.",
        `${incorporationYear}-01-01`,
        "2024-01-01",
        "2024-12-31",
        1,
        1,
        "SGD",
        now,
        now
      );

      // Group by source (PDF file) to create bank statements
      const groupedBySource = new Map<string, CategorisedTransaction[]>();

      for (const txn of data.transactions) {
        const key = txn.source;
        const list = groupedBySource.get(key) ?? [];
        list.push(txn);
        groupedBySource.set(key, list);
      }

      const insertStatement = sqlite.prepare(
        "INSERT INTO bank_statements (statement_id, company_id, bank_name, account_number, statement_date, file_name, file_hash, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
      );
      const insertTransaction = sqlite.prepare(
        "INSERT INTO transactions (transaction_id, statement_id, company_id, date, description, reference, debit, credit, balance, category, subcategory, is_taxable, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
      );

      for (const [source, txns] of groupedBySource.entries()) {
        if (txns.length === 0) continue;

        const sorted = [...txns].sort((a, b) => a.date.localeCompare(b.date));
        const last = sorted[sorted.length - 1];
        const statementId = `stmt_${source.replace(/[^a-zA-Z0-9]+/g, "_")}`;
        const fileName = source;
        const fileHash = "";

        const statement: NewBankStatement = {
          statementId,
          companyId,
          bankName: "OCBC",
          accountNumber: data.account,
          statementDate: last.date,
          fileName,
          fileHash,
          importedAt: now
        };

        insertStatement.run(
          statement.statementId,
          statement.companyId,
          statement.bankName,
          statement.accountNumber,
          statement.statementDate,
          statement.fileName,
          statement.fileHash,
          statement.importedAt
        );

        sorted.forEach((txn, index) => {
          const idSuffix = `${txn.date}_${Math.abs(txn.withdrawal ?? txn.deposit ?? 0)}_${index}`;
          const transactionId = `txn_${Buffer.from(idSuffix).toString("base64url")}`;
          const { dbCategory, subcategory } = mapTaxCategoryToDb(txn.category);

          const debit = txn.withdrawal ?? null;
          const credit = txn.deposit ?? null;
          const isTaxable = txn.category === "personal_non_deductible" ? 0 : 1;

          const row: NewTransaction = {
            transactionId,
            statementId,
            companyId,
            date: txn.date,
            description: txn.description,
            reference: null,
            debit: debit ?? undefined,
            credit: credit ?? undefined,
            balance: txn.balance,
            category: dbCategory,
            subcategory,
            isTaxable: Boolean(isTaxable),
            notes: null,
            createdAt: now
          };

          insertTransaction.run(
            row.transactionId,
            row.statementId,
            row.companyId,
            row.date,
            row.description,
            row.reference,
            row.debit ?? null,
            row.credit ?? null,
            row.balance ?? null,
            row.category,
            row.subcategory,
            row.isTaxable ? 1 : 0,
            row.notes,
            row.createdAt
          );
        });
      }
    });

    tx();

    console.log("Seed completed successfully.");
  } finally {
    sqlite.close();
  }
}

// eslint-disable-next-line unicorn/prefer-top-level-await
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

