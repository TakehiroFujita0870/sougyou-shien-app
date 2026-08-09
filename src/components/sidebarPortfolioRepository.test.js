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
    await expect(repository.load()).resolves.toEqual({ home: [], project: [], knowledge: [], activeHomeId: '' });
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

  it('persists the active Home id with the matching conversation snapshot', async () => {
    const storage = createStorage();
    const repository = createSidebarPortfolioRepository({ storage });
    const first = { messages: [{ role: 'user', content: 'first' }], proposals: [], input: '' };
    const second = { messages: [{ role: 'user', content: 'second' }], proposals: [], input: '' };
    await repository.upsertAndActivateHome({ id: 'home:first', title: 'first', snapshot: first });
    await repository.upsertAndActivateHome({ id: 'home:second', title: 'second', snapshot: second });
    await repository.archive('home', 'home:second');
    const reloaded = await createSidebarPortfolioRepository({ storage }).load();
    expect(reloaded.activeHomeId).toBe('home:second');
    expect(reloaded.home.find((item) => item.id === reloaded.activeHomeId)).toMatchObject({ archived: true, snapshot: second });
  });

  it('restores an archived owner-space scoped snapshot and reactivates Home atomically', async () => {
    const storage = createStorage();
    const repository = createSidebarPortfolioRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    const snapshot = { messages: [{ role: 'user', content: '再開する会話' }] };
    await repository.upsertAndActivateHome({ id: 'home:restore', title: '再開する会話', snapshot });
    await repository.archive('home', 'home:restore');
    const restored = await repository.restore('home', 'home:restore');
    expect(restored.activeHomeId).toBe('home:restore');
    expect(restored.home[0]).toMatchObject({ archived: false, snapshot });
    await expect(createSidebarPortfolioRepository({ ownerId: 'owner-b', spaceId: 'space-a', storage }).restore('home', 'home:restore')).rejects.toThrow('Archived snapshot is unavailable');
  });
});
