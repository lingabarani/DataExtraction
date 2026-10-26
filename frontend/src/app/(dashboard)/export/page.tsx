import type { Metadata } from "next";
import { ExportManager } from "@/components/export/export-manager";

export const metadata: Metadata = { title: "Export Data | DataExtraction Project" };

export default function ExportPage() {
  return <ExportManager />;
}
