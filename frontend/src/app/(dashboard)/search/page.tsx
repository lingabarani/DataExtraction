"use client";

import React, { useEffect, useRef, useState } from "react";
import { Globe, Loader2, MapPin, Search, ShieldAlert, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  api,
  DiscoveryAnswer,
  DiscoverySearchOptions,
  DiscoverySnapshot,
  DiscoverySourceStatus,
} from "@/lib/api";
import { SourceStatusPanel } from "@/components/discovery/SourceStatusPanel";
import { SearchResults } from "@/components/discovery/SearchResults";

const EXAMPLES = [
  "home care in Chennai",
  "hospitals in RS Puram, Coimbatore",
  "elderly care, home care in Charlotte metro area",
  "plumbers in Austin, TX",
  "restaurants in Paris, France",
];

const RESULT_SIZES = [25, 50, 100, 250, 500, 1000];

type Where = "internet" | "all";
type Detail = "fast" | "full";

function Choice<T extends string>({ value, options, onChange, disabled, testId }: {
  value: T;
  options: { value: T; label: string; hint: string }[];
  onChange: (v: T) => void;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <div className="flex rounded-md border overflow-hidden" role="radiogroup" data-testid={testId}>
      {options.map((o, i) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} disabled={disabled}
                onClick={() => onChange(o.value)} title={o.hint}
                className={`px-3 h-8 text-xs whitespace-nowrap ${i ? "border-l" : ""} ${value === o.value
                  ? "bg-primary text-primary-foreground font-medium" : "bg-background hover:bg-muted"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function DiscoverySearchPage() {
  const [query, setQuery] = useState("");
  const [where, setWhere] = useState<Where>("all");
  const [detail, setDetail] = useState<Detail>("full");
  const [maxResults, setMaxResults] = useState(100);
  const [includeUnverified, setIncludeUnverified] = useState(false);

  const [isSearching, setIsSearching] = useState(false);
  const [statuses, setStatuses] = useState<DiscoverySourceStatus[]>([]);
  const [snapshot, setSnapshot] = useState<DiscoverySnapshot | null>(null);
  const [answer, setAnswer] = useState<DiscoveryAnswer | null>(null);
  const [geography, setGeography] = useState<Record<string, any> | null>(null);
  const [searchId, setSearchId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [startedAt, setStartedAt] = useState(0);
  const [now, setNow] = useState(0);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => () => esRef.current?.close(), []);
  useEffect(() => {
    if (!isSearching) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [isSearching]);

  const upsertStatus = (s: DiscoverySourceStatus) =>
    setStatuses((prev) => [...prev.filter((p) => p.source !== s.source), s]);

  const stop = () => {
    esRef.current?.close();
    setIsSearching(false);
    setNotice("Search stopped. The results found so far are shown below.");
  };

  const runSearch = async (target?: string) => {
    const q = (target ?? query).trim();
    if (!q || isSearching) return;
    esRef.current?.close();
    setIsSearching(true);
    setAnswer(null);
    setSnapshot(null);
    setError(null);
    setNotice(null);
    setStatuses([]);
    setGeography(null);
    setStartedAt(Date.now());
    setNow(Date.now());

    const options: DiscoverySearchOptions = {
      max_results: maxResults,
      sources: where,
      crawl_websites: detail === "full",
      include_unverified: where === "all" && includeUnverified,
    };

    try {
      const init = await api.discovery.initSearch(q, options, 60);
      setSearchId(init.search_id);
      const es = new EventSource(api.discovery.getStreamUrl(init.search_id));
      esRef.current = es;
      let finished = false;

      const on = (name: string, fn: (data: any) => void) =>
        es.addEventListener(name, (evt) => {
          try {
            fn(JSON.parse((evt as MessageEvent).data));
          } catch {
            /* malformed event: ignore */
          }
        });

      on("plan", (d) => setGeography(d.intent?.geography ?? null));
      on("needs_location", (d) => setNotice(d.message));
      on("source_started", (d) =>
        upsertStatus({ source: d.source, status: "running", count: 0, elapsed_ms: 0 } as DiscoverySourceStatus));
      on("source_done", (d) => upsertStatus(d as DiscoverySourceStatus));
      on("snapshot", (d) => setSnapshot(d as DiscoverySnapshot));
      on("answer", (d) => {
        setAnswer(d as DiscoveryAnswer);
        if (d.message) setNotice(d.message);
      });
      on("error", (d) => setError(`Search failed: ${d.error ?? "unknown error"}`));
      es.addEventListener("done", () => {
        finished = true;
        es.close();
        setIsSearching(false);
      });
      es.onerror = async () => {
        if (finished || esRef.current !== es) return;
        es.close();
        try {
          const res = await api.discovery.getSearchResult(init.search_id);
          if (res.answer) setAnswer(res.answer);
          else setError("The connection was interrupted before the search finished. Please search again.");
        } catch (err: any) {
          setError(err.message || "Could not load the results");
        } finally {
          setIsSearching(false);
        }
      };
    } catch (err: any) {
      setError(err.message || "The search could not be started. Is the backend running on port 8000?");
      setIsSearching(false);
    }
  };

  const running = statuses.filter((s) => s.status === "running").length;
  const done = statuses.length - running;
  const elapsed = answer ? answer.elapsed_ms / 1000 : ((isSearching ? now : now || startedAt) - startedAt) / 1000;
  const found = answer?.total_organizations ?? snapshot?.total_organizations ?? 0;
  const view = answer && !answer.needs_location
    ? { cards: answer.cards, total: answer.total_organizations, people: answer.total_people, ms: answer.elapsed_ms, preliminary: false }
    : snapshot
      ? { cards: snapshot.cards, total: snapshot.total_organizations, people: snapshot.total_people, ms: snapshot.elapsed_ms, preliminary: true }
      : null;
  const started = statuses.length > 0 || isSearching;

  return (
    <div className="container mx-auto max-w-6xl py-8 px-4 sm:px-6 space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <Globe className="w-6 h-6 text-primary" /> Find businesses and organizations
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Type <b>what</b> you need and <b>where</b>: any city, area, ZIP or PIN code in the world. Results come live from
          Google Maps, the web, company websites and, in the U.S., government registries. It is free and needs no account
          or API key.
        </p>
      </div>

      <div className="bg-card border rounded-lg p-4 shadow-sm space-y-3">
        <form onSubmit={(e) => { e.preventDefault(); runSearch(); }} className="flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="w-5 h-5 absolute left-3 top-3 text-muted-foreground" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} disabled={isSearching} autoFocus
                   placeholder="What and where, for example: hospitals in RS Puram, Coimbatore"
                   className="pl-10 h-11 text-base" data-testid="search-input" aria-label="What and where" />
          </div>
          {isSearching ? (
            <Button type="button" variant="outline" onClick={stop} className="h-11 px-6 gap-2" data-testid="stop-button">
              <Square className="w-4 h-4" /> Stop
            </Button>
          ) : (
            <Button type="submit" disabled={!query.trim()} className="h-11 px-8 gap-2 text-base" data-testid="search-button">
              <Search className="w-4 h-4" /> Search
            </Button>
          )}
        </form>

        <div className="flex items-center gap-1.5 flex-wrap text-xs">
          <span className="text-muted-foreground">Examples:</span>
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" disabled={isSearching} onClick={() => { setQuery(ex); runSearch(ex); }}
                    className="text-primary hover:underline bg-muted/50 px-2 py-0.5 rounded border">
              {ex}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 pt-2 border-t text-xs">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Search in</span>
            <Choice<Where> value={where} onChange={setWhere} disabled={isSearching} testId="where" options={[
              { value: "internet", label: "Internet only", hint: "Only live results from the internet, nothing from the saved database" },
              { value: "all", label: "Internet + saved", hint: "Live internet results plus organizations saved by earlier searches" },
            ]} />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Details</span>
            <Choice<Detail> value={detail} onChange={setDetail} disabled={isSearching} testId="detail" options={[
              { value: "fast", label: "Fast", hint: "Finishes in about 2-5 seconds: names, phones, addresses, ratings, websites" },
              { value: "full", label: "Full", hint: "Also reads company websites for emails and staff names (about 10-20 seconds; results still appear in about 1 second)" },
            ]} />
          </div>
          <label className="flex items-center gap-2">
            <span className="text-muted-foreground">Results</span>
            <select value={maxResults} onChange={(e) => setMaxResults(Number(e.target.value))} disabled={isSearching}
                    className="h-8 rounded-md border bg-background px-2" data-testid="max-results">
              {RESULT_SIZES.map((n) => <option key={n} value={n}>{n === 1000 ? "Up to 1000" : `Up to ${n}`}</option>)}
            </select>
          </label>
          {where === "all" && (
            <label className="flex items-center gap-1.5 cursor-pointer select-none text-muted-foreground"
                   title="Old imported leads that were never checked against a live source">
              <input type="checkbox" checked={includeUnverified} disabled={isSearching}
                     onChange={(e) => setIncludeUnverified(e.target.checked)} />
              Include unchecked imported leads
            </label>
          )}
        </div>
      </div>

      {started && (
        <div className="space-y-2" data-testid="progress">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <div className="flex items-center gap-2">
              {isSearching ? <Loader2 className="w-4 h-4 animate-spin text-primary" /> : null}
              <span>
                {isSearching
                  ? <>Searching... <b>{found.toLocaleString()}</b> found so far · {done} of {statuses.length || "?"} sources finished</>
                  : <>Finished · <b>{found.toLocaleString()}</b> found</>}
                <span className="text-muted-foreground"> · {Math.max(0, elapsed).toFixed(1)}s</span>
              </span>
            </div>
            {statuses.length > 0 && (
              <button className="text-xs text-primary hover:underline" onClick={() => setShowSources((v) => !v)}>
                {showSources ? "Hide sources" : "Where are these results from?"}
              </button>
            )}
          </div>
          {isSearching && <Progress value={statuses.length ? (done / statuses.length) * 100 : 5} className="h-1.5" />}
          {geography && !geography.needs_location && (
            <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <MapPin className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary" />
              <span>
                Area: <b className="text-foreground">{geography.name}</b>
                {geography.counties?.length > 1 ? ` (${geography.counties.length} counties)` : ""}
                {geography.ambiguous && geography.alternatives ? `. Also exists in ${geography.alternatives.join(", ")}; add a state to change it.` : ""}
              </span>
            </div>
          )}
          {showSources && <SourceStatusPanel statuses={statuses} />}
        </div>
      )}

      {notice && (
        <div className="bg-amber-500/10 border border-amber-500/30 text-amber-800 dark:text-amber-200 text-sm p-3 rounded-lg"
             data-testid="notice">{notice}</div>
      )}
      {error && (
        <div className="bg-destructive/10 border border-destructive/20 text-destructive text-sm p-3 rounded-lg flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {view && (
        <SearchResults
          cards={view.cards}
          totalOrganizations={view.total}
          totalPeople={view.people}
          elapsedMs={view.ms}
          preliminary={view.preliminary || (isSearching && !answer)}
          searchId={answer ? searchId : null}
          summaryMarkdown={answer?.summary_markdown}
          citations={answer?.citations}
        />
      )}

      {!started && !view && (
        <div className="text-sm text-muted-foreground border border-dashed rounded-lg p-6 space-y-1">
          <p className="font-medium text-foreground">How to use</p>
          <p>1. Type what you are looking for and where, for example &quot;home care in Chennai&quot; or &quot;dentists near Anna Nagar, Chennai&quot;.</p>
          <p>2. Press Search. The first results appear in about a second and keep filling in.</p>
          <p>3. Use "Only show" to keep results with a phone, website or email, and "Download CSV" to save them.</p>
          <p>Click a name to see every detail and where it came from.</p>
        </div>
      )}
    </div>
  );
}
