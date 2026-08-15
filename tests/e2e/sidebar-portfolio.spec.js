import { test, expect } from '@playwright/test'
import { sidebarPortfolioStorageKey } from '../../src/components/sidebarPortfolioRepository.js'

const portfolioStorageKey = sidebarPortfolioStorageKey('local-owner', 'local-space')

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('dots:user-profile', JSON.stringify({
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
  await expect(secondHistoryItem).toHaveAttribute('title', '商店街の空き店舗活用を考えたい')
  const sidebarBox = await page.locator('#workspace-sidebar').boundingBox()
  expect(sidebarBox?.width).toBe(168)
  const titleBox = await secondHistoryItem.boundingBox()
  expect(titleBox?.width).toBeGreaterThanOrEqual(80)
  const archiveAction = page.getByRole('button', { name: '商店街の空き店舗活用を考えたいをアーカイブ' })
  await archiveAction.focus()
  await expect(archiveAction).toBeFocused()
  const archiveBox = await archiveAction.boundingBox()
  expect(archiveBox?.width).toBe(44)
  expect(archiveBox?.height).toBe(44)
  expect(await page.locator('.workspace-shell__nav-item').first().evaluate((element) => getComputedStyle(element).fontSize)).toBe('12.8px')
  const account = page.getByRole('button', { name: /タケヒロのアカウント/ })
  const accountBox = await account.boundingBox()
  expect(accountBox?.y).toBeGreaterThan(760)
  expect((accountBox?.y ?? 0) + (accountBox?.height ?? 0)).toBeLessThanOrEqual(900)

  await page.screenshot({ path: 'test-results/sidebar-portfolio-1440x900.png', fullPage: false })
  await page.keyboard.press('Enter')
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
    localStorage.setItem('dots:home-conversation', JSON.stringify({ messages, proposals }))
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

test('restores an archived Home snapshot with the keyboard and keeps its active snapshot after F5', async ({ page }) => {
  await page.goto('/')
  const message = 'F5後も戻せるHome会話'
  await page.locator('#home-supervisor-message').fill(message)
  await page.locator('#home-supervisor-message').press('Enter')
  const history = page.getByRole('button', { name: message, exact: true })
  await expect(history).toBeVisible()
  await page.getByRole('button', { name: `${message}をアーカイブ` }).click()
  const restart = page.getByRole('button', { name: `${message}を再開` })
  await expect(restart).toBeVisible()
  await expect(restart).toHaveAttribute('title', `${message}を再開`)
  const restartBox = await restart.boundingBox()
  expect(restartBox?.width).toBe(44)
  expect(restartBox?.height).toBe(44)
  await page.screenshot({ path: 'test-results/sidebar-archive-home-1440.png', fullPage: false })

  await restart.focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('[aria-label="会話履歴"]')).toContainText(message)
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key))?.portfolio, portfolioStorageKey)).toMatchObject({
    activeHomeId: expect.any(String),
    home: [expect.objectContaining({ title: message, archived: false })],
  })
  await page.screenshot({ path: 'test-results/sidebar-restored-home-1440.png', fullPage: false })

  await page.reload()
  await expect(page.locator('[aria-label="会話履歴"]')).toContainText(message)
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key))?.portfolio, portfolioStorageKey)).toMatchObject({
    activeHomeId: expect.any(String),
    home: [expect.objectContaining({ title: message, archived: false })],
  })
})

test('restores an archived Project snapshot by click and keeps the Project state after F5', async ({ page }) => {
  const project = {
    id: 'e2e-restored-project', ownerId: 'local-owner', spaceId: 'local-space', title: 'F5後も戻せるProject',
    fact: '顧客の作業時間が毎週失われている', inference: '受注管理の自動化が有効', reason: 'ヒアリングで確認済み', status: 'adopted',
  }
  await page.addInitScript((snapshot) => {
    sessionStorage.setItem('dots:selected-surface', 'project')
    localStorage.setItem('dots:adopted-projects', JSON.stringify({ schemaVersion: 1, projects: [snapshot] }))
    localStorage.setItem('dots:sidebar-portfolio:local-owner:local-space', JSON.stringify({
      activeHomeId: '', home: [], knowledge: [], project: [{ id: snapshot.id, title: snapshot.title, snapshot, archived: false, updatedAt: 1 }],
    }))
  }, project)
  await page.goto('/')
  await expect(page.locator('#project-surface-heading')).toHaveText(project.title)
  await page.getByRole('button', { name: `${project.title}をアーカイブ` }).click()
  const restart = page.getByRole('button', { name: `${project.title}を再開` })
  await expect(restart).toBeVisible()
  await page.screenshot({ path: 'test-results/sidebar-archive-project-1440.png', fullPage: false })

  await restart.click()
  await expect(page.locator('#project-surface-heading')).toHaveText(project.title)
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key))?.portfolio, portfolioStorageKey)).toMatchObject({
    project: [expect.objectContaining({ id: project.id, archived: false, snapshot: expect.objectContaining({ title: project.title }) })],
  })
  await page.screenshot({ path: 'test-results/sidebar-restored-project-1440.png', fullPage: false })

  await page.reload()
  await expect(page.locator('#project-surface-heading')).toHaveText(project.title)
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key))?.portfolio, portfolioStorageKey)).toMatchObject({
    project: [expect.objectContaining({ id: project.id, archived: false, snapshot: expect.objectContaining({ title: project.title }) })],
  })
})
