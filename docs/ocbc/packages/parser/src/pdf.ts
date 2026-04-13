import { PDFParse } from "pdf-parse";

import type { BankName, ParseStatementOptions, ParsedStatementDraft, ParsedTransactionDraft } from "./types";
import {
  detectAccountNumber,
  detectBankFromText,
  inferStatementDate,
  normalizeBankName,
  normalizeWhitespace,
  parseAmount,
  parseDateString
} from "./utils";

interface PdfTextPage {
  num: number;
  text: string;
}

interface OcbcBusinessGrowthParseResult {
  accountNumber?: string;
  transactions: ParsedTransactionDraft[];
  warnings: string[];
}

interface OcbcBusinessGrowthTransactionBlock {
  amount: number;
  balance: number;
  descriptionLines: string[];
  postedDate: string;
}

const PDF_ROW_PATTERNS: Record<BankName, RegExp> = {
  DBS: /^(?<date>\d{2}\s+[A-Za-z]{3}\s+\d{4})\s+(?<description>.+?)\s+(?<reference>\S+)\s+(?<debit>\(?[-\d.,]+\)?|-)\s+(?<credit>\(?[-\d.,]+\)?|-)\s+(?<balance>\(?[-\d.,]+\)?|-)$/,
  OCBC: /^(?<date>\d{2}\/\d{2}\/\d{4})\s+(?<description>.+?)\s+(?<reference>\S+)\s+(?<debit>\(?[-\d.,]+\)?|-)\s+(?<credit>\(?[-\d.,]+\)?|-)\s+(?<balance>\(?[-\d.,]+\)?|-)$/,
  UOB: /^(?<date>\d{2}-\d{2}-\d{4})\s+(?<description>.+?)\s+(?<reference>\S+)\s+(?<amount>\(?[-\d.,]+\)?|-)\s+(?<balance>\(?[-\d.,]+\)?|-)$/
};

const PDF_DATE_PREFIXES: Record<BankName, RegExp> = {
  DBS: /^\d{2}\s+[A-Za-z]{3}\s+\d{4}\b/,
  OCBC: /^\d{2}\/\d{2}\/\d{4}\b/,
  UOB: /^\d{2}-\d{2}-\d{4}\b/
};

const OCBC_REAL_STATEMENT_PERIOD_PATTERN = /(?<start>\d{1,2}\s+[A-Z]{3}\s+\d{4})\s+TO\s+(?<end>\d{1,2}\s+[A-Z]{3}\s+\d{4})/;
const OCBC_REAL_STARTING_BALANCE_PATTERN = /^(?<balance>[\d,]+\.\d{2})\s+BALANCE B\/F$/;
const OCBC_REAL_ENDING_BALANCE_PATTERN = /^(?<balance>[\d,]+\.\d{2})\s+BALANCE C\/F$/;
const OCBC_REAL_TRANSACTION_PATTERN =
  /^(?<valueDate>\d{2}\s+[A-Z]{3})\s+(?<amount>[\d,]+\.\d{2})\s+(?<balance>[\d,]+\.\d{2})\s+(?<postedDate>\d{2}\s+[A-Z]{3})\s+(?<description>.+)$/;

function amountsClose(left: number, right: number): boolean {
  return Math.abs(left - right) <= 0.01;
}

function extractOcbcReference(lines: string[]): string | undefined {
  for (const line of [...lines].reverse()) {
    const normalized = normalizeWhitespace(line);

    if (/^(?=.*\d)[A-Z0-9-]{8,}$/i.test(normalized)) {
      return normalized;
    }
  }

  return undefined;
}

function extractOcbcAccountNumber(lines: string[]): string | undefined {
  for (const line of lines) {
    const match = line.match(/Account No\.?\s+([A-Z0-9\-*]+)/i);

    if (match?.[1]) {
      return match[1].replace(/\s+/g, "");
    }
  }

  return undefined;
}

