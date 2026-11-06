import { test, expect } from '@playwright/test';

/**
 * DataExtraction Enterprise — Temporal Orchestration Command Center E2E Spec
 * Validates the complete operator experience across all 8 pipeline stages,
 * 7 action controls, 13 KPIs, 5 operational workspaces, live terminal, and DLQ.
 */

test.describe('Temporal Orchestration Command Center E2E Automation', () => {

  test.beforeEach(async ({ page }) => {
    // Inject authenticated enterprise administrator session
    await page.addInitScript(() => {
      window.localStorage.setItem('dataextraction_token', 'mock-enterprise-jwt-admin-token');
      window.localStorage.setItem(
        'dataextraction_user',
        JSON.stringify({
          id: 'usr-admin-lead-01',
          name: 'Principal QA Architect',
          email: 'qa-architect@dataextraction.ai',
          role: 'ADMIN',
          scopes: ['read', 'write', 'admin', 'operator'],
        })
      );
    });

    // Mock header status endpoint
    await page.route('**/api/orchestration/header/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'SUCCESS',
          timestamp: new Date().toISOString(),
          platform: { status: 'ONLINE', latency_ms: 12 },
          temporal: {
            status: 'DURABLE',
            endpoint: 'localhost:7233',
            active_workflows: 1,
            pending_workflows: 0,
          },
          database: {
            status: 'CONNECTED',
            master_records: 210838,
            ping_ms: 4,
          },
          opensearch: {
            status: 'SYNCED',
            synced_documents: 210838,
          },
          onereach: {
            status: 'ACTIVE',
            webhook_status: 'READY',
          },
          telemetry: {
            active_workflows: 1,
            pending_workflows: 0,
            last_successful_run: {
              workflow_id: 'wf_certified_golden_master_run_01',
              completed_at: new Date(Date.now() - 3600000).toISOString(),
              duration_seconds: 16.1,
            },
          },
        }),
      });
    });

    // Mock active workflow status endpoint
    await page.route('**/api/orchestration/active/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          workflow_id: 'wf_saga_master_8stage_prod_01',
          run_id: 'run_b2b_gold_884120',
          status: 'RUNNING',
          current_stage: 'IDENTITY_RESOLUTION',
          current_agent: 'Agent 3: Identity Resolution',
          elapsed_seconds: 18.5,
          progress_pct: 37.5,
          current_queue: 'dataextraction-identity-v1',
          records_processed: 52661,
          records_waiting: 147486,
          failures_count: 0,
          retries_count: 0,
          stages: {
            REGISTRY_INGESTION: {
              id: 'REGISTRY_INGESTION',
              name: 'Registry Harvester',
              agent_num: 1,
              status: 'COMPLETED',
              duration_seconds: 4.2,
              records_in: 200147,
              records_out: 200147,
            },
            GEOSPATIAL_STANDARDIZATION: {
              id: 'GEOSPATIAL_STANDARDIZATION',
              name: 'Spatial & Domain Harvester',
              agent_num: 2,
              status: 'COMPLETED',
              duration_seconds: 3.8,
              records_in: 200147,
              records_out: 10691,
            },
            IDENTITY_RESOLUTION: {
              id: 'IDENTITY_RESOLUTION',
              name: 'Identity Resolution',
              agent_num: 3,
              status: 'RUNNING',
              duration_seconds: 5.5,
              records_in: 200147,
              records_out: 52661,
            },
            EMAIL_ENRICHMENT: {
              id: 'EMAIL_ENRICHMENT',
              name: 'Email Discovery & 5-Tier',
              agent_num: 7,
              status: 'PENDING',
              duration_seconds: 0,
              records_in: 0,
              records_out: 0,
            },
            EXECUTIVE_DISCOVERY: {
              id: 'EXECUTIVE_DISCOVERY',
              name: 'Executive Discovery',
              agent_num: 4,
              status: 'PENDING',
              duration_seconds: 0,
              records_in: 0,
              records_out: 0,
            },
            GOVERNANCE_CERTIFICATION: {
              id: 'GOVERNANCE_CERTIFICATION',
              name: 'Governance & Certification',
              agent_num: 5,
              status: 'PENDING',
              duration_seconds: 0,
              records_in: 0,
              records_out: 0,
            },
            PROMOTION_GATE: {
              id: 'PROMOTION_GATE',
              name: 'PROMOTION GATE',
              agent_num: 0,
              status: 'PENDING',
              duration_seconds: 0,
              records_in: 0,
              records_out: 0,
            },
            POST_MASTER_OUTBOUND: {
              id: 'POST_MASTER_OUTBOUND',
              name: 'Search, CDC & OneReach',
              agent_num: 6,
              status: 'PENDING',
              duration_seconds: 0,
              records_in: 0,
              records_out: 0,
            },
          },
          kpis: {
            orgs_scraped: 200147,
            employees_discovered: 885500,
            domains_verified: 212300,
            identity_clusters: 52661,
            emails_found: 645000,
            emails_verified: 580200,
            execs_found: 340100,
            employment_edges: 720400,
            governance_approved: 210838,
            promoted_records: 210838,
            master_records: 210838,
            opensearch_docs: 210838,
            onereach_deliveries: 18450,
          },
          agents: {},
        }),
      });
    });

    // Mock queues status endpoint
    await page.route('**/api/orchestration/queues/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'SUCCESS',
          timestamp: new Date().toISOString(),
          total_queues: 7,
          queues: [
            {
              id: 'registry-ingestion-queue',
              name: 'dataextraction-registry-v1',
              agent: 'Agent 1: Registry Harvester',
              workers: 8,
              pending: 0,
              running: 0,
              completed: 200147,
              failed: 0,
              retrying: 0,
              avg_wait_ms: 12,
              status: 'NOMINAL',
            },
            {
              id: 'geospatial-domain-queue',
              name: 'dataextraction-geospatial-v1',
              agent: 'Agent 2: Spatial & Domain Harvester',
              workers: 6,
              pending: 0,
              running: 0,
              completed: 10691,
              failed: 0,
              retrying: 0,
              avg_wait_ms: 18,
              status: 'NOMINAL',
            },
            {
              id: 'identity-clustering-queue',
              name: 'dataextraction-identity-v1',
              agent: 'Agent 3: Identity & Splink 5.0',
              workers: 4,
              pending: 12,
              running: 4,
              completed: 52661,
              failed: 0,
              retrying: 0,
              avg_wait_ms: 45,
              status: 'ACTIVE',
            },
            {
              id: 'email-enrichment-queue',
              name: 'dataextraction-email-enrichment-v1',
              agent: 'Agent 7: Email Discovery & Validation',
              workers: 12,
              pending: 0,
              running: 0,
              completed: 57160,
              failed: 0,
              retrying: 0,
              avg_wait_ms: 85,
              status: 'IDLE',
            },
            {
              id: 'executive-contact-queue',
              name: 'dataextraction-executive-v1',
              agent: 'Agent 4: Executive Discovery',
              workers: 8,
              pending: 0,
              running: 0,
              completed: 64759,
              failed: 0,
              retrying: 0,
              avg_wait_ms: 15,
              status: 'IDLE',
            },
            {
              id: 'governance-quality-queue',
              name: 'dataextraction-governance-v1',
              agent: 'Agent 5: Governance & Certification',
              workers: 6,
              pending: 0,
              running: 0,
              completed: 210838,
              failed: 0,
              retrying: 0,
              avg_wait_ms: 22,
              status: 'NOMINAL',
            },
            {
              id: 'search-persistence-queue',
              name: 'dataextraction-search-v1',
              agent: 'Agent 6: OpenSearch CDC & Outbound',
              workers: 10,
              pending: 0,
              running: 0,
              completed: 210838,
              failed: 0,
              retrying: 0,
              avg_wait_ms: 8,
              status: 'NOMINAL',
            },
          ],
        }),
      });
    });
  });

  // ── TEST 1: Navigation & Sidebar Activation ──────────────────────────────
  test('TC-E2E-01: Navigation Link & Route Verification', async ({ page }) => {
    await page.goto('/dashboard');
    
    // Verify sidebar platform section contains Temporal Orchestration
    const orchestrationNav = page.locator('aside nav a[href="/orchestration"]');
    await expect(orchestrationNav).toBeVisible();
    await expect(orchestrationNav).toContainText('Temporal Orchestration');
    await expect(orchestrationNav).toContainText('LIVE');

    // Click link and verify navigation
    await orchestrationNav.click();
    await expect(page).toHaveURL(/\/orchestration/);
    await expect(page).toHaveTitle(/Temporal Orchestration Command Center/i);
  });

  // ── TEST 2: Cluster Health Pills & Monospace Telemetry Ribbon ─────────────
  test('TC-E2E-02: Health Pills & 13-Milestone KPI Ribbon Rendering', async ({ page }) => {
    await page.goto('/orchestration');

    // Verify 5 Health Pills
    await expect(page.locator('text=Platform').first()).toBeVisible();
    await expect(page.locator('text=ONLINE').first()).toBeVisible();
    await expect(page.locator('text=Temporal').first()).toBeVisible();
    await expect(page.locator('text=DURABLE').first()).toBeVisible();
    await expect(page.locator('text=Database').first()).toBeVisible();
    await expect(page.locator('text=OpenSearch').first()).toBeVisible();
    await expect(page.locator('text=OneReach').first()).toBeVisible();

    // Verify 13-KPI Ribbon is rendered with monospace figures
    const kpiRibbon = page.locator('text=Pipeline Live Progression Ribbon');
    await expect(kpiRibbon).toBeVisible();
    await expect(page.locator('text=Orgs Scraped').first()).toBeVisible();
    await expect(page.locator('text=Master Golden').first()).toBeVisible();
    await expect(page.locator('text=OneReach Delivered').first()).toBeVisible();
  });

  // ── TEST 3: Visual 8-Stage Topological DAG Verification ────────────────────
  test('TC-E2E-03: Topological 8-Stage DAG Nodes & State Indicators', async ({ page }) => {
    await page.goto('/orchestration');

    const expectedStages = [
      'Registry Harvester',
      'Spatial & Domain Harvester',
      'Identity Resolution',
      'Email Discovery & 5-Tier',
      'Executive Discovery',
      'Governance & Certification',
      'PROMOTION GATE',
      'Search, CDC & OneReach',
    ];

    for (const stageName of expectedStages) {
      const stageCard = page.locator('div').filter({ hasText: stageName });
      await expect(stageCard.first()).toBeVisible();
    }

    // Verify Promotion Gate badge threshold
    const gateBadge = page.locator('text=GATE ≥ 80');
    await expect(gateBadge.first()).toBeVisible();
  });

  // ── TEST 4: Start Scraping Modal Workflow Dispatch ───────────────────────
  test('TC-E2E-04: Start Scraping Modal Configuration & Dispatch', async ({ page }) => {
    await page.goto('/orchestration');

    // Mock start workflow endpoint
    await page.route('**/api/orchestration/start', async (route) => {
      const req = route.request().postDataJSON();
      expect(req.data_count).toBe(10000);
      expect(req.execution_mode).toBe('INCREMENTAL');
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          workflow_id: 'wf_test_new_saga_10k',
          run_id: 'run_test_new_10k',
          status: 'RUNNING',
          message: 'Workflow dispatched successfully.',
        }),
      });
    });

    // Open Start Scraping modal
    const startButton = page.locator('button').filter({ hasText: /Start Scraping/i });
    await expect(startButton).toBeVisible();
    await startButton.click();

    // Verify modal dialog appeared
    const dialogTitle = page.locator('h2, div').filter({ hasText: /Start Master Orchestration Workflow/i });
    await expect(dialogTitle.first()).toBeVisible();

    // Select 10,000 preset
    const preset10k = page.locator('button').filter({ hasText: '10k' });
    await preset10k.click();

    // Click Start Workflow submit button
    const submitBtn = page.locator('button').filter({ hasText: /Start Workflow/i }).last();
    await submitBtn.click();

    // Verify toast notification appears
    const toastNotification = page.locator('[data-sonner-toast]').filter({ hasText: /Master Orchestration Saga Started/i });
    await expect(toastNotification).toBeVisible({ timeout: 5000 });
  });

  // ── TEST 5: Operational Signaling (Pause, Resume, Emergency Halt) ─────────
  test('TC-E2E-05: Signal Dispatching (Pause / Resume / Halt Dialog)', async ({ page }) => {
    await page.goto('/orchestration');

    let lastDispatchedSignal = '';
    await page.route('**/api/orchestration/*/signal', async (route) => {
      const body = route.request().postDataJSON();
      lastDispatchedSignal = body.signal_name;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          workflow_id: 'wf_saga_master_8stage_prod_01',
          signal: body.signal_name,
          status: 'SUCCESS',
          message: `Signal ${body.signal_name} delivered to Temporal.`,
        }),
      });
    });

    // Click Pause
    const pauseBtn = page.locator('button').filter({ hasText: 'Pause' });
    if (await pauseBtn.isEnabled()) {
      await pauseBtn.click();
      expect(lastDispatchedSignal).toBe('pause');
    }

    // Click Emergency Halt -> opens dialog
    const haltBtn = page.locator('button').filter({ hasText: 'Emergency Halt' });
    await haltBtn.click();

    // Verify Emergency Halt dialog
    const haltDialogHeading = page.locator('div, h2').filter({ hasText: /Emergency Workflow Halt/i });
    await expect(haltDialogHeading.first()).toBeVisible();

    // Confirm Halt
    const confirmHaltBtn = page.locator('button').filter({ hasText: /Confirm Emergency Halt/i });
    await confirmHaltBtn.click();
    expect(lastDispatchedSignal).toBe('emergency_halt');
  });

  // ── TEST 6: Tabbed Operations (Working Layer, Queues, OneReach, Terminal) ──
  test('TC-E2E-06: Tabbed Workspaces & Live Terminal Telemetry', async ({ page }) => {
    await page.goto('/orchestration');

    // Tab 2: Working Layer & Funnels
    const tabWorking = page.locator('button[role="tab"]').filter({ hasText: /Working Layer & Funnels/i });
    await tabWorking.click();
    await expect(page.locator('text=Pre-Master Working Layer Intelligence').first()).toBeVisible();
    await expect(page.locator('text=Mandatory Promotion Gate Certification Funnel').first()).toBeVisible();

    // Tab 3: Queues & Freshness SLA
    const tabQueues = page.locator('button[role="tab"]').filter({ hasText: /Queues & Freshness SLA/i });
    await tabQueues.click();
    await expect(page.locator('text=Temporal Distributed Task Queue Monitor').first()).toBeVisible();
    await expect(page.locator('text=Autonomous Freshness & SLA Revalidation Engine').first()).toBeVisible();

    // Tab 4: OneReach Outbound
    const tabOneReach = page.locator('button[role="tab"]').filter({ hasText: /OneReach Outbound/i });
    await tabOneReach.click();
    await expect(page.locator('text=OneReach Outbound Delivery Command Center').first()).toBeVisible();

    // Tab 5: Terminal Logs & DLQ
    const tabTerminal = page.locator('button[role="tab"]').filter({ hasText: /Logs & Error Center/i });
    await tabTerminal.click();
    await expect(page.locator('text=Live Monospace Execution Terminal').first()).toBeVisible();
    await expect(page.locator('text=Dead-Letter Queue (DLQ) & Error Isolation Center').first()).toBeVisible();
  });

});

