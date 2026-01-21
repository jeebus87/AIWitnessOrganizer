import { test } from '@playwright/test';

const AUTH_TOKEN = process.env.TEST_AUTH_TOKEN || '';

test('check job status', async ({ page, context }) => {
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

  // Get all job rows
  const rows = await page.locator('table tbody tr').all();
  console.log(`\n=== Found ${rows.length} jobs ===\n`);

  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const jobId = await row.locator('td').first().textContent();
    const status = await row.locator('td:nth-child(3)').textContent();
    const progress = await row.locator('td:nth-child(4)').textContent();
    const witnesses = await row.locator('td:nth-child(5)').textContent();
    console.log(`Job ${jobId}: ${status} | Progress: ${progress} | Witnesses: ${witnesses}`);
  }

  // Check for Case Law button
  const caseLawBtn = page.locator('button:has-text("Case Law")');
  const hasCaseLaw = await caseLawBtn.count() > 0;
  console.log(`\nCase Law button visible: ${hasCaseLaw}`);

  await page.screenshot({ path: 'test-results/job-status-check.png' });
});
