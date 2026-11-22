"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";

interface PlaceResponse {
  place: {
    place_id: string;
    name: string | null;
    address: string | null;
    phone: string | null;
    website: string | null;
    category: string | null;
    status: string;
    rating: number | null;
    review_count: number | null;
    scraped_at: string;
    source: string;
  };
  services: { group_name: string; service_name: string; is_enabled: boolean; origin: string }[];
  contacts: { contact_type: string; value: string; label: string | null; extraction_method: string }[];
  people: { full_name: string; role_title: string; email: string | null; extraction_method: string }[];
}

export function PlaceDetail({ placeId }: { placeId: string }) {
  const [data, setData] = useState<PlaceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PlaceResponse>(`/v1/places/${encodeURIComponent(placeId)}`)
      .then((d) => {
        setData(d);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load place"));
  }, [placeId]);

  if (error) return <div className="p-6 text-sm text-destructive">{error}</div>;
  if (!data) return <div className="p-6"><Loader2 className="animate-spin" /></div>;

  const { place } = data;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{place.name ?? place.place_id}</h1>
        <p className="text-sm text-muted-foreground">
          {place.address ?? "No address"} · {place.phone ?? "no phone"}
          {place.website && (
            <> · <a className="underline" href={place.website} target="_blank" rel="noreferrer noopener">website</a></>
          )}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Badge>{place.status}</Badge>
          <Badge variant="outline">rating {place.rating ?? "n/a"} ({place.review_count ?? 0} on Google)</Badge>
          <Badge variant="secondary">scraped {new Date(place.scraped_at).toLocaleString()}</Badge>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader><CardTitle className="text-base">Services</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            {data.services.length === 0 && <p className="text-muted-foreground">None found.</p>}
            {data.services.map((s) => (
              <div key={`${s.group_name}:${s.service_name}`}>
                {s.service_name}
                <span className="ml-2 text-xs text-muted-foreground">{s.group_name || s.origin}</span>
                {!s.is_enabled && <span className="ml-2 text-xs text-amber-500">not offered</span>}
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">Contacts</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            {data.contacts.length === 0 && <p className="text-muted-foreground">None found.</p>}
            {data.contacts.map((c) => (
              <div key={`${c.contact_type}:${c.value}`}>
                <Badge variant="outline" className="mr-2">{c.contact_type}</Badge>{c.value}
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">People</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            {data.people.length === 0 && <p className="text-muted-foreground">None found.</p>}
            {data.people.map((p) => (
              <div key={`${p.full_name}:${p.role_title}`}>
                <b>{p.full_name}</b> <span className="text-muted-foreground">{p.role_title}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
