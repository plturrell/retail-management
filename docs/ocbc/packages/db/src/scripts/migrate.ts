import { migrateDatabaseAtPath } from "../migrate";

const instance = migrateDatabaseAtPath(process.env.TAX_BUILD_DB_PATH);

instance.sqlite.close();
console.log(`Applied migrations to ${process.env.TAX_BUILD_DB_PATH ?? "dev.sqlite"}.`);
