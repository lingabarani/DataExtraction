import type { Metadata } from "next";
import { IntegrationsPage } from "@/components/integrations/integrations-page";

export const metadata: Metadata = { title: "Integrations | DataExtraction" };

export default function Page() {
  return <IntegrationsPage />;
}
