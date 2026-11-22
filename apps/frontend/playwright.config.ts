import { defineConfig, devices } from '@playwright/test';

/**
 * E2E contra la solución levantada con docker compose (front en :8080, API, MCP, mocks y LLM reales).
 *   $env:API_DEMO_PASSWORD = "<de .env>"   (o se lee de ../../.env)
 *   npm run e2e
 * Usa el LLM real (~US$ 0,02 por corrida). Reinicia los mocks antes y después (datos limpios).
 */
export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/preparar.ts',
  globalTeardown: './e2e/limpiar.ts',
  timeout: 90_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env['E2E_URL'] ?? 'http://localhost:8080',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'es-CO',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
});
