import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Health check endpoint for container orchestrators (Docker, Kubernetes, ECS).
 * Returns HTTP 200 OK with runtime metadata.
 */
export async function GET() {
  return NextResponse.json(
    {
      status: "ok",
      service: "dataextraction-frontend",
      timestamp: new Date().toISOString(),
      uptime_seconds: process.uptime(),
    },
    { status: 200 }
  );
}
