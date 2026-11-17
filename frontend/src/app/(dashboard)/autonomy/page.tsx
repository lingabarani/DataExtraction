import type { Metadata } from "next";
import { AutonomyPanel } from "@/components/ai/autonomy-panel";

export const metadata: Metadata = { title: "Autonomy | DataExtraction Project" };

export default function AutonomyPage() {
  return <AutonomyPanel />;
}
