import fs from "node:fs/promises";
import path from "node:path";

import { parseCsvStatement } from "./csv";
import { parsePdfStatement } from "./pdf";
import type { ParseStatementOptions, ParsedStatementDraft, StatementSource } from "./types";
import { computeFileHash, detectStatementFormat } from "./utils";

async function resolveStatementInput(
  input: StatementSource,
  fileName?: string
): Promise<{ data: Uint8Array; fileName?: string }> {
  if (typeof input === "string") {
    return {
      data: await fs.readFile(input),
      fileName: path.basename(input)
    };
  }

  return {
    data: input instanceof Uint8Array ? input : new Uint8Array(input),
    fileName
  };
}

export async function parseStatement(
  input: StatementSource,
  options: ParseStatementOptions = {}
): Promise<ParsedStatementDraft> {
  const resolved = await resolveStatementInput(input, options.fileName);
  const format = detectStatementFormat(resolved.data, resolved.fileName, options.format);
  const statement =
    format === "csv"
      ? parseCsvStatement(resolved.data, { ...options, fileName: resolved.fileName })
      : await parsePdfStatement(resolved.data, { ...options, fileName: resolved.fileName });

  return {
    ...statement,
    fileName: resolved.fileName,
    fileHash: computeFileHash(resolved.data)
  };
}