import Papa from "papaparse";

import type { BankName, ParseStatementOptions, ParsedStatementDraft, ParsedTransactionDraft } from "./types";
import {
  detectAccountNumber,
  detectBankFromHeaders,
  hasRowContent,
  inferStatementDate,
  normalizeBankName,
  parseAbsoluteAmount,
  parseAmount,
  parseDateString,
  pickCell
} from "./utils";

interface CsvColumnConfig {
  date: string[];
  description: string[];
  reference: string[];
  debit?: string[];
  credit?: string[];
  amount?: string[];
  balance: string[];
}

const CSV_CONFIGS: Record<BankName, CsvColumnConfig> = {
  DBS: {
    date: ["Transaction Date", "Date"],
    description: ["Description", "Transaction Description"],
    reference: ["Reference", "Reference No."],
    debit: ["Debit"],
    credit: ["Credit"],
    balance: ["Balance"]
  },
  OCBC: {
    date: ["Date"],
    description: ["Transaction Details", "Description"],
    reference: ["Cheque No.", "Reference"],
    debit: ["Withdrawal", "Debit"],
    credit: ["Deposit", "Credit"],
    balance: ["Running Balance", "Balance"]
  },
  UOB: {
    date: ["Date"],
    description: ["Transaction Description", "Description"],
    reference: ["Reference No.", "Reference"],
    amount: ["Amount"],
    balance: ["Balance"]
  }
};

function parseCsvRow(bankName: BankName, row: Record<string, string | undefined>): ParsedTransactionDraft | null {
  if (!hasRowContent(row)) {
    return null;
  }

  const config = CSV_CONFIGS[bankName];
  const date = parseDateString(pickCell(row, config.date) ?? "");
  const description = pickCell(row, config.description)?.trim();

  if (!date || !description) {
    return null;
  }

  let debit = config.debit ? parseAbsoluteAmount(pickCell(row, config.debit)) : undefined;
  let credit = config.credit ? parseAbsoluteAmount(pickCell(row, config.credit)) : undefined;

  if (config.amount) {
    const signedAmount = parseAmount(pickCell(row, config.amount));

    if (signedAmount !== undefined) {
      if (signedAmount < 0) {
        debit = Math.abs(signedAmount);
      } else {
        credit = signedAmount;
      }
    }
  }

  return {
    date,
    description,
    reference: pickCell(row, config.reference)?.trim() || undefined,
    debit,
    credit,
    balance: parseAmount(pickCell(row, config.balance))
  };
}

export function parseCsvStatement(
  input: string | Uint8Array,
  options: ParseStatementOptions = {}
): ParsedStatementDraft {
  const text = typeof input === "string" ? input : Buffer.from(input).toString("utf8");
  const csvText = text.replace(/^\uFEFF/, "");
  const result = Papa.parse<Record<string, string>>(csvText, {
    header: true,
    skipEmptyLines: true,
    transformHeader: (header) => header.trim()
  });

  const headers = result.meta.fields ?? [];
  const bankName = normalizeBankName(options.bankName) ?? detectBankFromHeaders(headers);

  if (!bankName) {
    throw new Error("Unable to detect bank from CSV headers.");
  }

  const warnings = result.errors.map((error) => `CSV parse warning: ${error.message}`);
  const transactions: ParsedTransactionDraft[] = [];

  result.data.forEach((row, index) => {
    const transaction = parseCsvRow(bankName, row);

    if (transaction) {
      transactions.push(transaction);
      return;
    }

    if (hasRowContent(row)) {
      warnings.push(`Skipped CSV row ${index + 2}: missing or invalid transaction fields.`);
    }
  });

  if (transactions.length === 0) {
    throw new Error("No parseable transactions found in CSV statement.");
  }

  return {
    bankName,
    accountNumber: options.accountNumber ?? detectAccountNumber(csvText) ?? "UNKNOWN",
    statementDate: inferStatementDate(transactions),
    format: "csv",
    transactions,
    warnings,
    fileName: options.fileName
  };
}