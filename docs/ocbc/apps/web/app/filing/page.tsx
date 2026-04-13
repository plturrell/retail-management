import Link from "next/link";

import { updateFilingStatusAction } from "@/app/actions";
import { NoticeBanner } from "@/components/notice-banner";
import { PrintButton } from "@/components/print-button";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCompanyContext, getFilingExportData, YA_OPTIONS } from "@/lib/server/data";
import { readParam, type PageSearchParams } from "@/lib/search-params";
import { formatCurrency, normalizeYaYear } from "@/lib/tax-ui";
import { cn } from "@/lib/utils";

const FIELD_LABELS: Record<string, string> = {
  revenue: "Revenue",
  otherIncome: "Other income",
  netProfitLoss: "Net profit / (loss)",
  totalAddBacks: "Total add-backs",
  totalDeductions: "Total deductions",
  adjustedProfitLoss: "Adjusted profit / (loss)",
  capitalAllowancesClaimed: "Capital allowances claimed",
  lossesBroughtForwardUsed: "Losses brought forward used",
  capitalAllowancesBroughtForwardUsed: "Capital allowances b/f used",
  donationsBroughtForwardUsed: "Donations brought forward used",
  chargeableIncome: "Chargeable income",
  exemptAmount: "Exempt amount",
  taxableIncomeAfterExemptions: "Taxable income after exemptions",
  grossTaxPayable: "Gross tax payable",
  citRebateAmount: "CIT rebate",
  taxPayable: "Tax payable"
};

export default function FilingPage({ searchParams }: { searchParams?: PageSearchParams }) {
  const companyId = readParam(searchParams?.companyId);
  const yaYear = normalizeYaYear(readParam(searchParams?.ya));
  const { selectedCompany } = getCompanyContext(companyId);

  if (!selectedCompany) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Create a company before reviewing the filing</CardTitle>
          <CardDescription>The review page needs company data plus a computed tax summary.</CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/company" className={buttonVariants()}>
            Go to company setup
          </Link>
        </CardContent>
      </Card>
    );
  }

  const payload = getFilingExportData(selectedCompany.companyId, yaYear);

  if (!payload) {
    return null;
  }

  return (
    <div className="space-y-6 print:space-y-4">
      <div className="space-y-2 print:hidden">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Form C-S review & export</p>
        <h2 className="text-3xl font-semibold tracking-tight">Review filing fields and export JSON</h2>
      </div>

      {readParam(searchParams?.notice) ? <NoticeBanner tone="notice" message={readParam(searchParams?.notice)!} /> : null}
      {readParam(searchParams?.error) ? <NoticeBanner tone="error" message={readParam(searchParams?.error)!} /> : null}

      <Card className="print:border-none print:shadow-none">
        <CardHeader className="print:px-0">
          <CardTitle>{payload.company.name}</CardTitle>
          <CardDescription>
            UEN {payload.company.uen} · Basis period {payload.basisPeriod.label}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 print:px-0">
          <div className="grid gap-4 md:grid-cols-[1fr_200px_160px] print:hidden">
            <div className="space-y-2">
              <Label>Company</Label>
              <Input value={payload.company.name} readOnly />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ya">YA</Label>
              <Select id="ya" name="ya" defaultValue={String(yaYear)} form="filing-scope-form">
                {YA_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    YA {value}
                  </option>
                ))}
              </Select>
            </div>
            <form id="filing-scope-form" action="/filing" className="flex items-end">
              <input type="hidden" name="companyId" value={payload.company.companyId} />
              <button type="submit" className={cn(buttonVariants({ variant: "outline" }), "w-full justify-center")}>
                Update
              </button>
            </form>
          </div>

          <div className="flex flex-wrap gap-3 print:hidden">
            <Link href={`/api/filing?companyId=${payload.company.companyId}&ya=${payload.yaYear}`} className={buttonVariants()}>
              Export JSON
            </Link>
            <PrintButton />
            <form action={updateFilingStatusAction}>
              <input type="hidden" name="companyId" value={payload.company.companyId} />
              <input type="hidden" name="yaYear" value={String(payload.yaYear)} />
              <input type="hidden" name="status" value={payload.filingStatus === "filed" ? "draft" : "filed"} />
              <button type="submit" className={cn(buttonVariants({ variant: "outline" }), "justify-center")}>
                Mark as {payload.filingStatus === "filed" ? "draft" : "filed"}
              </button>
            </form>
            <Badge variant={payload.filingStatus === "filed" ? "success" : "secondary"}>Status: {payload.filingStatus}</Badge>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="print:border-none print:shadow-none">
              <CardHeader className="print:px-0">
                <CardTitle>Company details</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 print:px-0">
                <p className="text-sm text-muted-foreground">Incorporation date: {payload.company.incorporationDate}</p>
                <p className="text-sm text-muted-foreground">Financial year: {payload.company.financialYearStart} → {payload.company.financialYearEnd}</p>
                <p className="text-sm text-muted-foreground">Shareholders: {payload.company.shareholderCount}</p>
                <p className="text-sm text-muted-foreground">Tax resident: {payload.company.isTaxResident ? "Yes" : "No"}</p>
                <p className="text-sm text-muted-foreground">Form type: {payload.formType}</p>
              </CardContent>
            </Card>

            <Card className="print:border-none print:shadow-none">
              <CardHeader className="print:px-0">
                <CardTitle>Summary</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 print:px-0">
                <p className="text-sm text-muted-foreground">Revenue: {formatCurrency(payload.summary.revenue)}</p>
                <p className="text-sm text-muted-foreground">Expenses: {formatCurrency(payload.summary.expenses)}</p>
                <p className="text-sm text-muted-foreground">Net profit: {formatCurrency(payload.summary.netProfitLoss)}</p>
                <p className="text-sm text-muted-foreground">Chargeable income: {formatCurrency(payload.summary.chargeableIncome)}</p>
                <p className="text-sm text-muted-foreground">Tax payable: {formatCurrency(payload.summary.taxPayable)}</p>
              </CardContent>
            </Card>
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead className="text-right">Value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(payload.formCsOutput).map(([field, value]) => (
                <TableRow key={field}>
                  <TableCell>{FIELD_LABELS[field] ?? field}</TableCell>
                  <TableCell className="text-right">{typeof value === "number" ? formatCurrency(value) : String(value)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}