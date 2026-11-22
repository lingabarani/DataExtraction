"use client";

import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Building2, ExternalLink, Globe, ShieldCheck,
  ChevronRight, Sparkles, Layers, Star,
} from "lucide-react";
import type { Lead } from "@/hooks/use-leads";
import { cn } from "@/lib/utils";

// ── Jurisdiction Badges ───────────────────────────────────────────────────────

function JurisdictionBadge({ jurisdiction, country }: { jurisdiction?: string | null; country?: string | null }) {
  const isMexico = (jurisdiction && jurisdiction.toUpperCase().includes("MX")) || (country && country.toUpperCase().includes("MEX"));
  if (isMexico) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wide uppercase bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
        MX
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wide uppercase bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20">
      US
    </span>
  );
}

// ── Score Cell ────────────────────────────────────────────────────────────────

function ScoreCell({ score }: { score: number | null }) {
  if (!score) return <span className="text-muted-foreground/30 text-[12px]">—</span>;
  const color = score >= 80 ? "text-emerald-600 dark:text-emerald-400"
              : score >= 50 ? "text-amber-600 dark:text-amber-400"
              :               "text-red-500";
  return (
    <div className="flex items-center gap-1.5">
      <span className={`text-[12px] font-mono tabnum font-semibold ${color}`}>{score}</span>
      <span className="text-[10px] text-muted-foreground/50">/100</span>
    </div>
  );
}

// ── Currency Formatter ────────────────────────────────────────────────────────

