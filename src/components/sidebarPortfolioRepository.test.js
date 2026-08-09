import { describe, expect, it } from 'vitest';
import { createSidebarPortfolioRepository } from './sidebarPortfolioRepository';

function createStorage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

describe('sidebar portfolio repository', () => {
  it('persists active and archived history independently by owner and space', async () => {
    const storage = createStorage();
    const ownerA = createSidebarPortfolioRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    const ownerB = createSidebarPortfolioRepository({ ownerId: 'owner-b', spaceId: 'space-a', storage });
    await ownerA.upsert('home', { id: 'home:default', title: '工場の困りごと' });
    await ownerA.archive('home', 'home:default');

    expect((await ownerA.load()).home).toEqual([expect.objectContaining({ id: 'home:default', archived: true })]);
    expect((await ownerB.load()).home).toEqual([]);
  });

  it('reopens an archived item only when a new active mirror is explicitly upserted', async () => {
    const repository = createSidebarPortfolioRepository({ storage: createStorage() });
    await repository.upsert('project', { id: 'project:1', title: '保全ノート' });
    await repository.archive('project', 'project:1');
    await repository.upsert('project', { id: 'project:1', title: '保全ノート' });

    expect((await repository.load()).project).toEqual([expect.objectContaining({ id: 'project:1', archived: false })]);
  });

  it('quarantines malformed storage without leaking a partial portfolio', async () => {
    const repository = createSidebarPortfolioRepository({ storage: { getItem: () => '{', setItem: () => {} } });
    await expect(repository.load()).resolves.toEqual({ home: [], project: [], knowledge: [] });
  });

  it('serializes concurrent mirror and adoption writes without dropping either item', async () => {
    const repository = createSidebarPortfolioRepository({ storage: createStorage() });
    await Promise.all([
      repository.ensure('knowledge', { id: 'asset:1', title: '資料' }),
      repository.upsert('project', { id: 'project:1', title: '採用した事業' }),
    ]);
    const saved = await repository.load();
    expect(saved.knowledge).toEqual([expect.objectContaining({ id: 'asset:1' })]);
    expect(saved.project).toEqual([expect.objectContaining({ id: 'project:1' })]);
  });

  it('bounds the all-items contract to the newest 100 records and marks Knowledge as read', async () => {
    const repository = createSidebarPortfolioRepository({ storage: createStorage() });
    for (let index = 0; index < 105; index += 1) await repository.upsert('knowledge', { id: `knowledge:${index}`, title: `資料 ${index}`, unread: true, updatedAt: index + 1 });
    const bounded = await repository.load();
    expect(bounded.knowledge).toHaveLength(100);
    expect(bounded.knowledge[0].id).toBe('knowledge:104');
    const read = await repository.markRead('knowledge', 'knowledge:104');
    expect(read.knowledge[0]).toMatchObject({ id: 'knowledge:104', unread: false });
  });
});
