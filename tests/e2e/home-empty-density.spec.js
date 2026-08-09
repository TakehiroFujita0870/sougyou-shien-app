import { test, expect } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('kadode:user-profile', JSON.stringify({
      status: 'completed',
      values: { experience: 'manufacturing', strengths: 'operations', interests: 'AI', time: '4 hours', budget: '100000', avoidances: 'high risk' },
    }))
  })
})

test('keeps the empty desktop Home as a compact LLM conversation canvas', async ({ page }) => {
  await page.goto('/')
  const surface = page.locator('[data-home-state="empty"]')
  const composer = page.locator('#home-supervisor-message')

  await expect(surface).toBeVisible()
  await expect(composer).toBeVisible()
  await page.screenshot({ path: 'test-results/home-empty-1440x900.png', fullPage: true })

  const composerBox = await composer.boundingBox()
  expect(composerBox?.width).toBeGreaterThanOrEqual(760)
  expect(composerBox?.width).toBeLessThanOrEqual(960)
  expect(composerBox?.y).toBeGreaterThan(280)
  expect(composerBox?.y).toBeLessThan(680)
})
