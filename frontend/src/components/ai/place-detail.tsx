"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

interface PlaceResponse {
  place: {
    place_id: string;
    name: string | null;
    address: string | null;
    phone: string | null;
    website: string | null;
    rating: string | number | null;
    review_count: number | null;
    status: string;
    scraped_at: string;
    source: string;
  };
  services: { group_name: string; service_name: string; is_enabled: boolean; origin: string }[];
  contacts: { contact_type: string; value: string; label: string | null; extraction_method: string }[];
  people: { full_name: string; role_title: string; email: string | null; extraction_method: string }[];
  reviews_summary: { stored: number; average_rating: number | null };
}
interface Review {
  review_id: string;
  reviewer_name: string | null;
  reviewer_hash_prefix: string;
  rating: number | null;
  review_text: string | null;
  published_at: string | null;
  owner_response_text: string | null;
  sentiment: string | null;
  topics: string[];
}

const PAGE = 20;

export function PlaceDetail({ placeId }: { placeId: string }) {
  const [data, setData] = useState<PlaceResponse | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const loadReviews = useCallback(async (offset: number) => {
    setLoadingMore(true);
    try {
      const r = await api.get<{ total: number; reviews: Review[] }>(
        `/v1/places/${encodeURIComponent(placeId)}/reviews?limit=${PAGE}&offset=${offset}`,
      );
      setTotal(r.total);
      setReviews((prev) => (offset === 0 ? r.reviews : [...prev, ...r.reviews]));
    } finally {
      setLoadingMore(false);
    }
  }, [placeId]);

  useEffect(() => {
    api
      .get<PlaceResponse>(`/v1/places/${encodeURIComponent(placeId)}`)
      .then((d) => {
        setData(d);
        return loadReviews(0);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load place"));
  }, [placeId, loadReviews]);

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
          <Badge variant="outline">{data.reviews_summary.stored} reviews stored</Badge>
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

      <Card>
        <CardHeader><CardTitle>Reviews ({total})</CardTitle></CardHeader>
        <CardContent className="space-y-3" data-testid="reviews">
          {reviews.map((r) => (
            <div key={r.review_id} className="rounded-md border p-3 text-sm">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <b>{r.reviewer_name ?? `Reviewer ${r.reviewer_hash_prefix || "anonymous"}`}</b>
                <span>{"★".repeat(r.rating ?? 0)}</span>
                {r.sentiment && <Badge variant="outline">{r.sentiment}</Badge>}
                {r.topics.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}
                <span className="text-xs text-muted-foreground">
                  {r.published_at ? new Date(r.published_at).toLocaleDateString() : ""}
                </span>
              </div>
              <p>{r.review_text ?? <i className="text-muted-foreground">No text</i>}</p>
              {r.owner_response_text && (
                <p className="mt-2 border-l-2 pl-3 text-muted-foreground">Owner: {r.owner_response_text}</p>
              )}
            </div>
          ))}
          {reviews.length < total && (
            <Button variant="outline" disabled={loadingMore} onClick={() => void loadReviews(reviews.length)}>
              {loadingMore && <Loader2 className="animate-spin" />} Load more
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
