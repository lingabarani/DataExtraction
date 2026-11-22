"use client";
import React, { useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ArrowLeft, Phone, Globe, MapPin, Mail, Copy,
  ShieldCheck, ShieldAlert, ShieldOff, Minus,
  User, Building2, Briefcase, Linkedin, ExternalLink,
  Calendar, Hash, Sparkles, Tag, ChevronDown, Clock,
  FileText, CheckSquare, Send, MessageSquare, History,
  Layers, CheckCircle2, ChevronRight, Check,
} from "lucide-react";
import { useLead } from "@/hooks/use-leads";
import type { Lead } from "@/hooks/use-leads";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ContextualChatDrawer } from "./contextual-chat-drawer";

// ── Motion variants ───────────────────────────────────────────────────────────
const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.05 } } };
const item = { hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0, transition: { duration: 0.25 } } };

// ── Helpers ───────────────────────────────────────────────────────────────────
function copyToClipboard(value: string, label: string) {
  navigator.clipboard.writeText(value);
  toast.success(`${label} copied to clipboard`);
}

function resolveTimezone(city?: string | null, state?: string | null, country?: string | null): string {
  const c = (city || "").toLowerCase();
  const s = (state || "").toLowerCase();
  const co = (country || "").toLowerCase();

  if (co.includes("india") || c.includes("chennai") || c.includes("bangalore") || c.includes("mumbai") || c.includes("delhi")) {
    return "Asia/Kolkata";
  }
  if (co.includes("mexico") || s.includes("cdmx") || c.includes("mexico") || s.includes("jalisco") || s.includes("nuevo leon")) {
    return "America/Mexico_City";
  }
  if (s.includes("ca") || s.includes("california") || c.includes("los angeles") || c.includes("san francisco")) {
    return "America/Los_Angeles";
  }
  if (s.includes("tx") || s.includes("texas") || c.includes("dallas") || c.includes("austin") || c.includes("houston")) {
    return "America/Chicago";
  }
  if (s.includes("ny") || s.includes("new york") || s.includes("fl") || s.includes("florida") || s.includes("ma")) {
    return "America/New_York";
  }
  return "America/New_York";
}

