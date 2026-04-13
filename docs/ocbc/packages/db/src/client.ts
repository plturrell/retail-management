import fs from "node:fs";
import path from "node:path";

import BetterSqlite3 from "better-sqlite3";
import { drizzle, type BetterSQLite3Database } from "drizzle-orm/better-sqlite3";

import * as schema from "./schema";

export type SqliteClient = InstanceType<typeof BetterSqlite3>;
export type TaxDatabase = BetterSQLite3Database<typeof schema>;

export interface DatabaseInstance {
  sqlite: SqliteClient;
  db: TaxDatabase;
}

export const DEFAULT_DATABASE_PATH = path.resolve(process.cwd(), "dev.sqlite");

export function createDatabase(databasePath = DEFAULT_DATABASE_PATH): DatabaseInstance {
  fs.mkdirSync(path.dirname(databasePath), { recursive: true });

  const sqlite = new BetterSqlite3(databasePath);
  sqlite.pragma("foreign_keys = ON");
  sqlite.pragma("journal_mode = WAL");

  return {
    sqlite,
    db: drizzle(sqlite, { schema })
  };
}

let defaultInstance: DatabaseInstance | undefined;

export function getDefaultDatabase(): DatabaseInstance {
  defaultInstance ??= createDatabase();
  return defaultInstance;
}

export function getDbClient(): TaxDatabase {
  return getDefaultDatabase().db;
}

export function closeDefaultDatabase(): void {
  if (!defaultInstance) {
    return;
  }

  defaultInstance.sqlite.close();
  defaultInstance = undefined;
}
