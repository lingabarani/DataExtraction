"use client";
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
  User, Building2, ContactIcon, Briefcase,
  Linkedin, CheckCircle2, XCircle, AlertCircle,
  Calendar, Hash, Flag, Users,
} from "lucide-react";
import { useLead } from "@/hooks/use-leads";
import type { PersonJSON, CompanyJSON, ContactJSON } from "@/hooks/use-leads";
import { toast } from "sonner";

// ── Helpers ───────────────────────────────────────────────────────────────────

const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.07 } } };
const item      = { hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0 } };

function copy(value: string, label: string) {
  navigator.clipboard.writeText(value);
  toast.success(`${label} copied`);
}

function Row({ icon: Icon, label, value, copyable = false }: {
  icon: React.ElementType; label: string; value: string | null | undefined; copyable?: boolean;
}) {
  if (!value) return null;
  return (
    <div className="flex items-start gap-3 py-1.5">
      <Icon className="w-3.5 h-3.5 text-muted-foreground mt-0.5 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wide">{label}</p>
        <p className="text-sm break-all">{value}</p>
      </div>
      {copyable && (
        <Button
          variant="ghost" size="icon"
          className="h-6 w-6 opacity-40 hover:opacity-100 flex-shrink-0"
          onClick={() => copy(value, label)}
        >
          <Copy className="w-3 h-3" />
        </Button>
      )}
    </div>
  );
}

function SectionTitle({ icon: Icon, title, color = "text-primary" }: {
  icon: React.ElementType; title: string; color?: string;
}) {
  return (
    <CardHeader className="pb-3 pt-4">
      <CardTitle className="text-sm flex items-center gap-2">
        <Icon className={`w-4 h-4 ${color}`} />
        {title}
      </CardTitle>
    </CardHeader>
  );
}

// ── Email status badge ────────────────────────────────────────────────────────
function EmailStatusBadge({ status }: { status: string | null }) {
  if (status === "DELIVERABLE" || status === "VERIFIED") return (
    <Badge className="bg-emerald-500/10 text-emerald-600 border-emerald-200 gap-1 text-xs">
      <ShieldCheck className="w-3 h-3" /> Deliverable
    </Badge>
  );
  if (status === "MX_CONFIRMED" || status === "VALID") return (
    <Badge className="bg-blue-500/10 text-blue-600 border-blue-200 gap-1 text-xs">
      <ShieldCheck className="w-3 h-3" /> MX Confirmed
    </Badge>
  );
  if (status === "SYNTAX_VALID") return (
    <Badge className="bg-indigo-500/10 text-indigo-600 border-indigo-200 gap-1 text-xs">
      <ShieldCheck className="w-3 h-3" /> Syntax Valid
    </Badge>
  );
  if (status === "RISKY" || status === "GUESSED") return (
    <Badge className="bg-amber-500/10 text-amber-600 border-amber-200 gap-1 text-xs">
      <ShieldAlert className="w-3 h-3" /> Risky
    </Badge>
  );
  if (status === "UNDELIVERABLE" || status === "INVALID") return (
    <Badge className="bg-red-500/10 text-red-600 border-red-200 gap-1 text-xs">
      <ShieldOff className="w-3 h-3" /> Undeliverable
    </Badge>
  );
  return (
    <Badge variant="outline" className="gap-1 text-xs text-muted-foreground">
      <Minus className="w-3 h-3" /> No email
    </Badge>
  );
}

// ── Email check row ───────────────────────────────────────────────────────────
function CheckRow({ label, passed }: { label: string; passed: boolean }) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      {passed
        ? <CheckCircle2 className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
        : <XCircle      className="w-3.5 h-3.5 text-red-400  flex-shrink-0" />
      }
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

// ── Score arc ─────────────────────────────────────────────────────────────────
function ScoreArc({ score }: { score: number | null }) {
  if (!score) return null;
  const color = score >= 80 ? "#22c55e" : score >= 50 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex flex-col items-center justify-center py-2">
      <div className="relative w-20 h-20">
        <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
          <circle cx="40" cy="40" r="32" fill="none" stroke="hsl(var(--muted))" strokeWidth="6" />
          <circle
            cx="40" cy="40" r="32" fill="none"
            stroke={color} strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={`${2 * Math.PI * 32}`}
            strokeDashoffset={`${2 * Math.PI * 32 * (1 - score / 100)}`}
            className="transition-all duration-700"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xl font-bold" style={{ color }}>{score}</span>
        </div>
      </div>
      <p className="text-xs text-muted-foreground mt-1">Lead Score</p>
    </div>
  );
}

