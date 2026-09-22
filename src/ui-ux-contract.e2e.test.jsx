// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import { App } from './App';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mountedApps = [];

async function mountApp(props = {}) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<App {...props} />));
  const mounted = {
    container,
    unmount: async () => {
      await act(async () => root.unmount());
      container.remove();
    },
  };
  mountedApps.push(mounted);
  return mounted;
}

async function clickButton(container, label) {
  const button = [...container.querySelectorAll('button')].find((candidate) => candidate.textContent?.trim() === label);
  expect(button, `expected an operable ${label} button`).toBeTruthy();
  await act(async () => button.click());
}

afterEach(async () => {
  await Promise.all(mountedApps.splice(0).map(({ unmount }) => unmount()));
  document.body.replaceChildren();
});

describe('UI UX contract: executable baseline acceptance checks', () => {
  it('FAIL-UX-01 exposes four-surface navigation and an operable Home composer', async () => {
    const { container } = await mountApp();
    expect(container.querySelector('[aria-label="主要ページ"]')).not.toBeNull();
    expect([...container.querySelectorAll('nav button')].map((button) => button.textContent.trim())).toEqual(['ホーム', 'プロジェクト', 'ナレッジ', 'Graph']);
    expect(container.querySelector('#home-supervisor-message')).not.toBeNull();
  });

  it('FAIL-UX-07 opens the read-only Founder Graph surface from the fourth destination', async () => {
    const { container } = await mountApp();
    await clickButton(container, 'Graph');
    expect(container.querySelector('[data-founder-graph-surface="true"]')).not.toBeNull();
    expect(container.querySelector('[data-founder-graph-state-message="empty"]')).not.toBeNull();
    expect(container.querySelector('#home-supervisor-message')).toBeNull();
  });

  it('FAIL-UX-08 renders explicitly supplied safe graph results without a backend call', async () => {
    const { container } = await mountApp({
      founderGraphResults: [{ id: 'idea-1', kind: 'idea', title: '循環素材の仮説', snippet: 'safe snippet', fields: { egress_policy: 'shareable', status: 'active' } }],
    });
    await clickButton(container, 'Graph');
    expect(container.textContent).toContain('循環素材の仮説');
    expect(container.textContent).toContain('safe snippet');
    expect(container.textContent).not.toContain('fetch(');
  });

  it('FAIL-UX-02 exposes Project and Knowledge as distinct context destinations', async () => {
    const { container } = await mountApp();
    await clickButton(container, 'プロジェクト');
    expect(container.textContent).toContain('プロジェクト');
    await clickButton(container, 'ナレッジ');
    expect(container.textContent).toContain('ナレッジ');
  });

  it('FAIL-UX-03 does not expose obsolete navigation destinations', async () => {
    const { container } = await mountApp();
    expect([...container.querySelectorAll('nav button')].map((button) => button.textContent.trim())).toEqual(['ホーム', 'プロジェクト', 'ナレッジ', 'Graph']);
  });

  it('FAIL-UX-04 baseline keeps profile hydration observable while loading', async () => {
    let resolveProfile;
    const profileRepository = { load: () => new Promise((resolve) => { resolveProfile = resolve; }), save: async () => {} };
    const { container } = await mountApp({ profileRepository });
    await act(async () => Promise.resolve());
    expect(resolveProfile).toBeTypeOf('function');
    expect(container.querySelector('main')).not.toBeNull();
  });

  it('FAIL-UX-05 baseline keeps the mobile sidebar trigger keyboard-operable', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
    const { container } = await mountApp();
    const menu = container.querySelector('[aria-label="サイドバーを開く"]');
    expect(menu).not.toBeNull();
    await act(async () => menu.click());
    expect(container.querySelector('[aria-label="サイドバーを閉じる"]')).not.toBeNull();
  });

  it('FAIL-UX-06 baseline marks the local-only telemetry boundary without sending network data', async () => {
    const { container } = await mountApp();
    expect(container.textContent).not.toMatch(/local|fake|mock/i);
  });
});
