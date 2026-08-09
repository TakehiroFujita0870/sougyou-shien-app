// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { completeProjectDraft, ProjectSurface } from './ProjectSurface';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root;
let container;

function deferred() {
  let resolve;
  const promise = new Promise((next) => { resolve = next; });
  return { promise, resolve };
}

async function mount(props) {
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () => { root.render(<ProjectSurface {...props} />); });
}

async function enter(value) {
  const input = container.querySelector('#project-composer');
  const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
  await act(async () => {
    setValue.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  });
}

afterEach(() => {
  if (root) act(() => root.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

describe('ProjectSurface conversation parity', () => {
  it('uses the shared catalog with GPT-5.6 Terra by default and exposes deterministic draft completion', async () => {
    await mount({ conversationRepository: { load: async () => [], save: async (messages) => messages } });
    expect(container.querySelector('[aria-label="モデル: GPT-5.6 Terra"]')).toBeTruthy();
    expect(container.textContent).toContain('AI補完');
    expect(completeProjectDraft('採算を知りたい')).toContain('顧客、根拠、次に確かめること');
  });

  it('keeps the composer unavailable through late hydration, then restores the loaded conversation', async () => {
    const pending = deferred();
    await mount({ conversationRepository: { load: () => pending.promise, save: async (messages) => messages } });
    expect(container.querySelector('#project-composer').disabled).toBe(true);
    await act(async () => { pending.resolve([{ id: 'old', role: 'assistant', content: '以前の会話' }]); await pending.promise; });
    expect(container.querySelector('#project-composer').disabled).toBe(false);
    expect(container.textContent).toContain('以前の会話');
  });

  it('serializes rapid Enter sends so every message pair is persisted', async () => {
    let saved = [];
    const save = vi.fn(async (messages) => { await Promise.resolve(); saved = messages; return messages; });
    await mount({ conversationRepository: { load: async () => [], save } });
    await act(async () => { await Promise.resolve(); });
    await enter('最初の確認');
    await enter('次の確認');
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
    expect(save).toHaveBeenCalledTimes(2);
    expect(saved).toHaveLength(4);
    expect(saved.map((message) => message.content).join(' ')).toContain('最初の確認');
    expect(saved.map((message) => message.content).join(' ')).toContain('次の確認');
    expect(container.querySelectorAll('[data-message-role]').length).toBe(4);
  });
});
