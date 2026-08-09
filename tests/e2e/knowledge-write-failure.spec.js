import { expect, test } from '@playwright/test'

test('keeps the Knowledge confirmation visible and retryable when its local save fails', async ({ page }) => {
  test.setTimeout(120_000)
  await page.addInitScript(() => {
    localStorage.setItem('kadode:user-profile', JSON.stringify({
      status: 'completed',
      values: { experience: 'manufacturing', strengths: 'operations', interests: 'AI', time: '4 hours', budget: '100000', avoidances: 'high risk' },
    }))
    const storage = window.localStorage
    Object.defineProperty(window, 'localStorage', { configurable: true, value: {
      getItem: storage.getItem.bind(storage),
      setItem(key, value) {
        if (String(key).startsWith('kadode:knowledge-conversation:')) throw new Error('offline')
        return storage.setItem(key, value)
      },
      removeItem: storage.removeItem.bind(storage),
      clear: storage.clear.bind(storage),
    } })
  })

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.evaluate(() => { try { localStorage.setItem('kadode:knowledge-conversation:probe', 'x'); return false } catch { return true } })).resolves.toBe(true)
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
})
