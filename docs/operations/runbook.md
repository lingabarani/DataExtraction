# DataExtraction Operations Runbook

## Routine Maintenance Operations

### 1. Database Backups
Automated database backups run daily via pg_dump with SHA-256 integrity hashing and 7-day FIFO rotation.
- **Trigger Manual Backup:**
  ```powershell
  .\manage.ps1 backup
  ```
- **Simulate Backup (Dry Run):**
  ```powershell
  .\manage.ps1 backup:verify
  ```
- **List Cataloged Backups:**
  ```powershell
  .\manage.ps1 restore:list
  ```

### 2. Database Restoration
- **Dry-run verification:**
  ```powershell
  .\manage.ps1 restore:verify
  ```
- **Restore from latest verified archive:**
  ```powershell
  .\manage.ps1 restore
  ```

---

## Incident Response & Triage

### Scenario A: High Dead-Letter Queue (DLQ) Backlog
- **Symptom:** Prometheus alert `dataextraction_dlq_pending_total > 100` or Human Approval card on UI.
- **Triage:**
  1. Inspect failed records in DLQ table:
     ```sql
     SELECT source, error_message, count(1) FROM dlq_quarantine GROUP BY source, error_message;
     ```
  2. If errors were due to temporary API outage, approve replay in UI or trigger `DLQReplayWorkflow`.

### Scenario B: Database Connection Pool Starvation
- **Symptom:** `db_pool_utilization > 0.85` or `ResourceManagerAgent` sends throttle signal.
- **Triage:**
  1. Inspect active PostgreSQL queries:
     ```sql
     SELECT pid, now() - query_start AS duration, query FROM pg_stat_activity WHERE state != 'idle';
     ```
  2. The `ResourceManagerAgent` automatically throttles background Google Maps workers from concurrency 5 to 2. If utilization reaches 95%, active extractions are paused.

### Scenario C: Temporal Worker Failure
- **Symptom:** Temporal UI indicates task queue backlog with 0 active pollers.
- **Remediation:**
  Restart corresponding worker service:
  ```powershell
  .\manage.ps1 worker:federal
  ```

