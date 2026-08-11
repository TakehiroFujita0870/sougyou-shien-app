import { describe, expect, it, vi } from 'vitest';
import { createKnowledgeMetadataRepository, KNOWLEDGE_QUARANTINE_KEY, KNOWLEDGE_SCHEMA_VERSION, KNOWLEDGE_STORAGE_KEY, knowledgeMetadataStorageKey } from './knowledgeMetadataRepository';

const doc = { id: 'doc-1', name: 'brief.pdf', version: 1, state: 'searchable', mediaType: 'pdf', sizeBytes: 2048, lastModified: 1, extractedTextState: 'ready', indexState: 'ready' };
const currentDoc = { ...doc, ownerId: 'a', spaceId: 's', deletedAt: null, sourceType: 'local', confidence: 'unknown', createdAt: null, updatedAt: null, projectId: '', evaluationView: '' };
const currentKey = knowledgeMetadataStorageKey('a', 's');

function storage(seed = {}) {
  const values = new Map(Object.entries(seed));
  return { getItem: vi.fn((key) => values.get(key) ?? null), setItem: vi.fn((key, value) => values.set(key, String(value))) };
}

const scoped = (value, ownerId = 'a', spaceId = 's') => ({ ...value, ownerId, spaceId });
const currentEnvelope = (documents) => JSON.stringify({ schemaVersion: KNOWLEDGE_SCHEMA_VERSION, ownerId: 'a', spaceId: 's', documents });