function formatCurrency(val?: number | null) {
  if (!val || val <= 0) return "—";
  if (val >= 1_000_000_000) return `$${(val / 1_000_000_000).toFixed(1)}B`;
  if (val >= 1_000_000) return `$${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1_000) return `$${(val / 1_000).toFixed(0)}K`;
  return `$${val.toLocaleString()}`;
}

// ── Table Cells ───────────────────────────────────────────────────────────────

function TH({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={cn(
      "px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest",
      "text-muted-foreground whitespace-nowrap bg-card/95 border-b border-border sticky top-0 z-10 backdrop-blur-xs shadow-2xs",
      className
    )}>
      {children}
    </th>
  );
}

function TD({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <td className={cn("px-3 py-[7px] text-[12px] align-middle", className)}>
      {children}
    </td>
  );
}

// ── Main CompaniesTable ───────────────────────────────────────────────────────

interface Props {
  companies: Lead[];
  loading:   boolean;
}

export function CompaniesTable({ companies, loading }: Props) {
  if (loading) {
    return (
      <table className="w-full text-left">
        <thead>
          <tr>
            <TH>Organization</TH>
            <TH>Domain</TH>
            <TH>Industry</TH>
            <TH>Rating</TH>
            <TH>Region</TH>
            <TH className="hidden lg:table-cell">Size</TH>
            <TH className="hidden xl:table-cell">Revenue</TH>
            <TH className="text-center">Trust</TH>
            <TH className="text-right pr-4">Action</TH>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {Array.from({ length: 12 }).map((_, i) => (
            <tr key={i}>
              <TD><Skeleton className="h-3.5 w-28" /></TD>
              <TD><Skeleton className="h-3.5 w-24" /></TD>
              <TD><Skeleton className="h-3.5 w-20" /></TD>
              <TD><Skeleton className="h-3.5 w-14" /></TD>
              <TD><Skeleton className="h-3.5 w-10" /></TD>
              <TD className="hidden lg:table-cell"><Skeleton className="h-3.5 w-14" /></TD>
              <TD className="hidden xl:table-cell"><Skeleton className="h-3.5 w-14" /></TD>
              <TD className="text-center"><Skeleton className="h-3.5 w-10 mx-auto" /></TD>
              <TD className="text-right pr-4"><Skeleton className="h-3.5 w-14 ml-auto" /></TD>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  if (!companies.length) {
    return (
      <div className="py-20 text-center text-muted-foreground text-sm flex flex-col items-center gap-2">
        <Building2 className="w-8 h-8 text-muted-foreground/40 mb-1" />
        <p className="font-medium text-foreground">No organizations found</p>
        <p className="text-xs text-muted-foreground">Try broadening your search or resetting industry and regional filters.</p>
      </div>
    );
  }

  return (
    <table className="w-full text-left">
      <thead>
        <tr>
          <TH className="w-[24%] min-w-[150px]">Organization</TH>
          <TH className="w-[18%] min-w-[130px]">Domain</TH>
          <TH className="w-[18%] min-w-[120px]">Industry</TH>
          <TH className="w-[10%] min-w-[80px]">Rating</TH>
          <TH className="w-[8%] min-w-[60px]">Region</TH>
          <TH className="hidden lg:table-cell w-[10%] min-w-[80px]">Size</TH>
          <TH className="hidden xl:table-cell w-[10%] min-w-[80px]">Revenue</TH>
          <TH className="w-[6%] min-w-[50px] text-center">Trust</TH>
          <TH className="w-[6%] min-w-[70px] text-right pr-4">Dossier</TH>
        </tr>
      </thead>
      <tbody className="divide-y divide-border/60">
        {companies.map((org, idx) => {
          const orgId = org.id || org.company_id || `org-${idx}`;
          const companyName = org.company_name || "Commercial Entity";
          const domain = org.domain;
          const techList: string[] = Array.isArray((org as unknown as Record<string, unknown>).technologies)
            ? ((org as unknown as Record<string, unknown>).technologies as string[])
            : [];
          const revenue = (org as unknown as Record<string, unknown>).annual_revenue_usd as number | null;
          const trust = (org as unknown as Record<string, unknown>).trust_score as number | null ?? org.lead_score;
          const dossierUrl = `/company/${orgId}${domain ? `?domain=${encodeURIComponent(domain)}` : ""}`;

          return (
            <tr
              key={orgId}
              className="hover:bg-muted/40 transition-colors group cursor-pointer"
            >
              {/* Organization Name */}
              <TD className="font-medium">
                <Link
                  href={dossierUrl}
                  className="flex items-center gap-2 hover:text-primary transition-colors"
                >
                  <div className="w-6 h-6 rounded bg-primary/10 flex items-center justify-center text-primary flex-shrink-0 text-[11px] font-bold">
                    {companyName.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0 max-w-[200px]">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="truncate font-semibold text-foreground group-hover:text-primary transition-colors" title={companyName}>
                        {companyName}
                      </span>
                      {(org as any).updated_at && String((org as any).updated_at).startsWith("2026-11-22") ? (
                        <span className="px-1 py-0.2 rounded text-[9px] font-semibold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/25 shrink-0">
                          Updated today
                        </span>
                      ) : null}
                    </div>
                    {org.ein && (
                      <div className="text-[10px] text-muted-foreground font-mono">
                        EIN: {org.ein}
                      </div>
                    )}
                  </div>
                </Link>
              </TD>

              {/* Domain */}
              <TD>
                {domain ? (
                  <a
                    href={`https://${domain}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-primary hover:underline font-mono text-[11.5px]"
                    onClick={(e) => e.stopPropagation()}
                    title={domain}
                  >
                    <Globe className="w-3 h-3 text-muted-foreground/60 flex-shrink-0" />
                    <span className="truncate max-w-[150px]">{domain}</span>
                    <ExternalLink className="w-2.5 h-2.5 opacity-60" />
                  </a>
                ) : (
                  <span className="text-muted-foreground/30 text-[11px]">—</span>
                )}
              </TD>

              {/* Industry */}
              <TD className="text-muted-foreground max-w-[150px]">
                <span className="truncate block" title={org.industry || "General Commercial"}>
                  {org.industry || "General Commercial"}
                </span>
              </TD>

              {/* Rating & Reviews */}
              <TD className="whitespace-nowrap">
                {(org as any).rating ? (
                  <div className="flex items-center gap-1">
                    <Star className="size-3 fill-amber-500 text-amber-500 shrink-0" />
                    <span className="font-mono text-xs font-semibold text-amber-600 dark:text-amber-400">
                      {Number((org as any).rating).toFixed(1)}
                    </span>
                    <span className="text-[10px] text-muted-foreground/80 font-sans">
                      ({(org as any).review_count || 0})
                    </span>
                  </div>
                ) : (
                  <span className="text-muted-foreground/40 text-[11px]">—</span>
                )}
              </TD>

              {/* Region */}
              <TD>
                <JurisdictionBadge
                  jurisdiction={(org as unknown as Record<string, unknown>).jurisdiction as string}
                  country={org.country}
                />
              </TD>

              {/* Size */}
              <TD className="text-muted-foreground font-mono text-[11.5px] whitespace-nowrap hidden lg:table-cell">
                {org.employee_band || "1-50"}
              </TD>

              {/* Revenue */}
              <TD className="font-mono text-[11.5px] text-muted-foreground whitespace-nowrap hidden xl:table-cell">
                {formatCurrency(revenue)}
              </TD>

              {/* Trust Score */}
              <TD className="whitespace-nowrap text-center">
                <ScoreCell score={trust} />
              </TD>

              {/* Action Link to Company Dossier */}
              <TD className="text-right pr-4 whitespace-nowrap">
                <Link
                  href={dossierUrl}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium text-primary bg-primary/10 hover:bg-primary/20 transition-colors"
                >
                  <span>Dossier</span>
                  <ChevronRight className="w-3 h-3" />
                </Link>
              </TD>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
