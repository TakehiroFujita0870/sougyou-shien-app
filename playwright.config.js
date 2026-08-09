import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'

const systemChromium = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
  ?? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: './test-results',
  reporter: process.env.CI ? 'dot' : [['list'], ['html', { open: 'never' }]],
  use: { browserName: 'chromium', ...(existsSync(systemChromium) ? { launchOptions: { executablePath: systemChromium } } : {}), headless: true, video: 'on', trace: 'retain-on-failure', viewport: { width: 1440, height: 900 } },
})
