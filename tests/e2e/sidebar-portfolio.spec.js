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
  await composer.fill('商店街の空き店舗活用を考えたい')
  await composer.press('Enter')
  const secondHistoryItem = page.getByRole('button', { name: '商店街の空き店舗活用を考えたい', exact: true })
  await expect(secondHistoryItem).toBeVisible()
  const sidebarBox = await page.locator('#workspace-sidebar').boundingBox()
  expect(sidebarBox?.width).toBe(168)
  expect(await page.locator('.workspace-shell__nav-item').first().evaluate((element) => getComputedStyle(element).fontSize)).toBe('12.8px')
  const account = page.getByRole('button', { name: /タケヒロのアカウント/ })
  const accountBox = await account.boundingBox()
  expect(accountBox?.y).toBeGreaterThan(760)
  expect((accountBox?.y ?? 0) + (accountBox?.height ?? 0)).toBeLessThanOrEqual(900)

  await page.screenshot({ path: 'test-results/sidebar-portfolio-1440x900.png', fullPage: false })
  await page.getByRole('button', { name: '商店街の空き店舗活用を考えたいをアーカイブ' }).click()
  await expect(page.getByRole('heading', { name: 'アーカイブ履歴' })).toBeVisible()
  await expect(page.locator('#home-supervisor-message')).toHaveCount(0)
  await page.getByRole('button', { name: 'ホーム', exact: true }).click()
  await expect(page.locator('#home-supervisor-message')).toHaveCount(0)
  await expect(page.locator('#knowledge-heading')).toBeVisible()
  await historyItem.click()
  await expect(page.locator('#home-supervisor-message')).toBeVisible()
  await expect(page.getByLabel('会話履歴')).toContainText('地域の小さな工場の受注管理を助けたい')
  await expect(page.getByLabel('会話履歴')).not.toContainText('商店街の空き店舗活用を考えたい')
  await page.getByRole('button', { name: 'ナレッジ', exact: true }).click()

  await page.locator('#knowledge-file-picker').setInputFiles({ name: 'field-notes.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 local test') })
  await expect(page.getByRole('button', { name: /field-notes\.pdf/ })).toBeVisible()
  await expect(page.getByLabel('新着')).toBeVisible()
  await page.getByRole('button', { name: /field-notes\.pdf/ }).click()
  await expect(page.locator('#knowledge-heading')).toBeFocused()
})

test('keeps the Home composer and account visible with ten long turns', async ({ page }) => {
  await page.addInitScript(() => {
    const messages = Array.from({ length: 10 }, (_, index) => [
      { role: 'user', content: `利用者の困りごとを確認する長い会話 ${index + 1}` },
      { role: 'assistant', content: `根拠と次に確かめることを整理した回答 ${index + 1}` },
    ]).flat()
    const proposals = Array.from({ length: 10 }, (_, index) => ({
      id: `proposal-${index + 1}`,
      title: `提案 ${index + 1}`,
      fact: '現在のsurface: Home',
      inference: `検証する提案 ${index + 1}`,
      reason: '',
      action: 'ideate',
      confirmed: false,
      status: index === 0 ? 'pending' : 'held',
    }))
    localStorage.setItem('kadode:home-conversation', JSON.stringify({ messages, proposals }))
  })

  await page.goto('/')
  const scrollRegion = page.locator('[data-home-scroll-region="true"]')
  const composer = page.locator('[data-home-composer="true"]')
  const send = page.getByRole('button', { name: '発言を送信' })
  const account = page.getByRole('button', { name: /タケヒロのアカウント/ })
  await expect(scrollRegion).toBeVisible()
  await expect(composer).toBeVisible()
  await expect(send).toBeVisible()
  await expect(account).toBeVisible()

  const geometry = await page.evaluate(() => {
    const region = document.querySelector('[data-home-scroll-region="true"]')
    const form = document.querySelector('[data-home-composer="true"]')
    const sidebar = document.querySelector('#workspace-sidebar')
    const accountButton = sidebar.querySelector('footer button')
    const regionRect = region.getBoundingClientRect()
    const formRect = form.getBoundingClientRect()
    const sidebarRect = sidebar.getBoundingClientRect()
    const accountRect = accountButton.getBoundingClientRect()
    return {
      regionScrollable: region.scrollHeight > region.clientHeight,
      regionBottom: regionRect.bottom,
      formTop: formRect.top,
      formBottom: formRect.bottom,
      formLeft: formRect.left,
      sidebarRight: sidebarRect.right,
      accountBottom: accountRect.bottom,
    }
  })
  expect(geometry.regionScrollable).toBe(true)
  expect(geometry.regionBottom).toBeLessThanOrEqual(geometry.formTop)
  expect(geometry.formBottom).toBeLessThanOrEqual(900)
  expect(geometry.formLeft).toBeGreaterThanOrEqual(geometry.sidebarRight)
  expect(geometry.accountBottom).toBeLessThanOrEqual(900)

  const pendingReason = page.locator('#reject-proposal-1')
  const pendingAdopt = page.getByRole('button', { name: 'プロジェクトに採用' })
  await pendingReason.scrollIntoViewIfNeeded()
  await expect(pendingReason).toBeInViewport()
  await expect(pendingAdopt).toBeInViewport()
  const pendingGeometry = await page.evaluate(() => {
    const region = document.querySelector('[data-home-scroll-region="true"]').getBoundingClientRect()
    const form = document.querySelector('[data-home-composer="true"]').getBoundingClientRect()
    const reason = document.querySelector('#reject-proposal-1').getBoundingClientRect()
    const actions = document.querySelector('#reject-proposal-1').nextElementSibling.getBoundingClientRect()
    return { regionTop: region.top, regionBottom: region.bottom, formTop: form.top, reasonTop: reason.top, actionsBottom: actions.bottom }
  })
  expect(pendingGeometry.reasonTop).toBeGreaterThanOrEqual(pendingGeometry.regionTop)
  expect(pendingGeometry.actionsBottom).toBeLessThanOrEqual(pendingGeometry.regionBottom)
  expect(pendingGeometry.actionsBottom).toBeLessThanOrEqual(pendingGeometry.formTop)
  await pendingReason.focus()
  await page.keyboard.press('Tab')
  await expect(pendingAdopt).toBeFocused()
  await expect(send).toBeInViewport()
  await expect(account).toBeInViewport()
  await page.screenshot({ path: 'test-results/sidebar-portfolio-1440x900.png', fullPage: false })
})
