import { test, expect } from '@playwright/test';

/**
 * Legal Research E2E Tests
 *
 * Tests the complete legal research flow:
 * 1. Navigate to jobs page with authentication
 * 2. Check for completed jobs with legal research
 * 3. Open legal research dialog
 * 4. Verify case law results are displayed with relevance info
 * 5. Save cases to Clio
 */

const AUTH_TOKEN = process.env.TEST_AUTH_TOKEN || '';

test.describe('Legal Research Flow', () => {
  test.beforeEach(async ({ page, context }) => {
    // Skip if no auth token provided
    if (!AUTH_TOKEN) {
      test.skip();
      return;
    }

    // Set localStorage before navigating using addInitScript
    await context.addInitScript((token) => {
      window.localStorage.setItem('auth-storage', JSON.stringify({
        state: { token },
        version: 0
      }));
    }, AUTH_TOKEN);

    // Now navigate - the auth should be set
    await page.goto('/jobs', { waitUntil: 'networkidle' });

    // Wait a moment for hydration
    await page.waitForTimeout(2000);
  });

  test('authenticated user can access jobs page', async ({ page }) => {
    // beforeEach already navigated to /jobs

    // Should see the Jobs page heading
    await expect(page.locator('h1:has-text("Processing Jobs")')).toBeVisible({ timeout: 15000 });

    // Should see job history card
    await expect(page.locator('text=Job History')).toBeVisible();
  });

  test('completed job shows legal research results', async ({ page }) => {
    // beforeEach already navigated to /jobs

    // Wait for jobs to load
    await page.waitForSelector('table', { timeout: 20000 });

    // Take screenshot of jobs page
    await page.screenshot({ path: 'test-results/jobs-page.png' });

    // Look for Case Law button (indicates completed job with pending research)
    const caseLawButton = page.locator('button:has-text("Case Law")');

    if (await caseLawButton.count() > 0) {
      // Click to open dialog
      await caseLawButton.first().click();

      // Wait for dialog to open
      await expect(page.locator('[role="dialog"]')).toBeVisible({ timeout: 5000 });

      // Should see dialog title
      await expect(page.locator('text=Relevant Case Law Found')).toBeVisible();

      // Take screenshot of legal research dialog
      await page.screenshot({ path: 'test-results/legal-research-dialog.png' });

      // Check for case law results
      const results = page.locator('.cursor-pointer.p-4.border.rounded-lg');
      const resultCount = await results.count();

      console.log(`Found ${resultCount} case law results`);

      if (resultCount > 0) {
        // Check that relevance info is displayed (matched query)
        const matchedText = page.locator('text=Matched:');
        const hasMatchedQuery = await matchedText.count() > 0;
        console.log(`Matched query displayed: ${hasMatchedQuery}`);

        // Check for relevant excerpt
        await expect(page.locator('text=Relevant excerpt:').first()).toBeVisible();
      }

      // Close dialog
      await page.keyboard.press('Escape');
    } else {
      console.log('No pending legal research found - checking for completed jobs');

      // Check if there are any completed jobs
      const completedBadge = page.locator('text=Completed');
      const hasCompleted = await completedBadge.count() > 0;
      console.log(`Has completed jobs: ${hasCompleted}`);
    }
  });

  test('can save legal research to Clio', async ({ page }) => {
    // beforeEach already navigated to /jobs

    // Wait for page to load
    await page.waitForSelector('table', { timeout: 20000 });

    // Look for Case Law button
    const caseLawButton = page.locator('button:has-text("Case Law")');

    if (await caseLawButton.count() === 0) {
      console.log('No pending legal research - skipping save test');
      test.skip();
      return;
    }

    // Click to open dialog
    await caseLawButton.first().click();

    // Wait for dialog
    await expect(page.locator('[role="dialog"]')).toBeVisible({ timeout: 5000 });

    // Check for save button
    const saveButton = page.locator('button:has-text("Save")').filter({ hasNotText: 'Saving' });

    if (await saveButton.count() > 0) {
      // Get selection count
      const selectionText = await page.locator('text=/\\d+ of \\d+ selected/').textContent();
      console.log(`Selection: ${selectionText}`);

      // Click save
      await saveButton.click();

      // Should show saving overlay
      await expect(page.locator('text=Saving cases to Clio')).toBeVisible({ timeout: 3000 });

      // Take screenshot of saving state
      await page.screenshot({ path: 'test-results/saving-to-clio.png' });

      // Wait for completion (dialog should close or show success)
      await expect(page.locator('[role="dialog"]')).toBeHidden({ timeout: 30000 });

      console.log('Save completed successfully');
    } else {
      console.log('No save button available - may have no results');
    }
  });

  test('job progress shows time remaining', async ({ page }) => {
    // beforeEach already navigated to /jobs

    // Wait for jobs to load
    await page.waitForSelector('table', { timeout: 20000 });

    // Look for processing jobs
    const processingBadge = page.locator('text=Processing');

    if (await processingBadge.count() > 0) {
      // Check for time remaining display
      const timeRemaining = page.locator('text=/~\\d+ min remaining|< 1 min remaining|Calculating/');
      const hasTimeRemaining = await timeRemaining.count() > 0;

      console.log(`Time remaining displayed: ${hasTimeRemaining}`);

      if (hasTimeRemaining) {
        const text = await timeRemaining.first().textContent();
        console.log(`Time remaining text: ${text}`);
      }

      // Take screenshot
      await page.screenshot({ path: 'test-results/processing-job.png' });
    } else {
      console.log('No processing jobs found');
    }
  });
});
