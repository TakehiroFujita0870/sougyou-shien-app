import { test, expect } from '@playwright/test';

test('Storybook App stories receive the production global theme at 1440 × 900', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  const applicationTheme = await page.locator('.Dots-shell').evaluate((element) => ({
    canvas: getComputedStyle(element).getPropertyValue('--color-canvas').trim(),
    text: getComputedStyle(element).getPropertyValue('--color-text').trim(),
    font: getComputedStyle(element).fontFamily,
    background: getComputedStyle(element).backgroundColor,
  }));

  await page.goto('http://127.0.0.1:6007/iframe.html?id=dots-app--home&viewMode=story');

  await expect(page.locator('#home-supervisor-message')).toBeVisible();
  const theme = await page.locator('.Dots-shell').first().evaluate((element) => ({
    canvas: getComputedStyle(element).getPropertyValue('--color-canvas').trim(),
    text: getComputedStyle(element).getPropertyValue('--color-text').trim(),
    font: getComputedStyle(element).fontFamily,
    background: getComputedStyle(element).backgroundColor,
  }));
  expect(theme).toEqual(expect.objectContaining({ canvas: '#f8f5ed', text: '#18382f' }));
  expect(theme).toEqual(applicationTheme);
  expect(theme.font).toContain('Inter');
  expect(theme.background).not.toBe('rgba(0, 0, 0, 0)');

  for (const id of ['dots-app--project', 'dots-app--knowledge', 'dots-app--account']) {
    await page.goto(`http://127.0.0.1:6007/iframe.html?id=${id}&viewMode=story`);
    await expect(page.locator('.Dots-shell').first()).toBeVisible();
    await expect(page.locator('.workspace-shell__sidebar')).toBeVisible();
  }
});
