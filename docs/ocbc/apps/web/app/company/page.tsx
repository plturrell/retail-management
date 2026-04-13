import Link from "next/link";

import { saveCompanyAction } from "@/app/actions";
import { NoticeBanner } from "@/components/notice-banner";
import { SubmitButton } from "@/components/submit-button";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { getCompanyContext } from "@/lib/server/data";
import { readParam, type PageSearchParams } from "@/lib/search-params";
import { cn } from "@/lib/utils";

export default function CompanyPage({ searchParams }: { searchParams?: PageSearchParams }) {
  const companyId = readParam(searchParams?.companyId);
  const createNew = readParam(searchParams?.mode) === "new";
  const { companies, selectedCompany } = getCompanyContext(createNew ? undefined : companyId);
  const company = createNew ? null : selectedCompany;

  return (
    <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
      <div className="space-y-4">
        <div className="space-y-2">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Company setup</p>
          <h2 className="text-3xl font-semibold tracking-tight">Company master data</h2>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Saved companies</CardTitle>
            <CardDescription>Select a record to edit or create a new one.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Link href="/company?mode=new" className={cn(buttonVariants({ variant: "outline" }), "w-full justify-center")}>
              Create new company
            </Link>
            {companies.length === 0 ? (
              <p className="text-sm text-muted-foreground">No companies saved yet.</p>
            ) : (
              <div className="space-y-2">
                {companies.map((entry) => (
                  <Link
                    key={entry.companyId}
                    href={`/company?companyId=${entry.companyId}`}
                    className={cn(
                      "block rounded-lg border px-4 py-3 text-sm transition-colors hover:bg-muted/50",
                      company?.companyId === entry.companyId && "border-primary bg-primary/5"
                    )}
                  >
                    <p className="font-medium text-foreground">{entry.name}</p>
                    <p className="text-muted-foreground">{entry.uen}</p>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="space-y-4">
        {readParam(searchParams?.notice) ? <NoticeBanner tone="notice" message={readParam(searchParams?.notice)!} /> : null}
        {readParam(searchParams?.error) ? <NoticeBanner tone="error" message={readParam(searchParams?.error)!} /> : null}

        <Card>
          <CardHeader>
            <CardTitle>{company ? `Edit ${company.name}` : "Create company"}</CardTitle>
            <CardDescription>These details drive YA selection, SUTE eligibility, and tax filing outputs.</CardDescription>
          </CardHeader>
          <CardContent>
            <form action={saveCompanyAction} className="grid gap-5 md:grid-cols-2">
              <input type="hidden" name="companyId" value={company?.companyId ?? ""} />

              <div className="space-y-2">
                <Label htmlFor="uen">UEN</Label>
                <Input id="uen" name="uen" defaultValue={company?.uen ?? ""} placeholder="202412345A" required />
              </div>

              <div className="space-y-2">
                <Label htmlFor="name">Company name</Label>
                <Input id="name" name="name" defaultValue={company?.name ?? ""} placeholder="Acme Pte. Ltd." required />
              </div>

              <div className="space-y-2">
                <Label htmlFor="incorporationDate">Incorporation date</Label>
                <Input id="incorporationDate" name="incorporationDate" type="date" defaultValue={company?.incorporationDate ?? ""} required />
              </div>

              <div className="space-y-2">
                <Label htmlFor="shareholderCount">Shareholder count</Label>
                <Input id="shareholderCount" name="shareholderCount" type="number" min={1} defaultValue={company?.shareholderCount ?? 1} required />
              </div>

              <div className="space-y-2">
                <Label htmlFor="financialYearStart">Financial year start</Label>
                <Input id="financialYearStart" name="financialYearStart" type="date" defaultValue={company?.financialYearStart ?? ""} required />
              </div>

              <div className="space-y-2">
                <Label htmlFor="financialYearEnd">Financial year end</Label>
                <Input id="financialYearEnd" name="financialYearEnd" type="date" defaultValue={company?.financialYearEnd ?? ""} required />
              </div>

              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="isTaxResident">Tax residency</Label>
                <Select id="isTaxResident" name="isTaxResident" defaultValue={String(company?.isTaxResident ?? true)}>
                  <option value="true">Singapore tax resident</option>
                  <option value="false">Non-resident</option>
                </Select>
              </div>

              <div className="md:col-span-2 flex flex-wrap gap-3">
                <SubmitButton pendingText="Saving company...">Save company</SubmitButton>
                {company ? (
                  <Link href={`/tax?companyId=${company.companyId}&ya=2025`} className={cn(buttonVariants({ variant: "outline" }), "justify-center")}>
                    Continue to tax computation
                  </Link>
                ) : null}
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}