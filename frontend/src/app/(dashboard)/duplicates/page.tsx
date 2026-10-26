import type { Metadata } from "next";
import { DuplicatesManager } from "@/components/duplicates/duplicates-manager";

export const metadata: Metadata = { title: "Duplicates | DataExtraction Project" };

export default function DuplicatesPage() {
  return <DuplicatesManager />;
}
