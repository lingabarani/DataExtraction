import type { Metadata } from "next";
import { Globe2 } from "lucide-react";
import { LeadsList } from "@/components/leads/leads-list";

export const metadata: Metadata = { title: "US Leads | DataExtraction Project" };

export default function USLeadsPage() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-blue-500/10">
          <Globe2 className="w-5 h-5 text-blue-500" />
        </div>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">US Leads</h1>
          <p className="text-muted-foreground text-sm">
            906,579+ records — CMS NPI, SEC EDGAR, FDIC, USASpending, ProPublica
          </p>
        </div>
      </div>
      <LeadsList table="us_leads" />
    </div>
  );
}
