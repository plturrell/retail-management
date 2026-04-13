import { NextResponse } from "next/server";

import { getFilingExportData } from "@/lib/server/data";
import { normalizeYaYear } from "@/lib/tax-ui";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const companyId = searchParams.get("companyId");
  const yaYear = normalizeYaYear(searchParams.get("ya"));

  if (!companyId) {
    return NextResponse.json({ error: "companyId is required." }, { status: 400 });
  }

  const payload = getFilingExportData(companyId, yaYear);

  if (!payload) {
    return NextResponse.json({ error: "Company not found." }, { status: 404 });
  }

  return new NextResponse(JSON.stringify(payload, null, 2), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "content-disposition": `attachment; filename="${payload.company.name.replace(/[^a-zA-Z0-9_-]+/g, "-")}-ya-${payload.yaYear}.json"`
    }
  });
}