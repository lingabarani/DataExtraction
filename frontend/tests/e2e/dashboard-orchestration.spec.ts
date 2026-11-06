/**
 * DataExtraction — Enterprise E2E Test Suite
 * Automated Playwright Test Suite for Command Center & Dashboard Verification
 */

import { test, expect } from '@playwright/test';

test.describe('DataExtraction Enterprise Command Center E2E', () => {

  test.beforeEach(async ({ page }) => {
    // Navigate to root and bypass login using instant sign in
    await page.goto('http://localhost:3000/login');
    const signInBtn = page.getByRole('button', { name: /Sign in/i });
    if (await signInBtn.isVisible()) {
      await signInBtn.click();
      await page.waitForURL('**/dashboard');
    }
  });

  test('TC-E2E-01: Persistent Top Platform Taskbar across Modules', async ({ page }) => {
    // 1. Verify Taskbar on Dashboard
    await page.goto('http://localhost:3000/dashboard');
    const taskbar = page.locator('div:has(> a[href="/dashboard"])');
    await expect(taskbar).toBeVisible();

    const orchestrationTab = page.getByRole('link', { name: /Orchestration/i }).first();
    await expect(orchestrationTab).toBeVisible();

    // 2. Click Orchestration and verify taskbar remains docked
    await orchestrationTab.click();
    await page.waitForURL('**/orchestration');
    await expect(taskbar).toBeVisible();

    // 3. Verify active indicator is positioned under Orchestration
    const activeLink = page.getByRole('link', { name: /Orchestration/i, exact: true });
    await expect(activeLink).toHaveClass(/text-foreground/);
  });

  test('TC-E2E-02: Zero-Latency SWR Module Navigation', async ({ page }) => {
    await page.goto('http://localhost:3000/dashboard');
    
    // Time the click-to-render transition
    const start = Date.now();
    await page.getByRole('link', { name: /Orchestration/i, exact: true }).click();
    await expect(page.getByText('Temporal Orchestration Command Center')).toBeVisible();
    const durationMs = Date.now() - start;

    // Perceived transition must be snappy (< 200ms)
    expect(durationMs).toBeLessThan(200);
  });

  test('TC-E2E-03: Overview Dashboard Master Vault Data Hydration', async ({ page }) => {
    await page.goto('http://localhost:3000/dashboard');

    // Verify Master Golden Records Card
    await expect(page.getByText('Master Golden Records')).toBeVisible();
    await expect(page.getByText(/21[0-9],[0-9]{3}/)).toBeVisible();

    // Verify Mexico Leads
    await expect(page.getByText('Mexico Leads')).toBeVisible();
    await expect(page.getByText('50,208')).toBeVisible();

    // Verify Direct Phone Coverage (94%)
    await expect(page.getByText(/94% verified phone rate/i)).toBeVisible();

    // Verify Verified Deliverable Emails
    await expect(page.getByText('Verified Deliverable Emails')).toBeVisible();

    // Verify Source Distribution Chart exists with verified sources
    await expect(page.getByText('Records by Verified Data Source')).toBeVisible();
    await expect(page.getByText('OpenStreetMap')).toBeVisible();
  });

  test('TC-E2E-04: Start Scraping Modal Workflow Configuration', async ({ page }) => {
    await page.goto('http://localhost:3000/orchestration');

    const startBtn = page.getByRole('button', { name: 'Start Scraping' });
    await expect(startBtn).toBeVisible();
    await startBtn.click();

    // Verify modal dialog opened
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(page.getByText('Start Master Orchestration Workflow')).toBeVisible();

    // Verify Data Count presets
    for (const preset of ['100', '500', '1k', '5k', '10k', '50k', '100k']) {
      await expect(dialog.getByRole('button', { name: preset, exact: true })).toBeVisible();
    }

    // Verify Geographic Scope buttons
    await expect(dialog.getByRole('button', { name: /United States/i })).toBeVisible();
    await expect(dialog.getByRole('button', { name: /Mexico/i })).toBeVisible();
    await expect(dialog.getByRole('button', { name: /Canada/i })).toBeVisible();

    // Verify Ingestion Sources checkboxes
    await expect(dialog.getByLabel('Registry Sources')).toBeChecked();
    await expect(dialog.getByLabel('Google Maps')).toBeChecked();
    await expect(dialog.getByLabel('OpenStreetMap')).toBeChecked();

    // Cancel modal
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).not.toBeVisible();
  });

  test('TC-E2E-05: Bidirectional Hash Deep-Linking (OneReach & Freshness)', async ({ page }) => {
    await page.goto('http://localhost:3000/dashboard');

    // 1. Click OneReach in Platform Taskbar
    await page.locator('a[href="/orchestration#onereach"]').click();
    await page.waitForURL('**/orchestration#onereach');

    // Verify OneReach tab selected
    await expect(page.getByRole('tab', { name: 'OneReach Outbound' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText('OneReach Outbound Delivery Command Center')).toBeVisible();

    // 2. Click Freshness in Platform Taskbar
    await page.locator('a[href="/orchestration#freshness"]').click();
    await page.waitForURL('**/orchestration#freshness');

    // Verify Queues & Freshness SLA tab selected
    await expect(page.getByRole('tab', { name: 'Queues & Freshness SLA' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText('Temporal Distributed Task Queue Monitor')).toBeVisible();
  });

  test('TC-E2E-06: Dark Mode Contrast and Clipping Audit', async ({ page }) => {
    await page.goto('http://localhost:3000/dashboard');

    // Toggle theme to dark
    const themeBtn = page.getByRole('button', { name: /Toggle theme/i }).first();
    await themeBtn.click();

    // Confirm no black box overlay elements exist
    const rogueOverlays = page.locator('div.fixed.inset-0.bg-background\\/80');
    await expect(rogueOverlays).toHaveCount(0);
  });
});

