import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import BetterSqlite3 from "better-sqlite3";
import { drizzle, type BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import { migrate } from "drizzle-orm/better-sqlite3/migrator";

import * as schema from "@tax-build/db/schema";

const appRoot = process.cwd();
const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, "../../../../");
const migrationsPath = path.resolve(repoRoot, "packages/db/migrations");
const defaultDatabasePath = path.resolve(repoRoot, "packages/db/dev.sqlite");

interface WebDatabaseInstance {
  sqlite: InstanceType<typeof BetterSqlite3>;
  db: BetterSQLite3Database<typeof schema>;
}

declare global {
  var __taxBuildWebDatabase: WebDatabaseInstance | undefined;
  var __taxBuildWebDatabasePath: string | undefined;
  var __taxBuildWebDatabaseReady: boolean | undefined;
}

function resolveDatabasePath() {
  const configuredPath = process.env.TAX_BUILD_DB_PATH;

  if (!configuredPath) {
    return defaultDatabasePath;
  }

  return path.isAbsolute(configuredPath) ? configuredPath : path.resolve(appRoot, configuredPath);
}

export function getWebDatabase() {
  const databasePath = resolveDatabasePath();

  if (globalThis.__taxBuildWebDatabase && globalThis.__taxBuildWebDatabasePath !== databasePath) {
    globalThis.__taxBuildWebDatabase.sqlite.close();
    globalThis.__taxBuildWebDatabase = undefined;
    globalThis.__taxBuildWebDatabaseReady = undefined;
  }

  if (!globalThis.__taxBuildWebDatabase) {
    fs.mkdirSync(path.dirname(databasePath), { recursive: true });

    const sqlite = new BetterSqlite3(databasePath);
    sqlite.pragma("foreign_keys = ON");
    sqlite.pragma("journal_mode = WAL");

    globalThis.__taxBuildWebDatabase = {
      sqlite,
      db: drizzle(sqlite, { schema })
    };
    globalThis.__taxBuildWebDatabasePath = databasePath;
  }

  if (!globalThis.__taxBuildWebDatabaseReady) {
    migrate(globalThis.__taxBuildWebDatabase.db, { migrationsFolder: migrationsPath });
    globalThis.__taxBuildWebDatabaseReady = true;
  }

  return globalThis.__taxBuildWebDatabase;
}

export function getWebDbPath() {
  return resolveDatabasePath();
}

export function resetWebDatabaseForTests() {
  if (globalThis.__taxBuildWebDatabase) {
    globalThis.__taxBuildWebDatabase.sqlite.close();
  }

  globalThis.__taxBuildWebDatabase = undefined;
  globalThis.__taxBuildWebDatabasePath = undefined;
  globalThis.__taxBuildWebDatabaseReady = undefined;
}