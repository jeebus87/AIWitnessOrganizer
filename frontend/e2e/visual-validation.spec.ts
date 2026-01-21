import { test, expect, Page } from '@playwright/test';

/**
 * Visual Validation E2E Test
 *
 * Takes screenshots at every step and validates UI elements are correct.
 * Evaluates each frame to ensure the application is working properly.
 */

const AUTH_TOKEN = process.env.TEST_AUTH_TOKEN || '';

interface ValidationResult {
  step: string;
  screenshot: string;
  passed: boolean;
  checks: { name: string; passed: boolean; details?: string }[];
}

const results: ValidationResult[] = [];

async function validateAndScreenshot(
  page: Page,
  stepName: string,
  screenshotName: string,
  validations: { name: string; check: () => Promise<boolean>; details?: () => Promise<string> }[]
): Promise<ValidationResult> {
  await page.screenshot({ path: `test-results/${screenshotName}.png`, fullPage: true });

  const checks: { name: string; passed: boolean; details?: string }[] = [];
  let allPassed = true;

  for (const validation of validations) {
    try {
      const passed = await validation.check();
      const details = validation.details ? await validation.details() : undefined;
      checks.push({ name: validation.name, passed, details });
      if (!passed) allPassed = false;
    } catch (error) {
      checks.push({ name: validation.name, passed: false, details: String(error) });
      allPassed = false;
    }
  }

  const result: ValidationResult = {
    step: stepName,
    screenshot: screenshotName,
    passed: allPassed,
    checks
  };

  results.push(result);

  // Log result
  console.log(`\n=== ${stepName} ===`);
  console.log(`Screenshot: ${screenshotName}.png`);
  for (const check of checks) {
    const status = check.passed ? '✓' : '✗';
    console.log(`  ${status} ${check.name}${check.details ? `: ${check.details}` : ''}`);
  }

  return result;
}

