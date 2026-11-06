"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { TerminalLogEntry } from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Terminal,
  Search,
  Download,
  Copy,
  Trash2,
  ArrowDown,
  Filter,
  Check,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface LiveMonospaceTerminalProps {
  logs: TerminalLogEntry[];
  onClearLogs?: () => void;
  workflowId?: string | null;
}

const DEFAULT_LOGS: TerminalLogEntry[] = [
  {
    id: "log_01",
    timestamp: "2026-11-05T07:13:00.120Z",
    agent: "SAGA MONITOR",
    message: "Initializing Master 8-Stage Saga Orchestrator (Temporal Durable Mode)",
    type: "info",
  },
  {
    id: "log_02",
    timestamp: "2026-11-05T07:13:01.440Z",
    agent: "Agent 1: Registry Harvester",
    message: "Ingesting 200,147 records from SEC EDGAR, CMS NPI, SAM.gov, FDIC into staging_dataextraction.staging_companies",
    type: "info",
  },
  {
    id: "log_03",
    timestamp: "2026-11-05T07:13:03.110Z",
    agent: "Agent 2: Spatial & Domain Harvester",
    message: "Geocoding 10,691 locations via OSM Quadtree and resolving corporate domains",
    type: "info",
  },
  {
    id: "log_04",
    timestamp: "2026-11-05T07:13:05.800Z",
    agent: "Agent 3: Identity Resolution",
    message: "Executing Splink 5.0 Fellegi-Sunter clustering on DuckDB — isolated into working_organizations (52,661 clusters)",
    type: "info",
  },
  {
    id: "log_05",
    timestamp: "2026-11-05T07:13:08.200Z",
    agent: "Agent 7: Email Discovery & 5-Tier",
    message: "5-Tier email enrichment complete: verified 57,160 RFC 5322 deliverable emails into working_emails",
    type: "info",
  },
  {
    id: "log_06",
    timestamp: "2026-11-05T07:13:10.950Z",
    agent: "Agent 4: Executive Discovery",
    message: "Extracted 64,759 decision makers and resolved 79,601 career hierarchy edges into working_persons",
    type: "info",
  },
  {
    id: "log_07",
    timestamp: "2026-11-05T07:13:13.400Z",
    agent: "Agent 5: Governance & Certification",
    message: "Bayesian quality scoring complete: Quality Avg 94.2, Trust 0.91, OFAC/PEP Sanctions 100% CLEAR",
    type: "info",
  },
  {
    id: "log_08",
    timestamp: "2026-11-05T07:13:14.050Z",
    agent: "PROMOTION GATE",
    message: "ATOMIC PROMOTION: Committing 210,838 certified records from working layer to master_dataextraction Vault",
    type: "done",
  },
  {
    id: "log_09",
    timestamp: "2026-11-05T07:13:15.520Z",
    agent: "Agent 6: CDC, Search & OneReach",
    message: "OpenSearch 2.x CDC projection synced (210,838 docs). OneReach outbound webhook stream initialized and ready for dispatch.",
    type: "done",
  },
  {
    id: "log_10",
    timestamp: "2026-11-05T07:13:16.100Z",
    agent: "SAGA MONITOR",
    message: "Master Orchestrator Saga COMPLETED successfully in 16.1s. Single source of truth Vault certified.",
    type: "done",
  },
];

