"use client";

import Link from "next/link";
import React, { useEffect, useMemo, useState } from "react";
import { Download, LayoutList, Search, Table2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, DiscoveryCard, DiscoveryCitation } from "@/lib/api";
import { AnswerSummary } from "./AnswerSummary";
import { ResultCard, cardAddress, cardPhones } from "./ResultCard";
import { sourceLabel } from "./SourceStatusPanel";

const PAGE = 30;

type SortKey = "best" | "name" | "rating" | "reviews";
type Need = "phone" | "website" | "email" | "people" | "licensed" | "rated";

const NEEDS: { key: Need; label: string; test: (c: DiscoveryCard) => boolean }[] = [
  { key: "phone", label: "Has phone", test: (c) => cardPhones(c).length > 0 },
  { key: "website", label: "Has website", test: (c) => !!c.website },
  { key: "email", label: "Has email", test: (c) => c.emails.length > 0 || c.named_people.some((p) => p.emails.length > 0) },
  { key: "people", label: "Has contact person", test: (c) => c.named_people.length > 0 },
  { key: "licensed", label: "State licensed", test: (c) => !!c.nc_license_number },
  { key: "rated", label: "Medicare rated", test: (c) => c.cms_star_rating != null },
];

export interface SearchResultsProps {
  cards: DiscoveryCard[];
  totalOrganizations: number;
  totalPeople: number;
  elapsedMs: number;
  /** true while the search is still running: no links, no export, no summary yet */
  preliminary: boolean;
  searchId: string | null;
  summaryMarkdown?: string;
  citations?: DiscoveryCitation[];
}

