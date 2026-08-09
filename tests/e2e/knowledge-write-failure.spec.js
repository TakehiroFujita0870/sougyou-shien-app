import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1440, height: 900 } })

test('keeps the Knowledge confirmation visible and retryable when its local save fails', async ({ page }) => {
  await page.goto('http://127.0.0.1:6007/iframe.html?id=kadode-knowledgesurface--write-failure-recovery&viewMode=story', { waitUntil: 'domcontentloaded' })
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
  await dialog.getByRole('button').filter({ hasText: /ナレッジに追加/ }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByLabel(/ナレッジ一覧/)).toContainText('保存失敗時にも消えない確認内容')
})
