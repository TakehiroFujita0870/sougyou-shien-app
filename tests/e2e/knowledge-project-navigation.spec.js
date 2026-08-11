import { expect, test } from '@playwright/test'

const ownerId = 'local-owner'
const spaceId = 'local-space'
const project = { id: 'evidence-project', ownerId, spaceId, title: '根拠から開く事業', fact: '顧客ヒアリング', inference: '市場検証を進める', reason: '採用判断', status: 'adopted' }
const otherProject = { ...project, id: 'other-project', title: '先にある事業' }
const scopedKey = 'kadode:knowledge-conversation:11:local-owner:11:local-space:v1'

function entry(evaluationView, projectId = project.id) {
  return { id: `evidence:${evaluationView}`, category: 'decision', title: '採用判断の根拠', content: 'Projectで確認する根拠', createdAt: '2026-08-11T00:00:00.000Z', updatedAt: '2026-08-11T00:00:00.000Z', sourceType: 'local', confidence: 'unknown', unknowns: [], projectId, evaluationView }
}

async function seed(page, evaluationView, projectId = project.id) {
  await page.addInitScript(({ seededProject, seededEntry, key }) => {
    if (!localStorage.getItem('kadode:user-profile')) localStorage.setItem('kadode:user-profile', JSON.stringify({ status: 'completed', values: {} }))
    if (!localStorage.getItem('kadode:adopted-projects')) localStorage.setItem('kadode:adopted-projects', JSON.stringify({ schemaVersion: 1, projects: [seededProject.other, seededProject.current] }))
    if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify({ schemaVersion: 1, ownerId: seededProject.current.ownerId, spaceId: seededProject.current.spaceId, state: { messages: [], entries: [seededEntry] } }))
    if (!sessionStorage.getItem('kadode:selected-surface')) sessionStorage.setItem('kadode:selected-surface', 'knowledge')
  }, { seededProject: { current: project, other: otherProject }, seededEntry: entry(evaluationView, projectId), key: scopedKey })
}

test('opens a same-owner evidence link at its exact Project view and survives F5', async ({ page }) => {
  await seed(page, '市場はある？')
  await page.goto('/')
  await page.getByRole('button', { name: 'Projectを開く' }).click()
  const market = page.getByRole('tab', { name: '市場はある？' })
  await expect(market).toHaveAttribute('aria-selected', 'true')
  await expect(market).toBeFocused()
  await page.screenshot({ path: 'test-results/knowledge-project-navigation-1440.png', fullPage: false })
  await page.reload()
  await expect(page.getByRole('heading', { name: project.title })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'どんな事業？' })).toHaveAttribute('aria-selected', 'true')
})

test('does not render a stale or cross-project evidence action', async ({ page }) => {
  await seed(page, '市場はある？', 'missing-project')
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Projectを開く' })).toHaveCount(0)
})

test('creates a same-owner decision evidence link only after an explicit view choice and survives F5', async ({ page }) => {
  await page.addInitScript(({ seededProject, key }) => {
    if (!localStorage.getItem('kadode:user-profile')) localStorage.setItem('kadode:user-profile', JSON.stringify({ status: 'completed', values: {} }))
    if (!localStorage.getItem('kadode:adopted-projects')) localStorage.setItem('kadode:adopted-projects', JSON.stringify({ schemaVersion: 1, projects: [seededProject] }))
    if (!sessionStorage.getItem('kadode:selected-surface')) sessionStorage.setItem('kadode:selected-surface', 'knowledge')
  }, { seededProject: project, key: scopedKey })
  await page.goto('/')
  const composer = page.locator('#knowledge-composer')
  await composer.fill('採用判断: 顧客ヒアリングを始める')
  await composer.press('Enter')
  const marketChoice = page.getByRole('button', { name: '市場はある？' })
  await expect(marketChoice).toBeVisible()
  await marketChoice.click()
  await page.getByRole('button', { name: 'ナレッジに追加', exact: true }).click()
  const openProject = page.getByRole('button', { name: 'Projectを開く' })
  await expect(openProject).toBeVisible()
  await page.reload()
  await expect(openProject).toBeVisible()
  await openProject.focus()
  await page.keyboard.press('Enter')
  const market = page.getByRole('tab', { name: '市場はある？' })
  await expect(market).toBeFocused()
  await page.screenshot({ path: 'test-results/knowledge-confirm-evidence-link-1440.png', fullPage: false })
})

test('keeps Knowledge actionable when selecting a Project cannot persist, then retries without an unhandled error', async ({ page }) => {
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await seed(page, '市場はある？')
  await page.goto('/')
  await page.evaluate(() => {
    const original = Storage.prototype.setItem
    let failOnce = true
    Storage.prototype.setItem = function setItem(key, value) {
      if (failOnce && key === 'kadode:adopted-projects') {
        failOnce = false
        throw new DOMException('Storage quota exceeded', 'QuotaExceededError')
      }
      return original.call(this, key, value)
    }
  })

  const openProject = page.getByRole('button', { name: 'Projectを開く' })
  await openProject.click()
  await expect(page.getByRole('alert')).toContainText('Projectを開けませんでした。もう一度お試しください。')
  await expect(page.locator('#knowledge-heading')).toBeVisible()
  await expect(openProject).toBeVisible()
  await page.screenshot({ path: 'test-results/knowledge-project-navigation-error-1440.png', fullPage: false })

  await openProject.click()
  await expect(page.getByRole('tab', { name: '市場はある？' })).toBeFocused()
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(pageErrors).toEqual([])
  await page.screenshot({ path: 'test-results/knowledge-project-navigation-recovery-1440.png', fullPage: false })
})

for (const evaluationView of ['どんな事業？', '市場はある？', '競合は誰？', '利益は出る？', '実現できる？']) {
  test(`opens ${evaluationView} by keyboard`, async ({ page }) => {
    await seed(page, evaluationView)
    await page.goto('/')
    await page.getByRole('button', { name: 'Projectを開く' }).focus()
    await page.keyboard.press('Enter')
    const tab = page.getByRole('tab', { name: evaluationView })
    await expect(tab).toHaveAttribute('aria-selected', 'true')
    await expect(tab).toBeFocused()
  })
}
