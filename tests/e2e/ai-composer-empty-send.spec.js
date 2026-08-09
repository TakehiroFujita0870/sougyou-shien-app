import { test, expect } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('kadode:user-profile', JSON.stringify({ status: 'completed', values: { experience: 'manufacturing', strengths: 'operations', interests: 'AI', time: '4 hours', budget: '100000', avoidances: 'high risk' } })))
})

async function composerControls(page, id) {
  const input = page.locator(id)
  const form = input.locator('xpath=ancestor::form')
  return { input, send: form.locator('button[type="submit"]'), model: form.locator('button[aria-label^="モデル:"]') }
}

test('disables trim-empty sends consistently across Home, Project, and Knowledge', async ({ page }) => {
  await page.goto('/')
  const home = await composerControls(page, '#home-supervisor-message')
  await expect(home.send).toBeDisabled(); await expect(home.model).toBeEnabled()
  await home.input.fill('   '); await expect(home.send).toBeDisabled()
  await home.input.fill('Homeの相談'); await expect(home.send).toBeEnabled()
  await home.input.press('Shift+Enter'); await expect(home.input).toHaveValue('Homeの相談\n')
  await home.input.press('Enter'); await expect(home.input).toHaveValue(''); await expect(home.send).toBeDisabled()

  await page.getByRole('button', { name: 'プロジェクト', exact: true }).click()
  const project = await composerControls(page, '#project-composer')
  await expect(project.send).toBeDisabled(); await expect(project.model).toBeEnabled()
  await project.input.fill('Projectの相談'); await expect(project.send).toBeEnabled()
  await project.input.press('Enter'); await expect(project.input).toHaveValue(''); await expect(project.send).toBeDisabled()

  await page.getByRole('button', { name: 'ナレッジ', exact: true }).click()
  const knowledge = await composerControls(page, '#knowledge-composer')
  await expect(knowledge.send).toBeDisabled(); await expect(knowledge.model).toBeEnabled()
  await knowledge.input.fill('Knowledgeの相談'); await expect(knowledge.send).toBeEnabled()
  await knowledge.input.press('Enter')
  await page.getByRole('button', { name: 'ナレッジに追加' }).click()
  await expect(knowledge.input).toHaveValue(''); await expect(knowledge.send).toBeDisabled()
  await expect(knowledge.model).toBeEnabled()
  await page.screenshot({ path: 'test-results/ai-composer-empty-send-1440x900.png', fullPage: false })
})
