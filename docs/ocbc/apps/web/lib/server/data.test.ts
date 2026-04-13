import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resetWebDatabaseForTests } from "./db";
import { getComputationSnapshot, getFilteredTransactions, getStatementsOverview, importStatementUpload, saveCompanyRecord } from "./data";

const tempDatabasePath = path.join(os.tmpdir(), `tax-build-web-${process.pid}.sqlite`);

describe("web data integration", () => {
  beforeEach(async () => {
    process.env.TAX_BUILD_DB_PATH = tempDatabasePath;
    resetWebDatabaseForTests();
    await fs.rm(tempDatabasePath, { force: true });
  });

  afterEach(async () => {
    resetWebDatabaseForTests();
    await fs.rm(tempDatabasePath, { force: true });
    delete process.env.TAX_BUILD_DB_PATH;
  });

  it("imports transactions into SQLite and computes a YA snapshot", async () => {
    const companyId = await saveCompanyRecord({
      uen: "202400001A",
      name: "Acme Pte Ltd",
      incorporationDate: "2024-01-15",
      financialYearStart: "2024-01-01",
      financialYearEnd: "2024-12-31",
      shareholderCount: 2,
      isTaxResident: true
    });

    const csv = [
      "Transaction Date,Description,Reference,Debit,Credit,Balance",
      '05 Jan 2024,SOFTWARE SUBSCRIPTION NETFLIX SG,DBSREF001,17.98,,"4,982.02"',
      '06 Jan 2024,STRIPE CUSTOMER PAYMENT,DBSREF002,,3200.00,"8,182.02"'
    ].join("\n");

    const summary = await importStatementUpload({
      companyId,
      bankName: "DBS",
      file: new File([csv], "dbs.csv", { type: "text/csv" })
    });

    expect(summary.rowsImported).toBe(2);
    expect(getStatementsOverview(companyId)).toHaveLength(1);

    const filtered = getFilteredTransactions({ companyId, yaYear: 2025, category: "all", taxability: "all" });
    expect(filtered.transactions).toHaveLength(2);

    const snapshot = getComputationSnapshot(companyId, 2025);
    expect(snapshot?.summary.totalRevenue).toBe(3200);
    expect(snapshot?.summary.totalExpenses).toBe(17.98);
    expect(snapshot?.result.taxPayable).toBeGreaterThan(0);
  });
});