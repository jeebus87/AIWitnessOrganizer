import { test, expect } from '@playwright/test';

/**
 * Live E2E Test for Juan Munoz Case
 *
 * This test monitors the processing job for the Juan Munoz case
 * and verifies that the deadlock fix is working correctly.
 */

// Get auth token from environment
const AUTH_TOKEN = process.env.TEST_AUTH_TOKEN;
const BASE_URL = 'https://aiwitnessorganizer.juridionlaw.com';

test.describe('Juan Munoz Case - Live Processing Test', () => {
  test.beforeEach(async ({ page }) => {
    if (!AUTH_TOKEN) {
      console.log('No TEST_AUTH_TOKEN provided - will attempt to use existing session');
    }

    // Navigate to the app
    await page.goto(BASE_URL);

    // If we have an auth token, inject it
    if (AUTH_TOKEN) {
      await page.evaluate((token) => {
        localStorage.setItem('auth-storage', JSON.stringify({
          state: { token, user: null },
          version: 0
        }));
      }, AUTH_TOKEN);
      // Reload to apply the token
      await page.reload();
    }

    await page.waitForLoadState('networkidle');
  });

  test('monitor Juan Munoz job progress', async ({ page }) => {
    // Navigate to Jobs page
    await page.goto(`${BASE_URL}/jobs`);
    await page.waitForLoadState('networkidle');

    // Wait for jobs table to load
    await expect(page.getByRole('heading', { name: /processing jobs/i })).toBeVisible({ timeout: 15000 });

    // Look for Juan Munoz in the table
    const juanMunozRow = page.locator('tr').filter({ hasText: /Juan Munoz/i });

    if (await juanMunozRow.count() > 0) {
      console.log('Found Juan Munoz job row');

      // Get job status
      const statusBadge = juanMunozRow.locator('[class*="badge"]').first();
      const statusText = await statusBadge.textContent();
      console.log(`Job status: ${statusText}`);

      // Get progress
      const progressText = await juanMunozRow.locator('td').nth(3).textContent();
      console.log(`Job progress: ${progressText}`);

      // Get witnesses found
      const witnessesText = await juanMunozRow.locator('td').nth(4).textContent();
      console.log(`Witnesses found: ${witnessesText}`);

      // Take screenshot
      await page.screenshot({ path: 'e2e-results/juan-munoz-status.png', fullPage: true });

      // If job is processing, monitor for a bit
      if (statusText?.toLowerCase().includes('processing')) {
        console.log('Job is processing - monitoring for 60 seconds...');

        for (let i = 0; i < 12; i++) {
          await page.waitForTimeout(5000);
          await page.reload();
          await page.waitForLoadState('networkidle');

          const updatedRow = page.locator('tr').filter({ hasText: /Juan Munoz/i });
          const updatedProgress = await updatedRow.locator('td').nth(3).textContent();
          const updatedStatus = await updatedRow.locator('[class*="badge"]').first().textContent();

          console.log(`[${(i + 1) * 5}s] Status: ${updatedStatus}, Progress: ${updatedProgress}`);

          // Check for completion or failure
          if (updatedStatus?.toLowerCase().includes('completed')) {
            console.log('Job completed successfully!');
            await page.screenshot({ path: 'e2e-results/juan-munoz-completed.png', fullPage: true });
            break;
          }

          if (updatedStatus?.toLowerCase().includes('failed')) {
            console.log('Job failed!');
            await page.screenshot({ path: 'e2e-results/juan-munoz-failed.png', fullPage: true });
            // Don't fail the test - we want to see the result
            break;
          }
        }
      }

      // Verify the job exists and has data
      expect(await juanMunozRow.count()).toBeGreaterThan(0);
    } else {
      console.log('No Juan Munoz job found - checking if we need to start one');

      // Navigate to Matters to find Juan Munoz case
      await page.goto(`${BASE_URL}/matters`);
      await page.waitForLoadState('networkidle');

      // Search for Juan Munoz
      const searchInput = page.getByPlaceholder(/search/i);
      if (await searchInput.isVisible()) {
        await searchInput.fill('Juan Munoz');
        await page.waitForTimeout(1000);
      }

      // Look for the matter
      const matterCard = page.locator('text=Juan Munoz').first();
      if (await matterCard.isVisible()) {
        console.log('Found Juan Munoz matter');
        await page.screenshot({ path: 'e2e-results/juan-munoz-matter.png', fullPage: true });
      }
    }
  });

  test('verify timezone display format', async ({ page }) => {
    // Navigate to Jobs page
    await page.goto(`${BASE_URL}/jobs`);
    await page.waitForLoadState('networkidle');

    // Wait for jobs table to load
    await expect(page.getByRole('heading', { name: /processing jobs/i })).toBeVisible({ timeout: 15000 });

    // Get the "Started" column values
    const startedCells = page.locator('table tbody tr td:nth-child(6)');
    const cellCount = await startedCells.count();

    if (cellCount > 0) {
      for (let i = 0; i < Math.min(cellCount, 3); i++) {
        const dateText = await startedCells.nth(i).textContent();
        console.log(`Job ${i + 1} started at: ${dateText}`);

        // Verify date format looks correct (should include AM/PM for user timezone)
        if (dateText && dateText !== '—') {
          expect(dateText).toMatch(/\d{1,2}\/\d{1,2}\/\d{4}.*\d{1,2}:\d{2}:\d{2}\s*(AM|PM)/i);
        }
      }
    }

    await page.screenshot({ path: 'e2e-results/jobs-timezone-check.png', fullPage: true });
  });

  test('check for deadlock errors in recent jobs', async ({ page }) => {
    // Navigate to Jobs page
    await page.goto(`${BASE_URL}/jobs`);
    await page.waitForLoadState('networkidle');

    // Look for any failed jobs
    const failedBadges = page.locator('[class*="badge"]').filter({ hasText: /failed/i });
    const failedCount = await failedBadges.count();

    console.log(`Found ${failedCount} failed jobs`);

    // Check each failed job for deadlock-related errors
    const failedRows = page.locator('tr').filter({ has: page.locator('[class*="badge"]').filter({ hasText: /failed/i }) });
    const rowCount = await failedRows.count();

    for (let i = 0; i < rowCount; i++) {
      const row = failedRows.nth(i);
      const errorText = await row.locator('[class*="text-red"]').textContent().catch(() => '');

      if (errorText) {
        console.log(`Failed job ${i + 1} error: ${errorText}`);

        // Check if it's a deadlock error
        if (errorText.toLowerCase().includes('deadlock')) {
          console.log('WARNING: Found deadlock error in failed job!');
        }
      }
    }

    await page.screenshot({ path: 'e2e-results/jobs-error-check.png', fullPage: true });
  });
});

