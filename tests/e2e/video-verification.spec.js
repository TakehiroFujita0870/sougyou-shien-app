import { test, expect } from '@playwright/test'

const completedProfile = {
  status: 'completed',
  values: {
    experience: '製造業の改善活動を担当しています。',
    strengths: '現場の聞き取りと小さな実験です。',
    interests: '地域の学びと親子支援です。',
    time: '週末に4時間です。',
    budget: 'まずは5万円以内です。',
    avoidances: '在庫と大きな先行投資は避けます。',
  },
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript((profile) => {
    if (!localStorage.getItem('kadode:user-profile')) {
      localStorage.setItem('kadode:user-profile', JSON.stringify(profile))
    }
  }, completedProfile)
})

test('records the desktop PII-free Home, Project, and Knowledge happy path', async ({ page }) => {
  const applicationRequests = []
  page.on('request', (request) => {
    if (['fetch', 'xhr'].includes(request.resourceType())) applicationRequests.push(request.url())
  })

  await page.goto('/')
  await expect(page.getByRole('dialog', { name: 'あなたの情報' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Kadode AI' })).toBeVisible()

  const account = page.getByRole('button', { name: 'タケヒロのアカウント Free' })
  await account.click()
  await expect(page.getByRole('menu', { name: 'タケヒロのアカウント Free' })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: 'プロフィールを編集' })).toBeVisible()
  await page.keyboard.press('Escape')

  const modelTrigger = page.locator('#home-supervisor-message').locator('..').locator('..').getByRole('button', { name: /モデル:/ })
  const modelMenuName = await modelTrigger.getAttribute('aria-label')
  await modelTrigger.click()
  await expect(page.getByRole('menu', { name: modelMenuName })).toBeVisible()
  await page.getByRole('menuitem', { name: /GPT-5.6 Terra/ }).click()

  const composer = page.locator('#home-supervisor-message')
  await composer.fill('工場の保全担当者が故障履歴を探せず、確認に時間がかかっています。')
  await composer.press('Enter')
  await expect(page.getByLabel('会話履歴')).toContainText('故障履歴')
  await expect(page.getByText('推論:', { exact: true })).toBeVisible()

  await page.reload()
  await expect(page.getByLabel('会話履歴')).toContainText('故障履歴')
  await expect(page.getByRole('button', { name: 'プロジェクトに採用' })).toBeVisible()
  await page.getByRole('button', { name: 'プロジェクトに採用' }).click()

  await expect(page.locator('#project-surface-heading')).toBeVisible()
  await expect(page.locator('[data-project-question]')).toHaveCount(5)
  await page.reload()
  await expect(page.getByRole('button', { name: 'プロジェクト', exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(page.locator('#project-surface-heading')).toBeVisible()
  await expect(page.locator('[data-project-question]')).toHaveCount(5)

  const projectMessage = '最初に確かめる顧客候補を3つに絞りたい'
  const projectComposer = page.getByRole('textbox', { name: 'このプロジェクトについて Kadode AI に尋ねる' })
  const projectModelTrigger = page.getByRole('form', { name: 'Project Kadode AI composer' }).getByRole('button', { name: /モデル:/ })
  const projectModelMenuName = await projectModelTrigger.getAttribute('aria-label')
  await projectModelTrigger.click()
  await expect(page.getByRole('menu', { name: projectModelMenuName })).toBeVisible()
  await page.keyboard.press('Escape')
  await projectComposer.fill(projectMessage)
  await projectComposer.press('Enter')
  const projectConversation = page.getByRole('list', { name: 'Project conversation' })
  await expect(projectConversation).toContainText(projectMessage)
  await expect(projectConversation).toContainText('顧客・根拠・次に確かめることの順で整理していきましょう。')
  await page.reload()
  await expect(page.getByRole('button', { name: 'プロジェクト', exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('list', { name: 'Project conversation' })).toContainText(projectMessage)
  await expect(page.getByRole('list', { name: 'Project conversation' })).toContainText('顧客・根拠・次に確かめることの順で整理していきましょう。')

  await page.getByRole('button', { name: 'ナレッジ', exact: true }).click()
  await expect(page.locator('#knowledge-heading')).toBeVisible()
  const knowledgeComposer = page.getByRole('textbox', { name: 'KnowledgeについてKadode AIに相談' })
  await expect(knowledgeComposer).toBeVisible()
  const knowledgeModelTrigger = knowledgeComposer.locator('..').locator('..').getByRole('button', { name: /モデル:/ })
  const knowledgeModelMenuName = await knowledgeModelTrigger.getAttribute('aria-label')
  await knowledgeModelTrigger.click()
  await expect(page.getByRole('menu', { name: knowledgeModelMenuName })).toBeVisible()
  await page.keyboard.press('Escape')
  const knowledgeMessage = 'この資料から先に確認する根拠を教えてください'
  await knowledgeComposer.fill(knowledgeMessage)
  await knowledgeComposer.press('Enter')
  const knowledgeConversation = page.getByRole('list', { name: 'Knowledgeの会話履歴' })
  await expect(knowledgeConversation).toContainText(knowledgeMessage)
  await expect(knowledgeConversation).toContainText('根拠')

  const localFile = page.locator('#knowledge-file-picker')
  await localFile.setInputFiles({ name: '現場ヒアリング.pdf', mimeType: 'application/pdf', buffer: Buffer.from('local-only demo') })
  const uploadedAsset = page.getByRole('heading', { name: '現場ヒアリング.pdf' })
  await expect(uploadedAsset).toBeVisible()
  await expect(page.getByText('本文は未保存')).toBeVisible()

  const knowledgeAsset = page.getByRole('heading', { name: '顧客ヒアリング要約' })
  await expect(knowledgeAsset).toBeVisible()
  await knowledgeAsset.locator('xpath=../../..').getByRole('button', { name: '削除', exact: true }).click()
  const deleteDialog = page.getByRole('dialog', { name: 'この資料を削除しますか？' })
  await expect(deleteDialog).toBeVisible()
  await deleteDialog.getByRole('button', { name: '削除を確定' }).click()
  await expect(knowledgeAsset).toHaveCount(0)
  await expect(page.getByRole('button', { name: '資料を追加' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: 'ナレッジ', exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(knowledgeAsset).toHaveCount(0)
  await expect(uploadedAsset).toBeVisible()
  await expect(page.getByRole('list', { name: 'Knowledgeの会話履歴' })).toContainText(knowledgeMessage)
  expect(applicationRequests).toEqual([])
})
