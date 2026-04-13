import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";

import { autoCategoriseTransactions, bankStatements, transactions, type TaxDatabase } from "@tax-build/db";
import { and, eq } from "drizzle-orm";

import { parseStatement } from "./statement";
import type { ImportStatementSummary } from "./types";
import { computeFileHash } from "./utils";

function makeId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID()}`;
}

export async function importStatement(
  db: TaxDatabase,
  companyId: string,
  filePath: string,
  bankName?: string,
  accountNumber?: string
): Promise<ImportStatementSummary> {
  const fileData = await fs.readFile(filePath);
  const fileHash = computeFileHash(fileData);
  const existingStatement = db
    .select({ statementId: bankStatements.statementId })
    .from(bankStatements)
    .where(and(eq(bankStatements.companyId, companyId), eq(bankStatements.fileHash, fileHash)))
    .get();

  if (existingStatement) {
    return {
      statementId: existingStatement.statementId,
      duplicate: true,
      rowsImported: 0,
      rowsSkipped: 0,
      warnings: [`Statement ${path.basename(filePath)} has already been imported for company ${companyId}.`],
      fileHash
    };
  }

  const parsedStatement = await parseStatement(fileData, {
    fileName: path.basename(filePath),
    bankName,
    accountNumber
  });
  const statementId = makeId("stmt");

  return db.transaction((tx) => {
    tx.insert(bankStatements)
      .values({
        statementId,
        companyId,
        bankName: parsedStatement.bankName,
        accountNumber: parsedStatement.accountNumber,
        statementDate: parsedStatement.statementDate,
        fileName: path.basename(filePath),
        fileHash
      })
      .run();

    if (parsedStatement.transactions.length > 0) {
      tx.insert(transactions)
        .values(
          parsedStatement.transactions.map((transaction) => ({
            transactionId: makeId("txn"),
            statementId,
            companyId,
            date: transaction.date,
            description: transaction.description,
            reference: transaction.reference ?? null,
            debit: transaction.debit ?? null,
            credit: transaction.credit ?? null,
            balance: transaction.balance ?? null
          }))
        )
        .run();

      autoCategoriseTransactions(tx as TaxDatabase, { statementId, onlyUncategorised: true });
    }

    return {
      statementId,
      duplicate: false,
      rowsImported: parsedStatement.transactions.length,
      rowsSkipped: parsedStatement.warnings.length,
      warnings: parsedStatement.warnings,
      fileHash,
      bankName: parsedStatement.bankName,
      accountNumber: parsedStatement.accountNumber,
      statementDate: parsedStatement.statementDate
    };
  });
}