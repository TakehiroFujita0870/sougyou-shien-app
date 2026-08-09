// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import profileFixture from './fixtures/t-ia-01-home-profile.json';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted = [];
const profileKey = 'kadode:user-profile';

function mountHome(width) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted.push({ container, root });
  return act(async () => { root.render(<App />); await Promise.resolve(); await Promise.resolve(); return container; });
}

async function typeInto(textarea, value) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, value);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

beforeEach(() => {
  const values = new Map([[profileKey, JSON.stringify(profileFixture)]]);
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  } });
});

afterEach(async () => {
  await Promise.all(mounted.splice(0).map(({ container, root }) => act(async () => { root.unmount(); container.remove(); })));
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

describe('T-IA-01 Home AI-first visual regression acceptance contract', () => {
  it.each([1280, 390])('keeps the initial canvas composer-first at %ipx', async (width) => {
    const container = await mountHome(width);
    expect(container.textContent).toContain('Kadode AI');
    expect(container.querySelector('label[for="home-supervisor-message"]')).toBeTruthy();
    expect(container.querySelector('textarea#home-supervisor-message')).toBeTruthy();
    expect(container.textContent).not.toContain('アイデアを登録する');
    expect(container.querySelector('h1')).toBeTruthy();
    expect(container.querySelector('h1[class*="text-6xl"], h1[class*="text-5xl"], h1[class*="text-4xl"]')).toBeNull();
    expect(container.querySelector('.kadode-dialog-backdrop')).toBeNull();
    expect(container.querySelector('.workspace-shell__main')).toBeTruthy();
  });

  it('exposes keyboard and screen-reader acceptance landmarks', async () => {
    const container = await mountHome(390);
    const nav = container.querySelector('nav[aria-label="主要ページ"]');
    const main = container.querySelector('main');
    const textarea = container.querySelector('textarea#home-supervisor-message');
    expect(main).toBeTruthy();
    expect(nav).toBeTruthy();
    expect(textarea.getAttribute('id')).toBe('home-supervisor-message');
    expect(container.querySelector(`label[for="home-supervisor-message"]`)).toBeTruthy();
    expect([...container.querySelectorAll('button')].every((button) => button.type === 'button' || button.type === 'submit')).toBe(true);
    expect(container.querySelector('[aria-current="page"]')).toBeTruthy();
  });

  it('survives F5-equivalent remount without context leakage or network calls', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const first = await mountHome(390);
    await typeInto(first.querySelector('#home-supervisor-message'), '検証用の工場課題');
    const firstRoot = mounted[0].root;
    await act(async () => firstRoot.unmount());
    mounted.shift().container.remove();
    const second = await mountHome(390);
    expect(second.textContent).toContain('検証用の工場課題');
    expect(second.textContent).not.toMatch(/local|fake|mock/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
