import { test, expect } from '@playwright/test'
import { HOME_FIXTURE } from './fixtures/home-fixture.js'

test('records a PII-free Home conversation journey', async ({ page }) => {
  await page.setContent(HOME_FIXTURE)
  await expect(page.getByRole('heading', { name: '今日は何から始めますか？' })).toBeVisible()
  await page.getByLabel('Kadode AIへのメッセージ').fill('今週の優先課題を整理したい')
  await page.getByRole('button', { name: '送信' }).click()
  await expect(page.getByRole('heading', { name: '提案' })).toBeVisible()
  await page.getByRole('button', { name: 'プロジェクトに採用' }).click()
  await expect(page.getByTestId('fixture-status')).toHaveText('プロジェクトに採用しました。')
})
