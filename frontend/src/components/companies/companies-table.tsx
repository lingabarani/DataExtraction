"use client";

import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Building2, ExternalLink, ChevronRight } from "lucide-react";
import type { Lead } from "@/hooks/use-leads";
import {
  formatEmployeeBadge,
  formatRelativeSync,
  formatRevenueBadge,
  normalizePercentScore,
} from "@/lib/formatters";
import { cn } from "@/lib/utils";

interface Props {
  companies: Lead[];
  loading: boolean;
}

export function CompaniesTable({ companies, loading }: Props) {
  if (loading) {
    return (
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-border bg-muted/35 text-xs font-semibold text-muted-foreground">
            <th className="px-4 py-3.5">Company &amp; Domain</th>
            <th className="px-4 py-3.5">Industry</th>
            <th className="px-4 py-3.5">Revenue</th>
            <th className="px-4 py-3.5">Employees</th>
            <th className="px-4 py-3.5">Trust Score</th>
            <th className="px-4 py-3.5">Sources</th>
            <th className="px-4 py-3.5">Last Synced</th>
            <th className="px-4 py-3.5 text-right">Dossier</th>
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: 10 }).map((_, i) => (
            <tr key={i} className="border-b border-border/50">
              <td className="px-4 py-4"><Skeleton className="h-5 w-44" /></td>
              <td className="px-4 py-4"><Skeleton className="h-6 w-28 rounded-lg" /></td>
              <td className="px-4 py-4"><Skeleton className="h-6 w-20 rounded-lg" /></td>
              <td className="px-4 py-4"><Skeleton className="h-6 w-24 rounded-lg" /></td>
              <td className="px-4 py-4"><Skeleton className="h-2.5 w-28 rounded-full" /></td>
              <td className="px-4 py-4"><Skeleton className="h-6 w-16 rounded-lg" /></td>
              <td className="px-4 py-4"><Skeleton className="h-4 w-20" /></td>
              <td className="px-4 py-4 text-right"><Skeleton className="h-7 w-16 ml-auto rounded-lg" /></td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  if (!companies.length) {
    return (
      <div className="py-20 text-center text-muted-foreground flex flex-col items-center gap-2">
        <Building2 className="size-10 text-muted-foreground/40 mb-1" />
        <p className="text-base font-semibold text-foreground">No organizations found</p>
        <p className="text-sm text-muted-foreground">
          Try broadening your search or resetting industry and regional filters.
        </p>
      </div>
    );
  }

  return (
    <table className="w-full text-left border-collapse">
      <thead>
        <tr className="border-b border-border bg-muted/35 text-xs font-semibold text-muted-foreground">
          <th className="px-4 py-3.5 min-w-[250px]">Company &amp; Domain</th>
          <th className="px-4 py-3.5 min-w-[160px]">Industry</th>
          <th className="px-4 py-3.5 min-w-[120px]">Revenue</th>
          <th className="px-4 py-3.5 min-w-[130px]">Employees</th>
          <th className="px-4 py-3.5 min-w-[150px]">Trust Score</th>
          <th className="px-4 py-3.5 min-w-[100px]">Sources</th>
          <th className="px-4 py-3.5 min-w-[120px]">Last Synced</th>
          <th className="px-4 py-3.5 text-right min-w-[100px]">Dossier</th>
        </tr>
      </thead>
      <tbody>
        {companies.map((org, idx) => {
          const orgId = org.id || org.company_id || `org-${idx}`;
          const companyName = org.company_name || "Commercial Entity";
          const domain = org.domain;
          const recordObj = org as unknown as Record<string, unknown>;
          const revenue = recordObj.annual_revenue_usd as number | null | undefined;
          const trustPct = normalizePercentScore(
            (recordObj.trust_score as number | null | undefined) ?? org.lead_score,
            85
          );
          const rawSourceCount =
            (recordObj.source_count as number | null | undefined) ??
            org.company?.source_count;
          const sourceCount =
            typeof rawSourceCount === "number" && rawSourceCount > 0
              ? rawSourceCount
              : 1;
          const empMin =
            (recordObj.employee_min as number | null | undefined) ??
            org.company?.employee_min;
          const empMax =
            (recordObj.employee_max as number | null | undefined) ??
            org.company?.employee_max;
          const lastSynced =
            (recordObj.last_verified_at as string | null | undefined) ??
            org.company?.last_verified_at ??
            org.updated_at;
          const dossierUrl = `/company/${orgId}${domain ? `?domain=${encodeURIComponent(domain)}` : ""}`;

          return (
            <tr
              key={orgId}
              className="group border-b border-border/60 transition-colors duration-200 odd:bg-card even:bg-slate-50/70 dark:even:bg-slate-900/35 hover:bg-primary/[0.04] dark:hover:bg-primary/[0.08]"
            >
              {/* Logo + Company + Domain */}
              <td className="px-4 py-4">
                <Link href={dossierUrl} className="flex items-center gap-3.5 min-w-0">
                  <Avatar className="size-10 rounded-xl border border-border/70 shrink-0">
                    <AvatarFallback className="rounded-xl bg-primary/10 text-sm font-semibold text-primary">
                      {companyName.charAt(0).toUpperCase()}
                    </AvatarFallback>
                  </Avatar>
                  <div className="min-w-0 max-w-[220px]">
                    <p
                      className="truncate text-sm font-semibold text-foreground group-hover:text-primary transition-colors"
                      title={companyName}
                    >
                      {companyName}
                    </p>
                    {domain ? (
                      <span className="inline-flex items-center gap-1 text-xs font-mono text-muted-foreground truncate max-w-full">
                        <span className="truncate">{domain}</span>
                        <ExternalLink className="size-3 opacity-50 shrink-0" />
                      </span>
                    ) : (
                      <span className="text-xs font-mono text-muted-foreground/50">
                        Domain unlisted
                      </span>
                    )}
                  </div>
                </Link>
              </td>

              {/* Industry Badge */}
              <td className="px-4 py-4">
                <Badge
                  variant="secondary"
                  className="rounded-lg px-2.5 py-1 text-xs font-medium max-w-[180px] truncate"
                >
                  {org.industry || "Commercial Services"}
                </Badge>
              </td>

              {/* Revenue Badge */}
              <td className="px-4 py-4">
                <Badge
                  variant="outline"
                  className="rounded-lg px-2.5 py-1 text-xs font-medium tabular-nums whitespace-nowrap"
                >
                  {formatRevenueBadge(revenue)}
                </Badge>
              </td>

              {/* Employee Badge */}
              <td className="px-4 py-4">
                <Badge
                  variant="outline"
                  className="rounded-lg px-2.5 py-1 text-xs font-medium tabular-nums whitespace-nowrap"
                >
                  {formatEmployeeBadge(empMin, empMax, org.employee_band)}
                </Badge>
              </td>

              {/* Trust Score Progress Bar */}
              <td className="px-4 py-4">
                <div className="flex items-center gap-2.5 min-w-[120px]">
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn(
                        "h-full rounded-full",
                        trustPct >= 80
                          ? "bg-success"
                          : trustPct >= 50
                            ? "bg-warning"
                            : "bg-destructive"
                      )}
                      style={{ width: `${trustPct}%` }}
                    />
                  </div>
                  <span className="w-9 text-right text-xs font-semibold text-foreground tabular-nums">
                    {trustPct}%
                  </span>
                </div>
              </td>

              {/* Source Count */}
              <td className="px-4 py-4">
                <span className="inline-flex items-center rounded-lg bg-muted/70 px-2.5 py-1 text-xs font-medium text-foreground tabular-nums whitespace-nowrap">
                  {sourceCount} {sourceCount === 1 ? "source" : "sources"}
                </span>
              </td>

              {/* Last Synced */}
              <td className="px-4 py-4 text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                {formatRelativeSync(lastSynced)}
              </td>

              {/* Action */}
              <td className="px-4 py-4 text-right whitespace-nowrap">
                <Link
                  href={dossierUrl}
                  className="inline-flex items-center gap-1 rounded-lg bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary hover:text-primary-foreground transition-colors"
                >
                  <span>Dossier</span>
                  <ChevronRight className="size-3.5" />
                </Link>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
