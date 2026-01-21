import { test, expect } from '@playwright/test';

const AUTH_TOKEN = process.env.TEST_AUTH_TOKEN || '';
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'https://aiwitness-frontend-production.up.railway.app';

test('test new frontend service', async ({ page, context }) => {
  if (!AUTH_TOKEN) {
    test.skip();
    return;
  }

  await context.addInitScript((token) => {
    window.localStorage.setItem('auth-storage', JSON.stringify({ state: { token }, version: 0 }));
  }, AUTH_TOKEN);

  console.log(`Testing URL: ${BASE_URL}`);

  await page.goto(`${BASE_URL}/jobs`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);

  // Check what page we're on
  const url = page.url();
  console.log(`Current URL: ${url}`);

  const pageText = await page.textContent('body');
  const isLoginPage = pageText?.includes('Sign in with your Clio');
  const isJobsPage = pageText?.includes('Processing Jobs') || pageText?.includes('Job History');

  console.log(`Is login page: ${isLoginPage}`);
  console.log(`Is jobs page: ${isJobsPage}`);

  // Check for version marker
  const hasVersionMarker = pageText?.includes('v2.1');
  const hasTimeRemaining = pageText?.includes('remaining') || pageText?.includes('Calculating');

  console.log(`Has version marker (v2.1): ${hasVersionMarker}`);
  console.log(`Has time remaining text: ${hasTimeRemaining}`);

  await page.screenshot({ path: 'test-results/new-service-test.png' });

  // If on jobs page, check status column
  if (isJobsPage) {
    const statusCell = page.locator('table tbody tr:first-child td:nth-child(3)');
    if (await statusCell.count() > 0) {
      const statusHtml = await statusCell.innerHTML();
      console.log(`Status cell HTML: ${statusHtml.substring(0, 500)}`);
    }
  }
});
