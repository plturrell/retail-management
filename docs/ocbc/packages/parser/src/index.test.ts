import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

import { bankStatements, companies, createDatabase, migrateDatabase, transactions } from "@tax-build/db";
import { eq } from "drizzle-orm";
import { afterEach, describe, expect, it, vi } from "vitest";

import { importStatement, parseAmount, parseCsvStatement, parseStatement } from "./index";
import { parseOcbcBusinessGrowthPages } from "./pdf";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const fixturesDir = path.resolve(currentDir, "../fixtures");
const tempDirectories: string[] = [];

function fixturePath(name: string): string {
  return path.join(fixturesDir, name);
}

afterEach(() => {
  vi.restoreAllMocks();

  while (tempDirectories.length > 0) {
    const dir = tempDirectories.pop();

    if (dir) {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  }
});

describe("amount parsing", () => {
  it("handles commas, decimal commas, and parentheses negatives", () => {
    expect(parseAmount("1,234.56")).toBe(1234.56);
    expect(parseAmount("1.234,56")).toBe(1234.56);
    expect(parseAmount("(8.50)")).toBe(-8.5);
  });
});

describe("CSV statement parsing", () => {
  it("parses DBS, OCBC, and UOB CSV fixtures", async () => {
    const dbs = await parseStatement(fixturePath("dbs.csv"));
    const ocbc = await parseStatement(fixturePath("ocbc.csv"));
    const uob = await parseStatement(fixturePath("uob.csv"));

    expect(dbs.bankName).toBe("DBS");
    expect(dbs.transactions[0]).toMatchObject({
      date: "2026-01-05",
      description: "GIRO PAYMENT NETFLIX SG",
      reference: "DBSREF001",
      debit: 17.98,
      balance: 4982.02
    });
    expect(dbs.transactions[1]?.credit).toBe(3200);

    expect(ocbc.bankName).toBe("OCBC");
    expect(ocbc.transactions[0]).toMatchObject({
      date: "2026-01-07",
      debit: 150,
      balance: 7850
    });
    expect(ocbc.transactions[1]?.credit).toBe(2500);

    expect(uob.bankName).toBe("UOB");
    expect(uob.transactions[0]).toMatchObject({
      date: "2026-01-09",
      debit: 8.5,
      balance: 1991.5
    });
    expect(uob.transactions[1]?.credit).toBe(850);
  });

  it("supports buffer input and warns on malformed rows", () => {
    const malformedCsv = [
      "Transaction Date,Description,Reference,Debit,Credit,Balance",
      'bad-date,BROKEN ROW,REF001,10.00,,"90.00"',
      '05 Jan 2026,VALID ROW,REF002,5.00,,"85.00"'
    ].join("\n");

    const parsed = parseCsvStatement(malformedCsv, { bankName: "DBS" });

    expect(parsed.transactions).toHaveLength(1);
    expect(parsed.transactions[0]?.description).toBe("VALID ROW");
    expect(parsed.warnings).toHaveLength(1);
  });
});

describe("PDF statement parsing", () => {
  it("parses DBS, OCBC, and UOB PDF fixtures", async () => {
    const dbs = await parseStatement(fixturePath("dbs.pdf"));
    const ocbc = await parseStatement(fixturePath("ocbc.pdf"));
    const uob = await parseStatement(fixturePath("uob.pdf"));

    expect(dbs.format).toBe("pdf");
    expect(dbs.accountNumber).toBe("123-456789-01");
    expect(dbs.transactions).toHaveLength(2);

    expect(ocbc.bankName).toBe("OCBC");
    expect(ocbc.accountNumber).toBe("76543210");
    expect(ocbc.transactions[1]).toMatchObject({ reference: "OCBC002", credit: 2500 });

    expect(uob.bankName).toBe("UOB");
    expect(uob.accountNumber).toBe("11223344");
    expect(uob.transactions[0]).toMatchObject({ reference: "UOB001", debit: 8.5 });
  });

  it("parses real-style OCBC business growth account page text", () => {
    const parsed = parseOcbcBusinessGrowthPages([
      [
        "STATEMENT OF ACCOUNT",
        "BUSINESS GROWTH ACCOUNT",
        "Account No. 601483548001",
        "1 JAN 2024 TO 31 JAN 2024",
        "6,951.39\tBALANCE B/F",
        "31 DEC 715.00 7,666.39\t02 JAN PAYMENT/TRANSFER",
        "OTHR S$",
        "AXYU PARAS SOH XIAN",
        "via PayNow:",
        "SG24123100664845180000",
        "02 JAN 1,000.00 6,666.39\t02 JAN CASH WITHDRAWAL ATM",
        "xx-9618 OCBC-TANG PLAZA",
        "S",
        "1,725.95\tBALANCE C/F",
        "Total Withdrawals/Deposits"
      ].join("\n"),
      "OCBC PROMOTION & INFORMATION"
    ]);

    expect(parsed?.accountNumber).toBe("601483548001");
    expect(parsed?.warnings).toEqual([]);
    expect(parsed?.transactions).toHaveLength(2);
    expect(parsed?.transactions[0]).toMatchObject({
      date: "2024-01-02",
      credit: 715,
      balance: 7666.39,
      reference: "SG24123100664845180000"
    });
    expect(parsed?.transactions[1]).toMatchObject({
      date: "2024-01-02",
      debit: 1000,
      balance: 6666.39
    });
  });
});

describe("statement importing", () => {
  it("imports transactions into the DB and skips duplicate files", async () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "tax-build-parser-"));
    tempDirectories.push(tempDir);

    const databasePath = path.join(tempDir, "parser.sqlite");
    const { db, sqlite } = createDatabase(databasePath);

    try {
      migrateDatabase(db);
      db.insert(companies)
        .values({
          companyId: "company_001",
          uen: "202412345A",
          name: "Acme Tax Pte. Ltd.",
          incorporationDate: "2024-01-15",
          financialYearStart: "2024-01-01",
          financialYearEnd: "2024-12-31",
          shareholderCount: 2,
          functionalCurrency: "SGD",
          isTaxResident: true
        })
        .run();

      const firstImport = await importStatement(
        db,
        "company_001",
        fixturePath("dbs.csv"),
        "DBS",
        "123-CSV-001"
      );
      const secondImport = await importStatement(
        db,
        "company_001",
        fixturePath("dbs.csv"),
        "DBS",
        "123-CSV-001"
      );

      expect(firstImport.duplicate).toBe(false);
      expect(firstImport.rowsImported).toBe(2);
      expect(secondImport.duplicate).toBe(true);
      expect(secondImport.statementId).toBe(firstImport.statementId);

      const storedStatement = db.select().from(bankStatements).get();
      const storedTransactions = db
        .select()
        .from(transactions)
        .where(eq(transactions.statementId, firstImport.statementId!))
        .all();

      expect(storedStatement?.accountNumber).toBe("123-CSV-001");
      expect(storedTransactions).toHaveLength(2);
      expect(storedTransactions[0]?.description).toBe("GIRO PAYMENT NETFLIX SG");
      expect(storedTransactions[0]).toMatchObject({ category: "expense", subcategory: "operating_expense" });
      expect(storedTransactions[1]).toMatchObject({ category: "revenue", subcategory: null });
    } finally {
      sqlite.close();
    }
  });

  it("rolls back the statement insert when transaction insertion fails", async () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "tax-build-parser-"));
    tempDirectories.push(tempDir);

    const databasePath = path.join(tempDir, "parser.sqlite");
    const { db, sqlite } = createDatabase(databasePath);

    try {
      migrateDatabase(db);
      db.insert(companies)
        .values({
          companyId: "company_001",
          uen: "202412345A",
          name: "Acme Tax Pte. Ltd.",
          incorporationDate: "2024-01-15",
          financialYearStart: "2024-01-01",
          financialYearEnd: "2024-12-31",
          shareholderCount: 2,
          functionalCurrency: "SGD",
          isTaxResident: true
        })
        .run();

      const ids = ["statement-id", "duplicate-id", "duplicate-id"];
      vi.spyOn(crypto, "randomUUID").mockImplementation(() => ids.shift() ?? "fallback-id");

      await expect(importStatement(db, "company_001", fixturePath("dbs.csv"), "DBS", "123-CSV-001")).rejects.toThrow();

      expect(db.select().from(bankStatements).all()).toHaveLength(0);
      expect(db.select().from(transactions).all()).toHaveLength(0);
    } finally {
      sqlite.close();
    }
  });
});