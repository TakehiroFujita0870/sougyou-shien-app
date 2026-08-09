// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App, SELECTED_SURFACE_STORAGE_KEY } from './App';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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
};
const message = '工場の保全担当者が故障履歴を探せず、確認に時間がかかっています。';
const mounted = [];
let localValues;
let sessionValues;

function storage(values) {
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  };
}

function installStorage() {
  localValues = new Map([['kadode:user-profile', JSON.stringify(completedProfile)]]);
  sessionValues = new Map();
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage(localValues) });
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: storage(sessionValues) });
}

async function mount() {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
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

async function sendMessage(container) {
  const input = container.querySelector('#home-supervisor-message');
  expect(input).toBeTruthy();
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

describe('Issue #62 desktop current-main PII-free user journey', () => {
  it('keeps a completed profile on the desktop Home conversation surface', async () => {
    const { container, root } = await mount();
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector('#home-supervisor-message')).toBeTruthy();
    expect(container.querySelector('.workspace-shell__main')).toBeTruthy();
    expect(container.querySelector('nav[aria-label="主要ページ"]')).toBeTruthy();
    expect(container.querySelector('[aria-label="タケヒロのアカウント Free"]')).toBeTruthy();
    expect(container.querySelector('[aria-label^="モデル:"]')).toBeTruthy();
  });

  it('creates an explicit proposal, adopts it, and restores the five-view Project after an F5-equivalent remount without network', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const { container, root } = await mount();

    await sendMessage(container);
    expect(container.querySelector('[aria-label="会話履歴"]')?.textContent).toContain('故障履歴');
    await click(container, 'プロジェクトに採用');
    expect(container.querySelector('#project-surface-heading')).toBeTruthy();
    expect(container.querySelectorAll('[data-project-question]')).toHaveLength(5);
    await act(async () => { root.unmount(); container.remove(); });
    mounted.shift();
    const restored = await mount();
    expect(restored.container.querySelector('[aria-current="page"]')?.textContent).toBe('Project');
    expect(restored.container.querySelector('#project-surface-heading')).toBeTruthy();
    expect(restored.container.querySelectorAll('[data-project-question]')).toHaveLength(5);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('restores the conversation after an F5-equivalent remount and does not place message text in session storage', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const first = await mount();
    await sendMessage(first.container);
    await act(async () => { first.root.unmount(); first.container.remove(); });
    mounted.shift();

    const second = await mount();
    expect(second.container.querySelector('[aria-label="会話履歴"]')?.textContent).toContain('故障履歴');
    expect([...sessionValues.entries()]).toEqual([[SELECTED_SURFACE_STORAGE_KEY, 'home']]);
    expect([...sessionValues.values()].join('')).not.toContain(message);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('opens Knowledge from the same desktop journey with no axe violations', async () => {
    const { container } = await mount();
    await click(container, 'Knowledge');
    expect(container.querySelector('#knowledge-heading')).toBeTruthy();
    expect(container.querySelector('#knowledge-composer')).toBeTruthy();
    expect((await axe.run(container)).violations).toEqual([]);
  });
});
