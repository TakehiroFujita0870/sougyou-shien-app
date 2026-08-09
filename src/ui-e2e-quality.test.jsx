// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted = [];
const completedProfile = JSON.stringify({ status: 'completed', values: {} });

function installStorage() {
  const values = new Map([['kadode:user-profile', completedProfile]]);
  const session = new Map();
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  } });
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: {
    getItem: (key) => session.get(key) ?? null,
    setItem: (key, value) => session.set(key, String(value)),
    removeItem: (key) => session.delete(key),
    clear: () => session.clear(),
  } });
}

async function mountApp(width) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => { root.render(<App />); await Promise.resolve(); await Promise.resolve(); });
  mounted.push({ container, root });
  return { container, root };
}

beforeEach(installStorage);
afterEach(async () => {
  await Promise.all(mounted.splice(0).map(({ container, root }) => act(async () => { root.unmount(); container.remove(); })));
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

describe('UI E2E quality loop: Home / Project / Knowledge', () => {
  it.each([1280, 390])('keeps Home AI composer as the only input entry at %ipx', async (width) => {
    const { container } = await mountApp(width);
    expect(container.querySelector('nav[aria-label="主要ページ"]')).toBeTruthy();
    expect(container.querySelector('#home-composer')).toBeTruthy();
    expect(container.querySelectorAll('textarea')).toHaveLength(1);
    expect(container.querySelector('#idea-message')).toBeNull();
    expect(container.textContent).not.toContain('アイデア候補として保存');
    expect(container.textContent).not.toContain('アイデアを登録する');
  });

  it('keeps surface context and selected surface after an F5-equivalent remount without network', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const first = await mountApp(390);
    const project = [...first.container.querySelectorAll('nav button')].find((button) => button.textContent.trim() === 'Project');
    await act(async () => project.click());
    expect(first.container.querySelector('[aria-current="page"]').textContent).toBe('Project');
    await act(async () => first.root.unmount());
    mounted.shift().container.remove();
    const second = await mountApp(390);
    expect(second.container.querySelector('[aria-current="page"]').textContent).toBe('Project');
    expect(second.container.textContent).toContain('プロジェクト');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('exposes composer semantics without legacy candidate decision workflow', async () => {
    const { container } = await mountApp(1280);
    const composer = container.querySelector('#home-composer');
    expect(composer.getAttribute('aria-describedby')).toBe('home-composer-hint');
    expect(container.querySelector('label[for="home-composer"]')).toBeTruthy();
    expect(container.textContent).toContain('Enterで送信、Shift+Enterで改行');
    expect(container.querySelector('[data-testid="assist-request"]')).toBeNull();
    expect(container.querySelector('[data-testid="assist-adopt"]')).toBeNull();
  });
});
