import { PipelinesPanel } from "@/components/pipelines/pipelines-panel";

export const metadata = {
  title: "Temporal Workflows | DataExtraction",
  description: "Distributed execution topology across 5 isolated task queues with saga orchestration.",
};

export default function PipelinesPage() {
  return <PipelinesPanel />;
}