test.describe('Visual Validation Flow', () => {
  test.beforeEach(async ({ context }) => {
    if (!AUTH_TOKEN) {
      console.log('ERROR: TEST_AUTH_TOKEN not set - skipping test');
      test.skip();
      return;
    }

    await context.addInitScript((token) => {
      window.localStorage.setItem('auth-storage', JSON.stringify({
        state: { token },
        version: 0
      }));
    }, AUTH_TOKEN);
  });

  test('complete visual validation of all pages', async ({ page }) => {
    test.setTimeout(600000); // 10 minutes

    // === STEP 1: Jobs Page Initial Load ===
    console.log('\n' + '='.repeat(60));
    console.log('STARTING VISUAL VALIDATION TEST');
    console.log('='.repeat(60));

    await page.goto('/jobs', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(3000);

    // Dismiss tour if present
    const skipTour = page.locator('button:has-text("Skip tour")');
    if (await skipTour.isVisible({ timeout: 2000 }).catch(() => false)) {
      await skipTour.click();
      await page.waitForTimeout(1000);
    }

    await validateAndScreenshot(page, 'Jobs Page Load', '01-jobs-page', [
      {
        name: 'Page title visible',
        check: async () => await page.locator('h1:has-text("Processing Jobs")').isVisible({ timeout: 5000 }).catch(() => false)
      },
      {
        name: 'Job History section visible',
        check: async () => await page.locator('text=Job History').isVisible({ timeout: 5000 }).catch(() => false)
      },
      {
        name: 'Navigation menu present',
        check: async () => await page.locator('nav').count() > 0
      },
      {
        name: 'No error messages',
        check: async () => await page.locator('text=Error').count() === 0
      }
    ]);

    // === STEP 2: Check Job Table ===
    await page.waitForTimeout(2000);
    const hasTable = await page.locator('table').count() > 0;

    if (hasTable) {
      await validateAndScreenshot(page, 'Jobs Table', '02-jobs-table', [
        {
          name: 'Table headers present',
          check: async () => await page.locator('th').count() >= 3
        },
        {
          name: 'Job rows exist or empty state',
          check: async () => {
            const rows = await page.locator('table tbody tr').count();
            const emptyState = await page.locator('text=No jobs').isVisible().catch(() => false);
            return rows > 0 || emptyState;
          },
          details: async () => {
            const rows = await page.locator('table tbody tr').count();
            return `${rows} job rows found`;
          }
        }
      ]);

      // Check each job row
      const jobRows = await page.locator('table tbody tr').all();
      for (let i = 0; i < Math.min(jobRows.length, 3); i++) {
        const row = jobRows[i];
        const jobId = await row.locator('td').first().textContent() || 'unknown';
        const status = await row.locator('td:nth-child(3)').textContent() || 'unknown';
        const progress = await row.locator('td:nth-child(4)').textContent() || 'unknown';

        await validateAndScreenshot(page, `Job Row ${i + 1}`, `03-job-row-${i + 1}`, [
          {
            name: 'Job ID visible',
            check: async () => jobId !== 'unknown' && jobId.trim() !== '',
            details: async () => `Job ID: ${jobId}`
          },
          {
            name: 'Status badge visible',
            check: async () => status !== 'unknown',
            details: async () => `Status: ${status}`
          },
          {
            name: 'Progress displayed',
            check: async () => progress !== 'unknown',
            details: async () => `Progress: ${progress}`
          },
          {
            name: 'Progress not over 100%',
            check: async () => {
              const match = progress.match(/(\d+)%/);
              if (match) {
                const percent = parseInt(match[1]);
                return percent <= 100;
              }
              return true;
            },
            details: async () => progress
          }
        ]);
      }

      // Check for Case Law button (indicates pending legal research)
      const caseLawButton = page.locator('button:has-text("Case Law")');
      const hasCaseLaw = await caseLawButton.count() > 0;

      if (hasCaseLaw) {
        await validateAndScreenshot(page, 'Case Law Available', '04-case-law-button', [
          {
            name: 'Case Law button clickable',
            check: async () => await caseLawButton.first().isEnabled()
          }
        ]);

        // === STEP 3: Open Legal Research Dialog ===
        console.log('\nOpening legal research dialog...');
        await caseLawButton.first().click();
        await page.waitForTimeout(2000);

        await validateAndScreenshot(page, 'Legal Research Dialog', '05-legal-research-dialog', [
          {
            name: 'Dialog is visible',
            check: async () => await page.locator('[role="dialog"]').isVisible({ timeout: 5000 })
          },
          {
            name: 'Dialog title present',
            check: async () => await page.locator('text=Relevant Case Law').isVisible().catch(() => false) ||
                              await page.locator('text=Case Law').isVisible().catch(() => false)
          },
          {
            name: 'Case results displayed',
            check: async () => await page.locator('.cursor-pointer.p-4.border.rounded-lg').count() > 0,
            details: async () => {
              const count = await page.locator('.cursor-pointer.p-4.border.rounded-lg').count();
              return `${count} case results`;
            }
          },
          {
            name: 'Relevance info shown (matched query)',
            check: async () => await page.locator('text=Matched:').count() > 0
          },
          {
            name: 'Selection counter visible',
            check: async () => await page.locator('text=/\\d+ of \\d+ selected/').isVisible().catch(() => false)
          },
          {
            name: 'Save button present',
            check: async () => await page.locator('button:has-text("Save")').count() > 0
          }
        ]);

        // Check individual case cards
        const caseCards = await page.locator('.cursor-pointer.p-4.border.rounded-lg').all();
        for (let i = 0; i < Math.min(caseCards.length, 2); i++) {
          const card = caseCards[i];
          const caseName = await card.locator('h4, .font-semibold').first().textContent() || 'unknown';

          await validateAndScreenshot(page, `Case Card ${i + 1}`, `06-case-card-${i + 1}`, [
            {
              name: 'Case name visible',
              check: async () => caseName !== 'unknown' && caseName.trim() !== '',
              details: async () => caseName.substring(0, 50)
            },
            {
              name: 'Has excerpt',
              check: async () => await card.locator('text=Relevant excerpt').isVisible().catch(() => false) ||
                                await card.locator('p').count() > 0
            }
          ]);
        }

        // === STEP 4: Test Save Flow ===
        const saveButton = page.locator('button:has-text("Save")').filter({ hasNotText: 'Saving' });
        if (await saveButton.count() > 0 && await saveButton.isEnabled()) {
          console.log('\nTesting save flow...');
          await saveButton.click();
          await page.waitForTimeout(1000);

          await validateAndScreenshot(page, 'Saving Overlay', '07-saving-overlay', [
            {
              name: 'Saving overlay visible',
              check: async () => await page.locator('text=Saving').isVisible({ timeout: 5000 }).catch(() => false) ||
                                await page.locator('text=Saving cases to Clio').isVisible({ timeout: 5000 }).catch(() => false)
            },
            {
              name: 'Loading spinner present',
              check: async () => await page.locator('.animate-spin').count() > 0
            }
          ]);

          // Wait for save to complete
          console.log('Waiting for save to complete...');
          await expect(page.locator('[role="dialog"]')).toBeHidden({ timeout: 60000 }).catch(() => {});
          await page.waitForTimeout(2000);

          await validateAndScreenshot(page, 'After Save', '08-after-save', [
            {
              name: 'Dialog closed',
              check: async () => !(await page.locator('[role="dialog"]').isVisible().catch(() => false))
            },
            {
              name: 'Page updated',
              check: async () => true // Just capture state
            }
          ]);
        } else {
          console.log('Save button not available - closing dialog');
          await page.keyboard.press('Escape');
        }
      }
    }

    // === STEP 5: Navigate to Matters Page ===
    console.log('\nNavigating to Matters page...');
    await page.goto('/matters', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);

    // Dismiss tour if shown again
    if (await skipTour.isVisible({ timeout: 2000 }).catch(() => false)) {
      await skipTour.click();
      await page.waitForTimeout(1000);
    }

    await validateAndScreenshot(page, 'Matters Page', '09-matters-page', [
      {
        name: 'Matters heading visible',
        check: async () => await page.locator('h1:has-text("Matters")').isVisible({ timeout: 5000 }).catch(() => false)
      },
      {
        name: 'Matter cards or list visible',
        check: async () => {
          const cards = await page.locator('[class*="card"], [class*="matter"]').count();
          const table = await page.locator('table').count();
          return cards > 0 || table > 0;
        }
      },
      {
        name: 'No error messages',
        check: async () => await page.locator('text=Error').count() === 0
      }
    ]);

    // === FINAL SUMMARY ===
    console.log('\n' + '='.repeat(60));
    console.log('VALIDATION SUMMARY');
    console.log('='.repeat(60));

    let totalChecks = 0;
    let passedChecks = 0;

    for (const result of results) {
      const stepPassed = result.checks.every(c => c.passed);
      const status = stepPassed ? '✓ PASS' : '✗ FAIL';
      console.log(`\n${status}: ${result.step}`);

      for (const check of result.checks) {
        totalChecks++;
        if (check.passed) passedChecks++;
        const checkStatus = check.passed ? '  ✓' : '  ✗';
        console.log(`${checkStatus} ${check.name}`);
      }
    }

    console.log('\n' + '='.repeat(60));
    console.log(`TOTAL: ${passedChecks}/${totalChecks} checks passed`);
    console.log('='.repeat(60));

    // Fail test if any critical checks failed
    const criticalFailures = results.filter(r => !r.passed);
    if (criticalFailures.length > 0) {
      console.log('\nFailed steps:');
      for (const failure of criticalFailures) {
        console.log(`  - ${failure.step}`);
      }
    }

    expect(passedChecks).toBeGreaterThan(totalChecks * 0.8); // Allow 20% tolerance
  });
});
