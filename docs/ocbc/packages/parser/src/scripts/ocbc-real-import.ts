import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { companies, createDatabase, migrateDatabase } from "@tax-build/db";
import { eq } from "drizzle-orm";

import { importStatement, parseStatement } from "../index";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, "../../../..");
const defaultDatabasePath = path.resolve(repoRoot, "packages/db/dev.sqlite");

const defaultStatementDirectories = [
  "/Users/user/Downloads/c-s/2023",
  "/Users/user/Downloads/c-s/2024",
  "/Users/user/Downloads/c-s/2025"
];

const monthOrder = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const companyId = "company_ocbc_real_statements";

function formatAmount(value: number): string {
  return value.toFixed(2);
}

function sortStatementFiles(left: string, right: string): number {
  const leftMatch = path.basename(left).match(/-(?<month>[A-Za-z]{3})-(?<year>\d{2})(?: \d+)?\.pdf$/);
  const rightMatch = path.basename(right).match(/-(?<month>[A-Za-z]{3})-(?<year>\d{2})(?: \d+)?\.pdf$/);

  if (!leftMatch?.groups || !rightMatch?.groups) {
    return left.localeCompare(right);
  }

  const leftYear = Number(leftMatch.groups.year);
  const rightYear = Number(rightMatch.groups.year);

  if (leftYear !== rightYear) {
    return leftYear - rightYear;
  }

  return monthOrder.indexOf(leftMatch.groups.month) - monthOrder.indexOf(rightMatch.groups.month);
}

async function collectStatementFiles(): Promise<string[]> {
  const files = await Promise.all(
    defaultStatementDirectories.map(async (directory) => {
      const entries = await fs.readdir(directory);

      return entries
        .filter((entry) => /^BUSINESS GROWTH ACCOUNT-8001-[A-Za-z]{3}-\d{2}(?: \d+)?\.pdf$/.test(entry))
        .map((entry) => path.join(directory, entry));
    })
  );

  return files.flat().sort(sortStatementFiles);
}

function ensureCompanyRecord(db: ReturnType<typeof createDatabase>["db"]) {
  const existingCompany = db
    .select({ companyId: companies.companyId })
    .from(companies)
    .where(eq(companies.companyId, companyId))
    .get();

  if (existingCompany) {
    return;
  }

  db.insert(companies)
    .values({
      companyId,
      uen: "OCBC-REAL-0001",
      name: "CRAELL PTE. LTD.",
      incorporationDate: "2024-01-01",
      financialYearStart: "2024-01-01",
      financialYearEnd: "2024-12-31",
      shareholderCount: 1,
      functionalCurrency: "SGD",
      isTaxResident: true
    })
    .run();
}

async function main() {
  const files = await collectStatementFiles();

  if (files.length !== 36) {
    throw new Error(`Expected 36 OCBC PDF statements, found ${files.length}.`);
  }

  const { db, sqlite } = createDatabase(defaultDatabasePath);

  try {
    migrateDatabase(db);
    ensureCompanyRecord(db);

    console.log(`Importing ${files.length} OCBC statement(s) into ${defaultDatabasePath}`);
    console.log(`Company ID: ${companyId}`);

    for (const filePath of files) {
      const parsed = await parseStatement(filePath, { bankName: "OCBC" });
      const totalDebits = parsed.transactions.reduce((sum, transaction) => sum + (transaction.debit ?? 0), 0);
      const totalCredits = parsed.transactions.reduce((sum, transaction) => sum + (transaction.credit ?? 0), 0);
      const imported = await importStatement(db, companyId, filePath, "OCBC");

      console.log(
        [
          path.basename(filePath),
          `transactions=${parsed.transactions.length}`,
          `debits=${formatAmount(totalDebits)}`,
          `credits=${formatAmount(totalCredits)}`,
          `warnings=${parsed.warnings.length}`,
          `duplicate=${imported.duplicate}`
        ].join(" | ")
      );

      for (const warning of parsed.warnings) {
        console.log(`  warning: ${warning}`);
      }
    }
  } finally {
    sqlite.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : error);
  process.exit(1);
});