import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('kadode:user-profile', JSON.stringify({
      status: 'completed',
      values: { experience: '', strengths: '', interests: '', time: '', budget: '', avoidances: '' },
    }));
  });
});

async function adoptProject(page) {
  await page.goto('/');
  const composer = page.locator('#home-supervisor-message');
  await composer.fill('工場の保全担当者が故障履歴を探せず困っています');
  await composer.press('Enter');
  await page.getByRole('button', { name: 'プロジェクトに採用' }).click();
  await expect(page.locator('#project-surface-heading')).toBeVisible();
}

test('downloads the local Project PDF only after the user requests it', async ({ page }) => {
  await adoptProject(page);

  const download = page.waitForEvent('download');
  await page.locator('button').evaluateAll((buttons) => {
    const button = buttons.find(({ textContent }) => textContent?.startsWith('PDF'));
    if (!button) throw new Error('PDF export button is missing');
    button.click();
  });
  const file = await download;
  expect(file.suggestedFilename()).toBe('kadode-business-plan.pdf');
  expect(await file.createReadStream()).toBeTruthy();
});

test('downloads the local Project DOCX only after its lazy generator is ready', async ({ page }) => {
  await adoptProject(page);

  const download = page.waitForEvent('download');
  await page.locator('button').evaluateAll((buttons) => {
    const button = buttons.find(({ textContent }) => textContent?.startsWith('DOCX'));
    if (!button) throw new Error('DOCX export button is missing');
    button.click();
  });
  const file = await download;
  expect(file.suggestedFilename()).toBe('kadode-business-plan.docx');
  const stream = await file.createReadStream();
  expect(stream).toBeTruthy();
});
