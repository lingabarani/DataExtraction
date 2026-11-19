import type { Metadata } from "next";
import { PlaceDetail } from "@/components/ai/place-detail";

export const metadata: Metadata = { title: "Place | DataExtraction Project" };

interface Props {
  params: Promise<{ id: string }>;
}

export default async function PlacePage({ params }: Props) {
  const { id } = await params;
  return <PlaceDetail placeId={id} />;
}
