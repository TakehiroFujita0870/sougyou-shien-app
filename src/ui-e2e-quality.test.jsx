// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { PROFILE_STEPS } from './components/UserProfileInterview';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const setValue = (element, value) => {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
  setter.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
};

async function settle() {
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

async function mountApp(width, { reset = true } = {}) {
  window.innerWidth = width;
  if (reset) localStorage.clear();
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<App />));
  await settle();
  return { container, root };
}

async function completeProfile(container) {
  for (const [index] of PROFILE_STEPS.entries()) {
    const textarea = container.querySelector('textarea[aria-labelledby="profile-question"]');
    setValue(textarea, `回答${index + 1}`);
    await act(async () => { textarea.form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await Promise.resolve(); });
    await settle();
  }
}

async function runHappyPath(width) {
  const { container, root } = await mountApp(width);
  expect(container.querySelector('[role="dialog"]')).toBeTruthy();
  await completeProfile(container);
  expect(container.querySelector('[role="dialog"]')).toBeNull();

  const message = '工場の保全担当者が故障履歴を探せない';
  const input = container.querySelector('#idea-message');
  setValue(input, message);
  await act(async () => { input.form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await Promise.resolve(); });
  await settle();
  expect(container.textContent).toContain(message);
  const saveButton = [...container.querySelectorAll('button')].find((button) => button.textContent === 'アイデア候補として保存');
  expect(saveButton).toBeTruthy();
  await act(async () => { saveButton.click(); await Promise.resolve(); });
  await settle();
  expect(container.textContent).toContain('仮説カード（編集案）');

  await act(async () => root.unmount());
  container.remove();
  const reloaded = await mountApp(width, { reset: false });
  await settle();
  expect(reloaded.container.textContent).toContain(message.slice(0, 40));
  await act(async () => reloaded.root.unmount());
  reloaded.container.remove();
}

describe('UI E2E quality loop', () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it.each([1280, 390])('completes profile, local AI conversation, candidate save, and reload at %ipx without network', async (width) => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    await runHappyPath(width);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
