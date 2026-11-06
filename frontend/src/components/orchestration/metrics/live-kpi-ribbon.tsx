"use client";

import { LiveKPIMetrics } from "../types";
import {
  Building2,
  Users,
  Globe2,
  GitMerge,
  Mail,
  CheckCheck,
  UserCheck,
  Share2,
  ShieldCheck,
  Award,
  Database,
  Search,
  Send,
} from "lucide-react";

interface LiveKPIRibbonProps {
  metrics: LiveKPIMetrics;
}

interface KPICardConfig {
  id: keyof LiveKPIMetrics;
  label: string;
  source: string;
  icon: React.ElementType;
  colorScheme: "harvester" | "working" | "governance" | "master";
}

const KPI_CONFIGS: KPICardConfig[] = [
  {
    id: "orgs_scraped",
    label: "Orgs Scraped",
    source: "staging.companies",
    icon: Building2,
    colorScheme: "harvester",
  },
  {
    id: "employees_discovered",
    label: "Employees Found",
    source: "staging.persons",
    icon: Users,
    colorScheme: "harvester",
  },
  {
    id: "domains_verified",
    label: "Domains Verified",
    source: "Agent 2 Spatial",
    icon: Globe2,
    colorScheme: "harvester",
  },
  {
    id: "identity_clusters",
    label: "Identity Clusters",
    source: "working_orgs",
    icon: GitMerge,
    colorScheme: "working",
  },
  {
    id: "emails_found",
    label: "Emails Found",
    source: "RFC 5322 Raw",
    icon: Mail,
    colorScheme: "working",
  },
  {
    id: "emails_verified",
    label: "Emails Verified",
    source: "working_emails",
    icon: CheckCheck,
    colorScheme: "working",
  },
  {
    id: "execs_found",
    label: "Execs Found",
    source: "working_persons",
    icon: UserCheck,
    colorScheme: "working",
  },
  {
    id: "employment_edges",
    label: "Employment Edges",
    source: "kg_graph.edges",
    icon: Share2,
    colorScheme: "working",
  },
  {
    id: "governance_approved",
    label: "Gov Approved",
    source: "Agent 5 Bayesian",
    icon: ShieldCheck,
    colorScheme: "governance",
  },
  {
    id: "promoted_records",
    label: "Promoted Records",
    source: "Promotion Gate",
    icon: Award,
    colorScheme: "governance",
  },
  {
    id: "master_records",
    label: "Master Golden",
    source: "master_orgs (Vault)",
    icon: Database,
    colorScheme: "master",
  },
  {
    id: "opensearch_docs",
    label: "OpenSearch Docs",
    source: "Agent 6 CDC Sync",
    icon: Search,
    colorScheme: "master",
  },
  {
    id: "onereach_deliveries",
    label: "OneReach Delivered",
    source: "Outbound Webhooks",
    icon: Send,
    colorScheme: "master",
  },
];

export function LiveKPIRibbon({ metrics }: LiveKPIRibbonProps) {
  const getBadgeStyle = (scheme: KPICardConfig["colorScheme"]) => {
    switch (scheme) {
      case "harvester":
        return "text-blue-500 bg-blue-500/10 border-blue-500/20";
      case "working":
        return "text-cyan-500 bg-cyan-500/10 border-cyan-500/20";
      case "governance":
        return "text-purple-500 bg-purple-500/10 border-purple-500/20";
      case "master":
        return "text-emerald-500 bg-emerald-500/10 border-emerald-500/20";
    }
  };

  return (
    <div className="border-b border-border/60 bg-card/20 p-4 sm:px-6">
      <div className="mb-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/80">
            Pipeline Live Progression Ribbon
          </span>
          <span className="text-[11px] text-muted-foreground/50 font-mono">(13 Monitored Vault Nodes)</span>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground font-mono">
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-500" /> Harvester
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-cyan-500" /> Working Layer
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-purple-500" /> Governance
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Master Vault
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-7 lg:grid-cols-13 gap-2">
        {KPI_CONFIGS.map((item) => {
          const Icon = item.icon;
          const value = metrics[item.id] ?? 0;
          return (
            <div
              key={item.id}
              className="flex flex-col justify-between rounded-lg border border-border/70 bg-background/80 p-2.5 shadow-xs transition-all hover:border-border hover:shadow-sm"
            >
              <div className="flex items-center justify-between gap-1">
                <span className="text-[10px] font-semibold tracking-tight text-muted-foreground truncate" title={item.label}>
                  {item.label}
                </span>
                <div className={`p-1 rounded ${getBadgeStyle(item.colorScheme)} flex-shrink-0`}>
                  <Icon className="h-3 w-3" />
                </div>
              </div>

              <div className="mt-1.5">
                <span className="text-base font-bold font-mono tracking-tight text-foreground tabular-nums">
                  {value.toLocaleString()}
                </span>
                <p className="text-[9px] font-mono text-muted-foreground/50 truncate" title={item.source}>
                  {item.source}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

