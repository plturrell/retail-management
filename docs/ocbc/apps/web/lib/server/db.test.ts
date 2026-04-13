import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import { getWebDbPath } from "./db";

const originalDatabasePath = process.env.TAX_BUILD_DB_PATH;
const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, "../../../../");

afterEach(() => {
  if (originalDatabasePath === undefined) {
    delete process.env.TAX_BUILD_DB_PATH;
    return;
  }

  process.env.TAX_BUILD_DB_PATH = originalDatabasePath;
});

describe("web database path", () => {
  it("defaults to the shared workspace database", () => {
    delete process.env.TAX_BUILD_DB_PATH;

    expect(getWebDbPath()).toBe(path.resolve(repoRoot, "packages/db/dev.sqlite"));
  });

  it("still honours the TAX_BUILD_DB_PATH override", () => {
    process.env.TAX_BUILD_DB_PATH = "./tmp/custom.sqlite";

    expect(getWebDbPath()).toBe(path.resolve(process.cwd(), "./tmp/custom.sqlite"));
  });
});