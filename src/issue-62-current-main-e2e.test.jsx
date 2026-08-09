// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App, SELECTED_SURFACE_STORAGE_KEY } from './App';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const completedProfile = { status: 'completed', values: { purpose: '工場の改善を考える' } };
const message = '工場の保全担当者が故障履歴を探せない';
const mounted = [];
let localValues;
let sessionValues;

function installStorage() {
  localValues = new Map([['kadode:user-profile', JSON.stringify(completedProfile)]]);
  sessionValues = new Map();
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage(localValues) });
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: storage(sessionValues) });
}

function storage(values) {
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  };
}

async function mount(width) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => { root.render(<App />); await Promise.resolve(); await Promise.resolve(); });
  const app = { container, root };
  mounted.push(app);
  return app;
}

async function click(container, label) {
  const button = [...container.querySelectorAll('button')].find((candidate) => candidate.textContent.trim() === label);
  expect(button, `expected ${label} to be operable`).toBeTruthy();
  await act(async () => { button.click(); await Promise.resolve(); await Promise.resolve(); });
}

async function sendCandidateMessage(container) {
  const input = container.querySelector('#idea-message');
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
  await act(async () => {
    setter.call(input, message);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.closest('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await Promise.resolve(); await Promise.resolve();
  });
}

beforeEach(installStorage);
afterEach(async () => {
  await Promise.all(mounted.splice(0).map(({ container, root }) => act(async () => { root.unmount(); container.remove(); })));
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

describe('Issue #62 current-main PII-free user journey contract', () => {
  it.each([1280, 390])('keeps the completed-profile Home journey usable without overflow at %ipx', async (width) => {
    const { container } = await mount(width);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector('#idea-message')).toBeTruthy();
    expect(container.querySelector('.workspace-shell__main')).toBeTruthy();
    expect(container.querySelector('nav[aria-label="主要ページ"]')).toBeTruthy();
    expect(container.querySelector('main').className).toContain('kadode-shell');
    expect(container.querySelector('[aria-label="サイドバーを開く"]')).toBeTruthy();
  });

  it('covers candidate preview and every decision outcome without network or context leakage', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const { container } = await mount(1280);

    await sendCandidateMessage(container);
    expect(container.textContent).toContain('保存前プレビュー');
    await click(container, 'アイデア候補として保存');
    expect(container.textContent).toContain('仮説カード（編集案）');

    await click(container, 'プロジェクトに採用');
    expect(container.textContent).toContain('状態: 採用');
    await click(container, '保留');
    expect(container.textContent).toContain('状態: 保留');
    await click(container, '理由付きで却下');
    expect(container.querySelector('[role="alert"]').textContent).toContain('却下理由');

    const reason = container.querySelector('#reject-reason');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(reason, '検証対象の業務課題と合わない');
      reason.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await click(container, '理由付きで却下');
    expect(container.textContent).toContain('状態: 却下');
    expect(fetchSpy).not.toHaveBeenCalled();
    expect([...sessionValues.entries()]).toEqual([[SELECTED_SURFACE_STORAGE_KEY, 'home']]);
    expect([...sessionValues.values()].join('')).not.toContain(message);
  });

  it('preserves a local candidate after F5-equivalent remount and restores selected surfaces by keyboard', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const first = await mount(390);
    await sendCandidateMessage(first.container);
    await click(first.container, 'アイデア候補として保存');

    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: '2', altKey: true, shiftKey: true, bubbles: true })));
    expect(first.container.querySelector('[aria-current="page"]').textContent).toBe('Project');
    await act(async () => first.root.unmount());
    mounted.shift().container.remove();

    const second = await mount(390);
    expect(second.container.querySelector('[aria-current="page"]').textContent).toBe('Project');
    await click(second.container, 'Home');
    expect(second.container.textContent).toContain(message);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('keeps mobile keyboard behavior and axe checks free of violations', async () => {
    const { container } = await mount(390);
    const input = container.querySelector('#idea-message');
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: '2', altKey: true, shiftKey: true, bubbles: true })));
    expect(container.querySelector('[aria-current="page"]').textContent).toBe('Project');
    await click(container, 'Home');
    await act(async () => input.dispatchEvent(new KeyboardEvent('keydown', { key: '3', altKey: true, shiftKey: true, bubbles: true })));
    expect(container.querySelector('[aria-current="page"]').textContent).toBe('Home');
    expect((await axe.run(container)).violations).toEqual([]);
  });
});
