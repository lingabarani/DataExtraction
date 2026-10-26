import type { Metadata } from "next";
import { Suspense } from "react";
import { MapExtractionPanel } from "@/components/map-extraction/map-extraction-panel";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = {
  title: "Open Map Extraction | OneExtraction Project",
  description: "Fault-tolerant OpenStreetMap POI extraction, Overpass mirror telemetry, and deduplicated ingestion.",
};

function MapExtractionFallback() {
  return (
    <div className="space-y-6 animate-pulse p-6">
      <Skeleton className="h-24 w-full rounded-xl" />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Skeleton className="h-96 rounded-xl lg:col-span-1" />
        <Skeleton className="h-96 rounded-xl lg:col-span-2" />
      </div>
    </div>
  );
}

export default function MapExtractionPage() {
  return (
    <Suspense fallback={<MapExtractionFallback />}>
      <MapExtractionPanel />
    </Suspense>
  );
}
