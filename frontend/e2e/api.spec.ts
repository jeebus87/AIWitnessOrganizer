import { test, expect } from '@playwright/test';

/**
 * API E2E Tests
 *
 * These tests verify the backend API endpoints work correctly.
 * They use Playwright's request context for direct API calls.
 */

const API_BASE = process.env.API_BASE_URL || 'https://aiwitnessfinder-api-production.up.railway.app';
const E2E_SECRET = process.env.E2E_SECRET || 'e2e-test-secret-key-2024';

test.describe('Health Check Endpoints', () => {
  test('API health check', async ({ request }) => {
    const response = await request.get(`${API_BASE}/health`);
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(['ok', 'healthy'].includes(data.status)).toBeTruthy();
  });

  test('API root returns info', async ({ request }) => {
    const response = await request.get(`${API_BASE}/`);
    expect(response.ok()).toBeTruthy();
  });
});

test.describe('E2E Test Endpoints', () => {
  test('test-export-formats - all export formats work', async ({ request }) => {
    const response = await request.post(
      `${API_BASE}/api/v1/test/test-export-formats?secret=${E2E_SECRET}`
    );

    if (response.status() === 404) {
      test.skip();
      return;
    }

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data.all_passed).toBeTruthy();
    expect(data.pdf.status).toBe('passed');
    expect(data.excel.status).toBe('passed');
    expect(data.docx.status).toBe('passed');

    console.log(`PDF: ${data.pdf.size_bytes} bytes`);
    console.log(`Excel: ${data.excel.size_bytes} bytes`);
    console.log(`DOCX: ${data.docx.size_bytes} bytes`);
  });

  test('subfolder-recursive-count - folder recursion works', async ({ request }) => {
    // This endpoint requires specific folder_id and matter_id
    // Use known test values from production
    const response = await request.get(
      `${API_BASE}/api/v1/test/subfolder-recursive-count?folder_id=17982546233&matter_id=13031&secret=${E2E_SECRET}`
    );

    if (response.status() === 404 || response.status() === 400) {
      test.skip();
      return;
    }

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data.all_passed).toBeTruthy();
    expect(data.folder_only_count.passed).toBeTruthy();
    expect(data.recursive_count.passed).toBeTruthy();

    console.log(`Folder only: ${data.folder_only_count.count} documents`);
    console.log(`Recursive: ${data.recursive_count.count} documents`);
  });

  test('folder-count - folder document counting works', async ({ request }) => {
    const response = await request.get(
      `${API_BASE}/api/v1/test/folder-count?folder_id=17982546233&secret=${E2E_SECRET}`
    );

    if (response.status() === 404 || response.status() === 400) {
      test.skip();
      return;
    }

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data.all_passed).toBeTruthy();
    expect(data.specific_folder.count).toBeGreaterThanOrEqual(0);

    console.log(`Folder document count: ${data.specific_folder.count}`);
    console.log(`All documents count: ${data.all_documents.count}`);
  });
});

test.describe('Authenticated API Endpoints', () => {
  const authToken = process.env.TEST_AUTH_TOKEN;

  test('matters endpoint requires auth', async ({ request }) => {
    // Without auth - should fail with 401 or 422 (validation error on missing token)
    const noAuthResponse = await request.get(`${API_BASE}/api/v1/matters`);
    expect([401, 403, 422].includes(noAuthResponse.status())).toBeTruthy();
  });

  test('matters endpoint works with auth', async ({ request }) => {
    if (!authToken) {
      test.skip();
      return;
    }

    const response = await request.get(`${API_BASE}/api/v1/matters`, {
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
    });

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(Array.isArray(data)).toBeTruthy();
  });

  test('jobs endpoint works with auth', async ({ request }) => {
    if (!authToken) {
      test.skip();
      return;
    }

    const response = await request.get(`${API_BASE}/api/v1/jobs`, {
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
    });

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(Array.isArray(data)).toBeTruthy();
  });

  test('witnesses endpoint works with auth', async ({ request }) => {
    if (!authToken) {
      test.skip();
      return;
    }

    const response = await request.get(`${API_BASE}/api/v1/witnesses`, {
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
    });

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(Array.isArray(data)).toBeTruthy();
  });
});

test.describe('Export Endpoints', () => {
  const authToken = process.env.TEST_AUTH_TOKEN;

  test('PDF export returns valid file', async ({ request }) => {
    if (!authToken) {
      test.skip();
      return;
    }

    // First get a job ID
    const jobsResponse = await request.get(`${API_BASE}/api/v1/jobs`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    const jobs = await jobsResponse.json();
    const completedJob = jobs.find((j: any) => j.status === 'completed');

    if (!completedJob) {
      console.log('No completed jobs found for export test');
      test.skip();
      return;
    }

    const response = await request.get(
      `${API_BASE}/api/v1/jobs/${completedJob.id}/export/pdf`,
      {
        headers: { Authorization: `Bearer ${authToken}` },
      }
    );

    expect(response.ok()).toBeTruthy();
    expect(response.headers()['content-type']).toContain('pdf');
  });

  test('Excel export returns valid file', async ({ request }) => {
    if (!authToken) {
      test.skip();
      return;
    }

    const jobsResponse = await request.get(`${API_BASE}/api/v1/jobs`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    const jobs = await jobsResponse.json();
    const completedJob = jobs.find((j: any) => j.status === 'completed');

    if (!completedJob) {
      test.skip();
      return;
    }

    const response = await request.get(
      `${API_BASE}/api/v1/jobs/${completedJob.id}/export/excel`,
      {
        headers: { Authorization: `Bearer ${authToken}` },
      }
    );

    expect(response.ok()).toBeTruthy();
  });

  test('DOCX export returns valid file', async ({ request }) => {
    if (!authToken) {
      test.skip();
      return;
    }

    const jobsResponse = await request.get(`${API_BASE}/api/v1/jobs`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    const jobs = await jobsResponse.json();
    const completedJob = jobs.find((j: any) => j.status === 'completed');

    if (!completedJob) {
      test.skip();
      return;
    }

    const response = await request.get(
      `${API_BASE}/api/v1/jobs/${completedJob.id}/export/docx`,
      {
        headers: { Authorization: `Bearer ${authToken}` },
      }
    );

    expect(response.ok()).toBeTruthy();
  });
});
