import Link from "next/link";

import { NoticeBanner } from "@/components/notice-banner";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { getDashboardData, YA_OPTIONS } from "@/lib/server/data";
import { readParam, type PageSearchParams } from "@/lib/search-params";
import { formatCurrency, normalizeYaYear } from "@/lib/tax-ui";
import { cn } from "@/lib/utils";

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl">{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}

export default function HomePage({ searchParams }: { searchParams?: PageSearchParams }) {
  const companyId = readParam(searchParams?.companyId);
  const yaYear = normalizeYaYear(readParam(searchParams?.ya));
  const { companies, selectedCompany, snapshot } = getDashboardData(companyId, yaYear);

  if (!selectedCompany || !snapshot) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Create your first company</CardTitle>
          <CardDescription>Start by saving company details before importing statements or computing tax.</CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/company" className={buttonVariants()}>
            Go to company setup
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Dashboard</p>
        <h2 className="text-3xl font-semibold tracking-tight">Filing overview</h2>
        <p className="text-muted-foreground">Monitor revenue, tax payable, and filing readiness for the selected YA.</p>
      </div>

      {readParam(searchParams?.notice) ? <NoticeBanner tone="notice" message={readParam(searchParams?.notice)!} /> : null}
      {readParam(searchParams?.error) ? <NoticeBanner tone="error" message={readParam(searchParams?.error)!} /> : null}

      <Card>
        <CardHeader>
          <CardTitle>Scope</CardTitle>
          <CardDescription>Select a company and year of assessment.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4 md:grid-cols-[1fr_200px_auto]" action="/">
            <div className="space-y-2">
              <Label htmlFor="companyId">Company</Label>
              <Select id="companyId" name="companyId" defaultValue={selectedCompany.companyId}>
                {companies.map((company) => (
                  <option key={company.companyId} value={company.companyId}>
                    {company.name}
                  </option>
                ))}
              </Select>
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
              <button className={cn(buttonVariants({ variant: "outline" }), "w-full md:w-auto")} type="submit">
                Update view
              </button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <SummaryCard label="Revenue" value={formatCurrency(snapshot.summary.totalRevenue)} />
        <SummaryCard label="Expenses" value={formatCurrency(snapshot.summary.totalExpenses)} />
        <SummaryCard label="Net Profit" value={formatCurrency(snapshot.summary.netProfitLoss)} />
        <SummaryCard label="Chargeable Income" value={formatCurrency(snapshot.result.chargeableIncome)} />
        <SummaryCard label="Tax Payable" value={formatCurrency(snapshot.result.taxPayable)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>{selectedCompany.name}</CardTitle>
            <CardDescription>
              UEN {selectedCompany.uen} · Basis period {snapshot.basisPeriod.label}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-3">
              <Badge variant={snapshot.summary.status === "filed" ? "success" : "secondary"}>
                Filing status: {snapshot.summary.status === "filed" ? "Filed" : "Draft"}
              </Badge>
              <Badge variant={snapshot.eligibility.qualifiesForFormCS ? "success" : "warning"}>
                {snapshot.eligibility.formType.toUpperCase()}
              </Badge>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <Link href={`/statements?companyId=${selectedCompany.companyId}&ya=${yaYear}`} className={cn(buttonVariants({ variant: "outline" }), "justify-center")}>
                Import bank statements
              </Link>
              <Link href={`/transactions?companyId=${selectedCompany.companyId}&ya=${yaYear}`} className={cn(buttonVariants({ variant: "outline" }), "justify-center")}>
                Categorise transactions
              </Link>
              <Link href={`/tax?companyId=${selectedCompany.companyId}&ya=${yaYear}`} className={cn(buttonVariants({ variant: "outline" }), "justify-center")}>
                Review tax computation
              </Link>
              <Link href={`/filing?companyId=${selectedCompany.companyId}&ya=${yaYear}`} className={cn(buttonVariants({ variant: "outline" }), "justify-center")}>
                Review Form C-S export
              </Link>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Eligibility notes</CardTitle>
            <CardDescription>Current assumptions for Form C-S filing.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            {snapshot.eligibility.reasons.length > 0 ? (
              <ul className="list-disc space-y-2 pl-5">
                {snapshot.eligibility.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : (
              <p>Company currently qualifies for {snapshot.eligibility.qualifiesForFormCSLite ? "Form C-S (Lite)" : "Form C-S"} based on stored data.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
