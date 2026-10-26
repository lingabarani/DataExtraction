# Telemetry & Monitoring Architecture

## Metrics Taxonomy
DataExtraction exposes Prometheus metrics on port `9090` (`/metrics`):

### 1. Workflow & Orchestration Metrics
- `dataextraction_workflow_active_total{workflow_type}`: Currently running workflows.
- `dataextraction_workflow_completions_total{workflow_type, status}`: Completed workflow counts.
- `dataextraction_workflow_duration_seconds{workflow_type}`: Execution latency.

### 2. Activity & Scraper Execution
- `dataextraction_activity_executions_total{activity_name, status}`: Total attempts.
- `dataextraction_activity_duration_seconds{activity_name}`: Runtime distribution.
- `dataextraction_activity_retries_total{activity_name}`: Retry attempts count.

### 3. Database & Pipeline Quality
- `oneextraction_db_pool_active_connections`: Checked-out PostgreSQL connections.
- `oneextraction_db_pool_capacity`: Pool upper boundary.
- `oneextraction_dlq_pending_records`: Unprocessed quarantined records.

### 4. Agent Operations
- `dataextraction_agent_cycles_total{agent}`: Execution loops completed.
- `dataextraction_agent_decisions_total{agent, action}`: Count by action type (`noop`, `start_workflow`, `signal_workflow`, `alert`).
- `dataextraction_agent_approvals_pending_total`: Decisions waiting for human sign-off.
