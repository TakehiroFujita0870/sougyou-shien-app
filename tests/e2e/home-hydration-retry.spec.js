import { expect, test } from '@playwright/test';

test('keeps a local draft through repeated Home hydration failures and recovery', async ({ page }) => {
  await page.goto('http://127.0.0.1:6007/iframe.html?id=dots-homesupervisor--retryable-hydration-error&viewMode=story');
  const composer = page.locator('#home-supervisor-message');
  const alert = page.getByRole('alert');
  await expect(alert).toContainText('会話を読み込めませんでした');
  await expect(composer).toBeEnabled();
  await composer.fill('再試行で失わない下書き');

  await page.getByRole('button', { name: '再試行' }).click();
  await expect(alert).toContainText('会話を読み込めませんでした');
  await expect(composer).toHaveValue('再試行で失わない下書き');
  await page.screenshot({ path: 'test-results/home-hydration-retry-error-1440x900.png', fullPage: false });

  await page.getByRole('button', { name: '再試行' }).click();
  await expect(composer).toBeDisabled();
  await expect(composer.locator('xpath=ancestor::form')).toHaveAttribute('aria-busy', 'true');
  await expect(alert).toHaveCount(0);
  await expect(composer).toBeEnabled();
  await expect(composer).toHaveValue('再試行で失わない下書き');
  await page.screenshot({ path: 'test-results/home-hydration-retry-1440x900.png', fullPage: false });
});
