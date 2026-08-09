import { describe, expect, it } from 'vitest';
import {
  createKnowledgeConversationRepository,
  KNOWLEDGE_CONVERSATION_SCHEMA_VERSION,
  knowledgeConversationStorageKey,
  legacyKnowledgeConversationStorageKey,
  respondToKnowledge,
} from './knowledgeConversationRepository';

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  };
}

const message = { role: 'user', content: '確認したい', createdAt: '2026-08-10T00:00:00.000Z' };
const entry = { id: 'entry-1', category: 'note', title: 'メモ', content: '本文', createdAt: '2026-08-10T00:00:00.000Z', updatedAt: '2026-08-10T00:00:00.000Z', sourceType: 'local', projectId: '', evaluationView: '', confidence: 'unknown', unknowns: [] };
const state = { messages: [message], entries: [entry] };

describe('knowledge conversation repository', () => {
  it('isolates owner-space state and persists it across an F5-equivalent repository remount', async () => {
    const storage = memoryStorage();
    const a = createKnowledgeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    const b = createKnowledgeConversationRepository({ ownerId: 'owner-b', spaceId: 'space-a', storage });
    await a.save(state);
    expect(await createKnowledgeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage }).load()).toEqual(state);
    expect(await b.load()).toEqual({ messages: [], entries: [] });
  });

  it('refreshes the successful-save cache for a same-repository consumer remount', async () => {
    const storage = memoryStorage();
    const repository = createKnowledgeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect(await repository.load()).toEqual({ messages: [], entries: [] });
    await repository.save(state);
    expect(await repository.load()).toEqual(state);
  });

  it('uses collision-safe owner-space keys without changing the legacy source key contract', () => {
    expect(knowledgeConversationStorageKey('a:b', 'c')).not.toBe(knowledgeConversationStorageKey('a', 'b:c'));
    expect(legacyKnowledgeConversationStorageKey('a:b', 'c')).toBe(legacyKnowledgeConversationStorageKey('a', 'b:c'));
  });

  it.each([
    ['malformed JSON', '{broken'],
    ['future schema', JSON.stringify({ schemaVersion: 2, ownerId: 'owner-a', spaceId: 'space-a', state })],
    ['partial message', JSON.stringify({ schemaVersion: 1, ownerId: 'owner-a', spaceId: 'space-a', state: { messages: [{ role: 'user', content: '欠落' }], entries: [] } })],
    ['invalid timestamp', JSON.stringify({ schemaVersion: 1, ownerId: 'owner-a', spaceId: 'space-a', state: { messages: [{ role: 'user', content: '日付不正', createdAt: 'not-a-date' }], entries: [] } })],
    ['partial entry', JSON.stringify({ schemaVersion: 1, ownerId: 'owner-a', spaceId: 'space-a', state: { messages: [], entries: [{ id: 'partial', title: '欠落', content: '本文' }] } })],
    ['invalid entry metadata', JSON.stringify({ schemaVersion: 1, ownerId: 'owner-a', spaceId: 'space-a', state: { messages: [], entries: [{ ...entry, sourceType: 'forged' }] } })],
  ])('quarantines exact %s raw, preserves it, and blocks the next save', async (_label, raw) => {
    const key = knowledgeConversationStorageKey('owner-a', 'space-a');
    const storage = memoryStorage({ [key]: raw });
    const repository = createKnowledgeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect(await repository.load()).toEqual({ messages: [], entries: [] });
    expect(storage.getItem(key)).toBe(raw);
    expect(storage.getItem(`${key}:quarantine`)).toBe(raw);
    await expect(repository.save(state)).rejects.toThrow('requires recovery');
    expect(storage.getItem(key)).toBe(raw);
  });

  it('write-blocks a read exception without attempting a replacement', async () => {
    let writes = 0;
    const storage = { getItem: () => { throw new Error('offline'); }, setItem: () => { writes += 1; } };
    const repository = createKnowledgeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect(await repository.load()).toEqual({ messages: [], entries: [] });
    await expect(repository.save(state)).rejects.toThrow('requires recovery');
    expect(writes).toBe(0);
  });

  it('migrates a valid unversioned state to the strict envelope', async () => {
    const key = knowledgeConversationStorageKey('owner-a', 'space-a');
    const legacyKey = legacyKnowledgeConversationStorageKey('owner-a', 'space-a');
    const legacy = JSON.stringify({ messages: [{ role: 'user', content: '旧会話', createdAt: 'legacy-invalid-date' }], entries: [entry] });
    const storage = memoryStorage({ [legacyKey]: legacy });
    const repository = createKnowledgeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect(await repository.load()).toEqual({ messages: [{ role: 'user', content: '旧会話', createdAt: null }], entries: [entry] });
    expect(JSON.parse(storage.getItem(key))).toMatchObject({ schemaVersion: KNOWLEDGE_CONVERSATION_SCHEMA_VERSION, ownerId: 'owner-a', spaceId: 'space-a' });
    expect(storage.getItem(legacyKey)).toBe(legacy);
    expect((await createKnowledgeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage }).load()).messages[0].createdAt).toBeNull();
  });

  it('does not replace legacy raw until migration storage succeeds', async () => {
    const key = knowledgeConversationStorageKey('owner-a', 'space-a');
    const legacyKey = legacyKnowledgeConversationStorageKey('owner-a', 'space-a');
    const legacy = JSON.stringify({ messages: [{ role: 'user', content: '旧会話' }], entries: [] });
    const values = new Map([[legacyKey, legacy]]); let failMigration = true;
    const storage = { getItem: (name) => values.get(name) ?? null, setItem: (name, value) => { if (name === key && failMigration) { failMigration = false; throw new Error('quota'); } values.set(name, String(value)); } };
    const repository = createKnowledgeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect((await repository.load()).messages).toHaveLength(1);
    expect(storage.getItem(legacyKey)).toBe(legacy);
    expect(storage.getItem(key)).toBeNull();
    await repository.save(state);
    expect(JSON.parse(storage.getItem(key)).state).toEqual(state);
    expect(storage.getItem(legacyKey)).toBe(legacy);
  });

  it('keeps legacy evidence normalization without crossing owner-space', async () => {
    const key = legacyKnowledgeConversationStorageKey('owner-a', 'space-a');
    const legacyEntry = { id: 'legacy', category: 'note', title: '旧形式', content: '本文', createdAt: 'not-a-date', updatedAt: 'also-bad', sourceType: 'forged', confidence: 'certain', unknowns: [123] };
    const storage = memoryStorage({ [key]: JSON.stringify({ messages: [], entries: [legacyEntry] }) });
    const repository = createKnowledgeConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect((await repository.load()).entries[0]).toMatchObject({ sourceType: 'unknown', confidence: 'unknown', unknowns: [], createdAt: '1970-01-01T00:00:00.000Z', updatedAt: '1970-01-01T00:00:00.000Z' });
    expect((await createKnowledgeConversationRepository({ ownerId: 'owner-a', spaceId: 'other', storage }).load()).entries).toEqual([]);
  });

  it('summarizes current knowledge context without external calls', () => expect(respondToKnowledge('市場性', { asset: { name: '資料.pdf' }, decision: { judgement: '小さく検証' } })).toContain('資料.pdf'));
});
