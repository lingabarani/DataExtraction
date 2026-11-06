# DataExtraction Enterprise — Certified Master Data Architecture

## High-Level Architecture Assets

The approved enterprise target architecture has been exported and saved in multiple high-level image and visual formats inside this directory (`docs/architecture/`):

| Asset Name | Format | Purpose & Best Use |
| :--- | :--- | :--- |
| [`enterprise_b2b_certified_architecture_uhd.png`](file:///d:/Data%20Scraping%20Project%20POC/DataExtraction/docs/architecture/enterprise_b2b_certified_architecture_uhd.png) | **High-Res PNG Image** | Direct inclusion in presentations, pitch decks, Confluence, and image viewers. |
| [`enterprise_b2b_certified_architecture.svg`](file:///d:/Data%20Scraping%20Project%20POC/DataExtraction/docs/architecture/enterprise_b2b_certified_architecture.svg) | **Scalable Vector Graphic (SVG)** | 1920×1480 UHD crisp vector diagram for high-DPI displays, Figma, and print. |
| [`enterprise_b2b_certified_architecture.html`](file:///d:/Data%20Scraping%20Project%20POC/DataExtraction/docs/architecture/enterprise_b2b_certified_architecture.html) | **Interactive HTML Viewer** | Interactive browser canvas with Zoom In/Out, Reset, and One-Click PNG/SVG export. |
| [`enterprise_b2b_certified_architecture_flowchart.png`](file:///d:/Data%20Scraping%20Project%20POC/DataExtraction/docs/architecture/enterprise_b2b_certified_architecture_flowchart.png) | **Flowchart PNG Image** | Preserved exact flowchart diagram reflecting the 7-tier operational progression. |

---

## Architectural Highlights

```
1. Ingestion Fleet (Agent 1 Registry & Agent 2 Spatial)
   ↓
2. Raw Observation Lakehouse & Staging (staging_dataextraction & MinIO Parquet)
   ↓
3. Pre-Master Working Enrichment Layer (STRICT ISOLATION: Master is NOT touched)
   • Agent 3 (Splink 5.0 Identity Linkage) → working_organizations
   • Agent 7 (Email Discovery & 5-Tier Verification) → working_emails
   • Agent 4 (Executive Discovery & Hierarchy Graph) → working_persons
   ↓
4. Governance Certification & Promotion Gate (Agent 5)
   • Quality Score >= 80 | Trust Score >= 0.85 | Sanctions/OFAC: CLEARED
   • Sub-80 scores isolated in Dead-Letter Queue (DLQ)
   ↓
5. Master Database (master_dataextraction) ★ CERTIFIED SINGLE SOURCE OF TRUTH ★
   • 100% Canonical, Validated, Scored Golden Records
   • Zero in-flight enrichment writes occur here
   ↓
6. Autonomous Freshness & SLA Revalidation Engine
   • 30d Website | 48d Domain/Maps/Gov Registry | 90d Email/Executive
   • Decay Model: F(t) = exp(-λ · Δt) with 48d half-life
   ↓
7. Post-Master Processing & Outbound (Agent 6)
   • OpenSearch 2.x CDC Stream (kg_search watermarks)
   • Knowledge Graph (kg_graph bitemporal employment edges)
   • OneReach Outbound Delivery (HMAC-SHA256 Signed Webhooks)
```

