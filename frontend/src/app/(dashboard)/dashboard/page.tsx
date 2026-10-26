import type { Metadata } from "next";
import { Suspense } from "react";
import { DashboardOverview } from "@/components/dashboard/overview";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Dashboard | OneExtraction Project" };

function DashboardFallback() {
  return (
    <div className="space-y-6 animate-pulse">
      <Skeleton className="h-28 w-full rounded-xl" />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Skeleton className="h-24 rounded-lg" />
        <Skeleton className="h-24 rounded-lg" />
        <Skeleton className="h-24 rounded-lg" />
        <Skeleton className="h-24 rounded-lg" />
      </div>
      <Skeleton className="h-80 w-full rounded-xl" />
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<DashboardFallback />}>
      <DashboardOverview />
    </Suspense>
  );
}
