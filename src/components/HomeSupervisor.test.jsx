// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { HomeSupervisor, proposeHomeAction } from './HomeSupervisor';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe('Home supervisor', () => {
  it('keeps the empty desktop canvas as one compact greeting and wide composer cluster', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    await act(async () => root.render(<HomeSupervisor repository={{ load: async () => ({ messages: [], proposals: [], input: '' }), save: async (value) => value }} />)); await act(async () => {});
    const surface = container.querySelector('[data-home-state="empty"]'); const form = container.querySelector('form');
    expect(surface).toBeTruthy(); expect(surface.className).toContain('justify-center'); expect(form.className).toContain('max-w-[840px]'); expect(container.querySelector('#home-supervisor-message').className).toContain('min-h-36');
    await act(() => root.unmount()); container.remove();
  });
  it('starts with an empty large writing area and only inserts prompt text after an explicit click', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    const repository = { load: async () => ({ messages: [], proposals: [], input: '古い下書きは表示しない' }), save: async (value) => value };
    await act(async () => root.render(<HomeSupervisor repository={repository} />)); await act(async () => {});
    const input = container.querySelector('#home-supervisor-message');
    expect(input.value).toBe('');
    expect(input.placeholder).toBe('誰の、どんな困りごとを解決したいか、思いつくことを何でも教えてください。');
    expect(input.className).toContain('min-h-36');
    expect(container.textContent).toContain('アイディエーションからプロジェクト管理まで、あらゆる相談役');
    expect(container.textContent).not.toContain('AI補完');
    const mic = container.querySelector('[aria-label="音声入力（準備中）"]');
    expect(mic.disabled).toBe(true);
    const prompt = container.querySelector('[aria-label="会話のきっかけ"] button');
    await act(async () => prompt.click());
    expect(input.value).toBe(prompt.textContent);
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { setter.call(input, '自分の言葉で入力する'); input.dispatchEvent(new Event('input', { bubbles: true })); });
    expect(input.value).toBe('自分の言葉で入力する');
    await act(() => root.unmount()); container.remove();
  });
  it('keeps the populated desktop composer pinned with a small bottom gutter', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    await act(async () => root.render(<HomeSupervisor repository={{ load: async () => ({ messages: [{ role: 'user', content: '既存の会話' }], proposals: [], input: '' }), save: async (value) => value }} />)); await act(async () => {});
    const surface = container.querySelector('[data-home-state="populated"]'); const form = container.querySelector('form');
    expect(surface).toBeTruthy(); expect(form.className).toContain('sticky'); expect(form.className).toContain('pb-6'); expect(container.querySelector('[aria-label="会話履歴"]').className).not.toContain('sr-only');
    await act(() => root.unmount()); container.remove();
  });
  it('uses only a safe snapshot and never includes raw, token, or secret input', () => {
    const proposal = proposeHomeAction('プロジェクトを確認');
    expect(JSON.stringify(proposal)).not.toMatch(/raw|token|secret/i);
  });
  it('requires a visible confirmation before persisting a proposal as confirmed and never fetches', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container); const stored = { messages: [], proposals: [] }; const saves = [];
    const repository = { load: async () => stored, save: async (value) => { saves.push(value); Object.assign(stored, value); return value; } }; const fetchSpy = vi.spyOn(globalThis, 'fetch');
    await act(async () => root.render(<HomeSupervisor repository={repository} />)); await act(async () => {});
    const input = container.querySelector('#home-supervisor-message'); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { setter.call(input, 'プロジェクトを一覧で確認'); input.dispatchEvent(new Event('input', { bubbles: true })); container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    expect(stored.proposals[0].confirmed).toBe(false); expect(container.textContent).toContain('事実:'); expect(container.textContent).toContain('推論:'); expect(container.textContent).toContain('操作:');
    await act(async () => Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'プロジェクトに採用').click()); expect(stored.proposals[0].status).toBe('adopted'); expect(stored.proposals[0].confirmed).toBe(true); expect(fetchSpy).not.toHaveBeenCalled();
    await act(() => root.unmount()); const remount = createRoot(container); await act(async () => remount.render(<HomeSupervisor repository={repository} />)); await act(async () => {}); expect(container.textContent).toContain('Projectへ採用済み'); await act(() => remount.unmount()); container.remove(); fetchSpy.mockRestore();
  });
});
