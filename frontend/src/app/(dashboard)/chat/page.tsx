import type { Metadata } from "next";
import { ConversationalWorkspace } from "@/components/chat/conversational-workspace";

export const metadata: Metadata = {
  title: "AI Chatbot & Prospecting Intelligence | DataExtraction",
  description:
    "Enterprise Conversational B2B Intelligence powered by 305K+ verified organizations, Apollo-grade faceted filters, and zero-hallucination semantic search.",
};

export default function ChatbotPage() {
  return <ConversationalWorkspace />;
}
