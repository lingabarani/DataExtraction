import type { Metadata } from "next";
import { LeadDetail } from "@/components/leads/lead-detail";

export const metadata: Metadata = { title: "Lead Detail | DataExtraction Project" };

interface Props {
  params:      Promise<{ id: string }>;
  searchParams:Promise<{ table?: string }>;
}

export default async function LeadDetailPage({ params, searchParams }: Props) {
  const { id }   = await params;
  const { table } = await searchParams;
  return (
    <LeadDetail
      id={id}
      table={(table === "mexico_leads" ? "mexico_leads" : "us_leads")}
    />
  );
}
