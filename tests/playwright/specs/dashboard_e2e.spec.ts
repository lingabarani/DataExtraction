import { test, expect } from '@playwright/test';

test.describe('DataExtraction Enterprise Dashboard E2E', () => {

  test.beforeEach(async ({ page }) => {
    // Inject mock auth token to bypass login screen during isolated dashboard tests
    await page.addInitScript(() => {
      window.localStorage.setItem('oneextraction_token', 'mock-jwt-test-token');
      window.localStorage.setItem(
        'oneextraction_user',
        JSON.stringify({
          id: 'usr-test-01',
          name: 'Staff Test Engineer',
          email: 'admin@oneextraction.com',
          role: 'ADMIN',
        })
      );
    });
  });

  test('Root Layout & Branding Integrity', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page).toHaveTitle(/OneExtraction/);
    // Verify brand indicator exists
    const brandHeading = page.locator('header, nav, aside').filter({ hasText: /OneExtraction/i });
    await expect(brandHeading.first()).toBeVisible();
  });

  test('Pipeline & DLQ Control Panel', async ({ page }) => {
    await page.goto('/pipeline');
    await expect(page.locator('h1, h2, h3').filter({ hasText: /Pipeline/i }).first()).toBeVisible();

    // Verify key tabs or cards exist: Health, DLQ, Metrics
    const panelContent = page.locator('main');
    await expect(panelContent).toContainText(/Dead-Letter Queue|DLQ|Pipeline/i);
  });

  test('Map Extraction Panel Rendering', async ({ page }) => {
    await page.goto('/map-extraction');
    await expect(page.locator('h1, h2, h3').filter({ hasText: /Map|OpenStreetMap|Extraction/i }).first()).toBeVisible({ timeout: 10000 });
  });

  test('Export Manager Component', async ({ page }) => {
    await page.goto('/export');
    const exportButton = page.locator('button').filter({ hasText: /Export|Download/i });
    await expect(exportButton.first()).toBeVisible();
  });

});