function finalizeOcbcTransaction(
  block: OcbcBusinessGrowthTransactionBlock,
  statementYear: string,
  previousBalance: number | undefined,
  warnings: string[]
): ParsedTransactionDraft | null {
  const date = parseDateString(`${block.postedDate} ${statementYear}`);

  if (!date) {
    warnings.push(`Skipped OCBC PDF row with invalid date: ${block.postedDate}`);
    return null;
  }

  const description = normalizeWhitespace(block.descriptionLines.join(" "));
  const reference = extractOcbcReference(block.descriptionLines);
  const delta = previousBalance === undefined ? undefined : Number((block.balance - previousBalance).toFixed(2));

  let debit: number | undefined;
  let credit: number | undefined;

  if (delta !== undefined) {
    if (amountsClose(delta, block.amount)) {
      credit = block.amount;
    } else if (amountsClose(delta, -block.amount)) {
      debit = block.amount;
    } else {
      warnings.push(
        `Unable to infer debit/credit from OCBC balance flow for ${date}: prev=${previousBalance?.toFixed(2)} amount=${block.amount.toFixed(2)} balance=${block.balance.toFixed(2)}`
      );
    }
  } else {
    warnings.push(`Missing prior balance while parsing OCBC PDF row for ${date}.`);
  }

  return {
    date,
    description,
    reference,
    debit,
    credit,
    balance: block.balance
  };
}

export function parseOcbcBusinessGrowthPages(pageTexts: string[]): OcbcBusinessGrowthParseResult | null {
  const warnings: string[] = [];
  const transactions: ParsedTransactionDraft[] = [];

  let accountNumber: string | undefined;
  let statementYear: string | undefined;
  let previousBalance: number | undefined;
  let activeBlock: OcbcBusinessGrowthTransactionBlock | undefined;

  const flushBlock = () => {
    if (!activeBlock || !statementYear) {
      activeBlock = undefined;
      return;
    }

    const transaction = finalizeOcbcTransaction(activeBlock, statementYear, previousBalance, warnings);
    previousBalance = activeBlock.balance;
    activeBlock = undefined;

    if (transaction) {
      transactions.push(transaction);
    }
  };

  for (const pageText of pageTexts) {
    if (!pageText.includes("BUSINESS GROWTH ACCOUNT") || !pageText.includes("Account No.")) {
      continue;
    }

    const periodMatch = OCBC_REAL_STATEMENT_PERIOD_PATTERN.exec(pageText);

    if (!periodMatch?.groups?.end) {
      warnings.push("Found OCBC statement page without a detectable statement period.");
      continue;
    }

    const endDate = parseDateString(periodMatch.groups.end);
    statementYear ??= endDate?.slice(0, 4);

    const lines = pageText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    accountNumber ??= extractOcbcAccountNumber(lines) ?? detectAccountNumber(pageText)?.replace(/\s+/g, "");
    const periodLineIndex = lines.findIndex((line) => OCBC_REAL_STATEMENT_PERIOD_PATTERN.test(line));

    if (periodLineIndex < 0) {
      warnings.push("Found OCBC statement page without a transaction section.");
      continue;
    }

    for (const line of lines.slice(periodLineIndex + 1)) {
      if (
        line.startsWith("Total Withdrawals/Deposits") ||
        line.startsWith("CHECK YOUR STATEMENT") ||
        line.startsWith("UPDATING YOUR PERSONAL PARTICULARS")
      ) {
        flushBlock();
        break;
      }

      const openingBalanceMatch = OCBC_REAL_STARTING_BALANCE_PATTERN.exec(line);

      if (openingBalanceMatch?.groups?.balance) {
        flushBlock();
        previousBalance = parseAmount(openingBalanceMatch.groups.balance);
        continue;
      }

      if (OCBC_REAL_ENDING_BALANCE_PATTERN.test(line)) {
        flushBlock();
        continue;
      }

      const transactionMatch = OCBC_REAL_TRANSACTION_PATTERN.exec(line);

      if (transactionMatch?.groups) {
        flushBlock();

        const amount = parseAmount(transactionMatch.groups.amount);
        const balance = parseAmount(transactionMatch.groups.balance);

        if (amount === undefined || balance === undefined) {
          warnings.push(`Skipped OCBC PDF row with invalid amounts: ${line}`);
          continue;
        }

        activeBlock = {
          amount: Math.abs(amount),
          balance,
          postedDate: transactionMatch.groups.postedDate,
          descriptionLines: [transactionMatch.groups.description]
        };

        continue;
      }

      if (activeBlock) {
        activeBlock.descriptionLines.push(line);
      }
    }
  }

  flushBlock();

  if (transactions.length === 0) {
    return null;
  }

  return {
    accountNumber,
    transactions,
    warnings
  };
}

