"use client";
import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ChevronRight, Users, ShieldCheck, ShieldAlert,
  ShieldOff, Minus, Phone, Globe,
} from "lucide-react";
import type { Lead } from "@/hooks/use-leads";
import { cn } from "@/lib/utils";

// ── Source labels ─────────────────────────────────────────────────────────────

const SRC: Record<string, string> = {
  CMS_NPI:        "NPI",
  SEC_EDGAR:      "SEC",
  FDIC:           "FDIC",
  NCUA:           "NCUA",
  USASPENDING:    "SPEND",
  PROPUBLICA_990: "990",
  SAM_GOV:        "SAM",
  CSV:            "CSV",
  INTERNAL_JSON:  "INT",
  DB:             "DB",
};

// ── Seniority abbreviations ───────────────────────────────────────────────────

const SEN: Record<string, string> = {
  C_SUITE:  "C",
  VP:       "VP",
  DIRECTOR: "DIR",
  MANAGER:  "MGR",
  FOUNDER:  "FND",
  OWNER:    "OWN",
};

const SEN_COLOR: Record<string, string> = {
  C_SUITE:  "text-violet-600 bg-violet-50 border-violet-200 dark:bg-violet-950/30 dark:border-violet-800/50",
  VP:       "text-blue-600 bg-blue-50 border-blue-200 dark:bg-blue-950/30 dark:border-blue-800/50",
  DIRECTOR: "text-indigo-600 bg-indigo-50 border-indigo-200 dark:bg-indigo-950/30 dark:border-indigo-800/50",
  MANAGER:  "text-cyan-700 bg-cyan-50 border-cyan-200 dark:bg-cyan-950/30 dark:border-cyan-800/50",
  FOUNDER:  "text-amber-700 bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-800/50",
  OWNER:    "text-amber-700 bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-800/50",
};

// ── Email status icon ─────────────────────────────────────────────────────────

function EmailIcon({ status }: { status: string | null }) {
  if (status === "DELIVERABLE" || status === "VERIFIED") return <span title="Deliverable (verified)"><ShieldCheck className="w-3 h-3 text-emerald-600" /></span>;
  if (status === "MX_CONFIRMED" || status === "VALID")    return <span title="MX Confirmed"><ShieldCheck className="w-3 h-3 text-blue-500" /></span>;
  if (status === "SYNTAX_VALID")                         return <span title="Syntax Valid"><ShieldCheck className="w-3 h-3 text-indigo-400" /></span>;
  if (status === "RISKY" || status === "GUESSED")        return <span title="Risky"><ShieldAlert className="w-3 h-3 text-amber-500" /></span>;
  if (status === "UNDELIVERABLE" || status === "INVALID") return <span title="Undeliverable / Invalid"><ShieldOff className="w-3 h-3 text-red-500" /></span>;
  return <Minus className="w-3 h-3 text-muted-foreground/30" />;
}

// ── Score cell ────────────────────────────────────────────────────────────────

function ScoreCell({ score }: { score: number | null }) {
  if (!score) return <span className="text-muted-foreground/30 text-[12px]">—</span>;
  const color = score >= 80 ? "text-emerald-600"
              : score >= 50 ? "text-amber-600"
              :               "text-red-500";
  return <span className={`text-[12px] font-mono tabnum font-medium ${color}`}>{score}</span>;
}

// ── TH ────────────────────────────────────────────────────────────────────────

function TH({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={cn(
      "px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest",
      "text-muted-foreground whitespace-nowrap bg-muted/50 border-b border-border",
      className
    )}>
      {children}
    </th>
  );
}

// ── TD ────────────────────────────────────────────────────────────────────────

