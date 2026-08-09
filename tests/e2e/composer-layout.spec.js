import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1440, height: 900 } });

async function expectAnchoredGeometry(page, input) {
  const geometry = await input.evaluate((node) => {
    const composer = node.closest('form');
    const shell = document.querySelector('.workspace-shell');
    const sidebar = document.querySelector('.workspace-shell__sidebar');
    const rect = composer.getBoundingClientRect();
    const sidebarRect = sidebar.getBoundingClientRect();
    const buttons = [...composer.querySelectorAll('.kadode-composer__actions button')].map((button) => button.getBoundingClientRect());
    return {
      sidebarWidth: getComputedStyle(shell).getPropertyValue('--workspace-sidebar-width').trim(),
      leftGap: rect.left - sidebarRect.right,
      rightGap: innerWidth - rect.right,
      bottomGap: innerHeight - rect.bottom,
      overflow: rect.left < sidebarRect.right || rect.right > innerWidth,
      actionGaps: buttons.slice(1).map((button, index) => button.left - buttons[index].right),
    };
  });
  expect(geometry.sidebarWidth).toBe('168px');
  expect(Math.abs(geometry.leftGap - geometry.rightGap)).toBeLessThanOrEqual(1);
  expect(geometry.bottomGap).toBeGreaterThanOrEqual(16);
  expect(geometry.bottomGap).toBeLessThanOrEqual(24);
  expect(geometry.overflow).toBe(false);
  expect(geometry.actionGaps.every((gap) => gap >= 8)).toBe(true);
}

test('keeps Project and Knowledge composers anchored with outer-only keyboard focus', async ({ page }) => {
  await page.goto('/');
  await page.locator('nav button').nth(1).click();

  const projectInput = page.locator('#project-composer');
  await expect(projectInput).toBeVisible();
  await expect(projectInput).toHaveAttribute('placeholder', '検討したい事業案を簡単に教えてください');
  await projectInput.focus();
  const projectFocus = await projectInput.evaluate((node) => ({
    outlineWidth: getComputedStyle(node).outlineWidth,
  }));
  expect(projectFocus.outlineWidth).toBe('0px');
  await expectAnchoredGeometry(page, projectInput);
  await page.screenshot({ path: 'test-results/project-empty-composer-1440.png' });

  await projectInput.fill('地域事業の案を検討したい');
  await projectInput.press('Enter');
  await expect(page.locator('[data-message-role="user"]')).toContainText('地域事業の案を検討したい');
  await page.evaluate(() => scrollTo(0, document.body.scrollHeight));
  await expect(projectInput).toBeInViewport();
  const contentBottom = await page.locator('[role="tabpanel"]').evaluate((node) => node.getBoundingClientRect().bottom);
  const composerTop = await projectInput.evaluate((node) => node.closest('form').getBoundingClientRect().top);
  expect(contentBottom).toBeLessThanOrEqual(composerTop);
  await page.screenshot({ path: 'test-results/project-scrolled-composer-1440.png' });

  await page.setViewportSize({ width: 820, height: 900 });
  await page.evaluate(() => scrollTo(0, document.body.scrollHeight));
  await expectAnchoredGeometry(page, projectInput);
  const narrowContentBottom = await page.locator('aside[aria-labelledby="decision-history-heading"]').evaluate((node) => node.getBoundingClientRect().bottom);
  const narrowComposerTop = await projectInput.evaluate((node) => node.closest('form').getBoundingClientRect().top);
  expect(narrowContentBottom).toBeLessThanOrEqual(narrowComposerTop);
  await page.screenshot({ path: 'test-results/project-composer-820.png' });

  await page.locator('nav button').nth(2).click();
  const knowledgeInput = page.locator('#knowledge-composer');
  await expect(knowledgeInput).toHaveAttribute('placeholder', '追加したい情報はありますか？');
  await knowledgeInput.focus();
  expect(await knowledgeInput.evaluate((node) => getComputedStyle(node).outlineWidth)).toBe('0px');
  await expectAnchoredGeometry(page, knowledgeInput);
  await page.evaluate(() => scrollTo(0, document.body.scrollHeight));
  await expect(knowledgeInput).toBeInViewport();
  await page.screenshot({ path: 'test-results/knowledge-scrolled-composer-1440.png' });
});