export function LiveMonospaceTerminal({
  logs = DEFAULT_LOGS,
  onClearLogs,
  workflowId,
}: LiveMonospaceTerminalProps) {
  const [selectedAgent, setSelectedAgent] = useState<string>("ALL");
  const [selectedType, setSelectedType] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);

  const terminalEndRef = useRef<HTMLDivElement | null>(null);

  const displayLogs = logs.length > 0 ? logs : DEFAULT_LOGS;

  // Filter logs
  const filteredLogs = useMemo(() => {
    return displayLogs.filter((log) => {
      if (selectedAgent !== "ALL" && !log.agent.toLowerCase().includes(selectedAgent.toLowerCase())) {
        return false;
      }
      if (selectedType !== "ALL" && log.type.toLowerCase() !== selectedType.toLowerCase()) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        return (
          log.message.toLowerCase().includes(q) ||
          log.agent.toLowerCase().includes(q) ||
          log.timestamp.includes(q)
        );
      }
      return true;
    });
  }, [displayLogs, selectedAgent, selectedType, searchQuery]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [filteredLogs, autoScroll]);

  // Copy logs
  const handleCopyLogs = () => {
    const raw = filteredLogs
      .map((l) => `[${l.timestamp}] [${l.agent}] [${l.type.toUpperCase()}] ${l.message}`)
      .join("\n");
    navigator.clipboard.writeText(raw);
    setCopied(true);
    toast.success("Terminal logs copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  // Download logs
  const handleDownloadLogs = () => {
    const raw = filteredLogs
      .map((l) => `[${l.timestamp}] [${l.agent}] [${l.type.toUpperCase()}] ${l.message}`)
      .join("\n");
    const blob = new Blob([raw], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `temporal-orchestration-${workflowId ?? "live"}.log`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Log file download initiated");
  };

  return (
    <div className="flex flex-col rounded-xl border border-border/80 bg-zinc-950 shadow-md font-mono overflow-hidden">
      {/* Terminal Title Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 bg-zinc-900/80 px-4 py-2.5 text-xs">
        <div className="flex items-center gap-2">
          {/* Traffic light terminal dots */}
          <div className="flex items-center gap-1.5 mr-2">
            <span className="h-3 w-3 rounded-full bg-rose-500/80" />
            <span className="h-3 w-3 rounded-full bg-amber-500/80" />
            <span className="h-3 w-3 rounded-full bg-emerald-500/80" />
          </div>
          <Terminal className="h-4 w-4 text-emerald-400" />
          <span className="font-semibold text-zinc-200">
            Live Monospace Execution Terminal
          </span>
          <span className="text-zinc-500 text-[11px]">
            {workflowId ? `[${workflowId}]` : "[stream: active]"}
          </span>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setAutoScroll(!autoScroll)}
            className={cn(
              "h-7 px-2 text-[11px] gap-1 text-zinc-300 hover:text-white hover:bg-zinc-800",
              autoScroll && "text-emerald-400 font-semibold"
            )}
          >
            <ArrowDown className="h-3 w-3" />
            {autoScroll ? "Auto-scroll ON" : "Auto-scroll OFF"}
          </Button>

          <Button
            size="sm"
            variant="ghost"
            onClick={handleCopyLogs}
            className="h-7 px-2 text-[11px] gap-1 text-zinc-300 hover:text-white hover:bg-zinc-800"
          >
            {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
            Copy
          </Button>

          <Button
            size="sm"
            variant="ghost"
            onClick={handleDownloadLogs}
            className="h-7 px-2 text-[11px] gap-1 text-zinc-300 hover:text-white hover:bg-zinc-800"
          >
            <Download className="h-3 w-3" />
            Download
          </Button>

          {onClearLogs && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onClearLogs}
              className="h-7 px-2 text-[11px] gap-1 text-rose-400 hover:bg-rose-950/40"
            >
              <Trash2 className="h-3 w-3" />
              Clear
            </Button>
          )}
        </div>
      </div>

      {/* Terminal Filter Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800/80 bg-zinc-900/40 px-4 py-2 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          {/* Agent Filter */}
          <select
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-800/90 px-2 py-1 text-zinc-200 text-xs focus:ring-1 focus:ring-primary focus:outline-hidden"
          >
            <option value="ALL">All Agents & Gates</option>
            <option value="Agent 1">Agent 1: Registry</option>
            <option value="Agent 2">Agent 2: Spatial</option>
            <option value="Agent 3">Agent 3: Identity</option>
            <option value="Agent 7">Agent 7: Email</option>
            <option value="Agent 4">Agent 4: Executive</option>
            <option value="Agent 5">Agent 5: Governance</option>
            <option value="PROMOTION GATE">Promotion Gate</option>
            <option value="Agent 6">Agent 6: Search & Outbound</option>
            <option value="SAGA MONITOR">Saga Monitor</option>
          </select>

          {/* Type Filter */}
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-800/90 px-2 py-1 text-zinc-200 text-xs focus:ring-1 focus:ring-primary focus:outline-hidden"
          >
            <option value="ALL">All Levels</option>
            <option value="info">INFO</option>
            <option value="done">DONE</option>
            <option value="warn">WARN</option>
            <option value="error">ERROR</option>
          </select>
        </div>

        {/* Search */}
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-zinc-500" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search terminal output..."
            className="h-7.5 pl-8 bg-zinc-900 border-zinc-700 text-xs text-zinc-200 placeholder:text-zinc-500 focus-visible:ring-1 focus-visible:ring-emerald-500"
          />
        </div>
      </div>

      {/* Terminal Output Area */}
      <div className="h-96 overflow-y-auto p-4 space-y-1.5 scrollbar-enterprise text-xs leading-relaxed select-text">
        {filteredLogs.length === 0 ? (
          <div className="text-zinc-600 italic py-8 text-center">
            No log lines match current search/filter criteria.
          </div>
        ) : (
          filteredLogs.map((log) => {
            const isError = log.type === "error";
            const isWarn = log.type === "warn";
            const isDone = log.type === "done";

            return (
              <div key={log.id} className="flex items-start gap-2 group hover:bg-zinc-900/60 py-0.5 px-1 rounded">
                {/* Timestamp */}
                <span className="text-zinc-500 text-[11px] select-none flex-shrink-0">
                  {new Date(log.timestamp).toLocaleTimeString()}
                </span>

                {/* Agent Tag */}
                <span
                  className={cn(
                    "font-bold text-[11px] flex-shrink-0",
                    log.agent.includes("Agent 1") && "text-blue-400",
                    log.agent.includes("Agent 2") && "text-sky-400",
                    log.agent.includes("Agent 3") && "text-cyan-400",
                    log.agent.includes("Agent 7") && "text-emerald-400",
                    log.agent.includes("Agent 4") && "text-purple-400",
                    log.agent.includes("Agent 5") && "text-violet-400",
                    log.agent.includes("PROMOTION GATE") && "text-amber-400",
                    log.agent.includes("Agent 6") && "text-emerald-300",
                    log.agent.includes("SAGA MONITOR") && "text-zinc-400"
                  )}
                >
                  [{log.agent}]
                </span>

                {/* Log Type Badge */}
                <span
                  className={cn(
                    "text-[10px] font-semibold uppercase px-1 rounded select-none flex-shrink-0",
                    isDone && "bg-emerald-500/20 text-emerald-400",
                    isError && "bg-rose-500/20 text-rose-400 font-bold",
                    isWarn && "bg-amber-500/20 text-amber-400",
                    !isDone && !isError && !isWarn && "text-zinc-400"
                  )}
                >
                  {log.type}
                </span>

                {/* Message */}
                <span
                  className={cn(
                    "text-zinc-300 flex-1 break-words",
                    isDone && "text-emerald-300 font-medium",
                    isError && "text-rose-400 font-bold",
                    isWarn && "text-amber-300"
                  )}
                >
                  {log.message}
                </span>
              </div>
            );
          })
        )}
        <div ref={terminalEndRef} />
      </div>
    </div>
  );
}

