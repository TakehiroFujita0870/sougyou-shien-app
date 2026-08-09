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
    const third = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    await third.load();
    expect(third.list()).toEqual([]);
    expect(third.find('doc-1')).toMatchObject({ state: 'deleted' });
  });

  it('persists metadata-only PDF/DOCX fields without a binary payload', async () => {
    const store = storage();
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    await repository.add({ id: 'local-file:brief.pdf:2048:1', name: 'brief.pdf', version: 1, state: 'metadata_only', mediaType: 'pdf', sizeBytes: 2048, lastModified: 1 });
    const [persisted] = repository.list();
    expect(persisted).toMatchObject({ name: 'brief.pdf', state: 'metadata_only', mediaType: 'pdf', sizeBytes: 2048, lastModified: 1 });
    expect(persisted).not.toHaveProperty('content');
    expect(JSON.stringify(persisted)).not.toContain('Blob');
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

  it('persists a tombstone for a fixture that was not previously added', async () => {
    const store = storage();
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    await repository.load();
    await repository.delete('fixture-1', { id: 'fixture-1', name: 'fixture.pdf', state: 'searchable' });
    expect(repository.find('fixture-1')).toMatchObject({ state: 'deleted', ownerId: 'a', spaceId: 's' });
  });

  it('uses the composite id, owner, and space key when replacing or tombstoning metadata', async () => {
    const store = storage({ schemaVersion: 1, documents: [{ ...doc, ownerId: 'other-owner', spaceId: 'other-space' }] });
    const repository = createKnowledgeMetadataRepository({ ownerId: 'a', spaceId: 's', storage: store });
    await repository.load();
    await repository.add(doc);
    await repository.delete(doc.id);
    const persisted = JSON.parse(store.setItem.mock.calls.at(-1)[1]).documents;
    expect(persisted).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: doc.id, ownerId: 'other-owner', spaceId: 'other-space', state: 'searchable' }),
      expect.objectContaining({ id: doc.id, ownerId: 'a', spaceId: 's', state: 'deleted' }),
    ]));
  });
});
