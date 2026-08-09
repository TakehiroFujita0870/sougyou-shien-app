import { expect, test } from '@playwright/test';

test('downloads the local Project PDF only after the user requests it', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'プロジェクト', exact: true }).click();
  await expect(page.locator('#project-surface-heading')).toBeVisible();
  await page.locator('#project-surface-heading').locator('..').getByRole('button').click();
  await expect(page.locator('#project-surface-heading')).toBeVisible();

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