function TD({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <td className={cn("px-3 py-[7px] text-[12px] align-middle", className)}>
      {children}
    </td>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  leads:   Lead[];
  loading: boolean;
  table?:  "us_leads" | "mexico_leads";
}

export function LeadsTable({ leads, loading, table = "us_leads" }: Props) {

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (loading) {
    return (
      <table className="w-full min-w-[900px]">
        <thead>
          <tr>
            {["Person","Seniority","Title","Company","Industry","Email","Phone","Location","Score","Src",""].map(h => (
              <TH key={h}>{h}</TH>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {Array.from({ length: 12 }).map((_, i) => (
            <tr key={i}>
              {Array.from({ length: 11 }).map((_, j) => (
                <TD key={j}><Skeleton className="h-3.5 w-full" /></TD>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  // ── Empty state ───────────────────────────────────────────────────────────
  if (!leads.length) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3 text-center">
        <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center">
          <Users className="w-5 h-5 text-muted-foreground" />
        </div>
        <div>
          <p className="text-[13px] font-medium">No results found</p>
          <p className="text-[12px] text-muted-foreground mt-0.5">
            Try adjusting your search filters
          </p>
        </div>
      </div>
    );
  }

  // ── Table ─────────────────────────────────────────────────────────────────
  return (
    <table className="w-full min-w-[920px] border-collapse">
      <thead>
        <tr>
          <TH className="pl-4 sticky left-0 z-10">Person</TH>
          <TH>Seniority</TH>
          <TH>Title</TH>
          <TH>Company</TH>
          <TH>Industry</TH>
          <TH>Email</TH>
          <TH>Phone</TH>
          <TH>Location</TH>
          <TH className="text-right pr-3">Score</TH>
          <TH>Src</TH>
          <TH className="w-8" />
        </tr>
      </thead>
      <tbody className="divide-y divide-border/60">
        {leads.map(lead => (
          <tr
            key={lead.id}
            className="group hover:bg-muted/40 transition-colors duration-75"
          >
            {/* Person */}
            <TD className="pl-4 sticky left-0 bg-background group-hover:bg-muted/40 transition-colors z-10 min-w-[160px]">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-muted border border-border flex items-center justify-center text-[10px] font-semibold text-muted-foreground flex-shrink-0 uppercase">
                  {(lead.full_name ?? lead.company_name ?? "?").charAt(0)}
                </div>
                <span className="truncate max-w-[130px] font-medium text-foreground" title={lead.full_name ?? ""}>
                  {lead.full_name ?? <span className="text-muted-foreground italic font-normal">No name</span>}
                </span>
              </div>
            </TD>

            {/* Seniority badge */}
            <TD className="min-w-[60px]">
              {lead.seniority_level ? (
                <span className={cn(
                  "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border",
                  SEN_COLOR[lead.seniority_level] ?? "bg-muted text-muted-foreground border-border"
                )}>
                  {SEN[lead.seniority_level] ?? lead.seniority_level.slice(0, 3)}
                </span>
              ) : (
                <span className="text-muted-foreground/30">—</span>
              )}
            </TD>

            {/* Title */}
            <TD className="min-w-[140px] max-w-[180px]">
              <span className="truncate block text-muted-foreground" title={lead.title ?? ""}>
                {lead.standardized_title ?? lead.title ?? "—"}
              </span>
            </TD>

            {/* Company */}
            <TD className="min-w-[160px]">
              <div>
                <p className="font-medium truncate max-w-[150px]" title={lead.company_name ?? ""}>
                  {lead.company_name ?? "—"}
                </p>
                {lead.domain && (
                  <a
                    href={`https://${lead.domain}`}
                    target="_blank"
                    rel="noreferrer"
                    onClick={e => e.stopPropagation()}
                    className="flex items-center gap-0.5 text-[11px] text-accent hover:underline"
                  >
                    <Globe className="w-2.5 h-2.5 flex-shrink-0" />
                    {lead.domain}
                  </a>
                )}
              </div>
            </TD>

            {/* Industry */}
            <TD className="min-w-[110px] max-w-[140px]">
              <span className="truncate block text-muted-foreground" title={lead.industry ?? ""}>
                {lead.industry ?? "—"}
              </span>
            </TD>

            {/* Email */}
            <TD className="min-w-[170px]">
              <div className="flex items-center gap-1.5">
                <EmailIcon status={lead.email_status} />
                <span className="truncate max-w-[140px] font-mono text-[11px]" title={lead.email ?? ""}>
                  {lead.email ?? <span className="text-muted-foreground/30 not-italic font-sans">—</span>}
                </span>
              </div>
              {lead.email_confidence_score != null && lead.email_confidence_score > 0 && (
                <p className="text-[10px] text-muted-foreground/50 font-mono pl-4 mt-0.5">
                  {lead.email_confidence_score}%
                </p>
              )}
            </TD>

            {/* Phone */}
            <TD className="min-w-[130px]">
              {lead.phone ? (
                <div className="flex items-center gap-1.5">
                  <Phone className="w-3 h-3 text-muted-foreground/40 flex-shrink-0" />
                  <span className="font-mono text-[11px] tabnum">{lead.phone}</span>
                </div>
              ) : (
                <span className="text-muted-foreground/30">—</span>
              )}
            </TD>

            {/* Location */}
            <TD className="min-w-[90px]">
              <span className="text-muted-foreground font-mono text-[11px]">
                {[lead.city?.slice(0,12), lead.state_code].filter(Boolean).join(", ") || "—"}
              </span>
            </TD>

            {/* Score */}
            <TD className="text-right pr-3 min-w-[50px]">
              <ScoreCell score={lead.lead_score} />
            </TD>

            {/* Source */}
            <TD className="min-w-[48px]">
              <span className="text-[10px] font-mono text-muted-foreground tabnum">
                {SRC[lead.api_source ?? ""] ?? (lead.api_source?.slice(0, 4) ?? "—")}
              </span>
            </TD>

            {/* Detail arrow */}
            <TD className="pr-3 w-8">
              <Link
                href={`/leads/${lead.id}?table=${table}`}
                className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center"
              >
                <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />
              </Link>
            </TD>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
