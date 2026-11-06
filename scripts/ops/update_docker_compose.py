from pathlib import Path

compose_file = Path(r"D:\Data Scraping Project POC\DataExtraction\infra\docker-compose.yml")
content = compose_file.read_text(encoding="utf-8")

target = "  # ── Temporal Worker: Federal Ingestion (Legacy compatibility) ────────────────"
service = """  # ── Temporal Worker: Agent 7 - Post-Dedup Email Discovery & Verification ──────
  worker-email-enrichment:
    build:
      context: .
      dockerfile: infra/docker/Dockerfile.worker
    container_name: dex-worker-email-enrichment
    restart: unless-stopped
    depends_on:
      temporal:
        condition: service_healthy
      postgres:
        condition: service_healthy
    env_file:
      - .env
    environment:
      - TEMPORAL_HOST=temporal:7233
      - POSTGRES_HOST=postgres
      - WORKER_TYPE=email_enrichment
    command: ["python", "-m", "packages.temporal.workers.worker_email_enrichment"]
    volumes:
      - ./packages:/app/packages
    networks:
      - dataextraction

"""

if target in content:
    content = content.replace(target, service + target)
    compose_file.write_text(content, encoding="utf-8")
    print("SUCCESS")
else:
    print("NOT FOUND")

