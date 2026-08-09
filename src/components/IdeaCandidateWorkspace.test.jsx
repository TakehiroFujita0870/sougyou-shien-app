import { describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { IdeaCandidateWorkspace, approveCandidate, candidateFromConversation, createLocalIdeaUxObserver, decideCandidate, findDuplicate, legacyConversationFromIdeaForm, localAssistSuggestion, nextConversationQuestion, saveCandidate } from './IdeaCandidateWorkspace';
const candidate = { title: '工場ノート', summary: '設備保全を記録', pain: '履歴が探せない' };
describe('idea candidate repository boundary', () => {
  it('persists adopt, hold, and reasoned reject decisions without promoting hold/reject', async () => {
    const repository = { save: async (items) => items };
    const item = { ...candidate, id: '1' };
    expect((await decideCandidate(repository, [item], item, 'adopt')).items[0]).toMatchObject({ status: 'adopted', promotedTo: 'project' });
    expect((await decideCandidate(repository, [item], item, 'hold')).items[0]).toMatchObject({ status: 'held' });
    expect((await decideCandidate(repository, [item], item, 'reject', '対象顧客が不明')).items[0]).toMatchObject({ status: 'rejected', rejectionReason: '対象顧客が不明' });
    expect((await decideCandidate(repository, [item], item, 'reject')).error).toContain('理由');
  });
  it('never writes project or knowledge records before adoption', async () => {
    const writes = []; const repository = { save: async (items) => { writes.push(items); return items; } }; const item = { ...candidate, id: '1' };
    await decideCandidate(repository, [item], item, 'hold'); await decideCandidate(repository, [item], item, 'reject', '対象外');
    expect(writes.flat()).not.toEqual(expect.arrayContaining([expect.objectContaining({ projectId: expect.anything() }), expect.objectContaining({ knowledgeId: expect.anything() })]));
    await decideCandidate(repository, [item], item, 'adopt'); expect(writes.at(-1)[0].promotedTo).toBe('project');
  });
  it('saves a candidate and detects duplicates', async () => { const repository = { save: async (items) => items }; const result = await saveCandidate(repository, [], candidate); expect(result.items).toHaveLength(1); expect(findDuplicate(result.items, candidate)).toBeTruthy(); });
  it('updates only after approval', async () => { const repository = { save: async (items) => items }; const result = await approveCandidate(repository, [{ ...candidate, id: '1' }], { ...candidate, id: '1', title: '更新案' }); expect(result.items[0].title).toBe('更新案'); });
  it('returns a recoverable save failure', async () => { const result = await saveCandidate({ save: async () => { throw new Error('offline'); } }, [], candidate); expect(result.error).toContain('保存'); });
  it('asks deterministic questions for missing details without an external model', () => {
    expect(nextConversationQuestion([{ role: 'user', content: '保全のアイデアです' }])).toContain('誰');
    expect(nextConversationQuestion([{ role: 'user', content: '工場の担当者向けです' }])).toContain('困');
  });
  it('derives a preview from only local conversation messages', () => {
    expect(candidateFromConversation([{ role: 'user', content: '工場の担当者向けの記録アプリ' }]).title).toContain('工場');
  });
  it('migrates an existing three-field local draft into one conversation message', () => {
    expect(legacyConversationFromIdeaForm({ title: '工場ノート', ideaSummary: '保全記録をまとめる', painStatement: '履歴を探せない' })).toEqual([
      { role: 'user', content: '工場ノート\n保全記録をまとめる\n履歴を探せない' },
    ]);
  });
  it('creates a deterministic local assist suggestion without replacing the original', () => {
    const original = '工場の保全担当者向け';
    expect(localAssistSuggestion(original)).toBe(localAssistSuggestion(original));
    expect(original).toBe('工場の保全担当者向け');
  });
  it('records only deterministic metadata for hesitation events', () => {
    const observer = createLocalIdeaUxObserver();
    observer.record('idea_message', 'empty_submit');
    observer.record('idea_message', 'help_opened');
    expect(observer.events()).toEqual([
      { key: 'idea_message', type: 'empty_submit', sequence: 1 },
      { key: 'idea_message', type: 'help_opened', sequence: 2 },
    ]);
    expect(JSON.stringify(observer.events())).not.toMatch(/本文|顧客|銀行|customer|bank/);
    expect(() => observer.record('idea_message', '顧客本文')).toThrow('Unsupported');
    expect(() => observer.record('customer_name', 'help_opened')).toThrow('Unsupported');
  });
});

// @vitest-environment happy-dom
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
describe('idea conversation controls', () => {
  it('drives adopt, hold, and reason-required reject through the candidate card UI without fetch', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    const stored = [{ ...candidate, id: 'candidate-1' }]; const saves = []; const repository = { load: async () => stored, save: async (items) => { saves.push(items); stored.splice(0, stored.length, ...items); return items; } };
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    await act(async () => root.render(<IdeaCandidateWorkspace repository={repository} conversationRepository={{ load: async () => [], save: async (messages) => messages }} />)); await act(async () => {});
    const candidateButton = [...container.querySelectorAll('button')].find((button) => button.textContent.includes('工場ノート')); expect(candidateButton).toBeTruthy(); await act(async () => candidateButton.click());
    expect(container.textContent).toContain('仮説カード');
    const controls = [...container.querySelectorAll('button')]; const hold = controls.find((button) => button.textContent === '保留'); const adopt = controls.find((button) => button.textContent === 'プロジェクトに採用'); const reject = controls.find((button) => button.textContent === '理由付きで却下');
    expect(hold && adopt && reject).toBeTruthy();
    await act(async () => reject.click()); expect(container.textContent).toContain('却下理由を入力してください');
    const reason = container.querySelector('#reject-reason'); await act(async () => { reason.value = '対象顧客が不明'; reason.dispatchEvent(new Event('input', { bubbles: true })); }); await act(async () => reject.click()); expect(stored[0]).toMatchObject({ status: 'rejected', rejectionReason: '対象顧客が不明' });
    await act(async () => hold.click()); expect(stored[0]).toMatchObject({ status: 'held' }); expect(stored[0].promotedTo).toBeUndefined();
    await act(async () => adopt.click()); expect(stored[0]).toMatchObject({ status: 'adopted', promotedTo: 'project' }); expect(fetchSpy).not.toHaveBeenCalled();
    await act(() => root.unmount()); container.remove(); fetchSpy.mockRestore();
  });
  it('restores all candidate decision states and rejection reason after remount', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container); const stored = [{ ...candidate, id: 'a', status: 'adopted', promotedTo: 'project' }, { ...candidate, id: 'h', title: '保留案', status: 'held' }, { ...candidate, id: 'r', title: '却下案', status: 'rejected', rejectionReason: '重複している' }]; const repository = { load: async () => stored, save: async (items) => items };
    await act(async () => root.render(<IdeaCandidateWorkspace repository={repository} conversationRepository={{ load: async () => [], save: async (messages) => messages }} />)); await act(async () => {});
    expect(container.textContent).toContain('状態: 採用'); expect(container.textContent).toContain('状態: 保留'); expect(container.textContent).toContain('状態: 却下');
    await act(async () => container.querySelectorAll('button')[3].click()); expect(container.querySelector('#reject-reason').value).toBe('重複している'); await act(() => root.unmount()); container.remove();
  });
  it('exposes labeled, focusable decision controls for keyboard and screen readers', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container); const repository = { load: async () => [{ ...candidate, id: '1' }], save: async (items) => items };
    await act(async () => root.render(<IdeaCandidateWorkspace repository={repository} conversationRepository={{ load: async () => [], save: async (messages) => messages }} />)); await act(async () => {});
    await act(async () => [...container.querySelectorAll('button')].find((button) => button.textContent.includes('工場ノート')).click());
    expect(container.querySelector('label[for="reject-reason"]')).toBeTruthy(); expect(container.querySelector('#reject-reason').getAttribute('aria-label')).toBeNull(); expect(container.querySelector('#reject-reason').tabIndex).toBeGreaterThanOrEqual(0);
    for (const text of ['プロジェクトに採用', '保留', '理由付きで却下']) { const button = [...container.querySelectorAll('button')].find((node) => node.textContent === text); expect(button).toBeTruthy(); expect(button.tabIndex).toBeGreaterThanOrEqual(0); }
    await act(() => root.unmount()); container.remove();
  });
  it('renders a preview only after a user message and keeps 44px controls', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    const conversations = { load: async () => [{ role: 'user', content: '工場の担当者向けです' }], save: async (messages) => messages };
    await act(async () => root.render(<IdeaCandidateWorkspace repository={{ load: async () => [], save: async (items) => items }} conversationRepository={conversations} />));
    await act(async () => {});
    expect(container.textContent).toContain('保存前プレビュー');
    expect(container.innerHTML).toContain('min-h-11');
    await act(() => root.unmount()); container.remove();
  });
  it('keeps the original until the user adopts, edits, or discards a local assist preview', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    const observer = createLocalIdeaUxObserver();
    const inputRepository = { load: async () => '工場の保全担当者向け', save: async (value) => value };
    await act(async () => root.render(<IdeaCandidateWorkspace repository={{ load: async () => [], save: async (items) => items }} conversationRepository={{ load: async () => [], save: async (messages) => messages }} inputRepository={inputRepository} observer={observer} />));
    await act(async () => {});
    const input = container.querySelector('#idea-message');
    expect(input.value).toBe('工場の保全担当者向け');
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    await act(async () => container.querySelector('[data-testid="assist-request"]').click());
    expect(input.value).toBe('工場の保全担当者向け');
    expect(container.textContent).toContain('補完案のプレビュー');
    await act(async () => container.querySelector('[data-testid="assist-discard"]').click());
    expect(input.value).toBe('工場の保全担当者向け');
    await act(async () => container.querySelector('[data-testid="assist-request"]').click());
    const assist = container.querySelector('[aria-label="補完案を編集"]');
    const setTextareaValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { setTextareaValue.call(assist, '本人が編集した補完案'); assist.dispatchEvent(new Event('input', { bubbles: true })); });
    await act(async () => container.querySelector('[data-testid="assist-adopt"]').click());
    expect(input.value).toBe('本人が編集した補完案');
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(observer.events().map((event) => event.type)).toContain('conversation_resumed');
    expect(observer.events().map((event) => event.type)).toContain('assist_requested');
    await act(() => root.unmount()); container.remove();
  });
  it('records resume for stored conversation without exposing its content', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    const observer = createLocalIdeaUxObserver();
    await act(async () => root.render(<IdeaCandidateWorkspace repository={{ load: async () => [], save: async (items) => items }} conversationRepository={{ load: async () => [{ role: 'user', content: '銀行向けの顧客本文' }], save: async (messages) => messages }} inputRepository={{ load: async () => '', save: async (value) => value }} observer={observer} />));
    await act(async () => {});
    expect(observer.events()).toEqual([{ key: 'idea_message', type: 'conversation_resumed', sequence: 1 }]);
    expect(JSON.stringify(observer.events())).not.toMatch(/銀行|顧客/);
    await act(() => root.unmount()); container.remove();
  });
  it('keeps a saved conversation committed when clearing the local draft fails', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    let storedConversation = [];
    const conversationRepository = { load: async () => storedConversation, save: async (messages) => { storedConversation = messages; return messages; } };
    const inputRepository = { load: async () => '工場の担当者向けです', save: async () => { throw new Error('offline'); } };
    const workspace = () => <IdeaCandidateWorkspace repository={{ load: async () => [], save: async (items) => items }} conversationRepository={conversationRepository} inputRepository={inputRepository} />;
    await act(async () => root.render(workspace()));
    await act(async () => {});
    await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    expect(storedConversation.filter((message) => message.role === 'user')).toHaveLength(1);
    expect(container.querySelector('#idea-message').value).toBe('');
    expect(container.textContent).toContain('発言は保存しましたが、端末内の下書きを消去できませんでした');
    expect(container.textContent).toContain('工場の担当者向けです');
    await act(() => root.unmount());
    const remountedRoot = createRoot(container);
    await act(async () => remountedRoot.render(workspace()));
    await act(async () => {});
    expect(container.querySelector('#idea-message').value).toBe('');
    expect(storedConversation.filter((message) => message.role === 'user')).toHaveLength(1);
    await act(() => remountedRoot.unmount()); container.remove();
  });
  it('keeps a new unsaved input when slow hydration finishes after typing', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    let resolveConversation;
    const pendingConversation = new Promise((resolve) => { resolveConversation = resolve; });
    await act(async () => root.render(<IdeaCandidateWorkspace repository={{ load: async () => [], save: async (items) => items }} conversationRepository={{ load: () => pendingConversation, save: async (messages) => messages }} inputRepository={{ load: async () => '以前の下書き', save: async (value) => value }} />));
    const input = container.querySelector('#idea-message');
    const setTextareaValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { setTextareaValue.call(input, '今の未送信入力'); input.dispatchEvent(new Event('input', { bubbles: true })); });
    await act(async () => resolveConversation([]));
    expect(input.value).toBe('今の未送信入力');
    await act(() => root.unmount()); container.remove();
  });
  it('restores an old form draft as a conversation preview after reload', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    let savedConversation = [];
    const conversationRepository = { load: async () => savedConversation, save: async (messages) => { savedConversation = messages; return messages; } };
    const workspace = () => <IdeaCandidateWorkspace repository={{ load: async () => [], save: async (items) => items }} conversationRepository={conversationRepository} inputRepository={{ load: async () => '', save: async (value) => value }} legacyDraftRepository={{ load: async () => ({ title: '工場ノート', ideaSummary: '保全記録', painStatement: '履歴を探せない' }) }} />;
    await act(async () => root.render(workspace()));
    await act(async () => Promise.resolve());
    expect(container.textContent).toContain('保存前プレビュー');
    expect(savedConversation[0].content).toContain('工場ノート');
    await act(() => root.unmount()); container.remove();
  });
  it('sends with Enter and keeps Shift+Enter available for keyboard input', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    const saved = [];
    await act(async () => root.render(<IdeaCandidateWorkspace repository={{ load: async () => [], save: async (items) => items }} conversationRepository={{ load: async () => [], save: async (messages) => { saved.push(messages); return messages; } }} inputRepository={{ load: async () => '顧客の困りごと', save: async (value) => value }} />));
    await act(async () => {});
    const input = container.querySelector('#idea-message');
    await act(async () => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true })));
    expect(saved).toHaveLength(0);
    expect(input.value).toBe('顧客の困りごと');
    await act(async () => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })));
    expect(saved).toHaveLength(1);
    expect(input.value).toBe('');
    await act(() => root.unmount()); container.remove();
  });
  it('records empty submits, repeated edits, and explicit help without recording input content', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    const observer = createLocalIdeaUxObserver();
    await act(async () => root.render(<IdeaCandidateWorkspace repository={{ load: async () => [], save: async (items) => items }} conversationRepository={{ load: async () => [], save: async (messages) => messages }} inputRepository={{ load: async () => '', save: async (value) => value }} observer={observer} />));
    await act(async () => {});
    await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    const input = container.querySelector('#idea-message');
    for (const value of ['a', 'ab', 'abc']) await act(async () => { input.value = value; input.dispatchEvent(new Event('input', { bubbles: true })); });
    await act(async () => container.querySelector('[data-testid="idea-help"]').click());
    expect(observer.events().map((event) => event.type)).toEqual(expect.arrayContaining(['empty_submit', 'repeated_edit', 'help_opened']));
    expect(JSON.stringify(observer.events())).not.toContain('abc');
    await act(() => root.unmount()); container.remove();
  });
});
