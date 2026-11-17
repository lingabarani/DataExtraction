"use client";

import Link from "next/link";
import React from "react";
import { ExternalLink, Globe, Mail, Phone, ShieldCheck, Star, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { DiscoveryCard } from "@/lib/api";
import { sourceLabel } from "./SourceStatusPanel";

const EMAIL_STYLE: Record<string, string> = {
  found: "border-emerald-500 text-emerald-700",
  verified: "border-blue-500 text-blue-700",
  inferred: "border-muted-foreground/40 text-muted-foreground",
};

function EmailRow({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex items-center gap-1 text-[11px]">
      <Mail className="w-2.5 h-2.5 text-muted-foreground" />
      <span className="font-mono">{value}</span>
      <Badge variant="outline" className={`text-[9px] px-1 py-0 ${EMAIL_STYLE[label] ?? EMAIL_STYLE.inferred}`}
             title={label === "inferred" ? "Pattern guess with a valid mail domain. Not confirmed." : label}>
        {label}
      </Badge>
    </div>
  );
}

export function cardAddress(card: DiscoveryCard): string {
  const street = String(card.address?.street || "");
  const zip = String(card.address?.postal_code || "");
  const city = String(card.address?.city || "");
  // Some sources already put the full "street, city, ST zip" line in street: do not repeat city/state/zip
  if (street && ((zip && street.includes(zip)) || (city && street.toLowerCase().includes(city.toLowerCase())))) return street;
  return [street, card.address?.city, card.address?.state, zip].filter(Boolean).join(", ");
}

export function cardPhones(card: DiscoveryCard): string[] {
  return card.phones?.length ? card.phones : card.phone ? [card.phone] : [];
}

/** `linkable` is false while the search is still running: ids become final once results are saved. */
export function ResultCard({ card, linkable = true }: { card: DiscoveryCard; linkable?: boolean }) {
  const address = cardAddress(card);
  const phones = cardPhones(card);

  return (
    <Card className="border-border/80" data-testid="result-card">
      <CardHeader className="p-5 pb-3">
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              {linkable ? (
                <Link href={`/search/org/${card.org_id}`} className="text-lg font-bold tracking-tight hover:underline"
                      title="Open full details">
                  {card.name}
                </Link>
              ) : (
                <span className="text-lg font-bold tracking-tight">{card.name}</span>
              )}
            </div>
            {card.category && <p className="text-xs text-muted-foreground mt-0.5">{card.category}</p>}
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            {card.cms_star_rating != null && (
              <Badge variant="secondary" className="text-xs" title="CMS Care Compare star rating">
                <Star className="w-3 h-3 mr-1" />CMS {card.cms_star_rating}★
              </Badge>
            )}
            {card.nc_license_number && (
              <Badge variant="secondary" className="text-xs" title="Listed on the NC DHSR licensing roster">
                <ShieldCheck className="w-3 h-3 mr-1" />NC {card.nc_license_number}
              </Badge>
            )}
            {card.rating != null && (
              <Badge variant="outline" className="text-xs" title="Google Maps rating">
                ★ {card.rating} on Google · {(card.review_count || 0).toLocaleString()} reviews
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-5 pt-0 space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground pt-2 border-t">
          {address && <span>{address}</span>}
          {phones.map((ph) => (
            <a key={ph} href={`tel:${ph}`} className="flex items-center gap-1 text-foreground hover:underline font-medium">
              <Phone className="w-3 h-3 text-primary" />{ph}
            </a>
          ))}
          {card.website && (
            <a href={card.website} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-primary hover:underline">
              <Globe className="w-3 h-3" />Website<ExternalLink className="w-2.5 h-2.5" />
            </a>
          )}
          {Object.entries(card.social || {}).map(([k, v]) => (
            <a key={k} href={v} target="_blank" rel="noopener noreferrer" className="capitalize text-primary hover:underline">{k}</a>
          ))}
        </div>

        {card.emails.length > 0 && <div className="space-y-0.5">{card.emails.map((e) => <EmailRow key={e.value} {...e} />)}</div>}

        {card.services.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] font-medium text-muted-foreground">Services:</span>
            {card.services.map((svc) => (
              <Badge key={svc} variant="outline" className="text-[10px] py-0 capitalize">{svc.replace(/_/g, " ")}</Badge>
            ))}
          </div>
        )}

        {card.named_people.length > 0 && (
          <div className="bg-muted/30 rounded-md p-3 space-y-2 border">
            <div className="flex items-center gap-1 text-xs font-semibold"><Users className="w-3.5 h-3.5 text-primary" />People</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
              {card.named_people.map((p, i) => (
                <div key={i} className="flex flex-col gap-0.5">
                  <span className="font-medium text-foreground">{p.name}</span>
                  {p.title && <span className="text-[11px] text-muted-foreground">{p.title}</span>}
                  {p.emails.map((e) => <EmailRow key={e.value} value={e.value} label={e.label} />)}
                  {p.profile_urls.filter((u) => u.startsWith("http")).slice(0, 1).map((u) => (
                    <a key={u} href={u} target="_blank" rel="noopener noreferrer" className="text-[11px] text-primary hover:underline truncate">{u}</a>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-1 flex-wrap text-[11px] text-muted-foreground pt-1">
          <span>Found on:</span>
          {card.sources.map((src) => {
            const link = card.source_links?.find((l) => l.source === src)?.url;
            const badge = <Badge variant="outline" className="text-[10px] py-0">{sourceLabel(src)}</Badge>;
            return link ? <a key={src} href={link} target="_blank" rel="noopener noreferrer">{badge}</a> : <span key={src}>{badge}</span>;
          })}
        </div>
      </CardContent>
    </Card>
  );
}
