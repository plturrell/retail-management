import path from "node:path";

import { autoCategoriseTransactions, createDatabase, migrateDatabase } from "../index";

const databasePath = path.resolve(process.cwd(), process.argv[2] ?? "dev.sqlite");

const { db, sqlite } = createDatabase(databasePath);

try {
  migrateDatabase(db);
  const updatedCount = autoCategoriseTransactions(db, { onlyUncategorised: true });

  console.log(`Auto-categorised ${updatedCount} transaction(s) in ${databasePath}`);
} finally {
  sqlite.close();
}