import { describe, expect, it } from 'vitest';

import { createHomeConversationRepository, HOME_CONVERSATION_STORAGE_KEY, HOME_DRAFT_STORAGE_KEY } from './homeConversationRepository';

function memoryStorage(initial) {
  const values = new Map(initial ? [[HOME_CONVERSATION_STORAGE_KEY, initial]] : []);
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  };
}

describe('homeConversationRepository', () => {
  it('migrates a legacy input into independently persisted draft state', async () => {
    const storage = memoryStorage(JSON.stringify({ messages: [], proposals: [], input: '古い下書き' }));
    const repository = createHomeConversationRepository(storage);

    expect(await repository.load()).toEqual({ messages: [], proposals: [] });
    expect(await repository.loadDraft()).toBe('古い下書き');
    expect(await repository.saveDraft('送信前の下書き')).toBe('送信前の下書き');
    expect(storage.getItem(HOME_DRAFT_STORAGE_KEY)).toBe('送信前の下書き');
    expect(await repository.save({ messages: [], proposals: [], input: '保存しない下書き' })).toEqual({ messages: [], proposals: [] });
    expect(JSON.parse(storage.getItem(HOME_CONVERSATION_STORAGE_KEY))).toEqual({ messages: [], proposals: [] });
  });

  it('falls back to an empty conversation for corrupt storage', async () => {
    const repository = createHomeConversationRepository(memoryStorage('{broken'));
    expect(await repository.load()).toEqual({ messages: [], proposals: [] });
  });
});
