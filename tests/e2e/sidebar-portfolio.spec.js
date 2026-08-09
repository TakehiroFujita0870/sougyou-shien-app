import { test, expect } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('kadode:user-profile', JSON.stringify({
      status: 'completed',
      values: { experience: 'manufacturing', strengths: 'operations', interests: 'AI', time: '4 hours', budget: '100000', avoidances: 'high risk' },
    }))
  })
})

test('mirrors a real Home message, keeps the account fixed, and archives only after persistence', async ({ page }) => {
  await page.goto('/')
  const composer = page.locator('#home-supervisor-message')
  await composer.fill('地域の小さな工場の受注管理を助けたい')
  await composer.press('Enter')

  const historyItem = page.getByRole('button', { name: '地域の小さな工場の受注管理を助けたい', exact: true })
  await expect(historyItem).toBeVisible()
  const sidebarBox = await page.locator('#workspace-sidebar').boundingBox()
  expect(sidebarBox?.width).toBe(168)
  expect(await page.locator('.workspace-shell__nav-item').first().evaluate((element) => getComputedStyle(element).fontSize)).toBe('12.8px')
  const account = page.getByRole('button', { name: /タケヒロのアカウント/ })
  const accountBox = await account.boundingBox()
  expect(accountBox?.y).toBeGreaterThan(760)
  expect((accountBox?.y ?? 0) + (accountBox?.height ?? 0)).toBeLessThanOrEqual(900)

  await page.screenshot({ path: 'test-results/sidebar-portfolio-1440x900.png', fullPage: false })
  await page.getByRole('button', { name: '地域の小さな工場の受注管理を助けたいをアーカイブ' }).click()
  await expect(page.getByRole('heading', { name: 'アーカイブ履歴' })).toBeVisible()
  await expect(page.locator('#home-supervisor-message')).toHaveCount(0)
  await page.getByRole('button', { name: 'ホーム', exact: true }).click()
  await expect(page.locator('#home-supervisor-message')).toHaveCount(0)
  await expect(page.locator('#knowledge-heading')).toBeVisible()

  await page.locator('#knowledge-file-picker').setInputFiles({ name: 'field-notes.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 local test') })
  await expect(page.getByRole('button', { name: /field-notes\.pdf/ })).toBeVisible()
  await expect(page.getByLabel('新着')).toBeVisible()
  await page.getByRole('button', { name: /field-notes\.pdf/ }).click()
  await expect(page.locator('#knowledge-heading')).toBeFocused()
})
