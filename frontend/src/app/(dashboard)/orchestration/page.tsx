import { Metadata } from "next";
import { OrchestrationCommandCenter } from "@/components/orchestration/orchestration-command-center";

export const metadata: Metadata = {
  title: "Temporal Orchestration Command Center | DataExtraction",
  description: "Enterprise operations command center for B2B data extraction, entity resolution, and certified Master Golden Record pipeline.",
};

export default function OrchestrationPage() {
  return <OrchestrationCommandCenter />;
}

