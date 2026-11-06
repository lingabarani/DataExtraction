import { test, expect } from '@playwright/test';

test.describe('OneExtraction Agent Supervision & Observability E2E', () => {

  test.beforeEach(async ({ page }) => {
    // Inject mock auth token to bypass login screen during isolated tests
    await page.addInitScript(() => {
      window.localStorage.setItem('oneextraction_token', 'mock-jwt-test-token');
      window.localStorage.setItem(
        'oneextraction_user',
        JSON.stringify({
          id: 'usr-sre-lead',
          name: 'Staff SRE Engineer',
          email: 'sre@oneextraction.com',
          role: 'ADMIN',
        })
      );
    });
  });

  test('Agent Supervision Page & Layout Verification', async ({ page }) => {
    await page.goto('/agents');

    // 1. Verify Page Title & Heading
    await expect(page).toHaveTitle(/Agents/i);
    const heading = page.locator('h1').filter({ hasText: /Autonomous Agent Supervision/i });
    await expect(heading).toBeVisible();

    // 2. Verify Online Agents Badge (7 Agents)
    const agentBadge = page.locator('span, div').filter({ hasText: /7 Agents Online|7 Agents Configured/i });
    await expect(agentBadge.first()).toBeVisible();
  });

  test('7-Phase Interactive Execution DAG Topology', async ({ page }) => {
    await page.goto('/agents');

    // Verify all 7 phase nodes exist in the visual DAG
    const expectedPhases = [
      'Registry Ingestion',
      'Geospatial Discovery',
      'Identity & Clusters',
      'Email & SMTP Probe',
      'Executive Graph',
      'Bayesian Governance',
      'Search & CDC Sync',
    ];

    for (const phase of expectedPhases) {
      const nodeElement = page.locator('div[role="button"]').filter({ hasText: phase });
      await expect(nodeElement.first()).toBeVisible();
    }

    // Click Node 01 (Registry Ingestion) to open slide-over sheet inspector
    const node1 = page.locator('div[role="button"]').filter({ hasText: /Registry Ingestion/i }).first();
    await node1.click();

    // Verify Slide-Over Drawer opened
    const drawerTitle = page.locator('[role="dialog"]').filter({ hasText: /Registry Ingestion/i });
    await expect(drawerTitle).toBeVisible();
    await expect(drawerTitle).toContainText(/SEC EDGAR|CMS NPI|businesses/i);

    // Close the drawer
    const closeBtn = page.locator('[role="dialog"] button').filter({ hasText: /Close/i });
    await closeBtn.click();
    await expect(drawerTitle).not.toBeVisible();
  });

  test('Mission Control Command Bar & Trigger Modal', async ({ page }) => {
    await page.goto('/agents');

    // Verify Trigger Saga Run button exists
    const triggerBtn = page.locator('button').filter({ hasText: /Trigger Saga Run/i });
    await expect(triggerBtn).toBeVisible();
    await triggerBtn.click();

    // Verify Modal Dialog opens
    const dialog = page.locator('[role="dialog"]').filter({ hasText: /Mission Control: Trigger Execution/i });
    await expect(dialog).toBeVisible();

    // Verify all 3 Tabs exist in the modal
    const masterTab = dialog.locator('button[role="tab"]').filter({ hasText: /Master Saga/i });
    const scraperTab = dialog.locator('button[role="tab"]').filter({ hasText: /Single Scraper/i });
    const emailTab = dialog.locator('button[role="tab"]').filter({ hasText: /Email Batch/i });

    await expect(masterTab).toBeVisible();
    await expect(scraperTab).toBeVisible();
    await expect(emailTab).toBeVisible();

    // Switch to Single Scraper Tab
    await scraperTab.click();
    await expect(dialog).toContainText(/Target Sovereign Source/i);

    // Switch to Email Batch Tab
    await emailTab.click();
    await expect(dialog).toContainText(/Target Records Cap/i);

    // Close Modal
    const cancelBtn = dialog.locator('button').filter({ hasText: /Cancel/i });
    await cancelBtn.click();
    await expect(dialog).not.toBeVisible();
  });

  test('Data Journey & Storage Layers Navigation', async ({ page }) => {
    await page.goto('/agents');

    // Click on "Data Journey & Storage Layers" tab
    const journeyTab = page.locator('button[role="tab"]').filter({ hasText: /Data Journey/i });
    await journeyTab.click();

    // Verify Storage Layer pills exist (L01 through L06)
    await expect(page.locator('button').filter({ hasText: /Raw Landing/i }).first()).toBeVisible();
    await expect(page.locator('button').filter({ hasText: /PostgreSQL Staging/i }).first()).toBeVisible();
    await expect(page.locator('button').filter({ hasText: /Identity Resolution/i }).first()).toBeVisible();
    await expect(page.locator('button').filter({ hasText: /Downstream Search/i }).first()).toBeVisible();

    // Verify Schema Blueprint table is displayed
    const tableHeader = page.locator('th').filter({ hasText: /Column \/ Field/i });
    await expect(tableHeader).toBeVisible();
  });

  test('Dead-Letter Queue (DLQ) Quarantine Inspector', async ({ page }) => {
    await page.goto('/agents');

    // Click on "DLQ Quarantined Anomalies" tab
    const dlqTab = page.locator('button[role="tab"]').filter({ hasText: /DLQ Quarantined/i });
    await dlqTab.click();

    // Verify filter buttons exist (PENDING, REPLAYED, DISCARDED)
    await expect(page.locator('button').filter({ hasText: /PENDING/i }).first()).toBeVisible();
    await expect(page.locator('button').filter({ hasText: /REPLAYED/i }).first()).toBeVisible();
    await expect(page.locator('button').filter({ hasText: /DISCARDED/i }).first()).toBeVisible();
  });

});

