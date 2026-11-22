import type { Metadata } from "next";
import { Building2 } from "lucide-react";
import { CompaniesList } from "@/components/companies/companies-list";

export const metadata: Metadata = {
  title: "Company Data | DataExtraction Corporate Vault",
  description: "Browse 213,000+ certified organizations with firmographics, tech stack, and live deep intelligence.",
};

export default function CompaniesPage() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-blue-500/10">
          <Building2 className="w-5 h-5 text-blue-500" />
        </div>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Company Data</h1>
          <p className="text-muted-foreground text-sm">
            Master Corporate Vault — 213,129 Certified Organizations with Tech Stacks, Revenue Bands &amp; OneReach Dossiers
          </p>
        </div>
      </div>
      <CompaniesList />
    </div>
  );
}
