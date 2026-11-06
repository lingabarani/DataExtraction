import { PipelinePanel } from "@/components/pipeline/pipeline-panel";

export const metadata = {
  title: "Pipeline & DLQ Operations | DataExtraction",
  description: "Real-time pipeline health telemetry, database connection pooling, and dead-letter queue operations.",
};

export default function PipelinePage() {
  return <PipelinePanel />;
}
