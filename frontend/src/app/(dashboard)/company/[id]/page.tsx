import type { Metadata } from "next";
import { CompanyDetail } from "@/components/leads/company-detail";

export const metadata: Metadata = { title: "Company Intelligence | DataExtraction Project" };

interface Props {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ domain?: string; table?: string }>;
}

export default async function CompanyDetailPage({ params, searchParams }: Props) {
  const { id } = await params;
  const { domain, table } = await searchParams;
  return (
    <CompanyDetail
      companyId={id}
      domain={domain}
      table={table === "mexico_leads" ? "mexico_leads" : "us_leads"}
    />
  );
}