describe('knowledge metadata repository', () => {
  it('reports a read exception and recovers on a new-generation retry without overwriting data', async () => {
    let failRead = true;
    const raw = currentEnvelope([currentDoc]);
    const store = { getItem: vi.fn((key) => { if (failRead) throw new Error('blocked'); return key === currentKey ? raw : null; }), setItem: vi.fn() };
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    expect(await repository.load()).toEqual([]);
    expect(repository.getLastError()).toBeInstanceOf(Error);
    expect(store.setItem).not.toHaveBeenCalled();
    failRead = false;
    expect(await repository.retryLoad()).toEqual([currentDoc]);
    expect(repository.getLastError()).toBeNull();
  });

  it('adds, reloads, lists, and tombstones metadata through a collision-safe scoped envelope', async () => {
    const store = storage();
    const first = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    await first.add(doc);
    expect(first.list()[0]).toMatchObject({ id: 'doc-1', ownerId: 'a', spaceId: 's', sourceType: 'local', confidence: 'unknown', projectId: '' });
    expect(JSON.parse(store.getItem(currentKey))).toMatchObject({ schemaVersion: KNOWLEDGE_SCHEMA_VERSION, ownerId: 'a', spaceId: 's' });
    expect(knowledgeMetadataStorageKey('a:b', 'c')).not.toBe(knowledgeMetadataStorageKey('a', 'b:c'));

    const second = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    expect(await second.load()).toHaveLength(1);
    await second.delete('doc-1');
    const third = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    await third.load();
    expect(third.list()).toEqual([]);
    expect(third.find('doc-1')).toMatchObject({ state: 'deleted', deletedAt: expect.any(String) });
  });

  it('copies valid global legacy data into separate owner/space keys and never changes the legacy raw', async () => {
    const legacyRaw = JSON.stringify({ schemaVersion: 1, documents: [scoped(doc), scoped({ ...doc, id: 'other' }, 'b', 's')] });
    const store = storage({ [KNOWLEDGE_STORAGE_KEY]: legacyRaw });
    const a = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    const b = createKnowledgeMetadataRepository({ ownerId: 'b', spaceId: 's', storage: store });
    expect(await a.load()).toEqual([expect.objectContaining({ id: 'doc-1' })]);
    expect(await b.load()).toEqual([expect.objectContaining({ id: 'other' })]);
    expect(store.getItem(KNOWLEDGE_STORAGE_KEY)).toBe(legacyRaw);
    expect(JSON.parse(store.getItem(currentKey)).documents).toEqual([expect.objectContaining({ id: 'doc-1', ownerId: 'a' })]);
    expect(JSON.parse(store.getItem(knowledgeMetadataStorageKey('b', 's'))).documents).toEqual([expect.objectContaining({ id: 'other', ownerId: 'b' })]);
  });

  it('keeps valid legacy data usable when its copy write fails, then persists the complete migrated state on mutation retry', async () => {
    const legacyRaw = JSON.stringify({ documents: [scoped(doc)] });
    let failWrites = true;
    const values = new Map([[KNOWLEDGE_STORAGE_KEY, legacyRaw]]);
    const store = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => { if (failWrites) throw new Error('offline'); values.set(key, String(value)); } };
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    expect(await repository.load()).toHaveLength(1);
    expect(values.get(KNOWLEDGE_STORAGE_KEY)).toBe(legacyRaw);
    await expect(repository.add({ ...doc, id: 'doc-2' })).rejects.toThrow('offline');
    expect(repository.list().map(({ id }) => id)).toEqual(['doc-1']);
    failWrites = false;
    await repository.add({ ...doc, id: 'doc-2' });
    expect(JSON.parse(values.get(currentKey)).documents.map(({ id }) => id)).toEqual(['doc-1', 'doc-2']);
    expect(values.get(KNOWLEDGE_STORAGE_KEY)).toBe(legacyRaw);
  });

  it.each(['id', 'ownerId', 'spaceId', 'name', 'version', 'state', 'mediaType', 'sizeBytes', 'lastModified', 'extractedTextState', 'indexState', 'deletedAt', 'sourceType', 'confidence', 'createdAt', 'updatedAt', 'projectId', 'evaluationView'])
    ('strictly rejects a v2 record missing required own property %s', async (field) => {
      const partial = { ...currentDoc };
      delete partial[field];
      const raw = currentEnvelope([partial]);
      const store = storage({ [currentKey]: raw });
      const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
      expect(await repository.load()).toEqual([]);
      expect(store.getItem(currentKey)).toBe(raw);
      expect(store.getItem(`${currentKey}:quarantine`)).toBe(raw);
      await expect(repository.add(doc)).rejects.toThrow('requires recovery');
      expect(store.getItem(currentKey)).toBe(raw);
    });

  it.each([
    ['malformed scoped JSON', '{broken'],
    ['future scoped schema', JSON.stringify({ schemaVersion: 3, ownerId: 'a', spaceId: 's', documents: [] })],
    ['wrong scoped owner', JSON.stringify({ schemaVersion: 2, ownerId: 'b', spaceId: 's', documents: [] })],
  ])('quarantines exact %s and blocks replacement', async (_label, raw) => {
    const store = storage({ [currentKey]: raw });
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    expect(await repository.load()).toEqual([]);
    expect(store.getItem(`${currentKey}:quarantine`)).toBe(raw);
    await expect(repository.add(doc)).rejects.toThrow('requires recovery');
    expect(store.getItem(currentKey)).toBe(raw);
  });

  it.each([
    ['malformed JSON', '{broken'],
    ['future schema', JSON.stringify({ schemaVersion: 99, documents: [] })],
    ['invalid tombstone', JSON.stringify({ schemaVersion: 1, documents: [scoped({ ...doc, state: 'deleted', deletedAt: null })] })],
    ['invalid evidence metadata', JSON.stringify({ schemaVersion: 1, documents: [scoped({ ...doc, sourceType: 'forged', confidence: 'certain' })] })],
    ['invalid timestamps and project link', JSON.stringify({ schemaVersion: 1, documents: [scoped({ ...doc, createdAt: 'not-a-date', projectId: 42 })] })],
  ])('quarantines exact legacy %s raw and blocks add/delete from replacing it', async (_label, raw) => {
    const store = storage({ [KNOWLEDGE_STORAGE_KEY]: raw });
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    expect(await repository.load()).toEqual([]);
    expect(store.getItem(KNOWLEDGE_STORAGE_KEY)).toBe(raw);
    expect(store.getItem(KNOWLEDGE_QUARANTINE_KEY)).toBe(raw);
    await expect(repository.add(doc)).rejects.toThrow('requires recovery');
    await expect(repository.delete(doc.id, doc)).rejects.toThrow('requires recovery');
  });

  it('write-blocks on a storage read exception and never attempts a destructive write', async () => {
    let writes = 0;
    const store = { getItem: () => { throw new Error('offline'); }, setItem: () => { writes += 1; } };
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    expect(await repository.load()).toEqual([]);
    await expect(repository.add(doc)).rejects.toThrow('requires recovery');
    await expect(repository.delete(doc.id, doc)).rejects.toThrow('requires recovery');
    expect(writes).toBe(0);
  });

  it('refreshes cached state after add/delete for same-repository remount and F5 reload', async () => {
    const store = storage();
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    expect(await repository.load()).toEqual([]);
    await repository.add(doc);
    expect(await repository.load()).toHaveLength(1);
    await repository.delete(doc.id);
    expect(await repository.load()).toEqual([]);
    const reloaded = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    expect(await reloaded.load()).toEqual([]);
    expect(reloaded.find(doc.id)).toMatchObject({ state: 'deleted' });
  });

  it('persists a tombstone for a valid fixture that was not previously added', async () => {
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: storage() });
    await repository.delete('fixture-1', { name: 'fixture.pdf', state: 'searchable' });
    expect(repository.find('fixture-1')).toMatchObject({ state: 'deleted', ownerId: 'a', spaceId: 's' });
  });
});