export function SearchResults(props: SearchResultsProps) {
  const { cards, totalOrganizations, totalPeople, elapsedMs, preliminary, searchId } = props;
  const [text, setText] = useState("");
  const [needs, setNeeds] = useState<Set<Need>>(new Set());
  const [sort, setSort] = useState<SortKey>("best");
  const [view, setView] = useState<"cards" | "table">("cards");
  const [visible, setVisible] = useState(PAGE);

  useEffect(() => setVisible(PAGE), [text, needs, sort]);

  // Only offer filters that at least one result can satisfy
  const availableNeeds = useMemo(() => NEEDS.filter((n) => cards.some(n.test)), [cards]);

  const shown = useMemo(() => {
    const q = text.trim().toLowerCase();
    const tests = NEEDS.filter((n) => needs.has(n.key));
    const list = cards.filter((c) => {
      if (!tests.every((t) => t.test(c))) return false;
      if (!q) return true;
      return (
        c.name.toLowerCase().includes(q) ||
        (c.category || "").toLowerCase().includes(q) ||
        cardAddress(c).toLowerCase().includes(q) ||
        c.named_people.some((p) => (p.name || "").toLowerCase().includes(q))
      );
    });
    if (sort === "name") list.sort((a, b) => a.name.localeCompare(b.name));
    if (sort === "rating") list.sort((a, b) => (b.rating ?? b.cms_star_rating ?? -1) - (a.rating ?? a.cms_star_rating ?? -1));
    if (sort === "reviews") list.sort((a, b) => (b.review_count ?? 0) - (a.review_count ?? 0));
    return list;
  }, [cards, text, needs, sort]);

  const toggleNeed = (k: Need) =>
    setNeeds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  const download = async (format: "csv" | "jsonl") => {
    if (!searchId) return;
    try {
      await api.download(`/v1/discovery/search/${encodeURIComponent(searchId)}/export?format=${format}`,
                         `results_${searchId.slice(0, 8)}.${format}`);
    } catch (e: any) {
      toast.error(e.message || "Download failed");
    }
  };

  const page = shown.slice(0, visible);

  return (
    <div className="space-y-4" data-testid="results">
      <div className="bg-card border rounded-lg p-3 space-y-3">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-2">
          <div className="text-sm">
            <span className="font-semibold" data-testid="result-count">
              {totalOrganizations.toLocaleString()} {totalOrganizations === 1 ? "result" : "results"}
            </span>
            {totalPeople > 0 && <span className="text-muted-foreground"> · {totalPeople.toLocaleString()} contact people</span>}
            <span className="text-muted-foreground"> · {(elapsedMs / 1000).toFixed(1)}s</span>
            {cards.length < totalOrganizations && (
              <span className="text-muted-foreground">
                {" "}· {preliminary ? `best ${cards.length} shown while searching` : `top ${cards.length} shown, raise "Results" to see more`}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="relative w-56">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-muted-foreground" />
              <Input placeholder="Filter by name, city or person" value={text} onChange={(e) => setText(e.target.value)}
                     className="h-8 pl-8 text-xs" data-testid="result-filter" />
            </div>
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort results"
                    className="h-8 rounded-md border bg-background px-2 text-xs">
              <option value="best">Best match</option>
              <option value="name">Name A-Z</option>
              <option value="rating">Highest rating</option>
              <option value="reviews">Most reviews</option>
            </select>
            <div className="flex rounded-md border overflow-hidden" role="group" aria-label="View">
              <button onClick={() => setView("cards")} title="Cards"
                      className={`h-8 px-2.5 text-xs flex items-center gap-1 ${view === "cards" ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}>
                <LayoutList className="w-3.5 h-3.5" />Cards
              </button>
              <button onClick={() => setView("table")} title="Table" data-testid="view-table"
                      className={`h-8 px-2.5 text-xs flex items-center gap-1 border-l ${view === "table" ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}>
                <Table2 className="w-3.5 h-3.5" />Table
              </button>
            </div>
            <Button variant="outline" size="sm" disabled={preliminary || !searchId} onClick={() => download("csv")}
                    className="h-8 text-xs" title={preliminary ? "Available when the search finishes" : "Download as a spreadsheet"}>
              <Download className="w-3.5 h-3.5" /> Download CSV
            </Button>
          </div>
        </div>

        {availableNeeds.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap text-xs">
            <span className="text-muted-foreground mr-1">Only show:</span>
            {availableNeeds.map((n) => (
              <button key={n.key} onClick={() => toggleNeed(n.key)}
                      className={`px-2.5 py-1 rounded-full border ${needs.has(n.key)
                        ? "bg-primary/10 border-primary text-primary font-medium" : "text-muted-foreground hover:bg-muted"}`}>
                {n.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {!preliminary && props.summaryMarkdown && (
        <details className="border rounded-lg bg-card">
          <summary className="cursor-pointer select-none px-4 py-2.5 text-sm font-medium">Summary and source links</summary>
          <div className="px-4 pb-4">
            <AnswerSummary summaryMarkdown={props.summaryMarkdown} citations={props.citations || []} />
          </div>
        </details>
      )}

      {view === "cards" ? (
        <div className="grid grid-cols-1 gap-3" data-testid="result-cards">
          {page.map((card) => <ResultCard key={card.org_id} card={card} linkable={!preliminary} />)}
        </div>
      ) : (
        <div className="border rounded-lg overflow-x-auto bg-card" data-testid="result-table">
          <table className="w-full text-xs">
            <thead className="bg-muted/50 text-left">
              <tr>
                {["Name", "Type", "Phone", "Website", "Address", "Rating", "Found on"].map((h) => (
                  <th key={h} className="px-3 py-2 font-semibold whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {page.map((c) => (
                <tr key={c.org_id} className="border-t align-top">
                  <td className="px-3 py-2 font-medium min-w-[180px]">
                    {preliminary ? c.name : <Link href={`/search/org/${c.org_id}`} className="hover:underline">{c.name}</Link>}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{c.category}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {cardPhones(c).slice(0, 2).map((p) => <a key={p} href={`tel:${p}`} className="block hover:underline">{p}</a>)}
                  </td>
                  <td className="px-3 py-2 max-w-[180px] truncate">
                    {c.website && (
                      <a href={c.website} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                        {c.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}
                      </a>
                    )}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground min-w-[200px]">{cardAddress(c)}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {c.rating != null && <div>Google {c.rating} ({c.review_count || 0})</div>}
                    {c.cms_star_rating != null && <div>Medicare {c.cms_star_rating}/5</div>}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{c.sources.map(sourceLabel).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {shown.length === 0 && (
        <div className="text-center py-10 text-sm text-muted-foreground bg-muted/10 rounded-lg border border-dashed">
          {cards.length ? "No results match these filters." : preliminary ? "Waiting for the first results..." : "Nothing was found. Try a broader search or a nearby city."}
        </div>
      )}

      {shown.length > visible && (
        <div className="flex justify-center gap-2">
          <Button variant="outline" onClick={() => setVisible((v) => v + PAGE)} data-testid="show-more">
            Show {Math.min(PAGE, shown.length - visible)} more
          </Button>
          <Button variant="ghost" onClick={() => setVisible(shown.length)}>Show all {shown.length}</Button>
        </div>
      )}
    </div>
  );
}
