"use client";

import * as React from "react";
import {
  Building2,
  Users,
  ExternalLink,
  ShieldCheck,
  Mail,
  Phone,
  MapPin,
  Sparkles,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { CompanyRecord, PeopleRecord } from "@/lib/prospecting-api";
import {
  formatEmployeeBadge,
  formatRelativeSync,
  formatRevenueBadge,
  normalizePercentScore,
} from "@/lib/formatters";
import { cn } from "@/lib/utils";

interface RowPreviewPanelProps {
  company: CompanyRecord | null;
  person: PeopleRecord | null;
  onOpenFullDrawer: () => void;
  onDismiss: () => void;
}

export function RowPreviewPanel({
  company,
  person,
  onOpenFullDrawer,
  onDismiss,
}: RowPreviewPanelProps) {
  if (!company && !person) return null;

  const trustPct = company
    ? normalizePercentScore(company.trust_score, 85)
    : normalizePercentScore(person?.trust_score, 88);

  return (
    <aside
      aria-label="Selected entity quick preview"
      className="flex items-start justify-between gap-4 rounded-2xl border border-primary/25 bg-card p-5 shadow-card animate-slide-up"
    >
      <div className="flex items-start gap-4 min-w-0 flex-1">
        <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary font-semibold text-lg">
          {company ? (
            company.legal_name.charAt(0).toUpperCase()
          ) : person ? (
            person.full_name.charAt(0).toUpperCase()
          ) : (
            <Building2 className="size-5" />
          )}
        </div>

        <div className="min-w-0 flex-1 flex flex-col gap-2">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h3 className="text-base font-semibold text-foreground truncate">
              {company ? company.legal_name : person?.full_name}
            </h3>
            {company?.primary_domain && (
              <Badge variant="outline" className="rounded-lg font-mono text-xs">
                {company.primary_domain}
              </Badge>
            )}
            {person?.seniority_level && (
              <Badge variant="secondary" className="rounded-lg text-xs">
                {person.seniority_level.replace(/_/g, " ")}
              </Badge>
            )}
          </div>

          <p className="text-sm text-muted-foreground truncate">
            {company
              ? `${company.sub_industry || company.industry} · ${company.city ? `${company.city}, ` : ""}${company.state_code || company.jurisdiction}`
              : `${person?.title} at ${person?.company_name}`}
          </p>

          {/* Key Preview Badges */}
          <div className="flex items-center gap-3 flex-wrap pt-1 text-xs text-muted-foreground">
            {company ? (
              <>
                <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
                  <ShieldCheck className="size-3.5 text-success" />
                  <span className="tabular-nums">{trustPct}% Trust</span>
                </span>
                <span>Revenue: {formatRevenueBadge(company.annual_revenue_usd)}</span>
                <span>
                  Size:{" "}
                  {formatEmployeeBadge(
                    company.employee_count_min,
                    company.employee_count_max
                  )}
                </span>
                <span>
                  Synced {formatRelativeSync(company.last_verified_at || company.updated_at)}
                </span>
              </>
            ) : (
              <>
                {person?.email && (
                  <span className="inline-flex items-center gap-1.5 font-mono text-foreground">
                    <Mail className="size-3.5 text-primary" />
                    <span>{person.email}</span>
                  </span>
                )}
                {person?.phone && (
                  <span className="inline-flex items-center gap-1.5 font-mono text-foreground">
                    <Phone className="size-3.5 text-success" />
                    <span>{person.phone}</span>
                  </span>
                )}
                <span className="inline-flex items-center gap-1">
                  <MapPin className="size-3.5" />
                  <span>{person?.state_code || "US"}</span>
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <Button
          type="button"
          size="sm"
          onClick={onOpenFullDrawer}
          className="h-9 rounded-xl px-3.5 text-xs font-medium gap-1.5"
        >
          <Sparkles className="size-3.5" />
          <span>Full Intelligence</span>
          <ExternalLink className="size-3" />
        </Button>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label="Close quick preview"
        >
          <X className="size-4" />
        </button>
      </div>
    </aside>
  );
}
