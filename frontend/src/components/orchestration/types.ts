/**
 * DataExtraction — Temporal Orchestration Command Center Types
 * Strictly aligned with approved 8-stage pipeline & database schemas.
 */

export interface SystemHealthPill {
  name: string;
  label: string;
  status: "ONLINE" | "DURABLE" | "SYNCED" | "ACTIVE" | "DEGRADED" | "OFFLINE";
  subtext: string;
  color: "emerald" | "blue" | "amber" | "rose";
}

export interface HeaderStatusResponse {
  status: string;
  timestamp: string;
  platform: {
    status: string;
    uptime_seconds?: number;
    latency_ms: number;
  };
  temporal: {
    status: string;
    endpoint: string;
    active_workflows: number;
    pending_workflows: number;
  };
  database: {
    status: string;
    master_records: number;
    ping_ms: number;
  };
  opensearch: {
    status: string;
    synced_documents: number;
  };
  onereach: {
    status: string;
    webhook_status: string;
  };
  telemetry: {
    active_workflows: number;
    pending_workflows: number;
    last_successful_run: {
      workflow_id: string;
      completed_at: string;
      duration_seconds: number;
    } | null;
  };
}

export interface QueueTelemetry {
  id: string;
  name: string;
  agent: string;
  workers: number;
  pending: number;
  running: number;
  completed: number;
  failed: number;
  retrying: number;
  avg_wait_ms: number;
  status: "NOMINAL" | "ACTIVE" | "PRESSURE" | "OVERLOADED" | "IDLE";
}

export interface QueuesStatusResponse {
  status: string;
  timestamp: string;
  total_queues: number;
  queues: QueueTelemetry[];
}

export interface AgentTelemetry {
  id: string;
  agent_num: number;
  name: string;
  role: string;
  status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED" | "PAUSED";
  started_at: string | null;
  elapsed_seconds: number;
  progress_pct: number;
  processed_count: number;
  failed_count: number;
  retries_count: number;
  queue_name: string;
  current_activity: string;
  current_batch: string;
}

export interface StageTelemetry {
  id: string;
  name: string;
  agent_num: number;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "SKIPPED";
  started_at?: string;
  finished_at?: string;
  duration_seconds: number;
  records_in: number;
  records_out: number;
  error?: string;
}

export interface LiveKPIMetrics {
  orgs_scraped: number;
  employees_discovered: number;
  domains_verified: number;
  identity_clusters: number;
  emails_found: number;
  emails_verified: number;
  execs_found: number;
  employment_edges: number;
  governance_approved: number;
  promoted_records: number;
  master_records: number;
  opensearch_docs: number;
  onereach_deliveries: number;
}

export interface WorkingLayerTelemetry {
  working_orgs_count: number;
  working_emails_count: number;
  working_persons_count: number;
  clusters_distribution: {
    single_source: number;
    multi_source: number;
    conflict_resolved: number;
  };
  email_tiers: {
    tier1_deliverable: number;
    tier2_catch_all: number;
    tier3_disposable: number;
    tier4_invalid: number;
    tier5_spam_trap: number;
  };
  executive_depth: {
    c_level: number;
    vp: number;
    director: number;
    manager: number;
  };
}

export interface PromotionGateTelemetry {
  total_candidates: number;
  quality_passed: number;
  trust_passed: number;
  sanctions_cleared: number;
  promoted_to_master: number;
  quarantined_count: number;
  conversion_rate_pct: number;
  rejection_breakdown: {
    low_quality: number;
    low_trust: number;
    sanction_match: number;
    schema_violation: number;
  };
}

export interface FreshnessSLASlot {
  sla_window: string;
  target_hours: number;
  total_records: number;
  compliant_records: number;
  stale_records: number;
  compliance_pct: number;
}

export interface FreshnessSLATelemetry {
  website_30d: FreshnessSLASlot;
  email_90d: FreshnessSLASlot;
  executive_90d: FreshnessSLASlot;
  domain_gov_48d: FreshnessSLASlot;
  overall_sla_score: number;
  revalidation_scheduler_active: boolean;
  next_scheduled_run: string;
}

export interface OneReachDeliveryItem {
  id: string;
  org_name: string;
  golden_id: string;
  status: "DELIVERED" | "PENDING" | "FAILED";
  timestamp: string;
  latency_ms: number;
  payload_summary: string;
}

export interface OneReachDeliveryTelemetry {
  total_dispatched: number;
  delivered_success: number;
  failed_retry: number;
  avg_latency_ms: number;
  success_rate_pct: number;
  endpoint: string;
  recent_deliveries: OneReachDeliveryItem[];
}

export interface TerminalLogEntry {
  id: string;
  timestamp: string;
  agent: string;
  message: string;
  type: "info" | "warn" | "error" | "done" | "debug";
}

export interface DLQRecord {
  id: string | number;
  source_agent: string;
  entity_type: "organization" | "person" | "email";
  record_identifier: string;
  error_reason: string;
  error_category: "SCHEMA_VALIDATION" | "SMTP_TIMEOUT" | "SANCTION_MATCH" | "COLLISION" | "NETWORK_FAIL";
  payload: Record<string, unknown>;
  quarantined_at: string;
  retry_count: number;
  status: "PENDING" | "REPLAYED" | "DISCARDED";
}

export interface WorkflowStatusResponse {
  workflow_id: string;
  run_id?: string;
  status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED" | "PAUSED" | "TERMINATED";
  current_stage: string;
  current_agent: string;
  elapsed_seconds: number;
  progress_pct: number;
  current_queue: string;
  records_processed: number;
  records_waiting: number;
  failures_count: number;
  retries_count: number;
  stages: Record<string, StageTelemetry>;
  kpis: LiveKPIMetrics;
  agents: Record<string, AgentTelemetry>;
}

export interface StartScrapingPayload {
  data_count: number;
  countries: string[];
  sources: {
    registry_sources: boolean;
    google_maps: boolean;
    openstreetmap: boolean;
  };
  execution_mode: "INCREMENTAL" | "FULL_REFRESH";
}
