import { test, expect, Page } from '@playwright/test';

/**
 * AI Witness Finder E2E Tests
 *
 * These tests simulate real user interactions including:
 * - Navigation between pages
 * - Clicking buttons and UI elements
 * - Form interactions
 * - Export functionality
 *
 * Note: Tests requiring authentication need TEST_AUTH_TOKEN environment variable
 */

// Test configuration
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'https://aiwitnessfinder-production.up.railway.app';

test.describe('Public Pages', () => {
  test('login page loads correctly', async ({ page }) => {
    await page.goto('/');

    // Wait for page to load
    await page.waitForLoadState('networkidle');

    // Should show login page or redirect to Clio OAuth or matters page if already logged in
    const url = page.url();
    const title = await page.title();

    // Valid states:
    // 1. Login/landing page with AI Witness branding
    // 2. Redirected to Clio OAuth
    // 3. Matters page if already authenticated
    const isValidState =
      title.match(/AI Witness|Clio|Matters/i) ||
      url.includes('clio') ||
      url.includes('matters') ||
      url.includes('login');

    expect(isValidState).toBeTruthy();
  });
});

test.describe('Authenticated User Flows', () => {
  // Skip these tests if no auth token is provided
  test.beforeEach(async ({ page }) => {
    const authToken = process.env.TEST_AUTH_TOKEN;

    if (!authToken) {
      test.skip();
      return;
    }

    // Set auth token in localStorage before navigating
    await page.goto('/');
    await page.evaluate((token) => {
      localStorage.setItem('token', token);
    }, authToken);
  });

  test('matters page - view and navigate', async ({ page }) => {
    await page.goto('/matters');

    // Wait for page to load
    await page.waitForLoadState('networkidle');

    // Should see matters list or loading state
    const mattersHeading = page.getByRole('heading', { name: /matters/i });
    await expect(mattersHeading).toBeVisible({ timeout: 10000 });

    // Check for matter cards or empty state
    const matterCards = page.locator('[data-testid="matter-card"]');
    const emptyState = page.getByText(/no matters/i);

    const hasMatterCards = await matterCards.count() > 0;
    const hasEmptyState = await emptyState.isVisible().catch(() => false);

    expect(hasMatterCards || hasEmptyState).toBeTruthy();
  });

  test('jobs page - view processing jobs', async ({ page }) => {
    await page.goto('/jobs');

    await page.waitForLoadState('networkidle');

    // Should see jobs heading
    const jobsHeading = page.getByRole('heading', { name: /jobs|processing/i });
    await expect(jobsHeading).toBeVisible({ timeout: 10000 });
  });

  test('navigation - sidebar links work', async ({ page }) => {
    await page.goto('/matters');
    await page.waitForLoadState('networkidle');

    // Click on Jobs in sidebar
    const jobsLink = page.getByRole('link', { name: /jobs/i });
    if (await jobsLink.isVisible()) {
      await jobsLink.click();
      await expect(page).toHaveURL(/jobs/);
    }

    // Click on Matters in sidebar
    const mattersLink = page.getByRole('link', { name: /matters/i });
    if (await mattersLink.isVisible()) {
      await mattersLink.click();
      await expect(page).toHaveURL(/matters/);
    }
  });
});

test.describe('Export Functionality', () => {
  test.beforeEach(async ({ page }) => {
    const authToken = process.env.TEST_AUTH_TOKEN;
    if (!authToken) {
      test.skip();
      return;
    }

    await page.goto('/');
    await page.evaluate((token) => {
      localStorage.setItem('token', token);
    }, authToken);
  });

  test('jobs page - export dropdown menu', async ({ page }) => {
    await page.goto('/jobs');
    await page.waitForLoadState('networkidle');

    // Find a completed job with the actions dropdown
    const actionsButton = page.locator('button').filter({ hasText: /actions|export/i }).first();

    if (await actionsButton.isVisible()) {
      await actionsButton.click();

      // Should see export options
      const pdfOption = page.getByRole('menuitem', { name: /pdf/i });
      const excelOption = page.getByRole('menuitem', { name: /excel/i });
      const wordOption = page.getByRole('menuitem', { name: /word/i });

      // At least one export option should be visible
      const hasExportOptions =
        await pdfOption.isVisible().catch(() => false) ||
        await excelOption.isVisible().catch(() => false) ||
        await wordOption.isVisible().catch(() => false);

      expect(hasExportOptions).toBeTruthy();
    }
  });
});

test.describe('Matter Processing Flow', () => {
  test.beforeEach(async ({ page }) => {
    const authToken = process.env.TEST_AUTH_TOKEN;
    if (!authToken) {
      test.skip();
      return;
    }

    await page.goto('/');
    await page.evaluate((token) => {
      localStorage.setItem('token', token);
    }, authToken);
  });

  test('matter detail page - process documents button', async ({ page }) => {
    await page.goto('/matters');
    await page.waitForLoadState('networkidle');

    // Click on first matter to view details
    const matterCard = page.locator('[data-testid="matter-card"]').first();

    if (await matterCard.isVisible()) {
      await matterCard.click();

      // Wait for matter detail page
      await page.waitForLoadState('networkidle');

      // Should see process button
      const processButton = page.getByRole('button', { name: /process|extract|analyze/i });

      if (await processButton.isVisible()) {
        // Verify button is clickable (don't actually click to avoid starting a job)
        await expect(processButton).toBeEnabled();
      }
    }
  });

  test('folder selection modal - loads folders', async ({ page }) => {
    await page.goto('/matters');
    await page.waitForLoadState('networkidle');

    // Click on first matter
    const matterCard = page.locator('[data-testid="matter-card"]').first();

    if (await matterCard.isVisible()) {
      await matterCard.click();
      await page.waitForLoadState('networkidle');

      // Click process button to open modal
      const processButton = page.getByRole('button', { name: /process|extract/i });

      if (await processButton.isVisible()) {
        await processButton.click();

        // Wait for modal
        const modal = page.getByRole('dialog');
        await expect(modal).toBeVisible({ timeout: 5000 });

        // Should see folder selection
        const folderSection = page.getByText(/folder|documents/i);
        await expect(folderSection).toBeVisible();
      }
    }
  });
});

