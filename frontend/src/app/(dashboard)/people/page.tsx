import type { Metadata } from "next";
import { Users } from "lucide-react";
import { PeopleList } from "@/components/people/people-list";

export const metadata: Metadata = {
  title: "People Data | DataExtraction Decision-Maker Vault",
  description: "Browse 65,000+ verified executive decision-makers with deliverable emails, direct dials, and seniority levels.",
};

export default function PeoplePage() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-purple-500/10">
          <Users className="w-5 h-5 text-purple-600 dark:text-purple-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">People Data</h1>
          <p className="text-muted-foreground text-sm">
            Executive Decision-Maker Vault — Verified C-Suite, VPs, Directors &amp; Founders with RFC 5322 Deliverable Emails
          </p>
        </div>
      </div>
      <PeopleList />
    </div>
  );
}
