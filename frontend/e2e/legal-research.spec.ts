import { test, expect } from '@playwright/test';

/**
 * E2E Test for Legal Research / Case Law Feature
 *
 * Tests that:
 * 1. Case Law results dialog shows relevant civil cases
 * 2. Criminal cases are filtered out
 * 3. Relevance explanations are shown
 */

// Auth token for testing - replace with fresh token as needed
const AUTH_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyIiwiZW1haWwiOiJqdmFsbGVzQHNoYW5sZXlhcGMuY29tIiwiZXhwIjoxNzY5NjQ1ODUwLCJpYXQiOjE3NjkwNDEwNTB9.EixiNr8TLeuQ7vQU89Lf9momAKG-BiD5EAEFYG4rMHk';

test.describe('Legal Research Feature', () => {
  test.beforeEach(async ({ page }) => {
    // Inject auth token into localStorage before navigating
    await page.addInitScript((token) => {
      localStorage.setItem('auth-storage', JSON.stringify({
        state: { token },
        version: 0
      }));
    }, AUTH_TOKEN);
  });

  test('should display relevant civil case law without criminal cases', async ({ page }) => {
    // Navigate to jobs page
    await page.goto('/jobs');
    await page.waitForLoadState('networkidle');

    // Handle onboarding tour if it appears - use keyboard to dismiss
    const skipTourButton = page.getByRole('button', { name: 'Skip tour' });
    if (await skipTourButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      console.log('Dismissing onboarding tour...');
      await page.keyboard.press('Escape');
      await page.waitForTimeout(500);
    }

    // Check if Case Law results dialog is already open (from pending results)
    let dialog = page.locator('[role="dialog"]:has-text("Relevant Case Law Found")');
    let dialogAlreadyOpen = await dialog.isVisible({ timeout: 2000 }).catch(() => false);

    if (dialogAlreadyOpen) {
      console.log('Case Law results dialog already open - using existing results');
    } else {
      console.log('No existing dialog, need to trigger Case Law generation');

      // Wait for page to be ready and click Case Law button
      await page.waitForTimeout(1000);

      // Use keyboard Escape to close any remaining overlays
      await page.keyboard.press('Escape');
      await page.waitForTimeout(500);

      const caseLawButton = page.locator('button:has-text("Case Law")').first();
      await expect(caseLawButton).toBeVisible({ timeout: 10000 });
      console.log('Clicking Case Law button...');
      await caseLawButton.click({ force: true });

      // Wait for dialog to appear
      dialog = page.locator('[role="dialog"]');
      await expect(dialog).toBeVisible({ timeout: 120000 });

      // Wait for loading to complete
      const spinner = dialog.locator('.animate-spin');
      if (await spinner.isVisible({ timeout: 2000 }).catch(() => false)) {
        console.log('Waiting for API response...');
        await expect(spinner).toBeHidden({ timeout: 300000 });
      }
    }

    // Now verify the dialog content
    console.log('Verifying dialog content...');

    // Should show "Relevant Case Law Found"
    await expect(dialog.getByText('Relevant Case Law Found')).toBeVisible({ timeout: 10000 });
    console.log('Dialog title confirmed: Relevant Case Law Found');

    // Verify we have results counter
    const resultsCount = dialog.locator('text=/\\d+ of \\d+ selected/');
    await expect(resultsCount).toBeVisible();
    const countText = await resultsCount.textContent();
    console.log(`Results: ${countText}`);

    // Get all case cards and check for criminal cases
    const caseHeadings = dialog.locator('h4');
    const cardCount = await caseHeadings.count();
    console.log(`Found ${cardCount} case headings`);

    let criminalCasesFound = 0;
    const caseNames: string[] = [];

    for (let i = 0; i < cardCount; i++) {
      const caseText = await caseHeadings.nth(i).textContent();
      const caseLower = caseText?.toLowerCase() || '';
      caseNames.push(caseText || '');

      // Check for criminal case indicators
      if (caseLower.startsWith('people v') ||
          caseLower.startsWith('state v') ||
          caseLower.startsWith('united states v') ||
          caseLower.includes('murder') ||
          caseLower.includes('death penalty') ||
          caseLower.includes('criminal')) {
        console.error(`CRIMINAL CASE FOUND: ${caseText}`);
        criminalCasesFound++;
      }
    }

    console.log('Cases found:', caseNames.slice(0, 5).join(', ') + (caseNames.length > 5 ? '...' : ''));
    expect(criminalCasesFound).toBe(0);
    console.log('No criminal cases found in results');

    // Verify at least some cases have relevance explanations
    const relevanceExplanations = dialog.locator('text=/Why Relevant/');
    const explanationCount = await relevanceExplanations.count();
    console.log(`Found ${explanationCount} relevance explanations`);
    expect(explanationCount).toBeGreaterThan(0);

    // Take a screenshot of the results
    await page.screenshot({ path: 'e2e/screenshots/legal-research-results.png', fullPage: true });

    console.log('TEST PASSED: Criminal cases filtered out, civil cases shown with relevance explanations');
  });
});
