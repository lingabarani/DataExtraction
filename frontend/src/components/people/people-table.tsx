"use client";

import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Users, ShieldCheck, ShieldAlert, ShieldOff, Minus,
  Phone, Globe, ChevronRight, ExternalLink, Mail,
} from "lucide-react";
import type { Lead } from "@/hooks/use-leads";
import { cn } from "@/lib/utils";

// ── Seniority Styling ─────────────────────────────────────────────────────────

const SEN_COLOR: Record<string, string> = {
  C_SUITE:   "text-violet-600 bg-violet-50 border-violet-200 dark:bg-violet-950/30 dark:border-violet-800/50",
  VP:        "text-blue-600 bg-blue-50 border-blue-200 dark:bg-blue-950/30 dark:border-blue-800/50",
  DIRECTOR:  "text-indigo-600 bg-indigo-50 border-indigo-200 dark:bg-indigo-950/30 dark:border-indigo-800/50",
  MANAGER:   "text-cyan-700 bg-cyan-50 border-cyan-200 dark:bg-cyan-950/30 dark:border-cyan-800/50",
  FOUNDER:   "text-amber-700 bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-800/50",
  OWNER:     "text-amber-700 bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-800/50",
  EXECUTIVE: "text-purple-600 bg-purple-50 border-purple-200 dark:bg-purple-950/30 dark:border-purple-800/50",
};

const SEN_LABEL: Record<string, string> = {
  C_SUITE:   "C-Suite",
  VP:        "VP",
  DIRECTOR:  "Director",
  MANAGER:   "Manager",
  FOUNDER:   "Founder",
  OWNER:     "Owner",
  EXECUTIVE: "Executive",
};

