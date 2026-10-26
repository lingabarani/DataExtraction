import type { Metadata } from "next";
import { Globe2 } from "lucide-react";
import { LeadsList } from "@/components/leads/leads-list";

export const metadata: Metadata = { title: "Mexico Leads | DataExtraction Project" };

export default function MexicoLeadsPage() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-green-500/10">
          <Globe2 className="w-5 h-5 text-green-500" />
        </div>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Mexico Leads</h1>
          <p className="text-muted-foreground text-sm">
            50,208+ records — 12 industry exports, all verified emails
          </p>
        </div>
      </div>
      <LeadsList table="mexico_leads" />
    </div>
  );
}
