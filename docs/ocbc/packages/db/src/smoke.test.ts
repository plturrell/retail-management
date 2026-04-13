import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { eq } from "drizzle-orm";
import { afterEach, describe, expect, it } from "vitest";

import { companies, createDatabase, migrateDatabase } from "./index";

const tempDirectories: string[] = [];

afterEach(() => {
  while (tempDirectories.length > 0) {
    const dir = tempDirectories.pop();

    if (dir) {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  }
});

describe("database smoke test", () => {
  it("creates the schema, inserts a company, and reads it back", () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "tax-build-db-"));
    tempDirectories.push(tempDir);

    const databasePath = path.join(tempDir, "smoke.sqlite");
    const { db, sqlite } = createDatabase(databasePath);

    try {
      migrateDatabase(db);

      db.insert(companies).values({
        companyId: "company_001",
        uen: "202412345A",
        name: "Acme Tax Pte. Ltd.",
        incorporationDate: "2024-01-15",
        financialYearStart: "2024-01-01",
        financialYearEnd: "2024-12-31",
        shareholderCount: 2,
        functionalCurrency: "SGD",
        isTaxResident: true
      }).run();

      const company = db.select().from(companies).where(eq(companies.companyId, "company_001")).get();

      expect(company).toBeDefined();
      expect(company?.uen).toBe("202412345A");
      expect(company?.name).toBe("Acme Tax Pte. Ltd.");
      expect(company?.functionalCurrency).toBe("SGD");
    } finally {
      sqlite.close();
    }
  });
});
