import { test, expect } from '@playwright/test';

const AUTH_TOKEN = process.env.TEST_AUTH_TOKEN || '';

test('test with cache busting', async ({ page, context }) => {
  if (!AUTH_TOKEN) {
    test.skip();
    return;
  }

  await context.addInitScript((token) => {
    window.localStorage.setItem('auth-storage', JSON.stringify({ state: { token }, version: 0 }));
  }, AUTH_TOKEN);

  // Add cache-busting timestamp
  const timestamp = Date.now();
  await page.goto(`/jobs?nocache=${timestamp}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(5000);

  // Skip tour if present
  const skipTour = page.locator('button:has-text("Skip tour")');
  if (await skipTour.isVisible({ timeout: 2000 }).catch(() => false)) {
    await skipTour.click();
    await page.waitForTimeout(1000);
  }

  // Get job status
  const statusCell = page.locator('table tbody tr:first-child td:nth-child(3)');
  const fullHtml = await statusCell.innerHTML();

  console.log('\n=== Status Cell HTML (with cache bust) ===');
  console.log(fullHtml);

  // Check for time remaining
  const pageContent = await page.content();
  const hasCalculating = pageContent.includes('Calculating');
  const hasRemaining = pageContent.includes('remaining');
  console.log(`\nPage contains "Calculating": ${hasCalculating}`);
  console.log(`Page contains "remaining": ${hasRemaining}`);

  // Check the status of each job
  const rows = await page.locator('table tbody tr').all();
  console.log(`\n=== Job Status ===`);
  for (const row of rows) {
    const jobId = await row.locator('td').first().textContent() || '';
    const status = await row.locator('td:nth-child(3)').textContent() || '';
    const progress = await row.locator('td:nth-child(4)').textContent() || '';
    console.log(`${jobId}: ${status.trim()} | ${progress.trim()}`);
  }

  await page.screenshot({ path: 'test-results/cache-bust-test.png' });
});
