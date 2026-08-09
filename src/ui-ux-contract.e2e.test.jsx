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
  it('FAIL-UX-01 baseline exposes project navigation and an operable AI chat entry', async () => {
    const { container } = await mountApp();
    expect(container.querySelector('[aria-label="主要ページ"]')).not.toBeNull();
    await clickButton(container, 'AIチャット');
    expect(container.textContent).toContain('AIチャット');
  });

  it('FAIL-UX-02 baseline exposes an explicit idea-stock destination for future candidate decisions', async () => {
    const { container } = await mountApp();
    await clickButton(container, '事業のタネ');
    expect(container.querySelector('[aria-label="アイデアストック"]')).not.toBeNull();
    expect(container.textContent).toContain('まだ候補はありません');
  });

  it('FAIL-UX-03 baseline exposes the shared documents destination', async () => {
    const { container } = await mountApp();
    await clickButton(container, '資料');
    expect(container.textContent).toContain('資料');
  });

  it('FAIL-UX-04 baseline keeps profile hydration observable while loading', async () => {
    let resolveProfile;
    const profileRepository = { load: () => new Promise((resolve) => { resolveProfile = resolve; }), save: async () => {} };
    const { container } = await mountApp({ profileRepository });
    await act(async () => Promise.resolve());
    expect(resolveProfile).toBeTypeOf('function');
    expect(container.textContent).toContain('読み込めませんでした');
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
    expect(container.textContent).toContain('local / fake モード');
    expect(container.textContent).toContain('外部サービスへ送信しません');
  });
});
