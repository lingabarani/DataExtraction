"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, DiscoveryOrganization } from "@/lib/api";

function show(value: any): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") {
    if ("value" in value && Object.keys(value).length === 1) return String(value.value);
    return Object.entries(value).map(([k, v]) => `${k}: ${v}`).join(", ");
  }
  return String(value);
}

export function DiscoveryOrgDetail({ orgId }: { orgId: string }) {
  const [org, setOrg] = useState<DiscoveryOrganization | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.discovery.getOrganization(orgId).then(setOrg).catch((e) => setError(e.message || "Not found"));
  }, [orgId]);

  if (error) return <div className="p-6 text-sm text-destructive">{error}</div>;
  if (!org) return <div className="p-6"><Loader2 className="animate-spin" /></div>;

  const addr = [org.address.street, org.address.city, org.address.state, org.address.postal_code].filter(Boolean).join(", ");
  const reg = org.regulatory || {};

  return (
    <div className="container mx-auto max-w-5xl py-8 px-4 space-y-6">
      <Link href="/search" className="text-xs text-primary flex items-center gap-1 hover:underline">
        <ArrowLeft className="w-3 h-3" /> Back to search
      </Link>
      <div>
        <h1 className="text-2xl font-bold">{org.name}</h1>
        <p className="text-sm text-muted-foreground">{org.category}{addr ? ` · ${addr}` : ""}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {reg.cms_star_rating != null && <Badge>CMS {reg.cms_star_rating}★</Badge>}
          {reg.nc_license_number && <Badge variant="secondary">NC license {reg.nc_license_number}</Badge>}
          {org.rating != null && <Badge variant="outline">Google ★ {org.rating} ({org.review_count ?? 0})</Badge>}
          {org.website && <a className="text-xs underline" href={org.website} target="_blank" rel="noopener noreferrer">website</a>}
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <CardHeader><CardTitle className="text-base">Contacts</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            {org.phones.map((p) => <div key={p.number}>{p.number}</div>)}
            {org.emails.map((e) => (
              <div key={e.value}>{e.value} <Badge variant="outline" className="text-[10px]">{e.label}</Badge></div>
            ))}
            {Object.entries(org.social || {}).map(([k, v]) => (
              <div key={k}><a className="underline" href={v} target="_blank" rel="noopener noreferrer">{k}</a></div>
            ))}
            {!org.phones.length && !org.emails.length && <p className="text-muted-foreground">None recorded.</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">People</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {org.people.map((p) => (
              <div key={p.id}>
                <b>{p.name}</b> <span className="text-muted-foreground">{p.title}</span>
                <span className="ml-2 text-[10px] font-mono text-muted-foreground">{p.provenance}</span>
              </div>
            ))}
            {!org.people.length && <p className="text-muted-foreground">No named people recorded.</p>}
          </CardContent>
        </Card>
      </div>

      {org.services.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">Services</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-1">
            {org.services.map((s) => <Badge key={s} variant="outline" className="capitalize">{s.replace(/_/g, " ")}</Badge>)}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle className="text-base">Facts and sources</CardTitle></CardHeader>
        <CardContent>
          <table className="w-full text-xs" data-testid="facts-table">
            <thead><tr className="text-left text-muted-foreground border-b">
              <th className="py-1 pr-3">Field</th><th className="pr-3">Value</th><th className="pr-3">Source</th><th>Retrieved</th>
            </tr></thead>
            <tbody>
              {org.facts.map((f, i) => (
                <tr key={i} className="border-b last:border-0 align-top">
                  <td className="py-1 pr-3 font-mono">{f.field}</td>
                  <td className="pr-3">{show(f.value)}</td>
                  <td className="pr-3">
                    {f.source_url ? <a className="underline" href={f.source_url} target="_blank" rel="noopener noreferrer">{f.source}</a> : f.source}
                  </td>
                  <td>{f.retrieved_at ? new Date(f.retrieved_at).toLocaleString() : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
