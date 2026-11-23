import type { Metadata } from "next";
import { ProspectingWorkspace } from "@/components/prospecting/prospecting-workspace";

export const metadata: Metadata = {
  title: "Prospecting Grid | DataExtraction Enterprise",
  description:
    "Apollo-grade B2B Prospecting Grid with sub-second AI search, faceted filters, and 305K+ verified organizations.",
};

export default function ChatbotPage() {
  return <ProspectingWorkspace />;
}
