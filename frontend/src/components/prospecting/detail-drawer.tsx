"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  X,
  Building2,
  Users,
  ExternalLink,
  ShieldCheck,
  Send,
  Flame,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  Cpu,
  Mail,
  Phone,
  Linkedin,
  MapPin,
  DollarSign,
  Loader2,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  CompanyRecord,
  PeopleRecord,
  DecisionMaker,
  prospectingApi,
} from "@/lib/prospecting-api";
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
  const [activeTab, setActiveTab] = useState<"overview" | "tech" | "compliance" | "leadership">(
    "overview"
  );
  const [decisionMakers, setDecisionMakers] = useState<DecisionMaker[]>([]);
  const [isLoadingLeaders, setIsLoadingLeaders] = useState(false);

  useEffect(() => {
    if (company && isOpen) {
      setIsLoadingLeaders(true);
      prospectingApi
        .getCompanyDecisionMakers(company.org_id)
        .then((res) => setDecisionMakers(res.decision_makers || []))
        .catch(() => setDecisionMakers([]))
        .finally(() => setIsLoadingLeaders(false));
    }
  }, [company, isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-xs transition-opacity animate-in fade-in duration-200">
      <div className="relative w-full max-w-xl h-full bg-background border-l border-border/80 shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-right duration-200">
        {/* Drawer Header */}
        <div className="flex items-start justify-between p-5 border-b border-border/80 bg-muted/20">
          <div className="flex items-start gap-3">
            {company ? (
              <div className="flex items-center justify-center size-10 rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 font-bold text-base shrink-0">
                {company.legal_name.charAt(0).toUpperCase()}
              </div>
            ) : person ? (
              <div className="flex items-center justify-center size-10 rounded-full bg-purple-500/10 text-purple-600 dark:text-purple-400 font-bold text-base shrink-0">
                {person.full_name.charAt(0).toUpperCase()}
              </div>
            ) : null}

            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-base font-bold text-foreground">
                  {company ? company.legal_name : person?.full_name}
                </h3>
                {company && company.primary_domain && (
                  <Badge variant="outline" className="font-mono text-[10px] py-0">
                    {company.primary_domain}
                  </Badge>
                )}
                {person && (
                  <Badge variant="secondary" className="font-mono text-[10px] py-0">
                    {person.seniority_level.replace("_", " ")}
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                {company
                  ? `${company.industry} • ${company.city ? `${company.city}, ` : ""}${company.state_code || company.jurisdiction}`
                  : `${person?.title} at ${person?.company_name}`}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => {
                if (company) onPushToOneReach("company", company.org_id);
                else if (person) onPushToOneReach("person", person.person_id);
              }}
              disabled={isPushing}
              className="h-8 text-xs bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5 shadow-xs"
            >
              {isPushing ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Send className="size-3.5" />
              )}
              <span>Push OneReach</span>
            </Button>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            >
              <X className="size-4" />
            </button>
          </div>
        </div>

        {/* Intelligence Outbound Navigation Banner */}
        {company ? (
          <div className="bg-blue-500/5 dark:bg-blue-500/10 border-b border-blue-500/20 px-5 py-2.5 flex items-center justify-between text-xs">
            <span className="text-muted-foreground flex items-center gap-1.5 truncate">
              <Building2 className="size-3.5 text-blue-600 dark:text-blue-400 shrink-0" />
              <span className="truncate">Need deep technographics, SSL verification, or 360° dossier?</span>
            </span>
            <Link
              href={`/company/${company.org_id}${company.primary_domain ? `?domain=${encodeURIComponent(company.primary_domain)}` : ""}`}
              className="inline-flex items-center gap-1 font-semibold text-blue-600 dark:text-blue-400 hover:underline hover:opacity-80 transition-opacity shrink-0 ml-2"
            >
              <span>Full Intelligence Page</span>
              <ExternalLink className="size-3" />
            </Link>
          </div>
        ) : person ? (
          <div className="bg-purple-500/5 dark:bg-purple-500/10 border-b border-purple-500/20 px-5 py-2.5 flex items-center justify-between text-xs">
            <span className="text-muted-foreground flex items-center gap-1.5 truncate">
              <Users className="size-3.5 text-purple-600 dark:text-purple-400 shrink-0" />
              <span className="truncate">View verified deliverability, career history &amp; org chart:</span>
            </span>
            <Link
              href={`/leads/${person.person_id}`}
              className="inline-flex items-center gap-1 font-semibold text-purple-600 dark:text-purple-400 hover:underline hover:opacity-80 transition-opacity shrink-0 ml-2"
            >
              <span>Full Lead Dossier</span>
              <ExternalLink className="size-3" />
            </Link>
          </div>
        ) : null}

        {/* Company Tab Navigation */}
        {company && (
          <div className="flex items-center border-b border-border/60 px-5 bg-background text-xs">
            {[
              { id: "overview", label: "Overview & Intent" },
              { id: "tech", label: "Technographics" },
              { id: "compliance", label: "Security & Badges" },
              { id: "leadership", label: `Leadership (${decisionMakers.length})` },
            ].map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id as any)}
                className={cn(
                  "py-2.5 px-3 border-b-2 font-medium transition-colors",
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

        {/* Drawer Body Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5 text-xs">
          {company ? (
            /* ================== COMPANY DETAILS ================== */
            activeTab === "overview" ? (
              <div className="space-y-4">
                {/* Executive Summary */}
                <div className="p-3.5 rounded-xl border border-border/70 bg-card/60">
                  <h4 className="font-semibold text-xs text-foreground mb-1.5 flex items-center gap-1.5">
                    <Sparkles className="size-3.5 text-blue-500" />
                    <span>AI Executive Overview</span>
                  </h4>
                  <p className="text-muted-foreground leading-relaxed">
                    {company.short_description ||
                      `${company.legal_name} is an enterprise organization operating in the ${company.industry} sector, registered in ${company.jurisdiction}. Certified with enterprise data quality score of ${company.data_quality_score}/100.`}
                  </p>
                </div>

                {/* Key Metrics Bento */}
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                  <div className="p-3 rounded-lg border border-border/70 bg-card/40">
                    <span className="text-[11px] text-muted-foreground">Buyer Intent</span>
                    <div className="flex items-center gap-1.5 mt-1">
                      <Flame className="size-4 text-rose-500" />
                      <span className="text-base font-bold font-mono tabnum">
                        {Math.round(company.intent_score)}
                      </span>
                      <span className="text-[10px] px-1 rounded bg-muted uppercase font-mono">
                        {company.intent_strength}
                      </span>
                    </div>
                  </div>

                  <div className="p-3 rounded-lg border border-border/70 bg-card/40">
                    <span className="text-[11px] text-muted-foreground">Trust Rating</span>
                    <div className="flex items-center gap-1.5 mt-1 text-emerald-600 dark:text-emerald-400">
                      <ShieldCheck className="size-4" />
                      <span className="text-base font-bold font-mono tabnum">
                        {Math.round(company.trust_score)}%
                      </span>
                    </div>
                  </div>

                  <div className="p-3 rounded-lg border border-border/70 bg-card/40">
                    <span className="text-[11px] text-muted-foreground">Headcount</span>
                    <p className="text-sm font-bold font-mono mt-1 text-foreground">
                      {company.employee_count_min} - {company.employee_count_max}
                    </p>
                  </div>
                </div>

                {/* Intent Topics */}
                {company.intent_topics && company.intent_topics.length > 0 && (
                  <div className="p-3.5 rounded-xl border border-border/70 bg-card/40">
                    <h5 className="font-semibold text-xs mb-2">Active Buyer Research Topics</h5>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {company.intent_topics.map((topic) => (
                        <Badge
                          key={topic}
                          variant="secondary"
                          className="bg-primary/10 text-primary border-primary/20 text-[11px]"
                        >
                          {topic}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : activeTab === "tech" ? (
              <div className="space-y-4">
                <div className="p-3.5 rounded-xl border border-border/70 bg-card/40">
                  <h4 className="font-semibold text-xs mb-2 flex items-center gap-1.5">
                    <Cpu className="size-3.5 text-primary" />
                    <span>Detected Tech Stack &amp; Infrastructure</span>
                  </h4>
                  <div className="flex items-center gap-2 flex-wrap">
                    {company.technologies.map((tech) => (
                      <Badge
                        key={tech}
                        variant="outline"
                        className="text-xs px-2.5 py-1 bg-muted/60"
                      >
                        {tech}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            ) : activeTab === "compliance" ? (
              <div className="space-y-3">
                <div className="p-3.5 rounded-xl border border-border/70 bg-card/40">
                  <h4 className="font-semibold text-xs mb-2 flex items-center gap-1.5">
                    <ShieldCheck className="size-3.5 text-emerald-500" />
                    <span>Security &amp; Regulatory Certifications</span>
                  </h4>
                  <div className="grid grid-cols-2 gap-2">
                    {company.compliance_badges.map((badge) => (
                      <div
                        key={badge}
                        className="flex items-center gap-2 p-2 rounded-lg bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20"
                      >
                        <CheckCircle2 className="size-3.5" />
                        <span className="font-medium text-xs">{badge} Certified</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              /* Leadership Tab */
              <div className="space-y-2.5">
                {isLoadingLeaders ? (
                  <div className="flex items-center justify-center h-32 gap-2 text-muted-foreground">
                    <Loader2 className="size-4 animate-spin text-primary" />
                    <span>Loading leadership contacts...</span>
                  </div>
                ) : decisionMakers.length === 0 ? (
                  <p className="text-muted-foreground text-center py-8">
                    No verified executives currently linked to this organization record.
                  </p>
                ) : (
                  decisionMakers.map((leader) => (
                    <div
                      key={leader.person_id}
                      className="p-3 rounded-lg border border-border/70 bg-card/50 flex items-center justify-between gap-3 hover:bg-muted/40 transition-colors"
                    >
                      <div className="flex items-center gap-2.5">
                        <div className="flex items-center justify-center size-8 rounded-full bg-purple-500/10 text-purple-600 dark:text-purple-400 font-bold text-xs shrink-0">
                          {leader.name.charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <p className="font-semibold text-foreground">{leader.name}</p>
                          <p className="text-[11px] text-muted-foreground">{leader.title}</p>
                          <p className="text-[11px] font-mono text-muted-foreground mt-0.5">
                            {leader.email}
                          </p>
                        </div>
                      </div>
                      <Badge variant="outline" className="text-[10px] font-mono">
                        {leader.seniority.replace("_", " ")}
                      </Badge>
                    </div>
                  ))
                )}
              </div>
            )
          ) : person ? (
            /* ================== PEOPLE DETAILS ================== */
            <div className="space-y-4">
              {/* Deliverability Card */}
              <div className="p-4 rounded-xl border border-border/70 bg-card/60 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-xs flex items-center gap-1.5">
                    <Mail className="size-3.5 text-primary" />
                    <span>Email Deliverability Firewall</span>
                  </span>
                  <Badge
                    variant="outline"
                    className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/30 font-semibold"
                  >
                    Score: {person.deliverability_score}/100
                  </Badge>
                </div>

                <div className="p-3 rounded-lg bg-background/80 border border-border/60 flex items-center justify-between">
                  <span className="font-mono text-xs">{person.email}</span>
                  <span className="text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 uppercase">
                    {person.deliverability_status}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground font-mono">
                  <div>
                    <span>MX Provider:</span>{" "}
                    <span className="text-foreground font-semibold">{person.mx_provider}</span>
                  </div>
                  <div>
                    <span>Catch-All:</span>{" "}
                    <span className="text-foreground font-semibold">
                      {person.is_catch_all ? "Yes" : "No"}
                    </span>
                  </div>
                </div>
              </div>

              {/* Contact Information */}
              <div className="p-4 rounded-xl border border-border/70 bg-card/40 space-y-2">
                <h4 className="font-semibold text-xs mb-1">Direct Contact Details</h4>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Phone className="size-3.5 text-primary" />
                  <span className="font-mono text-foreground">{person.phone || "Not Listed"}</span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <MapPin className="size-3.5 text-primary" />
                  <span>
                    {person.city ? `${person.city}, ` : ""}
                    {person.state_code || "United States"}
                  </span>
                </div>
                {person.linkedin_url && (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Linkedin className="size-3.5 text-blue-500" />
                    <a
                      href={person.linkedin_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary hover:underline"
                    >
                      View LinkedIn Profile
                    </a>
                  </div>
                )}
              </div>

              {/* Employer Profile */}
              <div className="p-4 rounded-xl border border-border/70 bg-card/40 space-y-1.5">
                <h4 className="font-semibold text-xs mb-1">Employer Firmographics</h4>
                <p className="font-semibold text-foreground text-sm">{person.company_name}</p>
                <p className="text-muted-foreground font-mono text-xs">{person.company_domain}</p>
                <p className="text-muted-foreground text-xs">{person.company_industry}</p>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
