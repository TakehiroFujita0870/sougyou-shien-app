import { describe, expect, it, vi } from 'vitest';

import { ADOPTED_PROJECT_STORAGE_KEY, createAdoptedProjectRepository } from './adoptedProjectRepository';

const candidate = { id: 'candidate-1', title: '保全ノート', fact: '現場で履歴検索に時間がかかる', inference: '検索可能な保全記録を検討する', reason: '対話で採用', status: 'adopted' };

function storageWith(value = null) {
  const values = new Map(value === null ? [] : [[ADOPTED_PROJECT_STORAGE_KEY, value]]);
  return {
    getItem: vi.fn((key) => values.get(key) ?? null),
    setItem: vi.fn((key, next) => values.set(key, String(next))),
  };
}

describe('adopted project repository', () => {
  it('persists title, fact, inference, reason, and status after an adoption', async () => {
    const storage = storageWith();
    const repository = createAdoptedProjectRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });

    await repository.saveAdopted(candidate);
    const reloaded = createAdoptedProjectRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });

    await expect(reloaded.load()).resolves.toMatchObject(candidate);
  });

  it('returns only the current owner and space records', async () => {
    const storage = storageWith(JSON.stringify({ schemaVersion: 1, projects: [
      { ...candidate, ownerId: 'owner-a', spaceId: 'space-a' },
      { ...candidate, id: 'candidate-2', title: '別空間', ownerId: 'owner-a', spaceId: 'space-b' },
      { ...candidate, id: 'candidate-3', title: '別所有者', ownerId: 'owner-b', spaceId: 'space-a' },
    ] }));

    const repository = createAdoptedProjectRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    await expect(repository.load()).resolves.toMatchObject({ id: 'candidate-1', title: '保全ノート' });
    expect(repository.list()).toHaveLength(1);
  });

  it('replaces only the same id within the current owner and space', async () => {
    const storage = storageWith(JSON.stringify({ schemaVersion: 1, projects: [
      { ...candidate, ownerId: 'owner-b', spaceId: 'space-a', title: '別所有者の同一ID' },
      { ...candidate, ownerId: 'owner-a', spaceId: 'space-b', title: '別空間の同一ID' },
    ] }));
    const repository = createAdoptedProjectRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });

    await repository.saveAdopted(candidate);

    const projects = JSON.parse(storage.getItem(ADOPTED_PROJECT_STORAGE_KEY)).projects;
    expect(projects).toHaveLength(3);
    expect(projects).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: candidate.id, ownerId: 'owner-b', spaceId: 'space-a', title: '別所有者の同一ID' }),
      expect.objectContaining({ id: candidate.id, ownerId: 'owner-a', spaceId: 'space-b', title: '別空間の同一ID' }),
      expect.objectContaining({ id: candidate.id, ownerId: 'owner-a', spaceId: 'space-a', title: candidate.title }),
    ]));
  });

  it('quarantines corrupt data without overwriting it during hydration', async () => {
    const storage = storageWith('{broken');
    const repository = createAdoptedProjectRepository({ storage });

    await expect(repository.load()).resolves.toBeNull();
    expect(storage.setItem).not.toHaveBeenCalled();
    await expect(repository.saveAdopted(candidate)).rejects.toThrow(/recovery/);
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it('does not read or rewrite an unsupported future schema', async () => {
    const futureValue = JSON.stringify({ schemaVersion: 2, projects: [{ ...candidate, ownerId: 'local-owner', spaceId: 'local-space' }] });
    const storage = storageWith(futureValue);
    const repository = createAdoptedProjectRepository({ storage });

    await expect(repository.load()).resolves.toBeNull();
    await expect(repository.saveAdopted(candidate)).rejects.toThrow(/recovery/);
    expect(storage.setItem).not.toHaveBeenCalled();
    expect(storage.getItem(ADOPTED_PROJECT_STORAGE_KEY)).toBe(futureValue);
  });

  it('loads browser storage only once for a stable repository instance', async () => {
    const storage = storageWith();
    const repository = createAdoptedProjectRepository({ storage });

    await Promise.all([repository.load(), repository.load()]);
    expect(storage.getItem).toHaveBeenCalledTimes(1);
  });
});