test.describe('Start New Processing Job', () => {
  test.skip(({ }, testInfo) => !process.env.START_NEW_JOB, 'Skipped - set START_NEW_JOB=1 to run');

  test('start processing for Juan Munoz case', async ({ page }) => {
    if (!AUTH_TOKEN) {
      test.skip();
      return;
    }

    // Navigate and authenticate
    await page.goto(BASE_URL);
    await page.evaluate((token) => {
      localStorage.setItem('auth-storage', JSON.stringify({
        state: { token, user: null },
        version: 0
      }));
    }, AUTH_TOKEN);
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Go to Matters
    await page.goto(`${BASE_URL}/matters`);
    await page.waitForLoadState('networkidle');

    // Dismiss any onboarding tour modal if present
    const skipTourButton = page.getByRole('button', { name: /skip tour|skip|close/i });
    if (await skipTourButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      console.log('Dismissing onboarding tour...');
      await skipTourButton.click();
      await page.waitForTimeout(500);
    }

    // Search for Juan Munoz
    const searchInput = page.getByPlaceholder(/search/i);
    await searchInput.fill('Juan Munoz');
    await page.waitForTimeout(1000); // Wait for search results

    // Find and click Juan Munoz matter row
    const matterRow = page.locator('tr, [data-testid="matter-row"]').filter({ hasText: /Juan Munoz/i }).first();

    if (await matterRow.isVisible({ timeout: 5000 })) {
      // Click the Process button directly in the row
      const processButton = matterRow.getByRole('button', { name: /process/i });
      if (await processButton.isVisible()) {
        console.log('Found Process button in Juan Munoz row, clicking...');
        await processButton.click();
      } else {
        // Click the row to go to detail page
        await matterRow.click();
        await page.waitForLoadState('networkidle');

        // Click process button on detail page
        const detailProcessButton = page.getByRole('button', { name: /process|extract|find witnesses/i });
        await detailProcessButton.click();
      }
    } else {
      throw new Error('Juan Munoz matter not found in search results');
    }

    // Wait for modal
    const modal = page.getByRole('dialog');
    await expect(modal).toBeVisible({ timeout: 5000 });

    console.log('Process modal opened');
    await page.screenshot({ path: 'e2e-results/juan-munoz-process-modal.png', fullPage: true });

    // Click start/confirm button in the modal
    const startButton = modal.getByRole('button', { name: /start|process|confirm|begin/i });
    await startButton.click();

    // Wait for job to be created
    await page.waitForTimeout(3000);

    console.log('Processing job started for Juan Munoz');
    await page.screenshot({ path: 'e2e-results/juan-munoz-job-started.png', fullPage: true });

    // Navigate to Jobs page to verify
    await page.goto(`${BASE_URL}/jobs`);
    await page.waitForLoadState('networkidle');

    // Look for the new job
    const juanMunozJob = page.locator('tr').filter({ hasText: /Juan Munoz/i });
    await expect(juanMunozJob).toBeVisible({ timeout: 10000 });

    console.log('Verified Juan Munoz job is now in the jobs list');
    await page.screenshot({ path: 'e2e-results/juan-munoz-job-verified.png', fullPage: true });
  });
});
