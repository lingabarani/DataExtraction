"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Building2,
  Users,
  ExternalLink,
  ShieldCheck,
  Send,
  Flame,
  CheckCircle2,
  Cpu,
  Mail,
  Phone,
  Linkedin,
  MapPin,
  Loader2,
  Sparkles,
  Star,
  MessageSquare,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { api } from "@/lib/api";
import {
  CompanyRecord,
  PeopleRecord,
  DecisionMaker,
  prospectingApi,
} from "@/lib/prospecting-api";
import {
  formatEmployeeBadge,
  formatRevenueBadge,
  normalizePercentScore,
} from "@/lib/formatters";
import { cn } from "@/lib/utils";

interface DetailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  company: CompanyRecord | null;
  person: PeopleRecord | null;
  onPushToOneReach: (type: "company" | "person", id: string) => Promise<void>;
  isPushing: boolean;
}

export function DetailDrawer({
  isOpen,
  onClose,
  company,
  person,
  onPushToOneReach,
  isPushing,
}: DetailDrawerProps) {
  const [activeTab, setActiveTab] = useState<
    "overview" | "reviews" | "tech" | "compliance" | "leadership"
  >("overview");
  const [decisionMakers, setDecisionMakers] = useState<DecisionMaker[]>([]);
  const [isLoadingLeaders, setIsLoadingLeaders] = useState(false);
  const [reviewsData, setReviewsData] = useState<any>(null);
  const [isLoadingReviews, setIsLoadingReviews] = useState(false);

  useEffect(() => {
    if (!company || !isOpen) return;
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setActiveTab("overview");
      setIsLoadingLeaders(true);
      setIsLoadingReviews(true);
      const dom = company.primary_domain || "";

      const [leadersRes, reviewsRes] = await Promise.allSettled([
        prospectingApi.getCompanyDecisionMakers(company.org_id),
        api.get<any>(
          `/leads/company/${encodeURIComponent(company.org_id)}/intelligence?domain=${encodeURIComponent(dom)}`
        ),
      ]);

      if (!active) return;
      setDecisionMakers(
        leadersRes.status === "fulfilled" ? leadersRes.value.decision_makers || [] : []
      );
      setReviewsData(
        reviewsRes.status === "fulfilled" ? reviewsRes.value?.reviews ?? null : null
      );
      setIsLoadingLeaders(false);
      setIsLoadingReviews(false);
    });
    return () => {
      active = false;
    };
  }, [company, isOpen]);

  const titleText = company ? company.legal_name : person?.full_name || "Entity Details";
  const subtitleText = company
    ? `${company.industry} · ${company.city ? `${company.city}, ` : ""}${company.state_code || company.jurisdiction}`
    : person
      ? `${person.title} at ${person.company_name}`
      : "";

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-2xl p-0 flex flex-col overflow-hidden bg-card"
      >
        {/* Accessible Header */}
        <SheetHeader className="p-6 border-b border-border bg-muted/25 pr-12 text-left">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-3.5 min-w-0">
              <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary font-semibold text-lg">
                {company
                  ? company.legal_name.charAt(0).toUpperCase()
                  : person?.full_name.charAt(0).toUpperCase() || "E"}
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <SheetTitle className="text-xl font-semibold text-foreground truncate">
                    {titleText}
                  </SheetTitle>
                  {company?.primary_domain && (
                    <Badge variant="outline" className="rounded-lg font-mono text-xs">
                      {company.primary_domain}
                    </Badge>
                  )}
                  {person && (
                    <Badge variant="secondary" className="rounded-lg text-xs">
                      {(person.seniority_level || person.seniority || "C_SUITE").replace(/_/g, " ")}
                    </Badge>
                  )}
                </div>
                <SheetDescription className="text-sm text-muted-foreground mt-1 truncate">
                  {subtitleText}
                </SheetDescription>
              </div>
            </div>

            <Button
              size="sm"
              onClick={() => {
                if (company) onPushToOneReach("company", company.org_id);
                else if (person) onPushToOneReach("person", person.person_id);
              }}
              disabled={isPushing}
              className="h-9 rounded-xl px-3.5 text-xs font-medium gap-1.5 shrink-0"
            >
              {isPushing ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
              <span>Sync OneReach</span>
            </Button>
          </div>
        </SheetHeader>

        {/* Full Profile Outbound Link */}
        {(company || person) && (
          <div className="bg-primary/[0.04] border-b border-border/80 px-6 py-2.5 flex items-center justify-between text-xs">
            <span className="text-muted-foreground flex items-center gap-2 truncate">
              {company ? (
                <>
                  <Building2 className="size-3.5 text-primary shrink-0" />
                  <span>Explore full 360° firmographics, SSL &amp; org graph</span>
                </>
              ) : (
                <>
                  <Users className="size-3.5 text-primary shrink-0" />
                  <span>Explore verified career history &amp; deliverability logs</span>
                </>
              )}
            </span>
            <Link
              href={
                company
                  ? `/company/${company.org_id}${company.primary_domain ? `?domain=${encodeURIComponent(company.primary_domain)}` : ""}`
                  : `/leads/${person?.person_id}`
              }
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 font-semibold text-primary hover:underline shrink-0 ml-3"
            >
              <span>Open Full Dossier</span>
              <ExternalLink className="size-3" />
            </Link>
          </div>
        )}

        {/* Company Tab Navigation */}
        {company && (
          <div className="flex items-center border-b border-border px-6 bg-card text-xs overflow-x-auto scrollbar-none shrink-0">
            {[
              { id: "overview", label: "Overview" },
              { id: "leadership", label: `Leadership (${decisionMakers.length})` },
              { id: "reviews", label: `Reviews (${company.review_count || reviewsData?.total_scraped || 0})` },
              { id: "tech", label: "Tech Stack" },
              { id: "compliance", label: "Compliance" },
            ].map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id as any)}
                className={cn(
                  "py-3 px-3.5 border-b-2 font-medium transition-colors whitespace-nowrap",
                  activeTab === tab.id
                    ? "border-primary text-primary font-semibold"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6 scrollbar-enterprise">
          {company ? (
            activeTab === "overview" ? (
              <div className="flex flex-col gap-6">
                <div className="rounded-2xl border border-border/80 bg-muted/25 p-5">
                  <h4 className="text-sm font-semibold text-foreground flex items-center gap-2 mb-2">
                    <Sparkles className="size-4 text-primary" />
                    <span>Executive Summary</span>
                  </h4>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {company.short_description ||
                      `${company.legal_name} operates in the ${company.industry} sector (${company.jurisdiction}). Reconciled across verified corporate registries with a ${normalizePercentScore(company.trust_score, 85)}% trust rating.`}
                  </p>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                  <div className="rounded-xl border border-border/80 bg-card p-4">
                    <span className="text-meta text-muted-foreground">Trust Score</span>
                    <div className="mt-1.5 flex items-center gap-2 text-success font-semibold text-lg tabular-nums">
                      <ShieldCheck className="size-4" />
                      <span>{normalizePercentScore(company.trust_score, 85)}%</span>
                    </div>
                  </div>
                  <div className="rounded-xl border border-border/80 bg-card p-4">
                    <span className="text-meta text-muted-foreground">Revenue</span>
                    <p className="mt-1.5 text-lg font-semibold text-foreground tabular-nums">
                      {formatRevenueBadge(company.annual_revenue_usd)}
                    </p>
                  </div>
                  <div className="rounded-xl border border-border/80 bg-card p-4">
                    <span className="text-meta text-muted-foreground">Employees</span>
                    <p className="mt-1.5 text-sm font-semibold text-foreground tabular-nums">
                      {formatEmployeeBadge(company.employee_count_min, company.employee_count_max)}
                    </p>
                  </div>
                  <div className="rounded-xl border border-border/80 bg-card p-4">
                    <span className="text-meta text-muted-foreground">Buyer Intent</span>
                    <div className="mt-1.5 flex items-center gap-2">
                      <Flame className="size-4 text-warning" />
                      <span className="text-lg font-semibold text-foreground tabular-nums">
                        {Math.round(company.intent_score || 0)}
                      </span>
                    </div>
                  </div>
                </div>

                {company.intent_topics && company.intent_topics.length > 0 && (
                  <div className="rounded-2xl border border-border/80 bg-card p-5">
                    <h4 className="text-sm font-semibold text-foreground mb-3">
                      Active Buyer Intent Signals
                    </h4>
                    <div className="flex items-center gap-2 flex-wrap">
                      {company.intent_topics.map((topic) => (
                        <Badge key={topic} variant="secondary" className="rounded-lg text-xs">
                          {topic}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : activeTab === "reviews" ? (
              <div className="flex flex-col gap-5">
                {isLoadingReviews ? (
                  <div className="flex items-center justify-center h-36 gap-2 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin text-primary" />
                    <span>Loading sentiment analysis...</span>
                  </div>
                ) : (reviewsData?.total_scraped || 0) > 0 || (company.review_count || 0) > 0 ? (
                  <>
                    <div className="rounded-2xl border border-border/80 bg-muted/25 p-5 flex items-center justify-between gap-4">
                      <div>
                        <div className="flex items-baseline gap-2">
                          <span className="text-2xl font-semibold text-foreground tabular-nums">
                            {Number(reviewsData?.average_rating || company.rating || 0).toFixed(1)}
                          </span>
                          <span className="text-xs text-muted-foreground">/ 5.0</span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          {reviewsData?.total_scraped || company.review_count || 0} verified reviews
                        </p>
                      </div>
                      <div className="flex items-center gap-1 text-warning">
                        {[1, 2, 3, 4, 5].map((s) => (
                          <Star
                            key={s}
                            className={cn(
                              "size-4",
                              s <= Math.round(Number(reviewsData?.average_rating || company.rating || 0))
                                ? "fill-warning text-warning"
                                : "text-muted-foreground/30"
                            )}
                          />
                        ))}
                      </div>
                    </div>

                    {(reviewsData?.ai_summary?.pros?.length || company.praise_highlights?.length) && (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div className="rounded-xl border border-success/25 bg-success/5 p-4 flex flex-col gap-2">
                          <span className="flex items-center gap-1.5 text-xs font-semibold text-success">
                            <ThumbsUp className="size-3.5" /> Praise Highlights
                          </span>
                          <ul className="flex flex-col gap-1.5 text-xs text-foreground/85">
                            {(reviewsData?.ai_summary?.pros || company.praise_highlights || [])
                              .slice(0, 4)
                              .map((p: string, idx: number) => (
                                <li key={idx}>• {p}</li>
                              ))}
                          </ul>
                        </div>
                        <div className="rounded-xl border border-warning/25 bg-warning/5 p-4 flex flex-col gap-2">
                          <span className="flex items-center gap-1.5 text-xs font-semibold text-warning">
                            <ThumbsDown className="size-3.5" /> Watch Areas
                          </span>
                          <ul className="flex flex-col gap-1.5 text-xs text-foreground/85">
                            {(reviewsData?.ai_summary?.cons || company.complaint_alerts || [])
                              .slice(0, 4)
                              .map((c: string, idx: number) => (
                                <li key={idx}>• {c}</li>
                              ))}
                          </ul>
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="rounded-2xl border border-dashed border-border p-10 text-center flex flex-col items-center gap-2">
                    <MessageSquare className="size-8 text-muted-foreground/40" />
                    <p className="text-sm font-medium text-foreground">No reviews synchronized</p>
                    <p className="text-xs text-muted-foreground">
                      Customer sentiment data has not been linked to this entity yet.
                    </p>
                  </div>
                )}
              </div>
            ) : activeTab === "tech" ? (
              <div className="rounded-2xl border border-border/80 bg-card p-5 flex flex-col gap-3">
                <h4 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <Cpu className="size-4 text-primary" />
                  <span>Detected Technology Stack</span>
                </h4>
                {company.technologies?.length ? (
                  <div className="flex items-center gap-2 flex-wrap">
                    {company.technologies.map((tech) => (
                      <Badge key={tech} variant="secondary" className="rounded-lg px-3 py-1 text-xs">
                        {tech}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No technologies detected yet.</p>
                )}
              </div>
            ) : activeTab === "compliance" ? (
              <div className="rounded-2xl border border-border/80 bg-card p-5 flex flex-col gap-3">
                <h4 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <ShieldCheck className="size-4 text-success" />
                  <span>Security &amp; Compliance Certifications</span>
                </h4>
                {company.compliance_badges?.length ? (
                  <div className="grid grid-cols-2 gap-3">
                    {company.compliance_badges.map((badge) => (
                      <div
                        key={badge}
                        className="flex items-center gap-2 rounded-xl border border-success/25 bg-success/10 px-3 py-2.5 text-xs font-medium text-success"
                      >
                        <CheckCircle2 className="size-4 shrink-0" />
                        <span>{badge}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No compliance attestations listed.</p>
                )}
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {isLoadingLeaders ? (
                  <div className="flex items-center justify-center h-32 gap-2 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin text-primary" />
                    <span>Loading executives...</span>
                  </div>
                ) : decisionMakers.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
                    No executive contacts linked to this organization yet.
                  </div>
                ) : (
                  decisionMakers.map((leader) => (
                    <div
                      key={leader.person_id}
                      className="rounded-xl border border-border/80 bg-card p-4 flex items-center justify-between gap-4"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary font-semibold text-xs">
                          {leader.name.charAt(0).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-foreground truncate">{leader.name}</p>
                          <p className="text-xs text-muted-foreground truncate">{leader.title}</p>
                          {leader.email && (
                            <p className="text-xs font-mono text-primary truncate mt-0.5">
                              {leader.email}
                            </p>
                          )}
                        </div>
                      </div>
                      <Badge variant="outline" className="rounded-lg text-xs shrink-0">
                        {leader.seniority.replace(/_/g, " ")}
                      </Badge>
                    </div>
                  ))
                )}
              </div>
            )
          ) : person ? (
            <div className="flex flex-col gap-5">
              <div className="rounded-2xl border border-border/80 bg-muted/25 p-5 flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-foreground flex items-center gap-2">
                    <Mail className="size-4 text-primary" />
                    <span>Work Email Deliverability</span>
                  </span>
                  <Badge variant="success" className="rounded-lg">
                    Score: {person.deliverability_score ?? 90}/100
                  </Badge>
                </div>
                <div className="rounded-xl border border-border bg-card px-4 py-3 flex items-center justify-between">
                  <span className="font-mono text-sm text-foreground">{person.email || "Unavailable"}</span>
                  <span className="text-xs font-semibold text-success">
                    {person.deliverability_status || person.email_status || "VERIFIED"}
                  </span>
                </div>
              </div>

              <div className="rounded-2xl border border-border/80 bg-card p-5 flex flex-col gap-3 text-sm">
                <h4 className="font-semibold text-foreground">Contact &amp; Location</h4>
                <div className="flex items-center gap-2.5 text-muted-foreground">
                  <Phone className="size-4 text-primary shrink-0" />
                  <span className="font-mono text-foreground">{person.phone || "Not listed"}</span>
                </div>
                <div className="flex items-center gap-2.5 text-muted-foreground">
                  <MapPin className="size-4 text-primary shrink-0" />
                  <span>
                    {person.city ? `${person.city}, ` : ""}
                    {person.state_code || "United States"}
                  </span>
                </div>
                {person.linkedin_url && (
                  <div className="flex items-center gap-2.5">
                    <Linkedin className="size-4 text-primary shrink-0" />
                    <a
                      href={person.linkedin_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary hover:underline font-medium"
                    >
                      LinkedIn Profile
                    </a>
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-border/80 bg-card p-5 flex flex-col gap-1.5">
                <h4 className="text-sm font-semibold text-foreground">Employer Organization</h4>
                <p className="text-sm font-medium text-foreground">{person.company_name}</p>
                <p className="text-xs font-mono text-muted-foreground">{person.company_domain}</p>
                <p className="text-xs text-muted-foreground">{person.company_industry}</p>
              </div>
            </div>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}
