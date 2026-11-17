import type { Metadata } from "next";
import { AiKeysPanel } from "@/components/ai/ai-keys-panel";

export const metadata: Metadata = { title: "AI Keys | DataExtraction Project" };

export default function AiKeysPage() {
  return <AiKeysPanel />;
}
