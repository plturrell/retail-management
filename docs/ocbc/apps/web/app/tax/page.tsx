import Link from "next/link";

import { addTaxAdjustmentAction, deleteTaxAdjustmentAction } from "@/app/actions";
import { NoticeBanner } from "@/components/notice-banner";
import { SubmitButton } from "@/components/submit-button";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCompanyContext, getComputationSnapshot, YA_OPTIONS } from "@/lib/server/data";
import { readParam, type PageSearchParams } from "@/lib/search-params";
import { formatCurrency, normalizeYaYear } from "@/lib/tax-ui";
import { cn } from "@/lib/utils";

export default function TaxPage({ searchParams }: { searchParams?: PageSearchParams }) {
  const companyId = readParam(searchParams?.companyId);
  const yaYear = normalizeYaYear(readParam(searchParams?.ya));
  const { selectedCompany } = getCompanyContext(companyId);

  if (!selectedCompany) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Create a company before computing tax</CardTitle>
          <CardDescription>Tax computation uses company master data plus categorised transactions.</CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/company" className={buttonVariants()}>
            Go to company setup
          </Link>
        </CardContent>
      </Card>
    );
  }

  const snapshot = getComputationSnapshot(selectedCompany.companyId, yaYear);
  const comparisons = YA_OPTIONS.map((value) => getComputationSnapshot(selectedCompany.companyId, value)).filter((entry): entry is NonNullable<typeof snapshot> => Boolean(entry));

  if (!snapshot) {
    return null;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Tax computation</p>
        <h2 className="text-3xl font-semibold tracking-tight">Form C-S computation view</h2>
        <p className="text-muted-foreground">Editable tax adjustments layered on top of imported transaction data.</p>
      </div>

      {readParam(searchParams?.notice) ? <NoticeBanner tone="notice" message={readParam(searchParams?.notice)!} /> : null}
      {readParam(searchParams?.error) ? <NoticeBanner tone="error" message={readParam(searchParams?.error)!} /> : null}

      <Card>
        <CardHeader>
          <CardTitle>Computation scope</CardTitle>
          <CardDescription>Basis period {snapshot.basisPeriod.label}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4 md:grid-cols-[1fr_200px_160px]" action="/tax">
            <input type="hidden" name="companyId" value={selectedCompany.companyId} />
            <div className="space-y-2">
              <Label>Company</Label>
              <Input value={selectedCompany.name} readOnly />
            </div>
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
            <div className="flex items-end">
              <button className={cn(buttonVariants({ variant: "outline" }), "w-full justify-center")} type="submit">
                Update
              </button>
            </div>
          </form>
        </CardContent>
      </Card>

      <NoticeBanner
        tone={snapshot.eligibility.qualifiesForFormCS ? "notice" : "warning"}
        message={
          snapshot.eligibility.qualifiesForFormCS
            ? `Eligible for ${snapshot.eligibility.qualifiesForFormCSLite ? "Form C-S (Lite)" : "Form C-S"}.`
            : snapshot.eligibility.reasons.join(" ")
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Form C-S fields</CardTitle>
            <CardDescription>IRAS Form C-S line items for YA {snapshot.yaYear} (basis period ending {snapshot.basisPeriod.end})</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableBody>
                <TableRow>
                  <TableCell className="text-muted-foreground w-8">24</TableCell>
                  <TableCell>Revenue</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.summary.totalRevenue)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell className="text-muted-foreground">25</TableCell>
                  <TableCell>Gross Profit / (Loss)</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.summary.totalRevenue - snapshot.expenseBreakdown.costOfSales)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell className="text-muted-foreground">26</TableCell>
                  <TableCell>Directors&apos; Fees and Remuneration</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.expenseBreakdown.directorsFees)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell className="text-muted-foreground">27</TableCell>
                  <TableCell>Total Remuneration excl. Directors&apos; Fees</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.expenseBreakdown.totalRemuneration)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell className="text-muted-foreground">28</TableCell>
                  <TableCell>Medical Expenses</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.expenseBreakdown.medicalExpenses)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell className="text-muted-foreground">29</TableCell>
                  <TableCell>Transport / Travelling Expenses</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.expenseBreakdown.transportExpenses)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell className="text-muted-foreground">30</TableCell>
                  <TableCell>Entertainment Expenses</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.expenseBreakdown.entertainmentExpenses)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell className="text-muted-foreground">31</TableCell>
                  <TableCell>Inventories</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.expenseBreakdown.inventories)}</TableCell>
                </TableRow>
                <TableRow className="border-t-2">
                  <TableCell />
                  <TableCell className="font-semibold">Net Profit / (Loss)</TableCell>
                  <TableCell className="text-right font-semibold">{formatCurrency(snapshot.summary.netProfitLoss)}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Tax computation</CardTitle>
            <CardDescription>Chargeable income and tax payable.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableBody>
                <TableRow>
                  <TableCell>Net Profit / (Loss)</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.summary.netProfitLoss)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Total add-backs</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.result.formCsOutput.totalAddBacks)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Total deductions</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.result.formCsOutput.totalDeductions)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Adjusted Profit / (Loss)</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.result.adjustedProfitLoss)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Chargeable Income</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.result.chargeableIncome)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Exempt Amount</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.result.exemptAmount)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>CIT rebate</TableCell>
                  <TableCell className="text-right">{formatCurrency(snapshot.result.citRebateAmount)}</TableCell>
                </TableRow>
                <TableRow className="border-t-2">
                  <TableCell className="font-semibold">Tax Payable</TableCell>
                  <TableCell className="text-right font-semibold">{formatCurrency(snapshot.result.taxPayable)}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>YA comparison</CardTitle>
            <CardDescription>Quick side-by-side for YA 2024 vs 2025.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>YA</TableHead>
                  <TableHead>Revenue</TableHead>
                  <TableHead>Chargeable Income</TableHead>
                  <TableHead>Tax Payable</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {comparisons.map((entry) => (
                  <TableRow key={entry.yaYear}>
                    <TableCell>YA {entry.yaYear}</TableCell>
                    <TableCell>{formatCurrency(entry.summary.totalRevenue)}</TableCell>
                    <TableCell>{formatCurrency(entry.result.chargeableIncome)}</TableCell>
                    <TableCell>{formatCurrency(entry.result.taxPayable)}</TableCell>
                    <TableCell>
                      <Badge variant={entry.summary.status === "filed" ? "success" : "secondary"}>{entry.summary.status}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_420px]">
        <Card>
          <CardHeader>
            <CardTitle>Current adjustments</CardTitle>
            <CardDescription>Auto adjustments come from transaction categorisation; manual adjustments are editable below.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              <div>
                <p className="text-sm font-medium">Auto adjustments</p>
                <div className="mt-2 space-y-2">
                  {snapshot.autoAdjustments.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No automatic adjustments generated from the current transaction set.</p>
                  ) : (
                    snapshot.autoAdjustments.map((adjustment) => (
                      <div key={adjustment.description} className="rounded-lg border px-4 py-3 text-sm">
                        <div className="flex items-center justify-between gap-3">
                          <p className="font-medium">{adjustment.description}</p>
                          <Badge variant="outline">{adjustment.adjustmentType}</Badge>
                        </div>
                        <p className="mt-1 text-muted-foreground">{formatCurrency(adjustment.amount)}</p>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div>
                <p className="text-sm font-medium">Manual adjustments</p>
                <div className="mt-2 space-y-2">
                  {snapshot.manualAdjustments.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No manual adjustments added yet.</p>
                  ) : (
                    snapshot.manualAdjustments.map((adjustment) => (
                      <div key={adjustment.adjustmentId} className="flex items-center justify-between gap-3 rounded-lg border px-4 py-3 text-sm">
                        <div>
                          <p className="font-medium">{adjustment.description}</p>
                          <p className="text-muted-foreground">{adjustment.adjustmentType} · {adjustment.category} · {formatCurrency(adjustment.amount)}</p>
                        </div>
                        <form action={deleteTaxAdjustmentAction}>
                          <input type="hidden" name="companyId" value={selectedCompany.companyId} />
                          <input type="hidden" name="yaYear" value={String(yaYear)} />
                          <input type="hidden" name="adjustmentId" value={adjustment.adjustmentId} />
                          <button type="submit" className={cn(buttonVariants({ variant: "outline" }), "h-9 px-3")}>Remove</button>
                        </form>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Add manual adjustment</CardTitle>
            <CardDescription>Useful for donations, capital allowances, or prior year balances.</CardDescription>
          </CardHeader>
          <CardContent>
            <form action={addTaxAdjustmentAction} className="space-y-4">
              <input type="hidden" name="companyId" value={selectedCompany.companyId} />
              <input type="hidden" name="yaYear" value={String(yaYear)} />

              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Input id="description" name="description" placeholder="Private car expenses" required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="amount">Amount</Label>
                <Input id="amount" name="amount" type="number" min={0} step="0.01" placeholder="0.00" required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="adjustmentType">Adjustment type</Label>
                <Select id="adjustmentType" name="adjustmentType" defaultValue="add_back">
                  <option value="add_back">Add back</option>
                  <option value="deduct">Deduct</option>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="category">Category</Label>
                <Select id="category" name="category" defaultValue="other">
                  <option value="non_deductible">Non-deductible</option>
                  <option value="non_taxable">Non-taxable</option>
                  <option value="capital_allowance">Capital allowance</option>
                  <option value="donation">Donation</option>
                  <option value="loss_brought_forward">Loss brought forward</option>
                  <option value="other">Other</option>
                </Select>
              </div>

              <SubmitButton pendingText="Adding adjustment...">Add adjustment</SubmitButton>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}