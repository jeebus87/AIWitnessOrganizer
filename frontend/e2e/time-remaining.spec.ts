import { test, expect } from '@playwright/test';

const AUTH_TOKEN = process.env.TEST_AUTH_TOKEN || '';

test('check time remaining display', async ({ page, context }) => {
  if (!AUTH_TOKEN) {
    test.skip();
    return;
  }

  await context.addInitScript((token) => {
    window.localStorage.setItem('auth-storage', JSON.stringify({ state: { token }, version: 0 }));
  }, AUTH_TOKEN);

  await page.goto('/jobs', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  // Skip tour if present
  const skipTour = page.locator('button:has-text("Skip tour")');
  if (await skipTour.isVisible({ timeout: 2000 }).catch(() => false)) {
    await skipTour.click();
    await page.waitForTimeout(1000);
  }

  // Get the full HTML of the status column for processing jobs
  const statusCells = await page.locator('table tbody tr').all();

  console.log('\n=== Checking Time Remaining Display ===\n');

  for (const row of statusCells) {
    const jobId = await row.locator('td').first().textContent() || '';
    const statusCell = row.locator('td:nth-child(3)');
    const statusHtml = await statusCell.innerHTML();
    const statusText = await statusCell.textContent();

    console.log(`Job ${jobId}:`);
    console.log(`  Status text: ${statusText?.trim()}`);

    // Check for time remaining patterns
    const hasTimeRemaining = statusText?.includes('remaining') ||
                            statusText?.includes('min') ||
                            statusText?.includes('Calculating');
    console.log(`  Has time remaining: ${hasTimeRemaining}`);

    // Check if processing
    const isProcessing = statusText?.includes('Processing');
    console.log(`  Is processing: ${isProcessing}`);

    if (isProcessing) {
      console.log(`  Status HTML: ${statusHtml.substring(0, 500)}`);
    }
  }

  // Look for any text containing "remaining" or "Calculating"
  const timeRemainingText = page.locator('text=/remaining|Calculating/');
  const count = await timeRemainingText.count();
  console.log(`\nTime remaining elements found: ${count}`);

  if (count > 0) {
    const text = await timeRemainingText.first().textContent();
    console.log(`First match: ${text}`);
  }

  await page.screenshot({ path: 'test-results/time-remaining-check.png' });
});
