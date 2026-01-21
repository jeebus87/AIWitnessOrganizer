import { test, expect } from '@playwright/test';

const AUTH_TOKEN = process.env.TEST_AUTH_TOKEN || '';

test('check version marker', async ({ page, context }) => {
  if (!AUTH_TOKEN) {
    test.skip();
    return;
  }

  await context.addInitScript((token) => {
    window.localStorage.setItem('auth-storage', JSON.stringify({ state: { token }, version: 0 }));
  }, AUTH_TOKEN);

  await page.goto('/jobs', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);

  // Check for version marker
  const pageText = await page.textContent('body');
  const hasVersionMarker = pageText?.includes('v2.1');
  const hasOldText = pageText?.includes('Track the status of your document processing jobs');

  console.log(`\n=== Version Check ===`);
  console.log(`Has version marker (v2.1): ${hasVersionMarker}`);
  console.log(`Has page text: ${hasOldText}`);

  // Check page subtitle
  const subtitle = page.locator('p.text-muted-foreground').first();
  const subtitleText = await subtitle.textContent();
  console.log(`Subtitle text: ${subtitleText}`);

  await page.screenshot({ path: 'test-results/version-check.png' });
});
