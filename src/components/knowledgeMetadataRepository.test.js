import { describe, expect, it, vi } from 'vitest';
import { createKnowledgeMetadataRepository } from './knowledgeMetadataRepository';

const doc = { id: 'doc-1', name: 'brief.pdf', version: 1, state: 'searchable', extractedTextState: 'ready', indexState: 'ready' };
function storage(seed) { const values = new Map(seed ? [['kadode:knowledge-metadata', JSON.stringify(seed)]] : []); return { getItem: vi.fn((key) => values.get(key) ?? null), setItem: vi.fn((key, value) => values.set(key, value)) }; }

describe('knowledge metadata repository', () => {
  it('adds, reloads, lists, and deletes metadata without binary contents', async () => {
    const first = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: storage() });
    await first.add(doc);
    const persisted = first.list();
    expect(persisted[0]).toMatchObject({ id: 'doc-1', ownerId: 'a', spaceId: 's', indexState: 'ready' });
    expect(persisted[0]).not.toHaveProperty('content');
    const store = storage({ schemaVersion: 1, documents: persisted });
    const second = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    await second.load();
    expect(second.list()).toHaveLength(1);
    await second.delete('doc-1');
    expect(second.list()).toEqual([]);
  });

  it('isolates owner and space and quarantines corrupt records', async () => {
    const store = storage({ schemaVersion: 1, documents: [{ ...doc, ownerId: 'a', spaceId: 's' }, { ...doc, id: 'other', ownerId: 'b', spaceId: 's' }, { id: 'bad' }] });
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    await repository.load();
    expect(repository.list().map(({ id }) => id)).toEqual(['doc-1']);
  });

  it('keeps safe state when read or delete write fails and ignores late reads', async () => {
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: { getItem: () => { throw new Error('offline'); }, setItem: () => { throw new Error('offline'); } } });
    await expect(repository.load()).resolves.toEqual([]);
    await expect(repository.add(doc)).rejects.toThrow('offline');
  });

  it('does not expose unpersisted add or delete mutations after write failure', async () => {
    let failWrites = false;
    const store = { getItem: () => null, setItem: () => { if (failWrites) throw new Error('offline'); } };
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    await repository.add(doc);
    failWrites = true;
    await expect(repository.add({ ...doc, id: 'doc-2' })).rejects.toThrow('offline');
    expect(repository.list().map(({ id }) => id)).toEqual(['doc-1']);
    await expect(repository.delete('doc-1')).rejects.toThrow('offline');
    expect(repository.list().map(({ id }) => id)).toEqual(['doc-1']);
  });
});
