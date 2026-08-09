// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { HomeSupervisor, proposeHomeAction } from './HomeSupervisor';
import { createHomeConversationRepository } from './homeConversationRepository';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe('Home supervisor', () => {
  it('keeps the composer unavailable until initial conversation and draft hydration finish', async () => {
    let resolveConversation; let resolveDraft;
    const conversation = new Promise((resolve) => { resolveConversation = resolve; });
    const draft = new Promise((resolve) => { resolveDraft = resolve; });
    const repository = { load: () => conversation, loadDraft: () => draft, save: vi.fn(async (value) => value), saveDraft: vi.fn(async (value) => value) };
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    await act(async () => root.render(<HomeSupervisor repository={repository} />));
    const input = container.querySelector('#home-supervisor-message');
    expect(input.disabled).toBe(true); expect(input.form.getAttribute('aria-busy')).toBe('true');
    await act(async () => input.form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    expect(repository.save).not.toHaveBeenCalled();
    await act(async () => { resolveConversation({ messages: [{ role: 'user', content: '保存済みの会話' }], proposals: [] }); resolveDraft('保存済みの下書き'); await Promise.resolve(); });
    expect(input.disabled).toBe(false); expect(input.value).toBe('保存済みの下書き'); expect(container.textContent).toContain('保存済みの会話');
    await act(() => root.unmount()); container.remove();
  });

  it('ignores an initial hydration that resolves after unmount', async () => {
    let resolveConversation; const conversation = new Promise((resolve) => { resolveConversation = resolve; }); const onProjectAdopt = vi.fn();
    const repository = { load: () => conversation, loadDraft: async () => '', save: async (value) => value, saveDraft: async (value) => value };
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    await act(async () => root.render(<HomeSupervisor repository={repository} onProjectAdopt={onProjectAdopt} />));
    await act(() => root.unmount());
    await act(async () => { resolveConversation({ messages: [], proposals: [{ id: 'late', status: 'adopted' }] }); await Promise.resolve(); });
    expect(onProjectAdopt).not.toHaveBeenCalled(); container.remove();
  });

  it('keeps an optimistic turn visible and reports a conversation save rejection', async () => {
    const repository = { load: async () => ({ messages: [], proposals: [] }), loadDraft: async () => '', saveDraft: async (value) => value, save: vi.fn(async () => { throw new Error('offline'); }) };
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    await act(async () => root.render(<HomeSupervisor repository={repository} />)); await act(async () => {});
    const input = container.querySelector('#home-supervisor-message'); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { setter.call(input, '保存に失敗する相談'); input.dispatchEvent(new Event('input', { bubbles: true })); input.form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await Promise.resolve(); await Promise.resolve(); });
    expect(container.textContent).toContain('保存に失敗する相談'); expect(container.querySelector('[role="alert"]').textContent).toContain('会話を保存できませんでした');
    await act(() => root.unmount()); container.remove();
  });
  it('keeps conversation state when a pending draft write finishes after send', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    let releaseDraft;
    let stored = { messages: [], proposals: [] };
    let storedDraft = '';
    const repository = {
      load: async () => stored,
      loadDraft: async () => storedDraft,
      save: vi.fn(async (value) => { stored = value; return value; }),
      saveDraft: vi.fn(async (value) => {
        if (value && !releaseDraft) await new Promise((resolve) => { releaseDraft = resolve; });
        storedDraft = value; return value;
      }),
    };
    await act(async () => root.render(<HomeSupervisor repository={repository} />)); await act(async () => {});
    const input = container.querySelector('#home-supervisor-message');
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => {
      setter.call(input, '地域の小さな工場を支援したい');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    expect(stored.messages).toHaveLength(2);
    expect(stored.proposals).toHaveLength(1);
    expect(storedDraft).toBe('');
    await act(async () => { releaseDraft(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
    expect(stored.messages).toHaveLength(2);
    expect(stored.proposals).toHaveLength(1);
    expect(storedDraft).toBe('');
    await act(() => root.unmount()); container.remove();
  });
  it('restores an unsent draft after an F5-equivalent remount', async () => {
    const container = document.createElement('div'); document.body.append(container);
    const values = new Map();
    const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)) };
    const repository = createHomeConversationRepository(storage);
    let root = createRoot(container);
    await act(async () => root.render(<HomeSupervisor repository={repository} />)); await act(async () => {});
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { const input = container.querySelector('#home-supervisor-message'); setter.call(input, '送信前の事業メモ'); input.dispatchEvent(new Event('input', { bubbles: true })); await Promise.resolve(); });
    await act(() => root.unmount());
    root = createRoot(container);
    await act(async () => root.render(<HomeSupervisor repository={createHomeConversationRepository(storage)} />)); await act(async () => {});
    expect(container.querySelector('#home-supervisor-message').value).toBe('送信前の事業メモ');
    await act(() => root.unmount()); container.remove();
  });
  it('serializes rapid sends without losing either turn', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    let releaseFirst;
    let stored = { messages: [], proposals: [] };
    const repository = {
      load: async () => stored, loadDraft: async () => '', saveDraft: async (value) => value,
      save: vi.fn(async (value) => { if (!releaseFirst) await new Promise((resolve) => { releaseFirst = resolve; }); stored = value; return value; }),
    };
    await act(async () => root.render(<HomeSupervisor repository={repository} />)); await act(async () => {});
    const input = container.querySelector('#home-supervisor-message'); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { setter.call(input, '最初の相談'); input.dispatchEvent(new Event('input', { bubbles: true })); input.form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    await act(async () => { setter.call(input, '次の相談'); input.dispatchEvent(new Event('input', { bubbles: true })); input.form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    expect(container.querySelectorAll('[aria-label="会話履歴"] > li')).toHaveLength(6);
    expect(repository.save).toHaveBeenCalledTimes(1);
    await act(async () => { releaseFirst(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
    expect(stored.messages.map(({ content }) => content).join(' ')).toContain('最初の相談');
    expect(stored.messages.map(({ content }) => content).join(' ')).toContain('次の相談');
    expect(stored.messages).toHaveLength(4);
    await act(() => root.unmount()); container.remove();
  });
  it('serializes send and two proposal decisions against one authoritative snapshot', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    let releaseFirst;
    let stored = { messages: [], proposals: [
      { id: 'one', title: '案1', fact: '事実1', inference: '推論1', action: 'ideate', confirmed: false, status: 'pending' },
      { id: 'two', title: '案2', fact: '事実2', inference: '推論2', action: 'ideate', confirmed: false, status: 'pending' },
    ] };
    const repository = {
      load: async () => stored, loadDraft: async () => '', saveDraft: async (value) => value,
      save: vi.fn(async (value) => { if (!releaseFirst) await new Promise((resolve) => { releaseFirst = resolve; }); stored = value; return value; }),
    };
    await act(async () => root.render(<HomeSupervisor repository={repository} />)); await act(async () => {});
    const input = container.querySelector('#home-supervisor-message'); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { setter.call(input, '新しい相談'); input.dispatchEvent(new Event('input', { bubbles: true })); input.form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    const proposalItem = (text) => Array.from(container.querySelectorAll('[aria-label="会話履歴"] > li')).find((item) => item.textContent.includes(text));
    await act(async () => Array.from(proposalItem('推論1').querySelectorAll('button')).find((button) => button.textContent === '保留').click());
    await act(async () => Array.from(proposalItem('推論2').querySelectorAll('button')).find((button) => button.textContent === 'プロジェクトに採用').click());
    expect(repository.save).toHaveBeenCalledTimes(1);
    await act(async () => { releaseFirst(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
    expect(stored.messages).toHaveLength(2);
    expect(stored.proposals.find(({ id }) => id === 'one').status).toBe('held');
    expect(stored.proposals.find(({ id }) => id === 'two').status).toBe('adopted');
    await act(() => root.unmount()); container.remove();
  });
  it('keeps the empty desktop canvas as one compact greeting and wide composer cluster', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    await act(async () => root.render(<HomeSupervisor repository={{ load: async () => ({ messages: [], proposals: [], input: '' }), save: async (value) => value }} />)); await act(async () => {});
    const surface = container.querySelector('[data-home-state="empty"]'); const form = container.querySelector('form');
    expect(surface).toBeTruthy(); expect(surface.className).toContain('justify-center'); expect(form.className).toContain('max-w-[840px]'); expect(container.querySelector('#home-supervisor-message').className).toContain('min-h-36');
    await act(() => root.unmount()); container.remove();
  });
  it('restores the repository draft and still replaces it only after an explicit prompt click', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    const repository = { load: async () => ({ messages: [], proposals: [] }), loadDraft: async () => '保存済みの下書き', saveDraft: async (value) => value, save: async (value) => value };
    await act(async () => root.render(<HomeSupervisor repository={repository} />)); await act(async () => {});
    const input = container.querySelector('#home-supervisor-message');
    expect(input.value).toBe('保存済みの下書き');
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
    expect(surface).toBeTruthy(); expect(surface.className).toContain('overflow-hidden'); expect(form.className).toContain('shrink-0'); expect(container.querySelector('[aria-label="会話履歴"]').className).toContain('overflow-y-auto');
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
