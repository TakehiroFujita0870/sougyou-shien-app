import { expect, test } from '@playwright/test'

const ownerId = 'local-owner'
const spaceId = 'local-space'
const project = { id: 'evidence-project', ownerId, spaceId, title: '根拠から開く事業', fact: '顧客ヒアリング', inference: '市場検証を進める', reason: '採用判断', status: 'adopted' }
const scopedKey = 'kadode:knowledge-conversation:11:local-owner:11:local-space:v1'

function entry(evaluationView, projectId = project.id) {
  return { id: `evidence:${evaluationView}`, category: 'decision', title: '採用判断の根拠', content: 'Projectで確認する根拠', createdAt: '2026-08-11T00:00:00.000Z', updatedAt: '2026-08-11T00:00:00.000Z', sourceType: 'local', confidence: 'unknown', unknowns: [], projectId, evaluationView }
}

async function seed(page, evaluationView, projectId = project.id) {
  await page.addInitScript(({ seededProject, seededEntry, key }) => {
    localStorage.setItem('kadode:user-profile', JSON.stringify({ status: 'completed', values: {} }))
    localStorage.setItem('kadode:adopted-projects', JSON.stringify({ schemaVersion: 1, projects: [seededProject] }))
    localStorage.setItem(key, JSON.stringify({ schemaVersion: 1, ownerId: seededProject.ownerId, spaceId: seededProject.spaceId, state: { messages: [], entries: [seededEntry] } }))
    sessionStorage.setItem('kadode:selected-surface', 'knowledge')
  }, { seededProject: project, seededEntry: entry(evaluationView, projectId), key: scopedKey })
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
  await expect(page.getByRole('tab', { name: '市場はある？' })).toHaveAttribute('aria-selected', 'true')
})

test('does not render a stale or cross-project evidence action', async ({ page }) => {
  await seed(page, '市場はある？', 'missing-project')
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Projectを開く' })).toHaveCount(0)
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
