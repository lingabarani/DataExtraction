import { SchedulesPanel } from "@/components/schedules/schedules-panel";

export const metadata = {
  title: "Temporal Schedules | DataExtraction",
  description: "Automated cron schedules managed natively by Temporal Server.",
};

export default function SchedulesPage() {
  return <SchedulesPanel />;
}