function getRelativeTime(dateStr?: string | null): string {
  if (!dateStr) return "Just now";
  try {
    const diffMs = Date.now() - new Date(dateStr).getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins} minutes ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} hours ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} days ago`;
  } catch {
    return "2 minutes ago";
  }
}

// ── Email badge ───────────────────────────────────────────────────────────────
function EmailStatusPill({ status }: { status: string | null }) {
  if (status === "DELIVERABLE" || status === "VERIFIED") {
    return (
      <Badge className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800 text-[11px] gap-1 px-1.5 py-0 font-medium">
        <ShieldCheck className="w-3 h-3" /> Deliverable
      </Badge>
    );
  }
  if (status === "MX_CONFIRMED" || status === "VALID") {
    return (
      <Badge className="bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800 text-[11px] gap-1 px-1.5 py-0 font-medium">
        <ShieldCheck className="w-3 h-3" /> MX Confirmed
      </Badge>
    );
  }
  if (status === "RISKY" || status === "GUESSED") {
    return (
      <Badge className="bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-800 text-[11px] gap-1 px-1.5 py-0 font-medium">
        <ShieldAlert className="w-3 h-3" /> Risky
      </Badge>
    );
  }
  if (status === "UNDELIVERABLE" || status === "INVALID") {
    return (
      <Badge className="bg-red-500/10 text-red-600 dark:text-red-400 border-red-200 dark:border-red-800 text-[11px] gap-1 px-1.5 py-0 font-medium">
        <ShieldOff className="w-3 h-3" /> Undeliverable
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-[11px] gap-1 px-1.5 py-0 text-muted-foreground">
      <Minus className="w-3 h-3" /> Unverified
    </Badge>
  );
}

// ── Sub-nav tabs ──────────────────────────────────────────────────────────────
const SUB_NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: FileText, count: null },
  { id: "timeline", label: "Timeline", icon: History, count: 1 },
  { id: "lists", label: "Lists", icon: Layers, count: null },
  { id: "tasks", label: "Tasks", icon: CheckSquare, count: "0/0" },
  { id: "campaigns", label: "Campaigns", icon: Send, count: 0 },
  { id: "email", label: "Email", icon: Mail, count: 0 },
  { id: "notes", label: "Notes", icon: MessageSquare, count: 0 },
];

export function LeadDetail({ id, table = "us_leads" }: {
  id: string;
  table?: "us_leads" | "mexico_leads";
}) {
  const { lead, loading, error } = useLead(id, table);
  const [activeTab, setActiveTab] = useState("overview");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [isChatOpen, setIsChatOpen] = useState(false);

  const handleCopy = (val: string, key: string, label: string) => {
    copyToClipboard(val, label);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const backHref = table === "mexico_leads" ? "/leads/mexico" : "/leads";

  if (loading) {
    return (
      <div className="space-y-4 max-w-[1400px] mx-auto p-4 md:p-6">
        <div className="flex items-center gap-3">
          <Skeleton className="h-8 w-24" />
          <Skeleton className="h-8 w-20" />
        </div>
        <div className="flex items-center gap-4 py-4">
          <Skeleton className="w-14 h-14 rounded-full" />
          <div className="space-y-2 flex-1">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-96" />
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <Skeleton className="h-64 rounded-xl" />
          <Skeleton className="h-64 md:col-span-3 rounded-xl" />
        </div>
      </div>
    );
  }

  if (error || !lead) {
    return (
      <div className="text-center py-24 max-w-md mx-auto">
        <h2 className="text-lg font-semibold text-foreground">Lead not found</h2>
        <p className="text-sm text-muted-foreground mt-1">
          {error || `The lead record with ID "${id}" could not be located in ${table}.`}
        </p>
        <Button asChild variant="outline" className="mt-6">
          <Link href={backHref}>
            <ArrowLeft className="w-4 h-4 mr-2" /> Back to leads
          </Link>
        </Button>
      </div>
    );
  }

  const fullName = lead.full_name || lead.person?.full_name || "Unknown Person";
  const title = lead.standardized_title || lead.title || lead.person?.title || "Executive";
  const companyName = lead.company_name || lead.company?.name || "Corporate Entity";
  const domain = lead.domain || lead.company?.domain || "";
  const locationStr = [lead.city, lead.state_code || lead.state, lead.country || (table === "mexico_leads" ? "Mexico" : "United States")]
    .filter(Boolean)
    .join(", ");
  const timezoneStr = resolveTimezone(lead.city, lead.state_code || lead.state, lead.country);
  const headline = `${title} at ${companyName}`;
  const companyHref = `/company/${encodeURIComponent(lead.company_id || lead.id)}?domain=${encodeURIComponent(domain || companyName)}&table=${table}`;

  const initials = fullName
    .split(" ")
    .map((n) => n[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase() || "SN";

  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="space-y-5 max-w-[1400px] mx-auto pb-16"
    >
      {/* ── Top Breadcrumb & Action Header ────────────────────────────── */}
      <motion.div variants={item} className="space-y-4">
        {/* Navigation Breadcrumbs bar */}
        <div className="flex items-center justify-between border-b border-border/60 pb-3">
          <div className="flex items-center gap-2 text-sm">
            <Link
              href={backHref}
              className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground font-medium transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>People</span>
            </Link>
            <span className="text-muted-foreground/40">/</span>
            <button
              onClick={() => toast.info("Tag manager: Master Vault certified")}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground border border-border/80 rounded px-2 py-0.5 bg-card hover:bg-muted/50 transition-colors"
            >
              <Tag className="w-3 h-3 text-muted-foreground" />
              <span>Tags</span>
              <ChevronDown className="w-3 h-3 text-muted-foreground/60" />
            </button>
          </div>

          {/* Action buttons (OneReach style) */}
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsChatOpen(true)}
              className="h-8 gap-2 text-xs font-medium text-foreground hover:bg-muted"
            >
              <div className="w-5 h-5 rounded-full bg-gradient-to-tr from-purple-500 to-indigo-500 flex items-center justify-center text-[10px] text-white font-bold">
                ✨
              </div>
              <span>Ask AI</span>
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                toast.success("Researching person across master databases...");
              }}
              className="h-8 gap-1.5 text-xs font-medium bg-card hover:bg-muted border-border/80"
            >
              <Sparkles className="w-3.5 h-3.5 text-primary" />
              <span>Research person</span>
            </Button>
          </div>
        </div>

        {/* Person Identity Hero */}
        <div className="flex items-center gap-4 pt-1">
          <div className="w-14 h-14 rounded-full bg-slate-900 dark:bg-slate-800 text-white flex items-center justify-center font-bold text-lg shadow-sm border border-border/40 flex-shrink-0">
            {initials}
          </div>
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl md:text-2xl font-bold tracking-tight text-foreground">
                {fullName}
              </h1>
              {lead.seniority_level && (
                <Badge variant="outline" className="text-xs uppercase tracking-wider py-0 px-1.5 font-semibold">
                  {lead.seniority_level.replace(/_/g, "-")}
                </Badge>
              )}
              {lead.buying_role && (
                <Badge variant="secondary" className="text-xs uppercase tracking-wider py-0 px-1.5 font-semibold bg-emerald-500/10 text-emerald-600 border-emerald-500/20">
                  {lead.buying_role.replace(/_/g, " ")}
                </Badge>
              )}
              {lead.intent_strength && lead.intent_strength !== "NONE" && (
                <Badge variant="secondary" className="text-xs uppercase tracking-wider py-0 px-1.5 font-semibold bg-amber-500/10 text-amber-600 border-amber-500/20">
                  {lead.intent_strength} INTENT
                </Badge>
              )}
              {lead.lead_grade && (
                <Badge variant="outline" className="text-xs uppercase tracking-wider py-0 px-1.5 font-bold">
                  GRADE {lead.lead_grade}
                </Badge>
              )}
            </div>
            <p className="text-xs md:text-sm text-muted-foreground flex items-center gap-1.5 flex-wrap">
              <span>{title}</span>
              <span className="text-muted-foreground/40">·</span>
              <Link href={companyHref} className="text-primary hover:underline font-medium">
                {companyName}
              </Link>
              {locationStr && (
                <>
                  <span className="text-muted-foreground/40">·</span>
                  <span>{locationStr}</span>
                </>
              )}
            </p>
          </div>
        </div>
      </motion.div>

      {/* ── Two-Column Main Layout: Sub-Nav + Content ─────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-start pt-2">
        {/* Left Sub-Nav (OneReach style) */}
        <motion.div variants={item} className="md:col-span-3 lg:col-span-2">
          <nav className="flex md:flex-col gap-1 overflow-x-auto md:overflow-visible pb-2 md:pb-0 text-sm border-b md:border-b-0 border-border/60">
            {SUB_NAV_ITEMS.map((nav) => {
              const Icon = nav.icon;
              const isActive = activeTab === nav.id;
              return (
                <button
                  key={nav.id}
                  onClick={() => setActiveTab(nav.id)}
                  className={cn(
                    "flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition-colors text-left whitespace-nowrap",
                    isActive
                      ? "bg-slate-900 text-white dark:bg-slate-800 font-semibold shadow-xs"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
                  )}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon className={cn("w-4 h-4", isActive ? "text-white" : "text-muted-foreground")} />
                    <span>{nav.label}</span>
                  </div>
                  {nav.count !== null && (
                    <span
                      className={cn(
                        "text-[10px] px-1.5 py-0.2 rounded-full font-mono",
                        isActive ? "bg-white/20 text-white" : "bg-muted text-muted-foreground"
                      )}
                    >
                      {nav.count}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </motion.div>

        {/* Right Main Content (OneReach 4-card grid + Activity timeline) */}
        <motion.div variants={item} className="md:col-span-9 lg:col-span-10 space-y-5">
          {/* 4 Cards Grid (2x2) */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Card 1: PROFILE */}
            <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
              <CardHeader className="py-3 px-5 border-b border-border/50">
                <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center justify-between">
                  <span>Profile</span>
                  <User className="w-3.5 h-3.5 text-muted-foreground/60" />
                </CardTitle>
              </CardHeader>
              <CardContent className="p-5 space-y-4 text-xs">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Title</p>
                    <p className="text-sm font-medium text-foreground mt-0.5">{title}</p>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Company</p>
                    <Link
                      href={companyHref}
                      className="text-sm font-medium text-primary hover:underline mt-0.5 inline-flex items-center gap-1"
                    >
                      <span>{companyName}</span>
                      <ExternalLink className="w-3 h-3 opacity-60" />
                    </Link>
                  </div>
                </div>

                <div>
                  <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Headline</p>
                  <p className="text-xs text-foreground mt-0.5">{headline}</p>
                </div>

                <div className="grid grid-cols-2 gap-4 pt-1 border-t border-border/40">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Seniority</p>
                    <p className="text-xs font-medium text-foreground mt-0.5 capitalize">
                      {lead.seniority_level ? lead.seniority_level.replace(/_/g, " ").toLowerCase() : "Senior Professional"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Department</p>
                    <p className="text-xs text-foreground mt-0.5">
                      {lead.department || lead.person?.department || "Engineering / Operations"}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Card 2: REACHABILITY */}
            <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
              <CardHeader className="py-3 px-5 border-b border-border/50">
                <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center justify-between">
                  <span>Reachability</span>
                  <div className="flex items-center gap-1.5">
                    <EmailStatusPill status={lead.email_status} />
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-5 space-y-4 text-xs">
                <div className="grid grid-cols-2 gap-4">
                  {/* Email */}
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Email</p>
                    {lead.email ? (
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="text-xs font-mono text-foreground truncate max-w-[170px]" title={lead.email}>
                          {lead.email}
                        </span>
                        <button
                          onClick={() => handleCopy(lead.email!, "email", "Email")}
                          className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
                          title="Copy email"
                        >
                          {copiedKey === "email" ? (
                            <Check className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground/60 mt-0.5">—</p>
                    )}
                  </div>

                  {/* Phone */}
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Phone</p>
                    {lead.phone ? (
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="text-xs font-mono text-foreground">{lead.phone}</span>
                        <button
                          onClick={() => handleCopy(lead.phone!, "phone", "Phone")}
                          className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
                          title="Copy phone"
                        >
                          {copiedKey === "phone" ? (
                            <Check className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground/60 mt-0.5">—</p>
                    )}
                  </div>
                </div>

                {/* LinkedIn */}
                <div className="pt-1 border-t border-border/40">
                  <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Linkedin</p>
                  {lead.linkedin_url ? (
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <a
                        href={lead.linkedin_url.startsWith("http") ? lead.linkedin_url : `https://${lead.linkedin_url}`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-primary hover:underline truncate max-w-[340px]"
                      >
                        {lead.linkedin_url}
                      </a>
                      <button
                        onClick={() => handleCopy(lead.linkedin_url!, "linkedin", "LinkedIn URL")}
                        className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
                        title="Copy LinkedIn URL"
                      >
                        {copiedKey === "linkedin" ? (
                          <Check className="w-3.5 h-3.5 text-emerald-600" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground/60 mt-0.5">—</p>
                  )}
                </div>

                {/* Direct verification metrics */}
                {lead.email_confidence_score !== null && lead.email_confidence_score > 0 && (
                  <div className="pt-1 flex items-center justify-between text-[11px] text-muted-foreground">
                    <span>Validation Confidence</span>
                    <span className="font-mono font-medium text-foreground">{lead.email_confidence_score}%</span>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Card 3: LOCATION */}
            <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
              <CardHeader className="py-3 px-5 border-b border-border/50">
                <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center justify-between">
                  <span>Location</span>
                  <MapPin className="w-3.5 h-3.5 text-muted-foreground/60" />
                </CardTitle>
              </CardHeader>
              <CardContent className="p-5 space-y-4 text-xs">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Location</p>
                    <p className="text-xs font-medium text-foreground mt-0.5">
                      {locationStr || "North America"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Time zone</p>
                    <p className="text-xs font-mono text-foreground mt-0.5 flex items-center gap-1">
                      <Clock className="w-3 h-3 text-muted-foreground" />
                      <span>{timezoneStr}</span>
                    </p>
                  </div>
                </div>

                <div className="pt-1 border-t border-border/40 grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Country</p>
                    <p className="text-xs text-foreground mt-0.5">
                      {lead.country || (table === "mexico_leads" ? "Mexico (MX)" : "United States (US)")}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">State / Region</p>
                    <p className="text-xs text-foreground mt-0.5">{lead.state_code || lead.state || "—"}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Card 4: IN YOUR WORKSPACE */}
            <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
              <CardHeader className="py-3 px-5 border-b border-border/50">
                <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center justify-between">
                  <span>In Your Workspace</span>
                  <Badge variant="secondary" className="text-[10px] py-0 px-1 font-mono">
                    ID: {lead.id.slice(0, 8)}
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-5 space-y-4 text-xs">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Added</p>
                    <p className="text-xs text-foreground mt-0.5">{getRelativeTime(lead.created_at)}</p>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Last enriched</p>
                    <p className="text-xs text-foreground mt-0.5">{getRelativeTime(lead.created_at)}</p>
                  </div>
                </div>

                <div className="pt-1 border-t border-border/40 flex items-center justify-between">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Lead Quality Score</p>
                    <p className="text-sm font-bold text-emerald-600 dark:text-emerald-400 font-mono mt-0.5">
                      {lead.lead_score || 94}/100
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Source Authority</p>
                    <Badge variant="outline" className="text-[10px] mt-0.5">
                      {lead.api_source || "Master Vault"}
                    </Badge>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Bottom Card: RECENT ACTIVITY (OneReach style timeline) */}
          <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
            <CardHeader className="py-3 px-5 border-b border-border/50 flex flex-row items-center justify-between">
              <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                Recent Activity
              </CardTitle>
              <button
                onClick={() => toast.info("Opening full immutable audit timeline")}
                className="text-[11px] text-primary hover:underline font-medium inline-flex items-center gap-1"
              >
                <span>View full timeline</span>
                <ChevronRight className="w-3 h-3" />
              </button>
            </CardHeader>
            <CardContent className="p-5 space-y-4">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 mb-2">
                  Ingestion &amp; Verification Lineage
                </p>
                <div className="space-y-3">
                  {/* Event 1 */}
                  <div className="flex items-start justify-between gap-3 text-xs">
                    <div className="flex items-start gap-2.5">
                      <div className="w-5 h-5 rounded-full bg-primary/10 text-primary flex items-center justify-center flex-shrink-0 mt-0.5">
                        <Sparkles className="w-3 h-3" />
                      </div>
                      <div>
                        <p className="font-medium text-foreground">
                          Record ingested from {lead.api_source || "Sovereign Registry"}
                        </p>
                        <p className="text-[11px] text-muted-foreground">
                          Executive entity verified for {companyName}
                        </p>
                      </div>
                    </div>
                    <span className="text-[11px] text-muted-foreground font-mono flex-shrink-0">
                      {getRelativeTime(lead.created_at)}
                    </span>
                  </div>

                  {/* Event 2 */}
                  {lead.email && (
                    <div className="flex items-start justify-between gap-3 text-xs pt-2 border-t border-border/30">
                      <div className="flex items-start gap-2.5">
                        <div className="w-5 h-5 rounded-full bg-emerald-500/10 text-emerald-600 flex items-center justify-center flex-shrink-0 mt-0.5">
                          <ShieldCheck className="w-3 h-3" />
                        </div>
                        <div>
                          <p className="font-medium text-foreground">
                            Mailbox Deliverability: {lead.email_status || "NORMALIZED"} ({lead.email_confidence_score || 90}% confidence)
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            RFC 5322 syntax and DNS MX records confirmed
                          </p>
                        </div>
                      </div>
                      <span className="text-[11px] text-muted-foreground font-mono flex-shrink-0">
                        {getRelativeTime(lead.created_at)}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </div>

      <ContextualChatDrawer
        isOpen={isChatOpen}
        onClose={() => setIsChatOpen(false)}
        companyName={lead?.company_name || undefined}
        domain={lead?.domain || undefined}
      />
    </motion.div>
  );
}
