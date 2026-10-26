"use client";
import { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Sparkles, Search, Clock, ArrowRight, Loader2,
  CheckCircle2, Database, X, Lightbulb,
} from "lucide-react";
import { useAISearch } from "@/hooks/use-ai-search";
import { LeadsTable } from "@/components/leads/leads-table";

// ── Suggested queries ─────────────────────────────────────────────────────────

const SUGGESTIONS = [
  { label: "CEOs in Texas with verified email",          query: "CEOs in Texas with verified email" },
  { label: "CFOs in healthcare industry",                query: "CFOs in healthcare industry" },
  { label: "VP level in technology California",          query: "VP level in technology California" },
  { label: "Founders in manufacturing sector",           query: "Founders in manufacturing sector" },
  { label: "Directors in New York banking",              query: "Directors in New York banking" },
  { label: "Mexico C-Suite with verified email",         query: "Mexico C-Suite executives verified email" },
  { label: "Federal contractors in defense",             query: "federal contractors" },
  { label: "Nonprofit executives with phone",            query: "nonprofit executives" },
];

// ── SQL display ───────────────────────────────────────────────────────────────

function SQLExplainer({ where, explanation, confidence }: {
  where:       string;
  explanation: string;
  confidence:  number;
}) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
        <span className="text-xs font-medium text-green-700 dark:text-green-400">{explanation}</span>
        <Badge variant="outline" className="ml-auto text-[10px] bg-green-500/10 text-green-600 border-green-200">
          {confidence}% confidence
        </Badge>
      </div>
      {where && (
        <pre className="text-[11px] font-mono text-muted-foreground bg-background rounded p-2 overflow-x-auto">
          WHERE {where}
        </pre>
      )}
    </div>
  );
}

// ── History chip ──────────────────────────────────────────────────────────────

function HistoryChip({ query, onClick }: { query: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs
                 bg-muted hover:bg-muted/80 text-muted-foreground border border-border
                 transition-colors max-w-[200px] truncate"
    >
      <Clock className="w-3 h-3 flex-shrink-0" />
      <span className="truncate">{query}</span>
    </button>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function AnalyticsDashboard() {
  const [inputValue, setInputValue] = useState("");
  const { result, loading, error, history, search, clear } = useAISearch();
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSearch = () => {
    if (inputValue.trim()) search(inputValue.trim());
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  };

  const handleSuggestion = (query: string) => {
    setInputValue(query);
    search(query);
  };

  const handleClear = () => {
    setInputValue("");
    clear();
    inputRef.current?.focus();
  };

  return (
    <div className="space-y-5">
      {/* ── Page header ──────────────────────────────────────────────── */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">AI Data Query</h1>
        <p className="text-muted-foreground text-sm mt-0.5">
          Ask any question about your leads in plain English — the AI converts it to SQL and retrieves results instantly.
        </p>
      </div>

      {/* ── Main search card ─────────────────────────────────────────── */}
      <Card className="border-primary/30 bg-gradient-to-br from-primary/5 via-background to-accent/5">
        <CardContent className="pt-5 pb-4 space-y-4">
          {/* Search input */}
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Sparkles className="absolute left-3 top-3 h-4 w-4 text-primary" />
              {loading && (
                <Loader2 className="absolute right-3 top-3 h-4 w-4 text-primary animate-spin" />
              )}
              <Input
                ref={inputRef}
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onKeyDown={handleKey}
                placeholder='e.g. "Show me all CFOs in California tech companies with verified email"'
                className="pl-9 pr-9 h-11 text-sm border-primary/30 focus:border-primary bg-background"
                disabled={loading}
              />
            </div>
            <Button
              onClick={handleSearch}
              disabled={loading || !inputValue.trim()}
              className="h-11 px-5"
              variant="gradient"
            >
              <Search className="w-4 h-4 mr-2" />
              Search
            </Button>
            {result && (
              <Button variant="outline" size="icon" className="h-11 w-11" onClick={handleClear}>
                <X className="w-4 h-4" />
              </Button>
            )}
          </div>

          {/* History */}
          {history.length > 0 && !result && (
            <div className="flex flex-wrap gap-2 items-center">
              <span className="text-xs text-muted-foreground">Recent:</span>
              {history.slice(0, 5).map(q => (
                <HistoryChip key={q} query={q} onClick={() => handleSuggestion(q)} />
              ))}
            </div>
          )}

          {/* SQL explainer */}
          <AnimatePresence>
            {result?.parsed && (
              <motion.div
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                <SQLExplainer
                  where={result.parsed.sql_where}
                  explanation={result.parsed.explanation}
                  confidence={result.parsed.confidence}
                />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Error */}
          {error && (
            <p className="text-xs text-destructive flex items-center gap-2">
              <X className="w-3.5 h-3.5" /> {error}
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Suggestions (shown only when no result) ──────────────────── */}
      <AnimatePresence>
        {!result && !loading && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          >
            <div className="flex items-center gap-2 mb-3">
              <Lightbulb className="w-4 h-4 text-amber-500" />
              <span className="text-sm font-medium">Suggested queries</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
              {SUGGESTIONS.map(s => (
                <button
                  key={s.query}
                  onClick={() => handleSuggestion(s.query)}
                  className="text-left p-3 rounded-lg border bg-card hover:border-primary/40
                             hover:bg-primary/5 transition-all group"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium leading-relaxed">{s.label}</span>
                    <ArrowRight className="w-3.5 h-3.5 text-muted-foreground/40
                                          group-hover:text-primary group-hover:translate-x-0.5
                                          transition-all flex-shrink-0 ml-2" />
                  </div>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Results ──────────────────────────────────────────────────── */}
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="space-y-3"
          >
            {/* Result header */}
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <Database className="w-4 h-4 text-primary" />
                <span className="text-sm font-semibold">
                  {result.total.toLocaleString()} results
                </span>
                <Badge variant="outline" className="text-xs">
                  {result.parsed?.filters?.table ?? "us_leads"}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  in {result.duration_ms}ms
                </span>
              </div>
              {/* Re-run suggestions */}
              {result.parsed?.suggestions?.length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Refine:</span>
                  {result.parsed.suggestions.slice(0, 2).map(s => (
                    <button
                      key={s}
                      onClick={() => handleSuggestion(s)}
                      className="text-xs text-primary hover:underline"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <Separator />

            {/* Table */}
            <Card className="overflow-hidden">
              <CardContent className="p-0">
                <LeadsTable
                  leads={result.leads}
                  loading={false}
                  table={result.parsed?.filters?.table ?? "us_leads"}
                />
              </CardContent>
            </Card>

            {result.total > result.leads.length && (
              <p className="text-xs text-center text-muted-foreground">
                Showing first {result.leads.length.toLocaleString()} of {result.total.toLocaleString()} results.
                Use the{" "}
                <a href="/leads" className="text-primary underline">Leads page</a>
                {" "}for full paginated results.
              </p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
