import type { Metadata } from "next";
import { Suspense } from "react";
import { ScraperPanel } from "@/components/scraper/scraper-panel";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Scraper Control | OneExtraction Project" };

function ScraperFallback() {
  return (
    <div className="space-y-6 animate-pulse">
      <Skeleton className="h-20 w-full rounded-xl" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Skeleton className="h-44 rounded-xl" />
        <Skeleton className="h-44 rounded-xl" />
        <Skeleton className="h-44 rounded-xl" />
        <Skeleton className="h-44 rounded-xl" />
      </div>
    </div>
  );
}

export default function ScraperPage() {
  return (
    <Suspense fallback={<ScraperFallback />}>
      <ScraperPanel />
    </Suspense>
  );
}
