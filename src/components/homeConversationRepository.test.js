import { describe, expect, it } from 'vitest';

import {
  createHomeConversationRepository,
  HOME_CONVERSATION_SCHEMA_VERSION,
  HOME_CONVERSATION_STORAGE_KEY,
  HOME_DRAFT_STORAGE_KEY,
  homeConversationStorageKey,
  homeDraftStorageKey,
} from './homeConversationRepository';

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  };
}

const conversation = {
  messages: [{ role: 'user', content: '保存済みの会話' }, { role: 'assistant', content: '承知しました' }],
  proposals: [{ id: 'proposal-1', title: '市場調査', fact: '顧客候補あり', inference: '検証可能', reason: '', action: 'ideate', confirmed: false, status: 'pending' }],
};

describe('homeConversationRepository', () => {
  it('copies canonical legacy conversation and draft without deleting their source values', async () => {
    const legacyConversation = JSON.stringify({ ...conversation, input: '旧形式の下書き' });
    const storage = memoryStorage({ [HOME_CONVERSATION_STORAGE_KEY]: legacyConversation });
    const repository = createHomeConversationRepository({ storage });

    expect(await repository.load()).toEqual(conversation);
    expect(await repository.loadDraft()).toBe('旧形式の下書き');
    expect(storage.getItem(HOME_CONVERSATION_STORAGE_KEY)).toBe(legacyConversation);
    expect(JSON.parse(storage.getItem(homeConversationStorageKey('local-owner', 'local-space')))).toEqual({
      schemaVersion: HOME_CONVERSATION_SCHEMA_VERSION, ownerId: 'local-owner', spaceId: 'local-space', conversation,
    });
    expect(JSON.parse(storage.getItem(homeDraftStorageKey('local-owner', 'local-space'))).draft).toBe('旧形式の下書き');
  });

  it('copies the separately persisted canonical legacy draft and retains compatibility with the storage argument', async () => {
    const storage = memoryStorage({ [HOME_DRAFT_STORAGE_KEY]: '送信前の下書き' });
    const repository = createHomeConversationRepository(storage);
    expect(await repository.loadDraft()).toBe('送信前の下書き');
    expect(storage.getItem(HOME_DRAFT_STORAGE_KEY)).toBe('送信前の下書き');
  });

  it('isolates conversation and draft by owner and space', async () => {
    const storage = memoryStorage();
    const a = createHomeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    const b = createHomeConversationRepository({ ownerId: 'owner-b', spaceId: 'space-a', storage });
    await a.save(conversation);
    await a.saveDraft('Aだけの下書き');
    expect(await createHomeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage }).load()).toEqual(conversation);
    expect(await createHomeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage }).loadDraft()).toBe('Aだけの下書き');
    expect(await b.load()).toEqual({ messages: [], proposals: [] });
    expect(await b.loadDraft()).toBe('');
  });

  it.each([
    ['malformed JSON', '{broken'],
    ['future schema', JSON.stringify({ schemaVersion: 2, ownerId: 'owner-a', spaceId: 'space-a', conversation })],
    ['partial conversation', JSON.stringify({ schemaVersion: 1, ownerId: 'owner-a', spaceId: 'space-a', conversation: { messages: [{ role: 'user' }], proposals: [] } })],
  ])('quarantines exact %s conversation raw and refuses the next save', async (_label, raw) => {
    const key = homeConversationStorageKey('owner-a', 'space-a');
    const storage = memoryStorage({ [key]: raw });
    const repository = createHomeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect(await repository.load()).toEqual({ messages: [], proposals: [] });
    expect(storage.getItem(key)).toBe(raw);
    expect(storage.getItem(`${key}:quarantine`)).toBe(raw);
    await expect(repository.save(conversation)).rejects.toThrow('requires recovery');
    expect(storage.getItem(key)).toBe(raw);
  });

  it.each([
    ['malformed JSON', '{broken'],
    ['future schema', JSON.stringify({ schemaVersion: 2, ownerId: 'owner-a', spaceId: 'space-a', draft: 'draft' })],
    ['partial draft', JSON.stringify({ schemaVersion: 1, ownerId: 'owner-a', spaceId: 'space-a' })],
  ])('quarantines exact %s draft raw and refuses the next draft save', async (_label, raw) => {
    const key = homeDraftStorageKey('owner-a', 'space-a');
    const storage = memoryStorage({ [key]: raw });
    const repository = createHomeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect(await repository.loadDraft()).toBe('');
    expect(storage.getItem(key)).toBe(raw);
    expect(storage.getItem(`${key}:quarantine`)).toBe(raw);
    await expect(repository.saveDraft('replacement')).rejects.toThrow('requires recovery');
    expect(storage.getItem(key)).toBe(raw);
  });

  it('quarantines corrupt canonical legacy raw and never lets a later conversation or draft save replace it', async () => {
    const raw = JSON.stringify({ messages: [{ role: 'user' }], proposals: [], input: 42 });
    const storage = memoryStorage({ [HOME_CONVERSATION_STORAGE_KEY]: raw });
    const repository = createHomeConversationRepository({ storage });
    expect(await repository.load()).toEqual({ messages: [], proposals: [] });
    expect(await repository.loadDraft()).toBe('');
    expect(storage.getItem(`${HOME_CONVERSATION_STORAGE_KEY}:quarantine`)).toBe(raw);
    await expect(repository.save(conversation)).rejects.toThrow('requires recovery');
    await expect(repository.saveDraft('replacement')).rejects.toThrow('requires recovery');
    expect(storage.getItem(HOME_CONVERSATION_STORAGE_KEY)).toBe(raw);
  });

  it('persists valid scoped conversation and draft across a reload', async () => {
    const storage = memoryStorage();
    const repository = createHomeConversationRepository({ storage });
    await repository.save(conversation);
    await repository.saveDraft('F5後も残る');
    const reloaded = createHomeConversationRepository({ storage });
    expect(await reloaded.load()).toEqual(conversation);
    expect(await reloaded.loadDraft()).toBe('F5後も残る');
  });
});