function SeniorityBadge({ level }: { level?: string | null }) {
  if (!level) return <span className="text-muted-foreground/30 text-[11px]">—</span>;
  const key = level.toUpperCase().replace(/\s+/g, "_");
  const color = SEN_COLOR[key] || "text-muted-foreground bg-muted border-border";
  const label = SEN_LABEL[key] || level;

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${color}`}>
      {label}
    </span>
  );
}

// ── Email Status Icon ─────────────────────────────────────────────────────────

function EmailIcon({ status }: { status: string | null }) {
  if (status === "DELIVERABLE" || status === "VERIFIED") {
    return <span title="Deliverable (RFC 5322 verified)"><ShieldCheck className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" /></span>;
  }
  if (status === "MX_CONFIRMED" || status === "VALID") {
    return <span title="MX Record Confirmed"><ShieldCheck className="w-3.5 h-3.5 text-blue-500" /></span>;
  }
  if (status === "SYNTAX_VALID") {
    return <span title="Syntax Valid"><ShieldCheck className="w-3.5 h-3.5 text-indigo-400" /></span>;
  }
  if (status === "RISKY" || status === "GUESSED") {
    return <span title="Risky"><ShieldAlert className="w-3.5 h-3.5 text-amber-500" /></span>;
  }
  if (status === "UNDELIVERABLE" || status === "INVALID") {
    return <span title="Undeliverable / Invalid"><ShieldOff className="w-3.5 h-3.5 text-red-500" /></span>;
  }
  return <Minus className="w-3.5 h-3.5 text-muted-foreground/30" />;
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

// ── Main PeopleTable ──────────────────────────────────────────────────────────

interface Props {
  people:  Lead[];
  loading: boolean;
  table?:  "us_leads" | "mexico_leads";
}

export function PeopleTable({ people, loading, table = "us_leads" }: Props) {
  if (loading) {
    return (
      <table className="w-full text-left">
        <thead>
          <tr>
            <TH>Executive Person</TH>
            <TH>Seniority</TH>
            <TH>Title</TH>
            <TH>Company & Location</TH>
            <TH>Verified Email & Phone</TH>
            <TH>Score</TH>
            <TH className="text-right pr-4">Action</TH>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {Array.from({ length: 12 }).map((_, i) => (
            <tr key={i}>
              <TD><Skeleton className="h-4 w-32" /></TD>
              <TD><Skeleton className="h-4 w-16" /></TD>
              <TD><Skeleton className="h-4 w-28" /></TD>
              <TD><Skeleton className="h-4 w-36" /></TD>
              <TD><Skeleton className="h-4 w-36" /></TD>
              <TD><Skeleton className="h-4 w-12" /></TD>
              <TD className="text-right pr-4"><Skeleton className="h-4 w-16 ml-auto" /></TD>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  if (!people.length) {
    return (
      <div className="py-20 text-center text-muted-foreground text-sm flex flex-col items-center gap-2">
        <Users className="w-8 h-8 text-muted-foreground/40 mb-1" />
        <p className="font-medium text-foreground">No executive decision-makers found</p>
        <p className="text-xs text-muted-foreground">Try adjusting your filters, seniority level, or search keywords.</p>
      </div>
    );
  }

  return (
    <table className="w-full text-left">
      <thead>
        <tr>
          <TH className="w-[20%] min-w-[160px]">Executive Person</TH>
          <TH className="w-[10%] min-w-[75px]">Seniority</TH>
          <TH className="w-[18%] min-w-[140px]">Title</TH>
          <TH className="w-[22%] min-w-[160px]">Company & Location</TH>
          <TH className="w-[20%] min-w-[170px]">Verified Email & Phone</TH>
          <TH className="w-[5%] min-w-[55px] text-center">Score</TH>
          <TH className="w-[5%] min-w-[75px] text-right pr-4">Dossier</TH>
        </tr>
      </thead>
      <tbody className="divide-y divide-border/60">
        {people.map((person, idx) => {
          const personId = person.id || `person-${idx}`;
          const fullName = person.full_name || "Executive Lead";
          const title = person.standardized_title || person.title || "Leader";
          const companyName = person.company_name || "Commercial Entity";
          const companyId = person.company_id || "";
          const domain = person.domain;
          const location = [person.city, person.state_code || person.state, person.country]
            .filter(Boolean)
            .join(", ");
          const personUrl = `/leads/${personId}?table=${table}`;
          const companyUrl = companyId ? `/company/${companyId}${domain ? `?domain=${encodeURIComponent(domain)}` : ""}` : null;

          return (
            <tr
              key={personId}
              className="hover:bg-muted/40 transition-colors group cursor-pointer"
            >
              {/* Executive Person */}
              <TD className="font-medium">
                <Link
                  href={personUrl}
                  className="flex items-center gap-2 hover:text-primary transition-colors"
                >
                  <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center text-primary flex-shrink-0 text-[11px] font-bold">
                    {fullName.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0 max-w-[180px]">
                    <div className="truncate font-semibold text-foreground group-hover:text-primary transition-colors" title={fullName}>
                      {fullName}
                    </div>
                  </div>
                </Link>
              </TD>

              {/* Seniority */}
              <TD>
                <SeniorityBadge level={person.seniority_level} />
              </TD>

              {/* Title */}
              <TD className="text-muted-foreground max-w-[170px]">
                <span className="truncate block" title={title}>
                  {title}
                </span>
              </TD>

              {/* Company & Location */}
              <TD className="max-w-[200px]">
                {companyUrl ? (
                  <Link
                    href={companyUrl}
                    className="truncate block font-medium hover:text-primary hover:underline transition-colors"
                    title={companyName}
                  >
                    {companyName}
                  </Link>
                ) : (
                  <span className="truncate block font-medium text-foreground" title={companyName}>
                    {companyName}
                  </span>
                )}
                <div className="flex items-center gap-1.5 text-[10.5px] text-muted-foreground/70 font-mono truncate" title={`${domain ? `@${domain}` : ""} ${location ? `· ${location}` : ""}`}>
                  {domain && <span>@{domain}</span>}
                  {location && <span>· {location}</span>}
                </div>
              </TD>

              {/* Verified Email & Phone */}
              <TD className="font-mono text-[11.5px]">
                {person.email ? (
                  <div className="flex items-center gap-1.5 max-w-[190px]">
                    <EmailIcon status={person.email_status} />
                    <span className="truncate" title={person.email}>
                      {person.email}
                    </span>
                  </div>
                ) : (
                  <span className="text-muted-foreground/30 text-[11px]">—</span>
                )}
                {person.phone && person.phone !== "N/A" && (
                  <div className="flex items-center gap-1 text-[10.5px] text-muted-foreground/75 mt-0.5" title={person.phone}>
                    <Phone className="w-2.5 h-2.5 text-emerald-600/70 dark:text-emerald-400/70 flex-shrink-0" />
                    <span>{person.phone}</span>
                  </div>
                )}
              </TD>

              {/* Score */}
              <TD className="whitespace-nowrap text-center">
                <ScoreCell score={person.lead_score} />
              </TD>

              {/* Action Link to Person Dossier */}
              <TD className="text-right pr-4 whitespace-nowrap">
                <Link
                  href={personUrl}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-semibold text-primary bg-primary/10 hover:bg-primary/20 transition-colors shadow-2xs"
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
