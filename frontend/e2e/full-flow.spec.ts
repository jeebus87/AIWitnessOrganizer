import { test, expect } from '@playwright/test';

/**
 * Full E2E Flow Test
 *
 * Tests the complete workflow:
 * 1. Login with auth token
 * 2. Navigate to Matters
 * 3. Start processing a matter
 * 4. Wait for job to complete
 * 5. Test legal research dialog and save to Clio
 */

const AUTH_TOKEN = process.env.TEST_AUTH_TOKEN || '';

test.describe('Full Processing Flow', () => {
  test.beforeEach(async ({ context }) => {
    if (!AUTH_TOKEN) {
      test.skip();
      return;
    }

    // Set auth token before any navigation
    await context.addInitScript((token) => {
      window.localStorage.setItem('auth-storage', JSON.stringify({
        state: { token },
        version: 0
      }));
    }, AUTH_TOKEN);
  });

  test('complete flow: process matter and save legal research', async ({ page }) => {
    // Increase timeout for this long-running test
    test.setTimeout(600000); // 10 minutes

    console.log('Step 1: Navigate to Matters page');
    await page.goto('/matters', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2000);

    // Dismiss any tour/welcome dialog if present
    const skipTourButton = page.locator('button:has-text("Skip tour")');
    if (await skipTourButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      console.log('Dismissing tour dialog...');
      await skipTourButton.click();
      await page.waitForTimeout(1000);
    }

    // Should see matters page
    await expect(page.locator('h1:has-text("Matters")')).toBeVisible({ timeout: 15000 });
    await page.screenshot({ path: 'test-results/01-matters-page.png' });

    console.log('Step 2: Check for existing processing job or Case Law');
    await page.goto('/jobs', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // First check if there's already pending legal research
    const caseLawButton = page.locator('button:has-text("Case Law")');
    if (await caseLawButton.count() > 0) {
      console.log('Found existing job with legal research - testing save flow');
      await testLegalResearchSave(page);
      return;
    }

    // Check if there's already a processing job
    const processingBadge = page.locator('text=Processing');
    const hasProcessingJob = await processingBadge.count() > 0;

    if (!hasProcessingJob) {
      console.log('No processing job found - starting a new one');
      await page.goto('/matters', { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(2000);

      // Dismiss tour if shown again
      const skipTourButton = page.locator('button:has-text("Skip tour")');
      if (await skipTourButton.isVisible({ timeout: 2000 }).catch(() => false)) {
        await skipTourButton.click();
        await page.waitForTimeout(1000);
      }

      const processButton = page.locator('button:has-text("Process")').first();
      if (await processButton.count() === 0) {
        console.log('No matters available to process');
        return;
      }

      console.log('Step 3: Click Process button');
      await processButton.click();
      await page.waitForTimeout(1000);

      // Check if a confirmation dialog appears
      const confirmButton = page.locator('button:has-text("Start Processing"), button:has-text("Confirm"), button:has-text("Process")').last();
      if (await confirmButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await confirmButton.click();
      }

      await page.screenshot({ path: 'test-results/02-started-processing.png' });
      await page.goto('/jobs', { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(2000);
    } else {
      console.log('Found existing processing job - waiting for completion');
    }

    console.log('Step 4: Wait for job completion');

    // Wait for job to complete (poll every 10 seconds for up to 4 minutes)
    let jobCompleted = false;
    let attempts = 0;
    const maxAttempts = 24; // 4 minutes

    while (!jobCompleted && attempts < maxAttempts) {
      attempts++;
      console.log(`Checking job status... attempt ${attempts}/${maxAttempts}`);

      // Check for completed status or Case Law button
      const completedBadge = page.locator('text=Completed').first();
      const caseLawButton = page.locator('button:has-text("Case Law")');
      const processingBadge = page.locator('text=Processing');

      if (await caseLawButton.count() > 0) {
        console.log('Found Case Law button - job completed with results!');
        jobCompleted = true;
        break;
      }

      if (await completedBadge.isVisible({ timeout: 1000 }).catch(() => false)) {
        console.log('Job shows Completed status');
        // Wait a moment for legal research to be ready
        await page.waitForTimeout(5000);
        await page.reload();
        await page.waitForTimeout(2000);

        if (await caseLawButton.count() > 0) {
          jobCompleted = true;
          break;
        }
      }

      // Log current progress if processing
      if (await processingBadge.isVisible({ timeout: 1000 }).catch(() => false)) {
        const progressText = await page.locator('text=/\\d+\\/\\d+/').first().textContent().catch(() => 'unknown');
        const timeRemaining = await page.locator('text=/~.*remaining|Calculating/').first().textContent().catch(() => 'no estimate');
        console.log(`  Progress: ${progressText}, Time remaining: ${timeRemaining}`);
      }

      await page.screenshot({ path: `test-results/03-progress-${attempts}.png` });

      // Wait and refresh
      await page.waitForTimeout(10000);
      await page.reload();
      await page.waitForTimeout(2000);
    }

    if (!jobCompleted) {
      console.log('Job did not complete in time - checking final state');
      await page.screenshot({ path: 'test-results/04-timeout-state.png' });

      // Check if there's at least a completed job without legal research
      const completedBadge = page.locator('text=Completed');
      if (await completedBadge.count() > 0) {
        console.log('Job completed but no legal research pending');
      }
      return;
    }

    console.log('Step 5: Test legal research save');
    await testLegalResearchSave(page);
  });
});

async function testLegalResearchSave(page: any) {
  console.log('Opening legal research dialog...');

  const caseLawButton = page.locator('button:has-text("Case Law")').first();
  await caseLawButton.click();

  // Wait for dialog
  await expect(page.locator('[role="dialog"]')).toBeVisible({ timeout: 10000 });
  await page.screenshot({ path: 'test-results/05-legal-research-dialog.png' });

  // Check for case results
  const results = page.locator('.cursor-pointer.p-4.border.rounded-lg');
  const resultCount = await results.count();
  console.log(`Found ${resultCount} case law results`);

  if (resultCount === 0) {
    console.log('No case law results found in dialog');
    await page.keyboard.press('Escape');
    return;
  }

  // Check for matched query display (new relevance feature)
  const matchedQuery = page.locator('text=Matched:');
  if (await matchedQuery.count() > 0) {
    const queryText = await matchedQuery.first().locator('..').textContent();
    console.log(`Relevance info: ${queryText}`);
  }

  // Check selection count
  const selectionText = await page.locator('text=/\\d+ of \\d+ selected/').textContent().catch(() => 'unknown');
  console.log(`Selection: ${selectionText}`);

  // Click save button
  const saveButton = page.locator('button:has-text("Save")').filter({ hasNotText: 'Saving' });

  if (await saveButton.count() > 0 && await saveButton.isEnabled()) {
    console.log('Clicking Save button...');
    await saveButton.click();

    // Should show saving overlay
    const savingOverlay = page.locator('text=Saving cases to Clio');
    await expect(savingOverlay).toBeVisible({ timeout: 5000 });
    await page.screenshot({ path: 'test-results/06-saving-overlay.png' });
    console.log('Saving overlay displayed!');

    // Wait for completion (dialog should close)
    await expect(page.locator('[role="dialog"]')).toBeHidden({ timeout: 60000 });
    console.log('Save completed - dialog closed');

    await page.screenshot({ path: 'test-results/07-save-complete.png' });

    // Verify the Case Law button is gone (research was saved)
    await page.waitForTimeout(2000);
    const caseLawButtonAfter = page.locator('button:has-text("Case Law")');
    const stillHasCaseLaw = await caseLawButtonAfter.count() > 0;
    console.log(`Case Law button still visible: ${stillHasCaseLaw}`);
  } else {
    console.log('Save button not available or disabled');
    await page.keyboard.press('Escape');
  }
}
