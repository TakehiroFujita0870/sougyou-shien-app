import { describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { IdeaCandidateWorkspace, approveCandidate, candidateFromConversation, findDuplicate, nextConversationQuestion, saveCandidate } from './IdeaCandidateWorkspace';
const candidate = { title: '工場ノート', summary: '設備保全を記録', pain: '履歴が探せない' };
describe('idea candidate repository boundary', () => {
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
});

// @vitest-environment happy-dom
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
describe('idea conversation controls', () => {
  it('renders a preview only after a user message and keeps 44px controls', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    const conversations = { load: async () => [{ role: 'user', content: '工場の担当者向けです' }], save: async (messages) => messages };
    await act(async () => root.render(<IdeaCandidateWorkspace repository={{ load: async () => [], save: async (items) => items }} conversationRepository={conversations} />));
    await act(async () => {});
    expect(container.textContent).toContain('保存前プレビュー');
    expect(container.innerHTML).toContain('min-h-11');
    await act(() => root.unmount()); container.remove();
  });
});
