"use client";

import React from "react";
import { AlertCircle, CheckCircle2, Loader2, MinusCircle, ShieldAlert, Timer } from "lucide-react";
import { DiscoverySourceStatus } from "@/lib/api";

interface SourceStatusPanelProps {
  statuses: DiscoverySourceStatus[];
}

/** Plain-language names for each source. */
export const SOURCE_LABELS: Record<string, string> = {
  local_db: "Saved results",
  cms_care_compare: "Medicare (CMS)",
  state_registry: "State licence list",
  google_maps: "Google Maps",
  web_search: "Web search",
  linkedin_public: "LinkedIn (public)",
  website_crawl: "Company websites",
  enrichment: "Email check",
};

export const sourceLabel = (s: string) => SOURCE_LABELS[s] ?? s.replace(/_/g, " ");

const STYLE: Record<DiscoverySourceStatus["status"], { cls: string; Icon: React.ElementType }> = {
  running: { cls: "text-primary", Icon: Loader2 },
  ok: { cls: "text-emerald-600", Icon: CheckCircle2 },
  empty: { cls: "text-muted-foreground", Icon: MinusCircle },
  blocked: { cls: "text-amber-600", Icon: ShieldAlert },
  timeout: { cls: "text-amber-600", Icon: Timer },
  unavailable: { cls: "text-rose-600", Icon: AlertCircle },
  error: { cls: "text-rose-600", Icon: AlertCircle },
};

function statusText(s: DiscoverySourceStatus): string {
  if (s.status === "running") return "Searching...";
  if (s.status === "ok") return `Found ${s.count}`;
  if (s.status === "empty") return s.message?.startsWith("Not applicable") ? "Not used for this search" : "Nothing found";
  if (s.status === "blocked") return "Blocked by the site";
  if (s.status === "timeout") return "Too slow, skipped";
  return "Not available";
}

export function SourceStatusPanel({ statuses }: SourceStatusPanelProps) {
  if (statuses.length === 0) return null;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2" data-testid="source-status">
      {statuses.map((s) => {
        const style = STYLE[s.status] ?? STYLE.error;
        return (
          <div key={s.source} className="bg-background border rounded-md p-2.5 text-xs" title={s.message || undefined}>
            <div className="flex items-center justify-between gap-1">
              <span className="font-medium truncate">{sourceLabel(s.source)}</span>
              <style.Icon className={`w-3.5 h-3.5 shrink-0 ${style.cls} ${s.status === "running" ? "animate-spin" : ""}`} />
            </div>
            <div className="flex items-center justify-between text-[11px] mt-0.5">
              <span className={style.cls}>{statusText(s)}</span>
              {s.elapsed_ms > 0 && <span className="text-muted-foreground">{(s.elapsed_ms / 1000).toFixed(1)}s</span>}
            </div>
            {s.message && s.status !== "running" && !s.message.startsWith("Not applicable") && (
              <p className="mt-1 text-[10px] leading-snug text-muted-foreground line-clamp-2">{s.message}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
