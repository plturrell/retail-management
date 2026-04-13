import Link from "next/link";

import { importStatementAction } from "@/app/actions";
import { FileDropInput } from "@/components/file-drop-input";
import { NoticeBanner } from "@/components/notice-banner";
import { SubmitButton } from "@/components/submit-button";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCompanyContext, getFilteredTransactions, getStatementsOverview, YA_OPTIONS } from "@/lib/server/data";
import { readParam, type PageSearchParams } from "@/lib/search-params";
import { formatCurrency, getCategoryLabel, normalizeYaYear } from "@/lib/tax-ui";
import { cn } from "@/lib/utils";

export default function StatementsPage({ searchParams }: { searchParams?: PageSearchParams }) {
  const companyId = readParam(searchParams?.companyId);
  const yaYear = normalizeYaYear(readParam(searchParams?.ya));
  const search = readParam(searchParams?.search) ?? "";
  const category = readParam(searchParams?.category) ?? "all";
  const taxability = readParam(searchParams?.taxability) ?? "all";
  const { companies, selectedCompany } = getCompanyContext(companyId);

  if (!selectedCompany) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Create a company before importing statements</CardTitle>
          <CardDescription>Statement imports need a target company record in SQLite.</CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/company" className={buttonVariants()}>
            Go to company setup
          </Link>
        </CardContent>
      </Card>
    );
  }

  const statements = getStatementsOverview(selectedCompany.companyId);
  const filtered = getFilteredTransactions({ companyId: selectedCompany.companyId, yaYear, search, category, taxability });

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Bank statements</p>
        <h2 className="text-3xl font-semibold tracking-tight">Upload and review imported statements</h2>
        <p className="text-muted-foreground">Supports CSV/PDF imports for DBS, OCBC, UOB, or auto-detection.</p>
      </div>

      {readParam(searchParams?.notice) ? <NoticeBanner tone="notice" message={readParam(searchParams?.notice)!} /> : null}
      {readParam(searchParams?.warnings) ? <NoticeBanner tone="warning" message={readParam(searchParams?.warnings)!} /> : null}
      {readParam(searchParams?.error) ? <NoticeBanner tone="error" message={readParam(searchParams?.error)!} /> : null}

      <Card>
        <CardHeader>
          <CardTitle>Import statement</CardTitle>
          <CardDescription>DB is initialized automatically on first import.</CardDescription>
        </CardHeader>
        <CardContent>
          <form action={importStatementAction} className="space-y-4">
            <input type="hidden" name="companyId" value={selectedCompany.companyId} />
            <div className="grid gap-4 md:grid-cols-[1fr_200px_200px]">
              <div className="space-y-2">
                <Label htmlFor="statement-company">Company</Label>
                <Select id="statement-company" name="noop-company" defaultValue={selectedCompany.companyId} disabled>
                  {companies.map((company) => (
                    <option key={company.companyId} value={company.companyId}>
                      {company.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="bankName">Bank format</Label>
                <Select id="bankName" name="bankName" defaultValue="Auto">
                  <option value="Auto">Auto-detect</option>
                  <option value="DBS">DBS</option>
                  <option value="OCBC">OCBC</option>
                  <option value="UOB">UOB</option>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="ya">YA context</Label>
                <Select id="ya" name="ya-disabled" defaultValue={String(yaYear)} disabled>
                  {YA_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      YA {value}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            <FileDropInput name="statementFile" accept=".csv,.pdf,application/pdf,text/csv" />

            <SubmitButton pendingText="Importing statement...">Import statement</SubmitButton>
          </form>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Imported statements</CardTitle>
            <CardDescription>{statements.length} statement(s) imported for {selectedCompany.name}.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {statements.length === 0 ? (
              <p className="text-sm text-muted-foreground">No statements imported yet.</p>
            ) : (
              statements.map((statement) => (
                <div key={statement.statementId} className="rounded-lg border p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-medium">{statement.fileName}</p>
                      <p className="text-sm text-muted-foreground">{statement.bankName} · {statement.accountNumber}</p>
                    </div>
                    <Badge variant="outline">{statement.transactionCount} txns</Badge>
                  </div>
                  <p className="mt-3 text-sm text-muted-foreground">Date range: {statement.dateRange}</p>
                  <p className="text-sm text-muted-foreground">Imported at: {statement.importedAt}</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Transaction browser</CardTitle>
            <CardDescription>Review imported transactions for basis period {filtered.basisPeriod?.label ?? "-"}.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <form className="grid gap-4 md:grid-cols-[1fr_180px_180px_160px]" action="/statements">
              <input type="hidden" name="companyId" value={selectedCompany.companyId} />
              <input type="hidden" name="ya" value={String(yaYear)} />
              <div className="space-y-2">
                <Label htmlFor="search">Search</Label>
                <Input id="search" name="search" defaultValue={search} placeholder="Search description or reference" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="category">Category</Label>
                <Select id="category" name="category" defaultValue={category}>
                  <option value="all">All categories</option>
                  <option value="revenue">Revenue</option>
                  <option value="cost_of_sales">Cost of Sales</option>
                  <option value="operating_expense">Operating Expense</option>
                  <option value="non_deductible">Non-deductible</option>
                  <option value="capital">Capital</option>
                  <option value="transfer">Transfer</option>
                  <option value="other">Other</option>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="taxability">Taxability</Label>
                <Select id="taxability" name="taxability" defaultValue={taxability}>
                  <option value="all">All</option>
                  <option value="taxable">Taxable</option>
                  <option value="non-taxable">Non-taxable</option>
                </Select>
              </div>
              <div className="flex items-end">
                <button type="submit" className={cn(buttonVariants({ variant: "outline" }), "w-full justify-center")}>
                  Filter
                </button>
              </div>
            </form>

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Taxable</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.transactions.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground">
                      No transactions matched the selected filters.
                    </TableCell>
                  </TableRow>
                ) : (
                  filtered.transactions.slice(0, 100).map((transaction) => (
                    <TableRow key={transaction.transactionId}>
                      <TableCell>{transaction.date}</TableCell>
                      <TableCell>
                        <p className="font-medium">{transaction.description}</p>
                        <p className="text-xs text-muted-foreground">{transaction.reference ?? "No reference"}</p>
                      </TableCell>
                      <TableCell>{getCategoryLabel(transaction.uiCategory)}</TableCell>
                      <TableCell>{transaction.isTaxable ? "Yes" : "No"}</TableCell>
                      <TableCell className="text-right">{formatCurrency(transaction.amount)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}