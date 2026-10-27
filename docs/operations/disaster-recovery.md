# Disaster Recovery & Continuity Plan

## Recovery Objectives
- **Recovery Point Objective (RPO):** < 24 hours (nightly automated dumps + WAL replication in production)
- **Recovery Time Objective (RTO):** < 30 minutes (container redeployment + database restore)

---

## Recovery Procedures

### 1. Database Data Loss / Corruption
1. Stop all Temporal workers and API services to prevent split-brain writes:
   ```powershell
   .\manage.ps1 down
   ```
2. Verify available cataloged backups with valid SHA-256 hashes:
   ```powershell
   .\manage.ps1 restore:list
   ```
3. Execute dry-run restoration to validate SQL dump syntax and constraints:
   ```powershell
   .\manage.ps1 restore:verify
   ```
4. Restore the database:
   ```powershell
   .\manage.ps1 restore
   ```
5. Restart services and workers:
   ```powershell
   .\manage.ps1 up
   ```

### 2. Temporal State Desynchronization
Temporal Server maintains execution history in PostgreSQL/Cassandra.
If Temporal Server crashes:
1. Restart Temporal containers (`infra/docker-compose.yml`).
2. Workers automatically reconnect, re-register task queues, and resume pending workflows from their last recorded activity completion marker.
3. In-flight activities with timeouts will retry automatically per workflow retry policies.

