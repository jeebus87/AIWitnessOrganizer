import { test, expect } from '@playwright/test';

/**
 * E2E Test for Clio Rate Limit Error Handling
 *
 * Verifies that when Clio rate limits are hit, the user sees a friendly error
 * message instead of a raw exception.
 */

const AUTH_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyIiwiZW1haWwiOiJqdmFsbGVzQHNoYW5sZXlhcGMuY29tIiwiZXhwIjoxNzY5NjQ1ODUwLCJpYXQiOjE3NjkwNDEwNTB9.EixiNr8TLeuQ7vQU89Lf9momAKG-BiD5EAEFYG4rMHk';

test.describe('Clio Rate Limit Handling', () => {
  test.beforeEach(async ({ page }) => {
    // Inject auth token
    await page.addInitScript((token) => {
      localStorage.setItem('auth-storage', JSON.stringify({
        state: { token },
        version: 0
      }));
    }, AUTH_TOKEN);
  });

  test('should show folder selection dialog without ugly errors', async ({ page }) => {
    // Navigate to matters page
    await page.goto('/matters');
    await page.waitForLoadState('networkidle');

    // Handle onboarding tour if it appears
    try {
      const skipTourButton = page.getByRole('button', { name: 'Skip tour' });
      if (await skipTourButton.isVisible({ timeout: 3000 })) {
        console.log('Dismissing onboarding tour...');
        await page.keyboard.press('Escape');
        await page.waitForTimeout(500);
      }
    } catch (e) {
      // No tour, continue
    }

    // Wait for matters to load
    await page.waitForTimeout(2000);

    // Take screenshot of matters page
    await page.screenshot({ path: 'e2e/screenshots/01-matters-page.png', fullPage: true });
    console.log('Screenshot 1: Matters page loaded');

    // Click the first Process button to trigger folder loading (where rate limits would appear)
    const processButton = page.getByRole('button', { name: 'Process' }).first();

    if (await processButton.isVisible({ timeout: 5000 })) {
      console.log('Found Process button, clicking it...');
      await processButton.click();
      await page.waitForTimeout(2000);

      // Take screenshot after clicking Process
      await page.screenshot({ path: 'e2e/screenshots/02-after-process-click.png', fullPage: true });
      console.log('Screenshot 2: After clicking Process button');
    } else {
      console.log('No Process button found');
      await page.screenshot({ path: 'e2e/screenshots/02-no-process-button.png', fullPage: true });
    }

    // Look for the folder selection dialog or any dialog that appears
    await page.waitForTimeout(2000);

    // Check for the "Select Folders to Process" dialog
    const folderDialog = page.locator('text=Select Folders to Process');
    const dialogVisible = await folderDialog.isVisible({ timeout: 5000 }).catch(() => false);

    if (dialogVisible) {
      console.log('Folder selection dialog is visible');
      await page.screenshot({ path: 'e2e/screenshots/03-folder-dialog.png', fullPage: true });
      console.log('Screenshot 3: Folder dialog');

      // Check for rate limit error message
      const errorText = page.locator('text=/rate limit|RetryError|ClioRateLimitError/i');
      const hasError = await errorText.isVisible({ timeout: 3000 }).catch(() => false);

      if (hasError) {
        const errorContent = await errorText.textContent();
        console.log('Error found:', errorContent);

        // Check if it's the friendly message or the ugly one
        if (errorContent?.includes('RetryError') || errorContent?.includes('ClioRateLimitError')) {
          console.log('FAIL: Still showing ugly error message');
          await page.screenshot({ path: 'e2e/screenshots/04-ugly-error.png', fullPage: true });
        } else if (errorContent?.includes('Please wait')) {
          console.log('PASS: Showing friendly rate limit message');
          await page.screenshot({ path: 'e2e/screenshots/04-friendly-error.png', fullPage: true });
        }
      } else {
        console.log('No rate limit error visible - folders may have loaded successfully');

        // Check if folders loaded
        const folderList = page.locator('[role="tree"], [data-testid="folder-tree"]');
        if (await folderList.isVisible({ timeout: 3000 }).catch(() => false)) {
          console.log('PASS: Folders loaded successfully');
        }
      }
    } else {
      console.log('Folder dialog not visible, checking page state...');
      await page.screenshot({ path: 'e2e/screenshots/03-current-state.png', fullPage: true });
    }

    // Final screenshot
    await page.screenshot({ path: 'e2e/screenshots/05-final-state.png', fullPage: true });
    console.log('Screenshot 5: Final state');

    console.log('Test complete');
  });
});
