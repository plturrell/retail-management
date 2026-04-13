"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import type { FinancialSummary, TaxAdjustment } from "@tax-build/db";

import {
  addManualAdjustment,
  bulkUpdateTransactions,
  deleteManualAdjustment,
  importStatementUpload,
  saveCompanyRecord,
  setSummaryStatus
} from "@/lib/server/data";
import { normalizeYaYear, type UiTransactionCategory } from "@/lib/tax-ui";

function asString(value: FormDataEntryValue | null) {
  return typeof value === "string" ? value : "";
}

function buildPathname(pathname: string, entries: Record<string, string | undefined>) {
  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(entries)) {
    if (value) {
      params.set(key, value);
    }
  }

  const search = params.toString();
  return search ? `${pathname}?${search}` : pathname;
}

export async function saveCompanyAction(formData: FormData) {
  const payload = {
    companyId: asString(formData.get("companyId")) || undefined,
    uen: asString(formData.get("uen")),
    name: asString(formData.get("name")),
    incorporationDate: asString(formData.get("incorporationDate")),
    financialYearStart: asString(formData.get("financialYearStart")),
    financialYearEnd: asString(formData.get("financialYearEnd")),
    shareholderCount: Number(asString(formData.get("shareholderCount")) || 0),
    isTaxResident: asString(formData.get("isTaxResident")) === "true"
  };

  try {
    const companyId = await saveCompanyRecord(payload);
    revalidatePath("/");
    revalidatePath("/company");
    redirect(buildPathname("/company", { companyId, notice: "Company saved." }));
  } catch (error) {
    redirect(buildPathname("/company", { companyId: payload.companyId, error: error instanceof Error ? error.message : "Unable to save company." }));
  }
}

export async function importStatementAction(formData: FormData) {
  const companyId = asString(formData.get("companyId"));
  const bankName = asString(formData.get("bankName")) || "Auto";
  const file = formData.get("statementFile");

  if (!(file instanceof File) || file.size === 0) {
    redirect(buildPathname("/statements", { companyId, error: "Choose a CSV or PDF file to import." }));
  }

  try {
    const summary = await importStatementUpload({ companyId, bankName, file });
    revalidatePath("/");
    revalidatePath("/statements");
    revalidatePath("/transactions");
    revalidatePath("/tax");
    revalidatePath("/filing");
    redirect(
      buildPathname("/statements", {
        companyId,
        notice: summary.duplicate ? "Statement already imported." : `Imported ${summary.rowsImported} transaction row(s).`,
        warnings: summary.warnings.join(" | ") || undefined
      })
    );
  } catch (error) {
    redirect(buildPathname("/statements", { companyId, error: error instanceof Error ? error.message : "Import failed." }));
  }
}

export async function bulkCategoriseTransactionsAction(formData: FormData) {
  const companyId = asString(formData.get("companyId"));
  const yaYear = normalizeYaYear(asString(formData.get("yaYear")));
  const uiCategory = asString(formData.get("uiCategory")) as UiTransactionCategory;
  const taxability = (asString(formData.get("taxability")) || "keep") as "keep" | "taxable" | "non-taxable";
  const transactionIds = formData.getAll("transactionIds").map((value) => String(value));

  if (transactionIds.length === 0) {
    redirect(buildPathname("/transactions", { companyId, ya: String(yaYear), error: "Select at least one transaction." }));
  }

  await bulkUpdateTransactions({ transactionIds, uiCategory, taxability });
  revalidatePath("/");
  revalidatePath("/statements");
  revalidatePath("/transactions");
  revalidatePath("/tax");
  revalidatePath("/filing");
  redirect(buildPathname("/transactions", { companyId, ya: String(yaYear), notice: `Updated ${transactionIds.length} transaction(s).` }));
}

export async function addTaxAdjustmentAction(formData: FormData) {
  const companyId = asString(formData.get("companyId"));
  const yaYear = normalizeYaYear(asString(formData.get("yaYear")));

  try {
    await addManualAdjustment({
      companyId,
      yaYear,
      description: asString(formData.get("description")),
      amount: Number(asString(formData.get("amount")) || 0),
      adjustmentType: asString(formData.get("adjustmentType")) as TaxAdjustment["adjustmentType"],
      category: asString(formData.get("category")) as TaxAdjustment["category"]
    });
    revalidatePath("/tax");
    revalidatePath("/filing");
    redirect(buildPathname("/tax", { companyId, ya: String(yaYear), notice: "Adjustment added." }));
  } catch (error) {
    redirect(buildPathname("/tax", { companyId, ya: String(yaYear), error: error instanceof Error ? error.message : "Unable to add adjustment." }));
  }
}

export async function deleteTaxAdjustmentAction(formData: FormData) {
  const companyId = asString(formData.get("companyId"));
  const yaYear = normalizeYaYear(asString(formData.get("yaYear")));
  const adjustmentId = asString(formData.get("adjustmentId"));

  await deleteManualAdjustment(adjustmentId);
  revalidatePath("/tax");
  revalidatePath("/filing");
  redirect(buildPathname("/tax", { companyId, ya: String(yaYear), notice: "Adjustment removed." }));
}

export async function updateFilingStatusAction(formData: FormData) {
  const companyId = asString(formData.get("companyId"));
  const yaYear = normalizeYaYear(asString(formData.get("yaYear")));
  const status = asString(formData.get("status")) as FinancialSummary["status"];

  await setSummaryStatus({ companyId, yaYear, status });
  revalidatePath("/");
  revalidatePath("/filing");
  redirect(buildPathname("/filing", { companyId, ya: String(yaYear), notice: `Filing marked as ${status}.` }));
}