function isIgnoredPdfLine(line: string): boolean {
  const upper = line.toUpperCase();

  return (
    upper.includes("ACCOUNT NUMBER") ||
    upper.includes("ACCOUNT NO") ||
    upper.includes("TRANSACTION DATE") ||
    upper === "DBS BANK LTD" ||
    upper === "OCBC BANK" ||
    upper === "UNITED OVERSEAS BANK" ||
    /^-- \d+ OF \d+ --$/.test(upper)
  );
}

function parsePdfRow(bankName: BankName, line: string): ParsedTransactionDraft | null {
  const match = PDF_ROW_PATTERNS[bankName].exec(line);

  if (!match?.groups) {
    return null;
  }

  const date = parseDateString(match.groups.date);
  if (!date) {
    return null;
  }

  if (bankName === "UOB") {
    const signedAmount = parseAmount(match.groups.amount);

    return {
      date,
      description: match.groups.description.trim(),
      reference: match.groups.reference,
      debit: signedAmount !== undefined && signedAmount < 0 ? Math.abs(signedAmount) : undefined,
      credit: signedAmount !== undefined && signedAmount > 0 ? signedAmount : undefined,
      balance: parseAmount(match.groups.balance)
    };
  }

  return {
    date,
    description: match.groups.description.trim(),
    reference: match.groups.reference,
    debit: (() => {
      const value = parseAmount(match.groups.debit);
      return value === undefined ? undefined : Math.abs(value);
    })(),
    credit: (() => {
      const value = parseAmount(match.groups.credit);
      return value === undefined ? undefined : Math.abs(value);
    })(),
    balance: parseAmount(match.groups.balance)
  };
}

export async function parsePdfStatement(
  input: Uint8Array,
  options: ParseStatementOptions = {}
): Promise<ParsedStatementDraft> {
  const parser = new PDFParse({ data: input });

  try {
    const textResult = await parser.getText();
    const bankName = normalizeBankName(options.bankName) ?? detectBankFromText(textResult.text);

    if (!bankName) {
      throw new Error("Unable to detect bank from PDF statement text.");
    }

    const warnings: string[] = [];
    const transactions: ParsedTransactionDraft[] = [];

    if (bankName === "OCBC") {
      const parsedOcbcStatement = parseOcbcBusinessGrowthPages(
        (textResult.pages as PdfTextPage[] | undefined)?.map((page) => page.text) ?? [textResult.text]
      );

      if (parsedOcbcStatement) {
        return {
          bankName,
          accountNumber: options.accountNumber ?? parsedOcbcStatement.accountNumber ?? detectAccountNumber(textResult.text) ?? "UNKNOWN",
          statementDate: inferStatementDate(parsedOcbcStatement.transactions),
          format: "pdf",
          transactions: parsedOcbcStatement.transactions,
          warnings: parsedOcbcStatement.warnings,
          fileName: options.fileName
        };
      }
    }

    for (const rawLine of textResult.text.split(/\r?\n/)) {
      const line = normalizeWhitespace(rawLine);

      if (!line || isIgnoredPdfLine(line)) {
        continue;
      }

      const transaction = parsePdfRow(bankName, line);

      if (transaction) {
        transactions.push(transaction);
        continue;
      }

      if (PDF_DATE_PREFIXES[bankName].test(line)) {
        warnings.push(`Skipped PDF row: ${line}`);
      }
    }

    if (transactions.length === 0) {
      throw new Error("No parseable transactions found in PDF statement.");
    }

    return {
      bankName,
      accountNumber: options.accountNumber ?? detectAccountNumber(textResult.text) ?? "UNKNOWN",
      statementDate: inferStatementDate(transactions),
      format: "pdf",
      transactions,
      warnings,
      fileName: options.fileName
    };
  } finally {
    await parser.destroy();
  }
}