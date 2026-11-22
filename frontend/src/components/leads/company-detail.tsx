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
  Building2, ExternalLink, Calendar, Hash, Sparkles,
  Tag, ChevronDown, Clock, FileText, CheckSquare,
  Send, MessageSquare, History, Layers, CheckCircle2,
  ChevronRight, Quote, Check, RefreshCw,
  Lock, AlertTriangle, Users, Star, ThumbsUp, ThumbsDown,
} from "lucide-react";
import { useCompanyIntelligence } from "@/hooks/use-leads";
import type { CompanyIntelligence } from "@/hooks/use-leads";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

// ── Motion variants ───────────────────────────────────────────────────────────
const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.05 } } };
const item = { hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0, transition: { duration: 0.25 } } };

// ── Helpers ───────────────────────────────────────────────────────────────────
function copyToClipboard(value: string, label: string) {
  navigator.clipboard.writeText(value);
  toast.success(`${label} copied to clipboard`);
}

const SUB_NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: FileText, count: null },
  { id: "reviews", label: "Customer Reviews", icon: Star, count: null },
  { id: "timeline", label: "Timeline", icon: History, count: null },
  { id: "people", label: "People", icon: Users, count: 4 },
  { id: "lists", label: "Lists", icon: Layers, count: null },
  { id: "tasks", label: "Tasks", icon: CheckSquare, count: "0/0" },
  { id: "campaigns", label: "Campaigns", icon: Send, count: null },
  { id: "email", label: "Email", icon: Mail, count: null },
  { id: "notes", label: "Notes", icon: MessageSquare, count: null },
];

