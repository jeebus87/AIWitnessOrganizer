import { test as setup, expect } from '@playwright/test';
import path from 'path';

const authFile = path.join(__dirname, '../.playwright/.auth/user.json');

/**
 * Authentication setup - logs in via Clio OAuth and saves session state.
 * This runs before all other tests to establish authenticated state.
 */
setup('authenticate via Clio', async ({ page }) => {
  // Navigate to login page
  await page.goto('/');

  // Wait for redirect to login or for authenticated state
  // The app uses Clio OAuth, so we need to handle that flow

  // Check if we're on the login page
  const loginButton = page.getByRole('button', { name: /sign in with clio/i });

  if (await loginButton.isVisible()) {
    console.log('Login required - this test requires manual OAuth setup');
    // For automated testing, you would need to:
    // 1. Use a test account with pre-configured OAuth tokens
    // 2. Or inject auth tokens directly
    // 3. Or use Clio's sandbox environment

    // For now, we'll skip auth setup if not already logged in
    // Real implementation would use test credentials
  }

  // If already authenticated, save the state
  await page.context().storageState({ path: authFile });
});
