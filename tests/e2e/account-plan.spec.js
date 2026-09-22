import { test, expect } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('dots:user-profile', JSON.stringify({
      status: 'completed',
      values: { experience: 'manufacturing', strengths: 'operations', interests: 'AI', time: '4 hours', budget: '100000', avoidances: 'high risk' },
    }))
  })
})

test('keeps Account anchored and exposes distinct Plan, Settings, and Help contracts', async ({ page }) => {
  await page.goto('/')
  const account = page.getByRole('button', { name: /タケヒロのアカウント/ })
  const accountBox = await account.boundingBox()
  expect(accountBox?.y).toBeGreaterThan(760)
  expect((accountBox?.y ?? 0) + (accountBox?.height ?? 0)).toBeLessThanOrEqual(900)

  await account.click()
  const logout = page.getByRole('menuitem', { name: 'ログアウト（認証連携前）' })
  await expect(logout).toHaveAttribute('data-disabled')
  await expect(logout).toHaveAttribute('aria-disabled', 'true')

  await page.getByRole('menuitem', { name: '設定', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '設定' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '設定' })).toHaveCount(0)
  await expect(account).toBeFocused()

  await account.click()
  await page.getByRole('menuitem', { name: 'ヘルプ・ショートカット' }).click()
  await expect(page.getByRole('dialog', { name: 'ヘルプ・ショートカット' })).toContainText('Alt + Shift + 1')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'ヘルプ・ショートカット' })).toHaveCount(0)
  await expect(account).toBeFocused()

  await account.click()
  await page.getByRole('menuitem', { name: 'プランと利用状況' }).click()
  await expect(page.getByRole('heading', { name: 'プランと利用状況' })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(account).toBeInViewport()
  await page.screenshot({ path: 'test-results/account-plan-1440x900.png', fullPage: false })
})
