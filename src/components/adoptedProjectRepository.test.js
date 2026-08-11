import { describe, expect, it, vi } from 'vitest';

import {
  ADOPTED_PROJECT_STORAGE_KEY,
  adoptedProjectStorageKey,
  createAdoptedProjectRepository,
} from './adoptedProjectRepository';

const candidate = { id: 'candidate-1', title: '保全ノート', fact: '現場で履歴検索に時間がかかる', inference: '検索可能な保全記録を検討する', reason: '対話で採用', status: 'adopted' };
const storedProject = (value = candidate, ownerId = 'local-owner', spaceId = 'local-space') => ({ ...value, ownerId, spaceId, status: 'adopted' });

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: vi.fn((key) => values.get(key) ?? null),
    setItem: vi.fn((key, value) => values.set(key, String(value))),
    values,
  };
}

describe('adopted project repository', () => {
  it('uses collision-safe owner and space scoped keys', () => {
    expect(adoptedProjectStorageKey('a:b', 'c')).not.toBe(adoptedProjectStorageKey('a', 'b:c'));
    expect(adoptedProjectStorageKey('owner-a', 'space-a')).toBe('kadode:adopted-projects:7:owner-a:7:space-a:v1');
  });

  it('persists and restores the current scope after remount', async () => {
    const storage = memoryStorage();
    const options = { ownerId: 'owner-a', spaceId: 'space-a', storage };
    const repository = createAdoptedProjectRepository(options);
    await repository.saveAdopted(candidate);
    expect(repository.current()).toMatchObject(candidate);
    await expect(createAdoptedProjectRepository(options).load()).resolves.toMatchObject(candidate);
  });

  it('copies valid global legacy data to the scoped envelope without changing the source raw', async () => {
    const raw = JSON.stringify({ schemaVersion: 1, projects: [
      storedProject(candidate, 'owner-a', 'space-a'),
      storedProject({ ...candidate, id: 'other' }, 'owner-b', 'space-b'),
    ] });
    const storage = memoryStorage({ [ADOPTED_PROJECT_STORAGE_KEY]: raw });
    const repository = createAdoptedProjectRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    await expect(repository.load()).resolves.toMatchObject({ id: candidate.id });
    expect(storage.getItem(ADOPTED_PROJECT_STORAGE_KEY)).toBe(raw);
    expect(JSON.parse(storage.getItem(adoptedProjectStorageKey('owner-a', 'space-a')))).toMatchObject({
      schemaVersion: 1, ownerId: 'owner-a', spaceId: 'space-a', projects: [expect.objectContaining({ id: candidate.id })],
    });
  });

  it('retains legacy raw when migration write fails and later writes only the scoped key', async () => {
    const raw = JSON.stringify({ schemaVersion: 1, projects: [storedProject(candidate)] });
    const storage = memoryStorage({ [ADOPTED_PROJECT_STORAGE_KEY]: raw });
    storage.setItem.mockImplementationOnce(() => { throw new Error('quota'); });
    const repository = createAdoptedProjectRepository({ storage });
    await expect(repository.load()).resolves.toMatchObject(candidate);
    await expect(repository.saveAdopted({ ...candidate, title: '更新後' })).resolves.toMatchObject({ title: '更新後' });
    expect(storage.getItem(ADOPTED_PROJECT_STORAGE_KEY)).toBe(raw);
    expect(JSON.parse(storage.getItem(adoptedProjectStorageKey('local-owner', 'local-space'))).projects[0].title).toBe('更新後');
  });

  it.each([
    ['malformed JSON', '{broken'],
    ['future schema', JSON.stringify({ schemaVersion: 2, ownerId: 'local-owner', spaceId: 'local-space', projects: [] })],
    ['partial project', JSON.stringify({ schemaVersion: 1, ownerId: 'local-owner', spaceId: 'local-space', projects: [storedProject(candidate), { id: 'partial' }] })],
    ['missing current metadata', JSON.stringify({ schemaVersion: 1, ownerId: 'local-owner', spaceId: 'local-space', projects: [{ ...storedProject(candidate), reason: undefined }] })],
  ])('quarantines exact scoped %s and blocks the next mutation without overwriting raw', async (_label, raw) => {
    const key = adoptedProjectStorageKey('local-owner', 'local-space');
    const storage = memoryStorage({ [key]: raw });
    const repository = createAdoptedProjectRepository({ storage });
    await expect(repository.load()).resolves.toBeNull();
    expect(storage.getItem(key)).toBe(raw);
    expect(storage.getItem(`${key}:quarantine`)).toBe(raw);
    await expect(repository.saveAdopted(candidate)).rejects.toThrow(/recovery/);
    expect(storage.getItem(key)).toBe(raw);
    expect(repository.getLastError()).toBeInstanceOf(Error);
  });

  it('quarantines an invalid global legacy envelope without deleting or replacing it', async () => {
    const raw = JSON.stringify({ schemaVersion: 1, projects: [storedProject(candidate), { id: 'partial' }] });
    const storage = memoryStorage({ [ADOPTED_PROJECT_STORAGE_KEY]: raw });
    const repository = createAdoptedProjectRepository({ storage });
    await expect(repository.load()).resolves.toBeNull();
    expect(storage.getItem(ADOPTED_PROJECT_STORAGE_KEY)).toBe(raw);
    expect(storage.getItem(`${ADOPTED_PROJECT_STORAGE_KEY}:quarantine`)).toBe(raw);
    await expect(repository.clearAdopted()).rejects.toThrow(/recovery/);
  });

  it('blocks writes after a storage read exception and retries after recovery', async () => {
    const storage = memoryStorage();
    const originalGet = storage.getItem;
    let failing = true;
    storage.getItem = vi.fn((key) => { if (failing) throw new Error('denied'); return originalGet(key); });
    const repository = createAdoptedProjectRepository({ storage });
    await expect(repository.load()).resolves.toBeNull();
    await expect(repository.saveAdopted(candidate)).rejects.toThrow(/recovery/);
    expect(storage.setItem).not.toHaveBeenCalled();
    failing = false;
    await expect(repository.retryLoad()).resolves.toBeNull();
    expect(repository.getLastError()).toBeNull();
    await expect(repository.saveAdopted(candidate)).resolves.toMatchObject(candidate);
  });

  it('isolates interleaved A/B save, clear, and select operations after simultaneous loads', async () => {
    const storage = memoryStorage();
    const aOptions = { ownerId: 'a:b', spaceId: 'c', storage };
    const bOptions = { ownerId: 'a', spaceId: 'b:c', storage };
    const a = createAdoptedProjectRepository(aOptions);
    const b = createAdoptedProjectRepository(bOptions);
    await Promise.all([a.load(), b.load()]);
    await a.saveAdopted({ ...candidate, id: 'a-1', title: 'A 1' });
    await b.saveAdopted({ ...candidate, id: 'b-1', title: 'B 1' });
    await a.saveAdopted({ ...candidate, id: 'a-2', title: 'A 2' });
    await b.saveAdopted({ ...candidate, id: 'b-2', title: 'B 2' });
    await a.selectCurrent('a-1');
    await b.clearAdopted();
    expect(a.current()).toMatchObject({ id: 'a-1' });
    expect(b.current()).toBeNull();
    await expect(createAdoptedProjectRepository(aOptions).load()).resolves.toMatchObject({ id: 'a-1' });
    await expect(createAdoptedProjectRepository(bOptions).load()).resolves.toBeNull();
  });

  it('does not mutate cache when select persistence fails and can retry', async () => {
    const storage = memoryStorage();
    const repository = createAdoptedProjectRepository({ storage });
    await repository.saveAdopted({ ...candidate, id: 'one', title: 'One' });
    await repository.saveAdopted({ ...candidate, id: 'two', title: 'Two' });
    storage.setItem.mockImplementationOnce(() => { throw new Error('quota'); });
    await expect(repository.selectCurrent('one')).rejects.toThrow('quota');
    expect(repository.current()).toMatchObject({ id: 'two' });
    await expect(repository.selectCurrent('one')).resolves.toMatchObject({ id: 'one' });
  });
});
