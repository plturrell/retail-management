import crypto from "node:crypto";
import path from "node:path";

import type { BankName, ParsedTransactionDraft, StatementFormat } from "./types";

const MONTH_MAP: Record<string, string> = {
  JAN: "01",
  FEB: "02",
  MAR: "03",
  APR: "04",
  MAY: "05",
  JUN: "06",
  JUL: "07",
  AUG: "08",
  SEP: "09",
  OCT: "10",
  NOV: "11",
  DEC: "12"
};

export function computeFileHash(data: Uint8Array): string {
  return crypto.createHash("sha256").update(data).digest("hex");
}

export function canonicalizeHeader(header: string): string {
  return header.replace(/[^a-z0-9]/gi, "").toLowerCase();
}

export function normalizeWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function normalizeBankName(bankName?: string): BankName | undefined {
  if (!bankName) {
    return undefined;
  }

  const normalized = bankName.trim().toUpperCase();

  if (normalized.includes("DBS")) {
    return "DBS";
  }

  if (normalized.includes("OCBC")) {
    return "OCBC";
  }

  if (normalized.includes("UOB") || normalized.includes("UNITED OVERSEAS BANK")) {
    return "UOB";
  }

  return undefined;
}

export function detectBankFromHeaders(headers: string[]): BankName | undefined {
  const normalizedHeaders = headers.map(canonicalizeHeader);

  if (normalizedHeaders.includes("transactiondate") && normalizedHeaders.includes("reference")) {
    return "DBS";
  }

  if (normalizedHeaders.includes("transactiondetails") || normalizedHeaders.includes("runningbalance")) {
    return "OCBC";
  }

  if (normalizedHeaders.includes("transactiondescription") || normalizedHeaders.includes("amount")) {
    return "UOB";
  }

  return undefined;
}

export function detectBankFromText(text: string): BankName | undefined {
  return normalizeBankName(text);
}

export function detectStatementFormat(
  data: Uint8Array,
  fileName?: string,
  format?: StatementFormat
): StatementFormat {
  if (format) {
    return format;
  }

  const extension = fileName ? path.extname(fileName).toLowerCase() : "";

  if (extension === ".csv") {
    return "csv";
  }

  if (extension === ".pdf") {
    return "pdf";
  }

  if (Buffer.from(data).subarray(0, 4).toString("utf8") === "%PDF") {
    return "pdf";
  }

  throw new Error("Unable to detect statement format. Provide a .csv/.pdf file name or explicit format.");
}

export function detectAccountNumber(text: string): string | undefined {
  const match = text.match(/(?:ACCOUNT(?: NUMBER| NO\.?|)\s*[:#-]?\s*)([A-Z0-9\-*]+(?:-[A-Z0-9\-*]+)*)/i);
  return match?.[1];
}

export function pickCell(
  row: Record<string, string | undefined>,
  aliases: readonly string[]
): string | undefined {
  const normalizedEntries = new Map(
    Object.entries(row).map(([key, value]) => [canonicalizeHeader(key), typeof value === "string" ? value.trim() : ""])
  );

  for (const alias of aliases) {
    const value = normalizedEntries.get(canonicalizeHeader(alias));

    if (value !== undefined) {
      return value;
    }
  }

  return undefined;
}

export function hasRowContent(row: Record<string, string | undefined>): boolean {
  return Object.values(row).some((value) => Boolean(normalizeWhitespace(value ?? "")));
}

export function parseDateString(value: string): string | undefined {
  const normalized = normalizeWhitespace(value);

  if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) {
    return normalized;
  }

  const slashOrDashMatch = normalized.match(/^(\d{2})[/-](\d{2})[/-](\d{4})$/);
  if (slashOrDashMatch) {
    const [, day, month, year] = slashOrDashMatch;
    return `${year}-${month}-${day}`;
  }

  const monthNameMatch = normalized.match(/^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$/);
  if (monthNameMatch) {
    const [, day, monthName, year] = monthNameMatch;
    const month = MONTH_MAP[monthName.toUpperCase()];

    if (!month) {
      return undefined;
    }

    return `${year}-${month}-${day.padStart(2, "0")}`;
  }

  return undefined;
}

export function parseAmount(value?: string): number | undefined {
  if (!value) {
    return undefined;
  }

  let normalized = normalizeWhitespace(value);

  if (!normalized || normalized === "-") {
    return undefined;
  }

  let sign = 1;

  if (normalized.startsWith("(") && normalized.endsWith(")")) {
    sign = -1;
    normalized = normalized.slice(1, -1);
  }

  if (/CR$/i.test(normalized)) {
    normalized = normalized.replace(/CR$/i, "");
  }

  if (/DR$/i.test(normalized)) {
    sign = -1;
    normalized = normalized.replace(/DR$/i, "");
  }

  normalized = normalized.replace(/[A-Z$SGD]/gi, "").trim();

  if (normalized.startsWith("-")) {
    sign *= -1;
    normalized = normalized.slice(1);
  }

  if (normalized.endsWith("-")) {
    sign *= -1;
    normalized = normalized.slice(0, -1);
  }

  const lastComma = normalized.lastIndexOf(",");
  const lastDot = normalized.lastIndexOf(".");

  if (lastComma >= 0 && lastDot >= 0) {
    normalized = lastDot > lastComma ? normalized.replace(/,/g, "") : normalized.replace(/\./g, "").replace(/,/g, ".");
  } else if (lastComma >= 0) {
    normalized = /,\d{2}$/.test(normalized) ? normalized.replace(/,/g, ".") : normalized.replace(/,/g, "");
  }

  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? sign * parsed : undefined;
}

export function parseAbsoluteAmount(value?: string): number | undefined {
  const parsed = parseAmount(value);
  return parsed === undefined ? undefined : Math.abs(parsed);
}

export function inferStatementDate(transactions: ParsedTransactionDraft[]): string {
  return transactions.reduce((latest, transaction) => (transaction.date > latest ? transaction.date : latest), transactions[0]?.date ?? "");
}