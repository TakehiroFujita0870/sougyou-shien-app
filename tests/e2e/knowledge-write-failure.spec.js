import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1440, height: 900 } })

test('keeps the Knowledge confirmation visible and retryable when its local save fails', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('kadode:user-profile', JSON.stringify({
      status: 'completed',
      values: { experience: 'manufacturing', strengths: 'operations', interests: 'AI', time: '4 hours', budget: '100000', avoidances: 'high risk' },
    }))
    sessionStorage.setItem('kadode:e2e:knowledge-write-failure', '1')
  })

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'ナレッジ', exact: true }).click()
  const composer = page.locator('#knowledge-composer')
  await composer.fill('保存失敗時にも消えない確認内容')
  await composer.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'ナレッジに追加しますか？' })
  await expect(dialog).toContainText('保存失敗時にも消えない確認内容')
  await dialog.getByRole('button', { name: 'ナレッジに追加' }).click()
  await expect(page.getByRole('alert')).toContainText('ナレッジを保存できませんでした')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'ナレッジに追加' })).toBeEnabled()
  await page.screenshot({ path: 'test-results/knowledge-write-failure-1440.png', fullPage: false })
  await page.evaluate(() => sessionStorage.removeItem('kadode:e2e:knowledge-write-failure'))
  await dialog.getByRole('button').filter({ hasText: /ナレッジに追加/ }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByLabel(/ナレッジ一覧/)).toContainText('保存失敗時にも消えない確認内容')
})
