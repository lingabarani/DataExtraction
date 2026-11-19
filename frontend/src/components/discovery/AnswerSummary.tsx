"use client";

import React, { useState } from "react";
import { Sparkles, FileText, ChevronDown, ChevronUp, Link as LinkIcon } from "lucide-react";
import { DiscoveryCitation } from "@/lib/api";
import { Button } from "@/components/ui/button";

interface AnswerSummaryProps {
  summaryMarkdown: string;
  citations: DiscoveryCitation[];
}

export function AnswerSummary({ summaryMarkdown, citations }: AnswerSummaryProps) {
  const [showCitations, setShowCitations] = useState(false);

  if (!summaryMarkdown) return null;

  return (
    <div className="bg-card border rounded-lg p-5 mb-6 shadow-sm">
      <div className="flex items-center justify-between mb-3 border-b pb-3">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-md bg-primary/10 text-primary">
            <Sparkles className="w-4 h-4" />
          </div>
          <h3 className="font-semibold text-sm tracking-tight text-foreground">
            Multi-Source Synthesis & Grounded Citations
          </h3>
        </div>

        {citations.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowCitations(!showCitations)}
            className="text-xs h-7 gap-1"
          >
            <FileText className="w-3.5 h-3.5" />
            {citations.length} Citations
            {showCitations ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </Button>
        )}
      </div>

      <div className="prose prose-sm dark:prose-invert max-w-none text-xs leading-relaxed whitespace-pre-wrap">
        {summaryMarkdown}
      </div>

      {showCitations && citations.length > 0 && (
        <div className="mt-4 pt-3 border-t text-xs">
          <h4 className="font-semibold text-[11px] uppercase tracking-wider text-muted-foreground mb-2">
            Verification Footnotes & Evidence
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {citations.map((c) => (
              <div key={c.id} className="bg-muted/40 rounded p-2 text-[11px] flex items-start gap-1.5">
                <span className="font-mono font-bold text-primary shrink-0">[{c.id}]</span>
                <div className="flex flex-col">
                  <span className="font-medium text-foreground">{c.entity_name}</span>
                  <span className="text-muted-foreground">{c.fact_description}</span>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="font-mono text-[10px] text-primary/80 uppercase">{c.source}</span>
                    {c.url && (
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[10px] text-muted-foreground hover:underline flex items-center gap-0.5"
                      >
                        <LinkIcon className="w-2.5 h-2.5" />
                        source link
                      </a>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
