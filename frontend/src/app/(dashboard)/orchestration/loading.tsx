import { Skeleton } from "@/components/ui/skeleton";

export default function OrchestrationLoading() {
  return (
    <div className="flex flex-col min-h-screen bg-background space-y-4 p-4 sm:p-6">
      {/* Top nav skeleton */}
      <div className="flex gap-4 border-b border-border/60 pb-3">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <Skeleton key={i} className="h-8 w-24 rounded-md" />
        ))}
      </div>

      {/* Header skeleton */}
      <div className="space-y-4 rounded-xl border border-border/60 p-4">
        <div className="flex justify-between items-center">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-8 w-32" />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-14 rounded-lg" />
          ))}
        </div>
      </div>

      {/* Control bar skeleton */}
      <div className="flex justify-between items-center rounded-lg border border-border/60 p-3">
        <Skeleton className="h-7 w-48" />
        <div className="flex gap-2">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-8 w-24" />
          ))}
        </div>
      </div>

      {/* KPI ribbon skeleton */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
        {[1, 2, 3, 4, 5, 6, 7].map((i) => (
          <Skeleton key={i} className="h-16 rounded-lg" />
        ))}
      </div>

      {/* DAG skeleton */}
      <Skeleton className="h-48 w-full rounded-xl" />

      {/* Status panel skeleton */}
      <Skeleton className="h-36 w-full rounded-xl" />

      {/* Agent grid skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-44 rounded-xl" />
        ))}
      </div>
    </div>
  );
}

