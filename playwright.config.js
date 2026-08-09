import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'

const systemChromium = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
  ?? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: './test-results',
  reporter: process.env.CI ? 'dot' : [['list'], ['html', { open: 'never' }]],
  webServer: [
    { command: 'npm run dev -- --host 127.0.0.1 --port 4177', url: 'http://127.0.0.1:4177', reuseExistingServer: false, timeout: 120_000 },
    { command: 'npm run storybook -- --ci --host 127.0.0.1 --port 6007', url: 'http://127.0.0.1:6007', reuseExistingServer: false, timeout: 120_000 },
  ],
  use: {
    baseURL: 'http://127.0.0.1:4177',
    browserName: 'chromium',
    ...(existsSync(systemChromium) ? { launchOptions: { executablePath: systemChromium } } : {}),
    headless: true,
    video: { mode: 'on', size: { width: 1440, height: 900 } },
    trace: 'retain-on-failure',
    viewport: { width: 1440, height: 900 },
  },
})
