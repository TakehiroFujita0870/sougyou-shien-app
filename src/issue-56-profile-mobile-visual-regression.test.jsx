// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { UserProfileInterview } from './components/UserProfileInterview';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted = [];

async function mountInterview(width) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 844 });
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  const onClose = vi.fn();
  await act(async () => root.render(<UserProfileInterview repository={{ save: async (profile) => profile }} onClose={onClose} />));
  mounted.push({ container, root });
  return { container, onClose };
}

async function setTextareaValue(textarea, value) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, value);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

afterEach(async () => {
  await Promise.all(mounted.splice(0).map(({ root, container }) => act(async () => { root.unmount(); container.remove(); })));
  document.body.replaceChildren();
});

describe('Issue #56 profile mobile visual regression contract', () => {
  it.each([320, 390, 1440])('keeps dialog header and textarea shrinkable at %ipx', async (width) => {
    const { container } = await mountInterview(width);
    const dialog = container.querySelector('.kadode-dialog-panel');
    const header = dialog.querySelector('div');
    const textarea = dialog.querySelector('textarea');
    const close = dialog.querySelector('[aria-label="ヒアリングを閉じる"]');

    expect(dialog.className).toContain('min-w-0');
    expect(dialog.className).toContain('max-w-full');
    expect(dialog.className).toContain('overflow-hidden');
    expect(header.className).toContain('min-w-0');
    expect(textarea.className).toContain('min-w-0');
    expect(textarea.className).toContain('max-w-full');
    expect(close).toBeTruthy();
  });

  it('keeps Escape, Enter, and Shift+Enter behavior non-destructive at 390px', async () => {
    const { container, onClose } = await mountInterview(390);
    const textarea = container.querySelector('textarea');
    await setTextareaValue(textarea, '短い回答');

    await act(async () => textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    expect(container.textContent).toContain('2 / 6');

    await act(async () => textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true })));
    expect(container.textContent).toContain('2 / 6');

    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