// ── Person panel ──────────────────────────────────────────────────────────────
function PersonPanel({ person, seniority }: { person: PersonJSON | null; seniority: string | null }) {
  if (!person) return (
    <p className="text-xs text-muted-foreground px-4 pb-4 italic">No person data available</p>
  );
  return (
    <CardContent className="pt-0 space-y-0.5">
      <Row icon={User}      label="Full Name"    value={person.full_name} copyable />
      <Row icon={Briefcase} label="Title"        value={person.official_title ?? person.title} />
      <Row icon={Briefcase} label="Std. Title"   value={person.standardized_title} />
      {seniority && (
        <div className="flex items-center gap-3 py-1.5">
          <Flag className="w-3.5 h-3.5 text-muted-foreground" />
          <div>
            <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wide">Seniority</p>
            <Badge variant="outline" className="text-xs mt-0.5">{seniority.replace("_", "-")}</Badge>
          </div>
        </div>
      )}
      <Row icon={Hash}      label="Department"   value={person.department} />
      <Row icon={Calendar}  label="Joined Date"  value={person.joined_date} />
      <Row icon={Calendar}  label="Years at Co." value={person.years_at_company ? `${person.years_at_company} years` : null} />
      <Row icon={Hash}      label="Source"       value={person.source_registry ?? person.api_source} />

      {/* Career history */}
      {person.career_history && person.career_history.length > 0 && (
        <>
          <Separator className="my-3" />
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide px-0 pb-1">
            Career History ({person.career_history.length})
          </p>
          <div className="space-y-2">
            {person.career_history.map((c, i) => (
              <div key={i} className="pl-3 border-l-2 border-primary/20">
                <p className="text-xs font-medium">{c.role}</p>
                <p className="text-[11px] text-muted-foreground">{c.company_name}</p>
                <p className="text-[10px] text-muted-foreground/60">
                  {c.start_date} – {c.is_current ? "Present" : (c.end_date ?? "?")}
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </CardContent>
  );
}

// ── Company panel ─────────────────────────────────────────────────────────────
function CompanyPanel({ company }: { company: CompanyJSON | null }) {
  if (!company) return (
    <p className="text-xs text-muted-foreground px-4 pb-4 italic">No company data available</p>
  );
  const addr = company.address;
  const addrStr = addr
    ? [addr.street, addr.number, addr.city ?? addr.municipality, addr.state, addr.zip_code ?? (addr as any).postal_code, addr.country]
        .filter(Boolean).join(", ")
    : null;

  const empStr = company.employee_min || company.employee_max
    ? `${company.employee_min?.toLocaleString() ?? "?"} – ${company.employee_max?.toLocaleString() ?? "?"}`
    : company.employee_band ?? null;

  return (
    <CardContent className="pt-0 space-y-0.5">
      <Row icon={Building2} label="Legal Name"    value={company.legal_name ?? company.name} copyable />
      <Row icon={Building2} label="Trade Name"    value={company.trade_name} />
      <Row icon={Globe}     label="Website"       value={company.website} copyable />
      <Row icon={Globe}     label="Domain"        value={company.domain} copyable />
      <Row icon={Hash}      label="Industry"      value={company.industry} />
      <Row icon={Hash}      label="NAICS"         value={company.naics_code} />
      <Row icon={Hash}      label="EIN"           value={company.ein} copyable />
      <Row icon={Hash}      label="CIK"           value={company.cik} />
      <Row icon={Hash}      label="RFC"           value={company.rfc} copyable />
      <Row icon={Hash}      label="RFC Type"      value={company.rfc_type} />
      <Row icon={Users2}    label="Employees"     value={empStr} />
      <Row icon={Phone}     label="Main Phone"    value={company.phone} copyable />
      <Row icon={Mail}      label="Main Email"    value={company.email} copyable />
      <Row icon={MapPin}    label="Address"       value={addrStr} />
      {company.last_verified_at && (
        <Row icon={Calendar} label="Last Verified" value={new Date(company.last_verified_at).toLocaleDateString()} />
      )}
    </CardContent>
  );
}

// ── Contact / validation panel ────────────────────────────────────────────────
function ContactPanel({ contact }: { contact: ContactJSON | null }) {
  if (!contact) return (
    <p className="text-xs text-muted-foreground px-4 pb-4 italic">No contact validation data</p>
  );
  return (
    <CardContent className="pt-0 space-y-3">
      {/* Email block */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Mail className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold">Email</span>
          </div>
          <EmailStatusBadge status={contact.email_status} />
        </div>
        {contact.email ? (
          <div className="flex items-center gap-2 pl-5">
            <span className="text-sm break-all flex-1">{contact.email}</span>
            <Button variant="ghost" size="icon" className="h-6 w-6 opacity-50 hover:opacity-100"
              onClick={() => copy(contact.email!, "Email")}>
              <Copy className="w-3 h-3" />
            </Button>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground pl-5 italic">No email</p>
        )}
        {contact.email_evidence_level && (
          <p className="text-[11px] text-muted-foreground/70 pl-5 font-mono">
            Evidence: {contact.email_evidence_level}
          </p>
        )}
        {contact.email_confidence_score != null && (
          <div className="pl-5">
            <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
              <span>Confidence</span>
              <span className="font-medium text-foreground">{contact.email_confidence_score}%</span>
            </div>
            <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  contact.email_confidence_score >= 80 ? "bg-green-500" :
                  contact.email_confidence_score >= 50 ? "bg-amber-500" : "bg-red-400"
                }`}
                style={{ width: `${contact.email_confidence_score}%` }}
              />
            </div>
          </div>
        )}
        {/* Email checks */}
        {contact.email_checks && (
          <div className="pl-5 space-y-0.5 pt-1">
            <CheckRow label="Syntax valid"       passed={contact.email_checks.syntax} />
            <CheckRow label="Domain valid"       passed={contact.email_checks.domain} />
            <CheckRow label="MX record exists"   passed={contact.email_checks.mx_record} />
            <CheckRow label="Not disposable"     passed={!contact.email_checks.disposable} />
            <CheckRow label="Not role address"   passed={!contact.email_checks.role_addr} />
            <CheckRow label="Source verified"    passed={Boolean(contact.email_checks.pre_verified || contact.email_checks.smtp_verified)} />
          </div>
        )}
      </div>

      <Separator />

      {/* Phone block */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Phone className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold">Phone</span>
            {contact.phone_type && contact.phone_type !== "UNKNOWN" && (
              <Badge variant="outline" className="text-[10px] capitalize py-0 px-1.5">
                {contact.phone_type.toLowerCase().replace(/_/g, " ")}
              </Badge>
            )}
          </div>
          {contact.phone_status === "VALID_E164" && (
            <Badge className="bg-emerald-500/10 text-emerald-600 border-emerald-200 text-xs gap-1">
              <CheckCircle2 className="w-3 h-3" /> E.164
            </Badge>
          )}
          {contact.phone_status === "NORMALIZED" && (
            <Badge className="bg-blue-500/10 text-blue-600 border-blue-200 text-xs gap-1">
              <AlertCircle className="w-3 h-3" /> Normalized
            </Badge>
          )}
          {(!contact.phone_status || contact.phone_status === "MISSING") && (
            <Badge variant="outline" className="text-xs text-muted-foreground gap-1">
              <Minus className="w-3 h-3" /> No phone
            </Badge>
          )}
        </div>
        {contact.phone ? (
          <div className="flex items-center gap-2 pl-5">
            <span className="text-sm flex-1 font-mono">{contact.phone}</span>
            <Button variant="ghost" size="icon" className="h-6 w-6 opacity-50 hover:opacity-100"
              onClick={() => copy(contact.phone!, "Phone")}>
              <Copy className="w-3 h-3" />
            </Button>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground pl-5 italic">No phone</p>
        )}
        <div className="flex items-center gap-3 pl-5 text-[11px] text-muted-foreground">
          {contact.phone_country && (
            <span>Country: {contact.phone_country}</span>
          )}
          {contact.phone_national && (
            <span>National: {contact.phone_national}</span>
          )}
        </div>
      </div>

      <Separator />

      {/* LinkedIn */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <Linkedin className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">LinkedIn</span>
        </div>
        {contact.linkedin_url ? (
          <div className="flex items-center gap-2 pl-5">
            <a
              href={contact.linkedin_url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-accent hover:underline truncate flex-1"
            >
              {contact.linkedin_url}
            </a>
            <Button variant="ghost" size="icon" className="h-6 w-6 opacity-50 hover:opacity-100"
              onClick={() => copy(contact.linkedin_url!, "LinkedIn URL")}>
              <Copy className="w-3 h-3" />
            </Button>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground pl-5 italic">No LinkedIn</p>
        )}
      </div>

      {contact.validated_at && (
        <p className="text-[11px] text-muted-foreground/60 pt-1">
          Validated: {new Date(contact.validated_at).toLocaleString()}
        </p>
      )}
    </CardContent>
  );
}

// Workaround for Users2 not in some versions
function Users2({ className }: { className?: string }) {
  return <Users className={className} />;
}

// ── Main component ────────────────────────────────────────────────────────────
export function LeadDetail({ id, table = "us_leads" }: {
  id: string;
  table?: "us_leads" | "mexico_leads";
}) {
  const { lead, loading } = useLead(id, table);

  if (loading) {
    return (
      <div className="space-y-4 max-w-6xl">
        <div className="flex items-center gap-3">
          <Skeleton className="h-9 w-9 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-3.5 w-1/2" />
          </div>
          <Skeleton className="h-20 w-20 rounded-full" />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {[1,2,3].map(i => (
            <Card key={i}>
              <CardHeader><Skeleton className="h-4 w-24" /></CardHeader>
              <CardContent className="space-y-3">
                {[1,2,3,4].map(j => <Skeleton key={j} className="h-3.5 w-full" />)}
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (!lead) {
    return (
      <div className="text-center py-20">
        <p className="text-muted-foreground">Lead not found</p>
        <Button asChild variant="outline" className="mt-4">
          <Link href="/leads">Back to leads</Link>
        </Button>
      </div>
    );
  }

  const backHref = table === "mexico_leads" ? "/leads/mexico" : "/leads";

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="space-y-5 max-w-6xl">

      {/* ── Header row ──────────────────────────────────────────────── */}
      <motion.div variants={item} className="flex items-center gap-3 flex-wrap">
        <Button variant="ghost" size="icon" asChild>
          <Link href={backHref}><ArrowLeft className="h-4 w-4" /></Link>
        </Button>
        <div className="w-10 h-10 bg-gradient-brand rounded-xl flex items-center justify-center text-white font-bold flex-shrink-0 shadow-glow">
          {(lead.full_name ?? lead.company_name ?? "?").charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-bold">{lead.full_name ?? lead.company_name ?? "Unknown"}</h1>
            {lead.seniority_level && (
              <Badge variant="outline" className="text-xs">{lead.seniority_level.replace("_","-")}</Badge>
            )}
            {lead.email_status === "VERIFIED" && (
              <Badge className="bg-green-500/10 text-green-600 border-green-200 text-xs gap-1">
                <ShieldCheck className="w-3 h-3" /> Verified email
              </Badge>
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            {[lead.title, lead.company_name, lead.industry, [lead.city, lead.state_code].filter(Boolean).join(", ")]
              .filter(Boolean).join(" · ")}
          </p>
        </div>
        <ScoreArc score={lead.lead_score} />
      </motion.div>

      {/* ── 3-column JSONB panels ────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Person */}
        <motion.div variants={item}>
          <Card>
            <SectionTitle icon={User} title="Person" color="text-blue-500" />
            <Separator />
            <PersonPanel person={lead.person} seniority={lead.seniority_level} />
          </Card>
        </motion.div>

        {/* Company */}
        <motion.div variants={item}>
          <Card>
            <SectionTitle icon={Building2} title="Company" color="text-amber-500" />
            <Separator />
            <CompanyPanel company={lead.company} />
          </Card>
        </motion.div>

        {/* Contact Validation */}
        <motion.div variants={item}>
          <Card>
            <SectionTitle icon={ContactIcon} title="Contact Validation" color="text-green-500" />
            <Separator />
            <ContactPanel contact={lead.contact} />
          </Card>
        </motion.div>
      </div>

      {/* ── Raw data source row ──────────────────────────────────────── */}
      <motion.div variants={item}>
        <Card>
          <CardHeader className="pb-2 pt-3">
            <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wider">
              Record Metadata
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
              <div>
                <p className="text-muted-foreground">ID</p>
                <p className="font-mono text-[11px] truncate">{lead.id}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Source</p>
                <p className="font-medium">{lead.api_source ?? "—"}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Table</p>
                <p className="font-medium">{table}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Created</p>
                <p>{lead.created_at ? new Date(lead.created_at).toLocaleDateString() : "—"}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </motion.div>
  );
}