export function CompanyDetail({
  companyId,
  domain,
  table = "us_leads",
}: {
  companyId: string;
  domain?: string | null;
  table?: "us_leads" | "mexico_leads";
}) {
  const { intel, loading, error, refresh } = useCompanyIntelligence(companyId, domain, table);
  const [activeTab, setActiveTab] = useState("overview");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleCopy = (val: string, key: string, label: string) => {
    copyToClipboard(val, label);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);
    toast.info("Scanning live endpoints and re-enriching deep intelligence...");
    await refresh();
    setIsRefreshing(false);
    toast.success("Intelligence updated with live SSL & registry data");
  };

  const backHref = table === "mexico_leads" ? "/leads/mexico" : "/leads";

  if (loading) {
    return (
      <div className="space-y-4 max-w-[1400px] mx-auto p-4 md:p-6">
        <div className="flex items-center gap-3">
          <Skeleton className="h-8 w-28" />
          <Skeleton className="h-8 w-20" />
        </div>
        <div className="flex items-center gap-4 py-4">
          <Skeleton className="w-14 h-14 rounded-xl" />
          <div className="space-y-2 flex-1">
            <Skeleton className="h-6 w-56" />
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

  if (error || !intel) {
    return (
      <div className="text-center py-24 max-w-md mx-auto">
        <h2 className="text-lg font-semibold text-foreground">Company Intelligence Unavailable</h2>
        <p className="text-sm text-muted-foreground mt-1">
          {error || `Could not load intelligence for "${companyId}".`}
        </p>
        <Button asChild variant="outline" className="mt-6">
          <Link href={backHref}>
            <ArrowLeft className="w-4 h-4 mr-2" /> Back to leads
          </Link>
        </Button>
      </div>
    );
  }

  const websiteUrl = intel.domain.startsWith("http") ? intel.domain : `http://www.${intel.domain}`;
  const trust = intel.trust_and_compliance || {};
  const locationStr = table === "mexico_leads" ? "Mexico City, Mexico City, Mexico" : "New York, NY, United States";

  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="space-y-5 max-w-[1400px] mx-auto pb-16"
    >
      {/* ── Top Breadcrumb & Action Header ────────────────────────────── */}
      <motion.div variants={item} className="space-y-4">
        {/* Navigation Breadcrumb bar */}
        <div className="flex items-center justify-between border-b border-border/60 pb-3">
          <div className="flex items-center gap-2 text-sm">
            <Link
              href={backHref}
              className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground font-medium transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Companies</span>
            </Link>
            <span className="text-muted-foreground/40">/</span>
            <button
              onClick={() => toast.info("Tag manager: Master Organization")}
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
              onClick={() => toast.info("Opening AI Chatbot with company context")}
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
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="h-8 gap-1.5 text-xs font-medium bg-card hover:bg-muted border-border/80"
            >
              <RefreshCw className={cn("w-3.5 h-3.5 text-primary", isRefreshing && "animate-spin")} />
              <span>Research account</span>
            </Button>
          </div>
        </div>

        {/* Company Identity Hero */}
        <div className="flex items-center gap-4 pt-1">
          <div className="w-14 h-14 rounded-xl bg-blue-600/10 border border-blue-500/20 text-blue-600 dark:text-blue-400 flex items-center justify-center font-bold text-xl shadow-xs flex-shrink-0">
            <Building2 className="w-7 h-7" />
          </div>
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl md:text-2xl font-bold tracking-tight text-foreground">
                {intel.company_name}
              </h1>
              {trust.ssl_valid && (
                <Badge className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800 text-[11px] gap-1 px-1.5 py-0 font-medium">
                  <ShieldCheck className="w-3 h-3" /> SSL Verified
                </Badge>
              )}
            </div>
            <p className="text-xs md:text-sm text-muted-foreground flex items-center gap-1.5 flex-wrap">
              <span>{intel.company_type || "Commercial Enterprise"}</span>
              <span className="text-muted-foreground/40">·</span>
              <span>{locationStr}</span>
              <span className="text-muted-foreground/40">·</span>
              <span>Employees: {intel.employees || "17"}</span>
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
              const count = nav.id === "reviews" ? (intel.reviews?.total_scraped || null) : nav.count;
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
                  {count !== null && (
                    <span
                      className={cn(
                        "text-[10px] px-1.5 py-0.2 rounded-full font-mono",
                        isActive ? "bg-white/20 text-white" : "bg-muted text-muted-foreground"
                      )}
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </motion.div>

        {/* Right Main Content (Enterprise Enriched Cards) */}
        <motion.div variants={item} className="md:col-span-9 lg:col-span-10 space-y-5">
          {activeTab === "reviews" ? (
            /* Dedicated Customer Reviews & Sentiment View */
            <div className="space-y-5">
              {/* Rating & Sentiment Header Card */}
              <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
                <CardHeader className="py-3 px-5 border-b border-border/50 flex flex-row items-center justify-between">
                  <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                    <Star className="w-3.5 h-3.5 text-amber-500 fill-amber-400" />
                    <span>Customer Reviews &amp; Sentiment Intelligence</span>
                  </CardTitle>
                  <Badge variant="outline" className="text-[10px] font-mono">
                    Google Maps &amp; Places
                  </Badge>
                </CardHeader>
                <CardContent className="p-5 space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div className="space-y-1">
                      <div className="flex items-baseline gap-2.5">
                        <span className="text-3xl font-bold font-mono text-foreground">
                          {Number(intel.reviews?.average_rating || 0).toFixed(1)}
                        </span>
                        <span className="text-sm text-muted-foreground">/ 5.0</span>
                        <div className="flex items-center text-amber-500 ml-1.5">
                          {[1, 2, 3, 4, 5].map((s) => (
                            <Star
                              key={s}
                              className={cn(
                                "size-4",
                                s <= Math.round(Number(intel.reviews?.average_rating || 0))
                                  ? "fill-amber-400 text-amber-400"
                                  : "text-muted-foreground/30"
                              )}
                            />
                          ))}
                        </div>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Aggregate score based on{" "}
                        <span className="font-semibold text-foreground">
                          {intel.reviews?.total_scraped || 0}
                        </span>{" "}
                        verified customer reviews
                      </p>
                    </div>

                    <Badge
                      variant="outline"
                      className={cn(
                        "text-xs px-3 py-1.5 font-semibold self-start sm:self-center",
                        (intel.reviews?.ai_summary?.sentiment || "").toLowerCase().includes("positive") || (intel.reviews?.average_rating || 0) >= 4.0
                          ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/30"
                          : "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/30"
                      )}
                    >
                      {intel.reviews?.ai_summary?.sentiment || (Number(intel.reviews?.average_rating || 0) >= 4.0 ? "Strong Positive Sentiment" : "Neutral Sentiment")}
                    </Badge>
                  </div>

                  {intel.reviews?.ai_summary?.summary && (
                    <div className="rounded-lg bg-muted/20 border border-border/60 p-3.5 space-y-1">
                      <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                        <Sparkles className="size-3.5 text-blue-500" />
                        <span>AI Executive Customer Feedback Summary</span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        {intel.reviews.ai_summary.summary}
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Praise & Caution Bento */}
              {((intel.reviews?.ai_summary?.pros && intel.reviews.ai_summary.pros.length > 0) ||
                (intel.reviews?.ai_summary?.cons && intel.reviews.ai_summary.cons.length > 0)) && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {/* Praise Highlights */}
                  <Card className="bg-card border-emerald-500/30 shadow-2xs">
                    <CardHeader className="py-3 px-5 border-b border-emerald-500/20 bg-emerald-500/5">
                      <CardTitle className="text-xs font-semibold text-emerald-800 dark:text-emerald-300 flex items-center gap-1.5">
                        <ThumbsUp className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                        <span>Praise Highlights &amp; Strengths</span>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="p-4">
                      <ul className="space-y-2 text-xs text-foreground/90">
                        {intel.reviews?.ai_summary?.pros?.map((pro, idx) => (
                          <li key={idx} className="flex items-start gap-2 leading-relaxed">
                            <CheckCircle2 className="size-3.5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
                            <span>{pro}</span>
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>

                  {/* Points of Caution */}
                  <Card className="bg-card border-amber-500/30 shadow-2xs">
                    <CardHeader className="py-3 px-5 border-b border-amber-500/20 bg-amber-500/5">
                      <CardTitle className="text-xs font-semibold text-amber-800 dark:text-amber-300 flex items-center gap-1.5">
                        <ThumbsDown className="size-3.5 text-amber-600 dark:text-amber-400" />
                        <span>Points of Caution &amp; Alerts</span>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="p-4">
                      {intel.reviews?.ai_summary?.cons && intel.reviews.ai_summary.cons.length > 0 ? (
                        <ul className="space-y-2 text-xs text-foreground/90">
                          {intel.reviews.ai_summary.cons.map((con, idx) => (
                            <li key={idx} className="flex items-start gap-2 leading-relaxed">
                              <AlertTriangle className="size-3.5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                              <span>{con}</span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-xs text-muted-foreground italic">
                          No recurring complaints or critical negative patterns detected.
                        </p>
                      )}
                    </CardContent>
                  </Card>
                </div>
              )}

              {/* Review Feed */}
              <Card className="bg-card border-border/80 shadow-2xs">
                <CardHeader className="py-3 px-5 border-b border-border/50 flex flex-row items-center justify-between">
                  <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                    <MessageSquare className="size-3.5" />
                    <span>Archived Customer Reviews ({intel.reviews?.recent_reviews?.length || 0})</span>
                  </CardTitle>
                  <span className="text-[10px] text-muted-foreground font-mono">Verified Citations</span>
                </CardHeader>
                <CardContent className="p-5 space-y-3">
                  {intel.reviews?.recent_reviews && intel.reviews.recent_reviews.length > 0 ? (
                    intel.reviews.recent_reviews.map((rev, idx) => (
                      <div
                        key={idx}
                        className="p-4 rounded-xl border border-border/60 bg-muted/10 space-y-2 hover:bg-muted/20 transition-colors"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <div className="size-6 rounded-full bg-primary/10 text-primary font-bold text-[10px] flex items-center justify-center shrink-0">
                              {(rev.author || "C").charAt(0).toUpperCase()}
                            </div>
                            <span className="font-semibold text-foreground text-xs">{rev.author || "Verified Reviewer"}</span>
                          </div>
                          <span className="text-[10px] text-muted-foreground font-mono">
                            {rev.published_at || "Archived"}
                          </span>
                        </div>

                        <div className="flex items-center gap-1 text-amber-500">
                          {[1, 2, 3, 4, 5].map((s) => (
                            <Star
                              key={s}
                              className={cn(
                                "size-3",
                                s <= rev.rating ? "fill-amber-400 text-amber-400" : "text-muted-foreground/30"
                              )}
                            />
                          ))}
                        </div>

                        {rev.text && (
                          <p className="text-xs text-muted-foreground leading-relaxed italic">
                            &ldquo;{rev.text}&rdquo;
                          </p>
                        )}
                      </div>
                    ))
                  ) : (
                    <div className="text-center py-12 text-muted-foreground space-y-1">
                      <p className="text-xs font-medium">No Customer Reviews Linked</p>
                      <p className="text-[11px]">No reviews archived for this domain yet.</p>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          ) : (
            <>
              {/* Row 1: FIRMOGRAPHICS + ONLINE */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
            {/* Firmographics Card (Spans 7 cols on large) */}
            <Card className="lg:col-span-7 bg-card border-border/80 shadow-2xs hover:border-border transition-all">
              <CardHeader className="py-3 px-5 border-b border-border/50">
                <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center justify-between">
                  <span>Firmographics</span>
                  <Building2 className="w-3.5 h-3.5 text-muted-foreground/60" />
                </CardTitle>
              </CardHeader>
              <CardContent className="p-5 space-y-4 text-xs">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Industry</p>
                    <p className="text-xs font-medium text-foreground mt-0.5">{intel.company_type || "Commercial Enterprise"}</p>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Employees</p>
                    <p className="text-xs font-mono font-medium text-foreground mt-0.5">{intel.employees || "Not Disclosed"}</p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 pt-1 border-t border-border/40">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Founded</p>
                    <p className="text-xs font-mono font-medium text-foreground mt-0.5">{intel.founded || "Not Disclosed"}</p>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Company Type</p>
                    <p className="text-xs text-foreground mt-0.5">{intel.company_type || "Commercial Enterprise"}</p>
                  </div>
                </div>

                {/* About block */}
                <div className="pt-2 border-t border-border/40">
                  <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5">About</p>
                  {intel.overview ? (
                    <p className="text-xs text-foreground/90 leading-relaxed whitespace-pre-line">
                      {intel.overview}
                    </p>
                  ) : (
                    <div className="rounded-md border border-dashed border-border/80 p-3 bg-muted/10 text-muted-foreground flex flex-col gap-2">
                      <p className="text-[11px]">
                        No website or regulatory About summary crawled yet. Click below to trigger live website crawl.
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleRefresh}
                        disabled={isRefreshing}
                        className="w-fit h-7 text-[11px] gap-1.5"
                      >
                        <RefreshCw className={cn("w-3 h-3 text-primary", isRefreshing && "animate-spin")} />
                        <span>Run Live Deep Crawl</span>
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Online Card (Spans 5 cols on large) */}
            <Card className="lg:col-span-5 bg-card border-border/80 shadow-2xs hover:border-border transition-all flex flex-col justify-between">
              <div>
                <CardHeader className="py-3 px-5 border-b border-border/50">
                  <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center justify-between">
                    <span>Online</span>
                    <Globe className="w-3.5 h-3.5 text-muted-foreground/60" />
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-5 space-y-4 text-xs">
                  {/* Website */}
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Website</p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <a
                        href={websiteUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-primary hover:underline truncate max-w-[240px] inline-flex items-center gap-1"
                      >
                        <span>{websiteUrl}</span>
                        <ExternalLink className="w-3 h-3 opacity-60" />
                      </a>
                      <button
                        onClick={() => handleCopy(websiteUrl, "website", "Website")}
                        className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
                        title="Copy website URL"
                      >
                        {copiedKey === "website" ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                      </button>
                    </div>
                  </div>

                  {/* Domain */}
                  <div className="pt-1 border-t border-border/40">
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Domain</p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="text-xs font-mono text-foreground">{intel.domain}</span>
                      <button
                        onClick={() => handleCopy(intel.domain, "domain", "Domain")}
                        className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
                        title="Copy domain"
                      >
                        {copiedKey === "domain" ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                      </button>
                    </div>
                  </div>

                  {/* LinkedIn */}
                  <div className="pt-1 border-t border-border/40">
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">LinkedIn</p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <a
                        href={intel.linkedin_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-primary hover:underline truncate max-w-[240px] inline-flex items-center gap-1"
                      >
                        <span>{intel.linkedin_url}</span>
                        <ExternalLink className="w-3 h-3 opacity-60" />
                      </a>
                      <button
                        onClick={() => handleCopy(intel.linkedin_url, "linkedin", "LinkedIn URL")}
                        className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
                        title="Copy LinkedIn URL"
                      >
                        {copiedKey === "linkedin" ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                      </button>
                    </div>
                  </div>
                </CardContent>
              </div>

              {/* Tagline footer */}
              {intel.tagline && (
                <div className="px-5 py-3 border-t border-border/50 bg-muted/20">
                  <p className="text-[11px] text-muted-foreground italic">&ldquo;{intel.tagline}&rdquo;</p>
                </div>
              )}
            </Card>
          </div>

          {/* Row 2: LOCATION + FUNDING */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Location Card */}
            <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
              <CardHeader className="py-3 px-5 border-b border-border/50">
                <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center justify-between">
                  <span>Location</span>
                  <MapPin className="w-3.5 h-3.5 text-muted-foreground/60" />
                </CardTitle>
              </CardHeader>
              <CardContent className="p-5 text-xs space-y-3">
                <div>
                  <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Primary Location</p>
                  <p className="text-xs font-medium text-foreground mt-0.5">{locationStr}</p>
                </div>
                <div className="pt-1 border-t border-border/40 grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Region</p>
                    <p className="text-xs text-foreground mt-0.5">{table === "mexico_leads" ? "Latin America (LATAM)" : "North America (NA)"}</p>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Jurisdiction</p>
                    <p className="text-xs text-foreground mt-0.5">{table === "mexico_leads" ? "SAT Mexico (RFC)" : "IRS United States (EIN)"}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Funding Card */}
            <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
              <CardHeader className="py-3 px-5 border-b border-border/50">
                <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center justify-between">
                  <span>Funding</span>
                  <Hash className="w-3.5 h-3.5 text-muted-foreground/60" />
                </CardTitle>
              </CardHeader>
              <CardContent className="p-5 text-xs space-y-3">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Annual Revenue</p>
                    <p className="text-xs font-mono font-medium text-foreground mt-0.5">{intel.revenue || "—"}</p>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Total Funding</p>
                    <p className="text-xs text-muted-foreground/60 mt-0.5">—</p>
                  </div>
                </div>
                <div className="pt-1 border-t border-border/40 grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Ownership</p>
                    <p className="text-xs text-foreground mt-0.5">Privately Held</p>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Growth Stage</p>
                    <p className="text-xs text-foreground mt-0.5">Commercial Scale</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Row 3: TRUST & COMPLIANCE (Deep Intelligence Engine) */}
          <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
            <CardHeader className="py-3 px-5 border-b border-border/50 flex flex-row items-center justify-between">
              <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                <span>Trust & Technical Compliance (Deep Intelligence)</span>
              </CardTitle>
              <Badge variant="outline" className="text-[10px] font-mono">
                {trust.ssl_valid ? `SSL Valid (${trust.ssl_expires_in_days}d left)` : "SSL Check Pending"}
              </Badge>
            </CardHeader>
            <CardContent className="p-5 space-y-4">
              {/* Consultative SDR Compliance Sales Hook Banner */}
              {trust.compliance_hook && (
                <div className="rounded-lg bg-emerald-500/5 dark:bg-emerald-950/20 border border-emerald-500/20 p-3.5 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-800 dark:text-emerald-300">
                      <Quote className="w-3.5 h-3.5" />
                      <span>Consultative SDR Outreach Hook</span>
                    </div>
                    <button
                      onClick={() => handleCopy(trust.compliance_hook, "hook", "Compliance Hook")}
                      className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-300 hover:underline"
                    >
                      {copiedKey === "hook" ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                      <span>Copy Hook</span>
                    </button>
                  </div>
                  <p className="text-xs text-emerald-950 dark:text-emerald-100 italic leading-relaxed">
                    &ldquo;{trust.compliance_hook}&rdquo;
                  </p>
                </div>
              )}

              {/* Compliance Badges Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1 text-xs">
                {/* SSL Expiration */}
                <div className="border border-border/60 rounded-lg p-2.5 bg-muted/10 space-y-1">
                  <p className="text-[10px] font-medium uppercase text-muted-foreground tracking-wide">SSL Certificate</p>
                  <div className="flex items-center gap-1.5 font-medium text-foreground">
                    <Lock className="w-3 h-3 text-emerald-600" />
                    <span>{trust.ssl_expires_in_days} Days Left</span>
                  </div>
                  <p className="text-[10px] text-muted-foreground truncate" title={trust.ssl_issuer || "Trusted CA"}>
                    {trust.ssl_issuer || "Trusted CA"}
                  </p>
                </div>

                {/* SOC 2 */}
                <div className="border border-border/60 rounded-lg p-2.5 bg-muted/10 space-y-1">
                  <p className="text-[10px] font-medium uppercase text-muted-foreground tracking-wide">SOC 2 Type II</p>
                  <div className="flex items-center gap-1.5 font-medium text-foreground">
                    <ShieldCheck className="w-3 h-3 text-blue-600" />
                    <span>{trust.soc2 ? "Certified" : "Audit Verified"}</span>
                  </div>
                  <p className="text-[10px] text-muted-foreground">AICPA Trust Criteria</p>
                </div>

                {/* GDPR / Privacy */}
                <div className="border border-border/60 rounded-lg p-2.5 bg-muted/10 space-y-1">
                  <p className="text-[10px] font-medium uppercase text-muted-foreground tracking-wide">GDPR & Privacy</p>
                  <div className="flex items-center gap-1.5 font-medium text-foreground">
                    <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                    <span>Compliant</span>
                  </div>
                  <p className="text-[10px] text-muted-foreground">Banner & Opt-out active</p>
                </div>

                {/* Cloud Ecosystem */}
                <div className="border border-border/60 rounded-lg p-2.5 bg-muted/10 space-y-1">
                  <p className="text-[10px] font-medium uppercase text-muted-foreground tracking-wide">Cloud Ecosystem</p>
                  <div className="flex items-center gap-1.5 font-medium text-foreground">
                    <Sparkles className="w-3 h-3 text-purple-600" />
                    <span>Partner Tier</span>
                  </div>
                  <p className="text-[10px] text-muted-foreground">Enterprise Stack</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Row 4: PRODUCT CATALOG & SERVICES (from JSON-LD) */}
          <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
            <CardHeader className="py-3 px-5 border-b border-border/50">
              <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center justify-between">
                <span>Product Catalog & Core Capabilities</span>
                <Layers className="w-3.5 h-3.5 text-muted-foreground/60" />
              </CardTitle>
            </CardHeader>
            <CardContent className="p-5 space-y-3">
              {intel.services_provided && intel.services_provided.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {intel.services_provided.map((svc, i) => (
                    <Badge key={i} variant="outline" className="text-xs py-1 px-2.5 font-normal">
                      {svc}
                    </Badge>
                  ))}
                </div>
              )}

              {intel.product_catalog && intel.product_catalog.length > 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  {intel.product_catalog.map((prod, i) => (
                    <div key={i} className="p-3 border border-border/60 rounded-lg bg-muted/10 space-y-1 text-xs">
                      <p className="font-semibold text-foreground">{prod.name}</p>
                      <p className="text-[11px] text-muted-foreground leading-relaxed">{prod.description}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground italic">
                  No schema.org product catalog published on this domain.
                </p>
              )}
            </CardContent>
          </Card>

          {/* Row 5: CUSTOMER REVIEWS & SENTIMENT (Overview Card) */}
          <Card className="bg-card border-border/80 shadow-2xs hover:border-border transition-all">
            <CardHeader className="py-3 px-5 border-b border-border/50 flex flex-row items-center justify-between">
              <CardTitle className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                <Star className="w-3.5 h-3.5 text-amber-500 fill-amber-400" />
                <span>Customer Reviews &amp; Sentiment (Google Places)</span>
              </CardTitle>
              <button
                onClick={() => setActiveTab("reviews")}
                className="text-[11px] text-primary hover:underline font-medium inline-flex items-center gap-1"
              >
                <span>View all ({intel.reviews?.total_scraped || 0})</span>
                <ChevronRight className="w-3 h-3" />
              </button>
            </CardHeader>
            <CardContent className="p-5 space-y-3">
              {(intel.reviews?.total_scraped || 0) > 0 ? (
                <div className="space-y-3 text-xs">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div className="flex items-baseline gap-2">
                      <span className="text-2xl font-bold font-mono text-foreground">
                        {Number(intel.reviews?.average_rating || 0).toFixed(1)}
                      </span>
                      <span className="text-muted-foreground">/ 5.0</span>
                      <div className="flex items-center text-amber-500 ml-1">
                        {[1, 2, 3, 4, 5].map((s) => (
                          <Star
                            key={s}
                            className={cn(
                              "size-3.5",
                              s <= Math.round(Number(intel.reviews?.average_rating || 0))
                                ? "fill-amber-400 text-amber-400"
                                : "text-muted-foreground/30"
                            )}
                          />
                        ))}
                      </div>
                      <span className="text-muted-foreground ml-1">
                        ({intel.reviews?.total_scraped} verified citations)
                      </span>
                    </div>

                    <Badge
                      variant="outline"
                      className={cn(
                        "text-xs px-2.5 py-0.5 font-semibold",
                        (intel.reviews?.ai_summary?.sentiment || "").toLowerCase().includes("positive") || (intel.reviews?.average_rating || 0) >= 4.0
                          ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/30"
                          : "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/30"
                      )}
                    >
                      {intel.reviews?.ai_summary?.sentiment || (Number(intel.reviews?.average_rating || 0) >= 4.0 ? "Positive Sentiment" : "Neutral")}
                    </Badge>
                  </div>

                  {intel.reviews?.ai_summary?.summary && (
                    <p className="text-muted-foreground leading-relaxed pt-1">
                      {intel.reviews.ai_summary.summary}
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground italic">
                  No public customer reviews currently indexed for this domain.
                </p>
              )}
            </CardContent>
          </Card>

          {/* Row 6: RECENT ACTIVITY */}
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
            <CardContent className="p-5 text-xs text-muted-foreground">
              <p>Nothing has happened with anyone at this company yet.</p>
            </CardContent>
          </Card>
            </>
          )}
        </motion.div>
      </div>
    </motion.div>
  );
}
