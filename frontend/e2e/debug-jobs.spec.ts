import { test, expect } from '@playwright/test';

const AUTH_TOKEN = process.env.TEST_AUTH_TOKEN || '';

test('debug job data', async ({ page, context }) => {
  if (!AUTH_TOKEN) {
    test.skip();
    return;
  }

  await context.addInitScript((token) => {
    window.localStorage.setItem('auth-storage', JSON.stringify({ state: { token }, version: 0 }));
  }, AUTH_TOKEN);

  // Navigate to jobs page
  await page.goto('/jobs', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);

  // Skip tour if present
  const skipTour = page.locator('button:has-text("Skip tour")');
  if (await skipTour.isVisible({ timeout: 2000 }).catch(() => false)) {
    await skipTour.click();
    await page.waitForTimeout(1000);
  }

  // Capture the API responses by evaluating in browser context
  const jobData = await page.evaluate(async () => {
    // Get auth token from localStorage
    const storage = localStorage.getItem('auth-storage');
    if (!storage) return { error: 'No auth storage' };

    const { state } = JSON.parse(storage);
    const token = state?.token;
    if (!token) return { error: 'No token' };

    // Fetch jobs from API
    const apiUrl = (window as unknown as { __NEXT_DATA__?: { runtimeConfig?: { NEXT_PUBLIC_API_URL?: string } } }).__NEXT_DATA__?.runtimeConfig?.NEXT_PUBLIC_API_URL || '';

    // Try to find the API URL from environment or config
    let baseUrl = '';
    const envMeta = document.querySelector('meta[name="api-url"]');
    if (envMeta) {
      baseUrl = envMeta.getAttribute('content') || '';
    }

    // Fallback - check if there's a global config
    const anyWindow = window as { ENV?: { NEXT_PUBLIC_API_URL?: string } };
    if (anyWindow.ENV?.NEXT_PUBLIC_API_URL) {
      baseUrl = anyWindow.ENV.NEXT_PUBLIC_API_URL;
    }

    return {
      token: token.substring(0, 20) + '...',
      baseUrl: baseUrl || 'not found',
      localStorage: Object.keys(localStorage),
    };
  });

  console.log('\n=== Job Data Debug ===');
  console.log(JSON.stringify(jobData, null, 2));

  // Also check what's actually rendered in the DOM
  const statusCell = page.locator('table tbody tr:first-child td:nth-child(3)');
  const fullHtml = await statusCell.innerHTML();
  console.log('\n=== Full Status Cell HTML ===');
  console.log(fullHtml);

  // Check for any element with "Calculating" or "remaining" anywhere on page
  const pageContent = await page.content();
  const hasCalculating = pageContent.includes('Calculating');
  const hasRemaining = pageContent.includes('remaining');
  console.log(`\nPage contains "Calculating": ${hasCalculating}`);
  console.log(`Page contains "remaining": ${hasRemaining}`);

  // Check if there's a span with muted-foreground class inside the status cell
  const mutedSpans = await statusCell.locator('span.text-muted-foreground').count();
  console.log(`Muted foreground spans in status cell: ${mutedSpans}`);

  await page.screenshot({ path: 'test-results/debug-jobs.png' });
});
