import path from "node:path";
import { fileURLToPath } from "node:url";

import { migrate } from "drizzle-orm/better-sqlite3/migrator";

import { createDatabase, type TaxDatabase } from "./client";

const currentDir = path.dirname(fileURLToPath(import.meta.url));

export const DEFAULT_MIGRATIONS_PATH = path.resolve(currentDir, "../migrations");

export function migrateDatabase(db: TaxDatabase, migrationsFolder = DEFAULT_MIGRATIONS_PATH): void {
  migrate(db, { migrationsFolder });
}

export function migrateDatabaseAtPath(databasePath?: string): ReturnType<typeof createDatabase> {
  const instance = createDatabase(databasePath);
  migrateDatabase(instance.db);
  return instance;
}
