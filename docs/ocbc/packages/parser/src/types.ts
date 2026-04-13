export type BankName = "DBS" | "OCBC" | "UOB";

export type StatementFormat = "csv" | "pdf";

export type StatementSource = string | Buffer | Uint8Array;

export interface ParsedTransactionDraft {
  date: string;
  description: string;
  reference?: string;
  debit?: number;
  credit?: number;
  balance?: number;
}

export interface ParsedStatementDraft {
  bankName: BankName;
  accountNumber: string;
  statementDate: string;
  format: StatementFormat;
  transactions: ParsedTransactionDraft[];
  warnings: string[];
  fileName?: string;
  fileHash?: string;
}

export interface ParseStatementOptions {
  bankName?: BankName | string;
  accountNumber?: string;
  fileName?: string;
  format?: StatementFormat;
}

export interface ImportStatementSummary {
  statementId?: string;
  duplicate: boolean;
  rowsImported: number;
  rowsSkipped: number;
  warnings: string[];
  fileHash: string;
  bankName?: BankName;
  accountNumber?: string;
  statementDate?: string;
}