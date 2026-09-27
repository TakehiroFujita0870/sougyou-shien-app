// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { UserProfileInterview } from './components/UserProfileInterview';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted = [];

async function mountInterview() {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 720 });
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

describe('desktop profile keyboard contract', () => {
  it('keeps Escape, Enter, and Shift+Enter behavior non-destructive', async () => {
    const { container, onClose } = await mountInterview();
    const textarea = container.querySelector('textarea');
    await setTextareaValue(textarea, '短い回答');

    const enterEvent = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    await act(async () => textarea.dispatchEvent(enterEvent));
    expect(enterEvent.defaultPrevented).toBe(true);
    expect(container.textContent).toContain('2 / 6');

    const newlineEvent = new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true });
    await act(async () => container.querySelector('textarea').dispatchEvent(newlineEvent));
    expect(newlineEvent.defaultPrevented).toBe(false);
    expect(container.textContent).toContain('2 / 6');

    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
