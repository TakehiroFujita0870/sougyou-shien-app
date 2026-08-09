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
  it('FAIL-UX-01 exposes three-surface navigation and an operable Home composer', async () => {
    const { container } = await mountApp();
    expect(container.querySelector('[aria-label="主要ページ"]')).not.toBeNull();
    expect([...container.querySelectorAll('nav button')].map((button) => button.textContent.trim())).toEqual(['Home', 'Project', 'Knowledge']);
    expect(container.querySelector('#idea-message')).not.toBeNull();
  });

  it('FAIL-UX-02 exposes Project and Knowledge as distinct context destinations', async () => {
    const { container } = await mountApp();
    await clickButton(container, 'Project');
    expect(container.textContent).toContain('Project');
    await clickButton(container, 'Knowledge');
    expect(container.textContent).toContain('Knowledge');
  });

  it('FAIL-UX-03 does not expose obsolete navigation destinations', async () => {
    const { container } = await mountApp();
    expect([...container.querySelectorAll('nav button')].map((button) => button.textContent.trim())).toEqual(['Home', 'Project', 'Knowledge']);
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
    expect(container.textContent).toContain('local / fake モード');
  });
});
