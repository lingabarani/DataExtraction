import type { Metadata } from "next";
import { Sparkles } from "lucide-react";
import { ProspectingWorkspace } from "@/components/prospecting/prospecting-workspace";

export const metadata: Metadata = {
  title: "DataExtraction Chatbot | Enterprise B2B Search",
  description:
    "Apollo.io-style DataExtraction Chatbot with Company & People search, faceted filtering, and semantic intelligence.",
};

export default function ChatbotPage() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400">
          <Sparkles className="w-5 h-5" />
        </div>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">DataExtraction Chatbot</h1>
          <p className="text-muted-foreground text-sm">
            Enterprise B2B Search Engine with Apollo-Grade Faceted Filtering and Semantic Intelligence
          </p>
        </div>
      </div>
      <ProspectingWorkspace />
    </div>
  );
}
