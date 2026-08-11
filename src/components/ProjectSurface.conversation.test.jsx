// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { completeProjectDraft, ProjectSurface } from './ProjectSurface';
import { demoProjectFixture } from './projectDemoFixtureAdapter';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root;
let container;

function deferred() {
  let resolve; let reject;
  const promise = new Promise((next, fail) => { resolve = next; reject = fail; });
  return { promise, reject, resolve };
}

async function mount(props) {
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () => { root.render(<ProjectSurface project={demoProjectFixture} {...props} />); });
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
    expect(container.textContent).toContain('AIで補完');
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

  it('preserves the draft through repeated hydration failures and ignores a stale retry result', async () => {
    const stale = deferred();
    const repository = {
      load: vi.fn(async () => { throw new Error('offline'); }),
      retryLoad: vi.fn().mockRejectedValueOnce(new Error('still offline')).mockImplementationOnce(() => stale.promise),
      save: vi.fn(async (messages) => messages),
    };
    await mount({ conversationRepository: repository });
    await act(async () => Promise.resolve());
    const input = container.querySelector('#project-composer');
    expect(input.disabled).toBe(false);
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { setValue.call(input, '再試行しても残す下書き'); input.dispatchEvent(new Event('input', { bubbles: true })); });
    const retry = () => [...container.querySelectorAll('button')].find((button) => button.textContent === '会話を再試行');
    await act(async () => { retry().click(); await Promise.resolve(); });
    expect(input.value).toBe('再試行しても残す下書き');
    await act(async () => { retry().click(); await Promise.resolve(); });
    expect(input.disabled).toBe(true);
    const freshRepository = { load: async () => [{ id: 'fresh', role: 'assistant', content: '復元した会話' }], save: async (messages) => messages };
    await act(async () => { root.render(<ProjectSurface project={demoProjectFixture} conversationRepository={freshRepository} />); await Promise.resolve(); });
    expect(container.textContent).toContain('復元した会話');
    expect(input.disabled).toBe(false);
    await act(async () => { stale.resolve([{ id: 'stale', role: 'assistant', content: '古い結果' }]); await stale.promise; });
    expect(container.textContent).not.toContain('古い結果');
    expect(input.value).toBe('再試行しても残す下書き');
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

  it('never rolls the optimistic reference back when an intermediate queued save resolves', async () => {
    const first = deferred(); const second = deferred(); let calls = 0;
    const save = vi.fn((messages) => { calls += 1; if (calls === 1) return first.promise; if (calls === 2) return second.promise; return Promise.resolve(messages); });
    await mount({ conversationRepository: { load: async () => [], save } });
    await act(async () => { await Promise.resolve(); });
    await enter('最初の質問');
    await enter('二つ目の質問');
    const firstSnapshot = save.mock.calls[0][0];
    await act(async () => { first.resolve(firstSnapshot); await first.promise; await Promise.resolve(); });
    expect(save).toHaveBeenCalledTimes(2);
    await enter('三つ目の質問');
    const secondSnapshot = save.mock.calls[1][0];
    await act(async () => { second.resolve(secondSnapshot); await second.promise; await Promise.resolve(); await Promise.resolve(); });
    expect(save).toHaveBeenCalledTimes(3);
    expect(save.mock.calls.map(([messages]) => messages.length)).toEqual([2, 4, 6]);
    expect(save.mock.calls[2][0]).toHaveLength(6);
    expect(container.querySelectorAll('[data-message-role]')).toHaveLength(6);
  });

  it('continues from the optimistic conversation after a save rejection', async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error('offline')).mockImplementation(async (messages) => messages);
    await mount({ conversationRepository: { load: async () => [], save } });
    await act(async () => { await Promise.resolve(); });
    await enter('保存に失敗する質問');
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(container.getAttribute('aria-busy')).not.toBe('true');
    expect(container.querySelector('[role="alert"]').textContent).toContain('会話を保存できませんでした');
    await enter('失敗後の質問');
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(save.mock.calls[1][0]).toHaveLength(4);
    expect(container.querySelectorAll('[data-message-role]')).toHaveLength(4);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
});
