const { defineConfig } = require('@playwright/test');

// The preview readiness probe must bypass a workstation's outbound proxy.
process.env.NO_PROXY = [process.env.NO_PROXY, '127.0.0.1', 'localhost', '::1'].filter(Boolean).join(',');
process.env.no_proxy = process.env.NO_PROXY;

module.exports = defineConfig({
  testDir: './e2e',
  timeout: 30000,
  expect: { timeout: 7000 },
  fullyParallel: true,
  workers: 2,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:4179',
    browserName: 'chromium',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [320, 390, 768, 1024, 1440, 1920].flatMap(width =>
    ['light', 'dark'].map(colorScheme => ({
      name: `${width}-${colorScheme}`,
      use: { viewport: { width, height: width < 768 ? 844 : 1000 }, colorScheme },
    })),
  ),
  webServer: {
    command: 'pnpm exec vite preview --host 127.0.0.1 --port 4179 --strictPort',
    url: 'http://127.0.0.1:4179',
    reuseExistingServer: false,
    timeout: 30000,
  },
});
