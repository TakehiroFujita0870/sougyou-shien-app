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

describe('UI UX contract: intentionally failing acceptance scenarios', () => {
  it('FAIL-UX-01: portfolio steward is available from every page while each conversation stays project-scoped', async () => {
    const { container } = await mountApp();

    await clickButton(container, '資料');

    expect(container.querySelector('[aria-label="portfolio steward"]')).not.toBeNull();
    expect(container.textContent).toContain('対象プロジェクト');
  });

  it('FAIL-UX-02: conversation preview supports adopt, reasoned reject, and non-forced hold; rejection suppresses unchanged re-proposals', async () => {
    const { container } = await mountApp();

    await clickButton(container, '事業のタネ');

    expect(container.textContent).toContain('プロジェクトに採用して深掘り');
    expect(container.querySelector('[aria-label="却下理由"]')).not.toBeNull();
    expect(container.querySelector('[data-candidate-decision="hold"]')).not.toBeNull();
  });

  it('FAIL-UX-03: same-user-space knowledge is always available and approved attachments are reusable in another page and project', async () => {
    const { container } = await mountApp();

    await clickButton(container, '資料');

    expect(container.querySelector('[data-space-library="always-on"]')).not.toBeNull();
    expect(container.textContent).toContain('別のプロジェクトで参照');
  });

  it('FAIL-UX-04: slow hydration keeps saved profile, conversation, preview, and library state through F5', async () => {
    let resolveProfile;
    const profileRepository = { load: () => new Promise((resolve) => { resolveProfile = resolve; }), save: async () => {} };
    const { container } = await mountApp({ profileRepository });

    await act(async () => Promise.resolve());

    expect(resolveProfile).toBeTypeOf('function');
    const restorationStatus = container.querySelector('[role="status"]');
    expect(restorationStatus).not.toBeNull();
    expect(restorationStatus.textContent).toContain('保存済みの会話、芽、資料を復元しています');
  });

  it('FAIL-UX-05: the full path is operable at 1280px and 390px with keyboard and screen reader semantics', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
    const { container } = await mountApp();
    const menu = container.querySelector('[aria-label="サイドバーを開く"]');

    await act(async () => menu.click());
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));

    expect(document.activeElement).toBe(menu);
    expect(container.querySelector('[aria-label="サイドバーを閉じる"]')).toBeNull();
  });

  it('FAIL-UX-06: giant hero, separate IdeaForm, and local-fake warning do not block the primary path; telemetry stays PII-free', async () => {
    const { container } = await mountApp();

    await clickButton(container, '事業のタネ');

    expect(container.textContent).not.toContain('local / fake モード');
    expect(container.textContent).not.toContain('アイデアを登録する');
    expect(container.querySelector('[data-telemetry-boundary="pii-free"]')).not.toBeNull();
  });
});