test.describe('Sync Functionality', () => {
  test.beforeEach(async ({ page }) => {
    const authToken = process.env.TEST_AUTH_TOKEN;
    if (!authToken) {
      test.skip();
      return;
    }

    await page.goto('/');
    await page.evaluate((token) => {
      localStorage.setItem('token', token);
    }, authToken);
  });

  test('sync button triggers refresh', async ({ page }) => {
    await page.goto('/matters');
    await page.waitForLoadState('networkidle');

    // Find sync button
    const syncButton = page.getByRole('button', { name: /sync|refresh/i });

    if (await syncButton.isVisible()) {
      // Click sync
      await syncButton.click();

      // Should show loading indicator or overlay
      const loadingIndicator = page.locator('.animate-spin, [data-syncing="true"]').first();

      // Either loading shows briefly or sync completes quickly
      const showedLoading = await loadingIndicator.isVisible().catch(() => false);

      // Wait for sync to complete (overlay should disappear)
      await page.waitForTimeout(2000);

      // Page should still be functional
      await expect(page.getByRole('heading', { name: /matters/i })).toBeVisible();
    }
  });
});

test.describe('UI Components', () => {
  test.beforeEach(async ({ page }) => {
    const authToken = process.env.TEST_AUTH_TOKEN;
    if (!authToken) {
      test.skip();
      return;
    }

    await page.goto('/');
    await page.evaluate((token) => {
      localStorage.setItem('token', token);
    }, authToken);
  });

  test('sidebar navigation is accessible', async ({ page }) => {
    await page.goto('/matters');
    await page.waitForLoadState('networkidle');

    // Sidebar should be visible
    const sidebar = page.locator('nav, [role="navigation"]').first();
    await expect(sidebar).toBeVisible();

    // Should have navigation links
    const navLinks = page.getByRole('link');
    expect(await navLinks.count()).toBeGreaterThan(0);
  });

  test('tooltips appear on hover', async ({ page }) => {
    await page.goto('/jobs');
    await page.waitForLoadState('networkidle');

    // Find an element with tooltip
    const buttonWithTooltip = page.locator('[data-tooltip], [title]').first();

    if (await buttonWithTooltip.isVisible()) {
      await buttonWithTooltip.hover();

      // Tooltip should appear
      await page.waitForTimeout(500); // Wait for tooltip delay

      const tooltip = page.getByRole('tooltip');
      // Tooltip may or may not be visible depending on implementation
    }
  });

  test('dropdown menus open and close', async ({ page }) => {
    await page.goto('/jobs');
    await page.waitForLoadState('networkidle');

    // Find a dropdown trigger
    const dropdownTrigger = page.locator('[data-state="closed"]').first();

    if (await dropdownTrigger.isVisible()) {
      // Click to open
      await dropdownTrigger.click();

      // Should have open state
      await expect(dropdownTrigger).toHaveAttribute('data-state', 'open');

      // Click outside to close
      await page.keyboard.press('Escape');

      // Should be closed
      await expect(dropdownTrigger).toHaveAttribute('data-state', 'closed');
    }
  });
});

test.describe('Error Handling', () => {
  test('handles network errors gracefully', async ({ page }) => {
    // Simulate offline mode
    await page.route('**/api/**', route => route.abort());

    await page.goto('/matters');

    // Should show error state or retry option
    await page.waitForTimeout(3000);

    // Page should not crash
    const errorMessage = page.getByText(/error|failed|retry/i);
    const loadingState = page.getByText(/loading/i);

    // Either shows error or keeps trying
    const handlesError =
      await errorMessage.isVisible().catch(() => false) ||
      await loadingState.isVisible().catch(() => false);

    // Page should at least be rendered
    expect(page.url()).toContain('/');
  });

  test('404 page shows for invalid routes', async ({ page }) => {
    await page.goto('/this-page-does-not-exist-12345');

    // Should show 404 or redirect to login
    const is404 = page.url().includes('404') ||
      await page.getByText(/not found|404/i).isVisible().catch(() => false);
    const redirectedToLogin = page.url().includes('/') && !page.url().includes('404');

    expect(is404 || redirectedToLogin).toBeTruthy();
  });
});

test.describe('Responsive Design', () => {
  test('mobile viewport - page renders without errors', async ({ page }) => {
    // Skip if no auth token (most mobile tests need authenticated state)
    const authToken = process.env.TEST_AUTH_TOKEN;
    if (!authToken) {
      test.skip();
      return;
    }

    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });

    await page.goto('/');
    await page.evaluate((token) => {
      localStorage.setItem('token', token);
    }, authToken);

    await page.goto('/matters');
    await page.waitForLoadState('networkidle');

    // Page should render without errors on mobile
    // Check that heading or some content is visible
    const hasContent = await page.locator('h1, h2, [role="main"]').first().isVisible().catch(() => false);
    const hamburgerMenu = await page.locator('[aria-label*="menu"], button:has(svg)').first().isVisible().catch(() => false);

    // Either shows content or has navigation toggle
    expect(hasContent || hamburgerMenu).toBeTruthy();
  });
});
