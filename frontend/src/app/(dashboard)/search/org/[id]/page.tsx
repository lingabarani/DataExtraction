import type { Metadata } from "next";
import { DiscoveryOrgDetail } from "@/components/discovery/OrgDetail";

export const metadata: Metadata = { title: "Organization | DataExtraction Project" };

interface Props {
  params: Promise<{ id: string }>;
}

export default async function DiscoveryOrgPage({ params }: Props) {
  const { id } = await params;
  return <DiscoveryOrgDetail orgId={id} />;
}
