import Link from "next/link";

import { bulkCategoriseTransactionsAction } from "@/app/actions";
import { NoticeBanner } from "@/components/notice-banner";
import { SubmitButton } from "@/components/submit-button";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCompanyContext, getFilteredTransactions, YA_OPTIONS } from "@/lib/server/data";
import { readParam, type PageSearchParams } from "@/lib/search-params";
import { formatCurrency, getCategoryLabel, normalizeYaYear } from "@/lib/tax-ui";
import { cn } from "@/lib/utils";

export default function TransactionsPage({ searchParams }: { searchParams?: PageSearchParams }) {
  const companyId = readParam(searchParams?.companyId);
  const yaYear = normalizeYaYear(readParam(searchParams?.ya));
  const search = readParam(searchParams?.search) ?? "";
  const category = readParam(searchParams?.category) ?? "all";
  const taxability = readParam(searchParams?.taxability) ?? "all";
  const { selectedCompany } = getCompanyContext(companyId);

  if (!selectedCompany) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Create a company before categorising transactions</CardTitle>
          <CardDescription>Once a company exists, import statements and classify transactions in bulk.</CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/company" className={buttonVariants()}>
            Go to company setup
          </Link>
        </CardContent>
      </Card>
    );
  }

  const filtered = getFilteredTransactions({ companyId: selectedCompany.companyId, yaYear, search, category, taxability });

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Transaction categorisation</p>
        <h2 className="text-3xl font-semibold tracking-tight">Classify transactions for YA {yaYear}</h2>
        <p className="text-muted-foreground">Bulk-assign categories and taxability flags for the selected basis period.</p>
      </div>

      {readParam(searchParams?.notice) ? <NoticeBanner tone="notice" message={readParam(searchParams?.notice)!} /> : null}
      {readParam(searchParams?.error) ? <NoticeBanner tone="error" message={readParam(searchParams?.error)!} /> : null}

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>Basis period: {filtered.basisPeriod?.label ?? "-"}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4 md:grid-cols-[220px_180px_1fr_180px_160px]" action="/transactions">
            <input type="hidden" name="companyId" value={selectedCompany.companyId} />
            <div className="space-y-2">
              <Label htmlFor="ya">YA</Label>
              <Select id="ya" name="ya" defaultValue={String(yaYear)}>
                {YA_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    YA {value}
                  </option>
                ))}
              </Select>
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
              <Label htmlFor="search">Search</Label>
              <Input id="search" name="search" defaultValue={search} placeholder="Search description or reference" />
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
                Apply filters
              </button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Bulk categorisation</CardTitle>
          <CardDescription>Select multiple rows, then assign a category and taxability.</CardDescription>
        </CardHeader>
        <CardContent>
          <form action={bulkCategoriseTransactionsAction} className="space-y-4">
            <input type="hidden" name="companyId" value={selectedCompany.companyId} />
            <input type="hidden" name="yaYear" value={String(yaYear)} />

            <div className="grid gap-4 md:grid-cols-[220px_180px_auto]">
              <div className="space-y-2">
                <Label htmlFor="uiCategory">Assign category</Label>
                <Select id="uiCategory" name="uiCategory" defaultValue="operating_expense">
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
                <Label htmlFor="bulk-taxability">Taxability</Label>
                <Select id="bulk-taxability" name="taxability" defaultValue="keep">
                  <option value="keep">Keep existing</option>
                  <option value="taxable">Mark taxable</option>
                  <option value="non-taxable">Mark non-taxable</option>
                </Select>
              </div>
              <div className="flex items-end">
                <SubmitButton pendingText="Updating transactions...">Apply to selected rows</SubmitButton>
              </div>
            </div>

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">Pick</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Current</TableHead>
                  <TableHead>Suggested</TableHead>
                  <TableHead>Taxable</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.transactions.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center text-muted-foreground">
                      No transactions matched the current filters.
                    </TableCell>
                  </TableRow>
                ) : (
                  filtered.transactions.map((transaction) => (
                    <TableRow key={transaction.transactionId}>
                      <TableCell>
                        <Checkbox name="transactionIds" value={transaction.transactionId} />
                      </TableCell>
                      <TableCell>{transaction.date}</TableCell>
                      <TableCell>
                        <p className="font-medium">{transaction.description}</p>
                        <p className="text-xs text-muted-foreground">{transaction.reference ?? "No reference"}</p>
                      </TableCell>
                      <TableCell>{getCategoryLabel(transaction.uiCategory)}</TableCell>
                      <TableCell>
                        <Badge variant={transaction.suggestedCategory === transaction.uiCategory ? "secondary" : "outline"}>
                          {getCategoryLabel(transaction.suggestedCategory)}
                        </Badge>
                      </TableCell>
                      <TableCell>{transaction.isTaxable ? "Yes" : "No"}</TableCell>
                      <TableCell className="text-right">{formatCurrency(transaction.amount)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}