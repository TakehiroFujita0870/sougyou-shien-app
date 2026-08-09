// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';

import { App } from '../App';
import { PlanSelection } from './PlanSelection';
import { createLocalPlanRepository, PLAN_STORAGE_KEY } from './planSubscriptionRepository';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

async function mount(component) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(component));
  return { container, unmount: () => act(() => { root.unmount(); container.remove(); }) };
}

function click(element) {
  return act(() => element.dispatchEvent(new MouseEvent('click', { bubbles: true })));
}

function menuItem(label) {
  return [...document.querySelectorAll('[role="menuitem"]')].find((item) => item.textContent === label);
}

async function openAccount(container) {
  const trigger = container.querySelector('.workspace-shell__account-copy > button');
  await act(() => trigger.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0 })));
}

describe('local/fake plan subscription repository', () => {
  it('starts deterministically and normalizes an invalid Standard choice when returning to Free', () => {
    const repository = createLocalPlanRepository();

    expect(repository.getSubscription()).toMatchObject({ plan: 'free', modelKey: 'claude-haiku-4-5', reasoningMode: null });

    repository.applyPlan('standard', { modelKey: 'gpt-5.6-terra', reasoningMode: 'high' });
    expect(repository.applyPlan('free')).toMatchObject({ plan: 'free', modelKey: 'claude-haiku-4-5', reasoningMode: null });
  });

  it('persists and hydrates a normalized Standard model selection once', async () => {
    const values = new Map();
    const storage = { getItem: vi.fn((key) => values.get(key) ?? null), setItem: vi.fn((key, value) => values.set(key, value)) };
    const first = createLocalPlanRepository({}, storage);
    const selection = { plan: 'standard', modelKey: 'gpt-5.6-terra', reasoningMode: 'low' };

    await expect(first.save(selection)).resolves.toMatchObject({ error: '' });
    const second = createLocalPlanRepository({}, storage);
    await expect(second.load()).resolves.toMatchObject(selection);
    await second.load();
    expect(storage.getItem).toHaveBeenCalledTimes(1);
    expect(storage.setItem).toHaveBeenCalledWith(PLAN_STORAGE_KEY, expect.any(String));
  });

  it('normalizes corrupt and disallowed storage without escaping the boundary', async () => {
    const storage = { getItem: vi.fn(() => '{broken'), setItem: vi.fn() };
    const repository = createLocalPlanRepository({}, storage);
    await expect(repository.load()).resolves.toEqual(repository.getSubscription());

    const disallowed = createLocalPlanRepository({}, { getItem: () => JSON.stringify({ plan: 'standard', modelKey: 'unknown', reasoningMode: 'unsafe' }) });
    const normalized = await disallowed.load();
    expect(normalized.plan).toBe('standard');
    expect(normalized.modelKey).not.toBe('unknown');
    expect(normalized.reasoningMode).not.toBe('unsafe');
  });

  it('keeps the current state when storage write fails', async () => {
    const before = createLocalPlanRepository({}, { setItem: () => { throw new Error('offline'); } }).getSubscription();
    const repository = createLocalPlanRepository({}, { setItem: () => { throw new Error('offline'); } });
    await expect(repository.save({ plan: 'standard', modelKey: 'gpt-5.6-terra', reasoningMode: 'low' })).resolves.toMatchObject({ error: expect.any(String), subscription: before });
  });
});

describe('plan selection acceptance', () => {
  it('has no axe violations in the settings plan chooser', async () => {
    const { container, unmount } = await mount(<App />);

    await openAccount(container);
    await click(menuItem('設定'));
    const results = await axe.run(container);
    expect(results.violations).toEqual([]);
    await unmount();
  });

  it('compares Free and Standard, shows readable Pro content, and requires confirmation before applying a proposed change', async () => {
    const { container, unmount } = await mount(<App />);

    await openAccount(container);
    await click(menuItem('設定'));
    expect(container.textContent).toContain('アイデア整理');
    expect(container.textContent).toContain('小さな調査枠');
    expect(container.textContent).toContain('月額980円');
    expect(container.textContent).toContain('事業検討の拡張機能');
    const proCard = container.querySelector('[aria-labelledby="pro-plan-heading"]');
    expect(proCard.textContent).toContain('Pro');
    expect(proCard.textContent).toContain('2,980');
    expect(proCard.textContent).toContain('準備中');
    expect(proCard.textContent).toContain('提供開始に向けて準備中です。');
    expect(proCard.getAttribute('aria-describedby')).toBe('pro-plan-availability');
    const comparisonGrid = container.querySelector('fieldset');
    expect(comparisonGrid.className).toContain('sm:grid-cols-3');
    expect(comparisonGrid.contains(proCard)).toBe(true);
    expect([...comparisonGrid.children].filter((child) => child.tagName === 'LABEL' || child.tagName === 'ASIDE')).toHaveLength(3);
    const proButton = proCard.querySelector('button');
    expect(proCard.querySelectorAll('button')).toHaveLength(1);
    expect(proButton.disabled).toBe(true);
    expect(proButton.getAttribute('aria-describedby')).toBe('pro-plan-availability');
    expect(container.textContent).not.toContain('local / fake');
    expect(container.textContent).not.toContain('AIモデルを選ぶ');

    const standard = container.querySelector('input[value="standard"]');
    await click(standard);
    expect(container.textContent).toContain('変更内容を確認');
    expect(container.textContent).toContain('現在のプラン: Free');

    await click([...container.querySelectorAll('button')].find((button) => button.textContent === '変更を適用'));
    expect(container.textContent).toContain('現在のプラン: Standard');
    await unmount();
  });

  it('does not apply a plan or emit a request when the disabled Pro control is activated', async () => {
    const onApplyPlan = vi.fn();
    const { container, unmount } = await mount(<PlanSelection currentPlan="free" onApplyPlan={onApplyPlan} />);
    const proButton = container.querySelector('button[disabled]');

    await click(proButton);

    expect(proButton.disabled).toBe(true);
    expect(onApplyPlan).not.toHaveBeenCalled();
    await unmount();
  });

  it('supports keyboard plan confirmation without exposing model controls', async () => {
    const { container, unmount } = await mount(<App />);
    await openAccount(container);
    await click(menuItem('設定'));

    const selectedPlan = container.querySelector('input[name="plan"]:checked')?.value;
    const targetPlan = container.querySelector(`input[value="${selectedPlan === 'standard' ? 'free' : 'standard'}"]`);
    targetPlan.focus();
    expect(document.activeElement).toBe(targetPlan);
    await act(async () => {
      targetPlan.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      await Promise.resolve();
    });
    await click([...container.querySelectorAll('button')].find((button) => button.textContent === '変更を適用'));

    expect(container.querySelector('#model')).toBeNull();
    expect(container.querySelector('#reasoning-effort')).toBeNull();
    await unmount();
  });
});
