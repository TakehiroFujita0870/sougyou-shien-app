import { describe, expect, it } from 'vitest';
import { createSidebarPortfolioRepository, legacySidebarPortfolioStorageKey, sidebarPortfolioStorageKey, SIDEBAR_PORTFOLIO_SCHEMA_VERSION } from './sidebarPortfolioRepository';

function createStorage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), values };
}

describe('sidebar portfolio repository', () => {
  it('uses collision-safe owner-space keys while retaining the legacy key contract', () => {
    expect(sidebarPortfolioStorageKey('a:b', 'c')).not.toBe(sidebarPortfolioStorageKey('a', 'b:c'));
    expect(legacySidebarPortfolioStorageKey('a:b', 'c')).toBe(legacySidebarPortfolioStorageKey('a', 'b:c'));
  });

  it('keeps formerly colliding A/B scopes isolated across save and F5 remount', async () => {
    const storage = createStorage();
    const first = createSidebarPortfolioRepository({ ownerId: 'a:b', spaceId: 'c', storage });
    const second = createSidebarPortfolioRepository({ ownerId: 'a', spaceId: 'b:c', storage });
    await first.upsert('home', { id: 'first', title: 'first' });
    await second.upsert('home', { id: 'second', title: 'second' });
    expect((await createSidebarPortfolioRepository({ ownerId: 'a:b', spaceId: 'c', storage }).load()).home.map((entry) => entry.id)).toEqual(['first']);
    expect((await createSidebarPortfolioRepository({ ownerId: 'a', spaceId: 'b:c', storage }).load()).home.map((entry) => entry.id)).toEqual(['second']);
  });

  it('copies valid legacy state to the scoped envelope without changing the source raw', async () => {
    const storage = createStorage();
    const legacyKey = legacySidebarPortfolioStorageKey('owner-a', 'space-a');
    const key = sidebarPortfolioStorageKey('owner-a', 'space-a');
    const raw = JSON.stringify({ home: [{ id: 'home:legacy', title: 'legacy' }], project: [], knowledge: [], activeHomeId: 'home:legacy' });
    storage.values.set(legacyKey, raw);
    const repository = createSidebarPortfolioRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect((await repository.load()).home[0].id).toBe('home:legacy');
    expect(storage.getItem(legacyKey)).toBe(raw);
    expect(JSON.parse(storage.getItem(key))).toMatchObject({ schemaVersion: SIDEBAR_PORTFOLIO_SCHEMA_VERSION, ownerId: 'owner-a', spaceId: 'space-a' });
    expect((await createSidebarPortfolioRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage }).load()).activeHomeId).toBe('home:legacy');
  });

  it('retains the exact legacy source when migration storage fails and writes the scoped key on the next mutation', async () => {
    const legacyKey = legacySidebarPortfolioStorageKey('owner-a', 'space-a');
    const key = sidebarPortfolioStorageKey('owner-a', 'space-a');
    const raw = JSON.stringify({ home: [], project: [], knowledge: [], activeHomeId: '' });
    const values = new Map([[legacyKey, raw]]); let failMigration = true;
    const storage = { getItem: (name) => values.get(name) ?? null, setItem: (name, value) => { if (name === key && failMigration) { failMigration = false; throw new Error('quota'); } values.set(name, String(value)); } };
    const repository = createSidebarPortfolioRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect(await repository.load()).toEqual({ home: [], project: [], knowledge: [], activeHomeId: '' });
    expect(storage.getItem(legacyKey)).toBe(raw);
    expect(storage.getItem(key)).toBeNull();
    await repository.ensure('knowledge', { id: 'knowledge:new', title: 'new' });
    expect(JSON.parse(storage.getItem(key)).portfolio.knowledge[0].id).toBe('knowledge:new');
    expect(storage.getItem(legacyKey)).toBe(raw);
  });

  it.each([
    ['malformed', '{broken'],
    ['future', JSON.stringify({ schemaVersion: 2, ownerId: 'owner-a', spaceId: 'space-a', portfolio: { home: [], project: [], knowledge: [], activeHomeId: '' } })],
    ['partial entry', JSON.stringify({ schemaVersion: 1, ownerId: 'owner-a', spaceId: 'space-a', portfolio: { home: [{ id: 'partial', title: 'partial' }], project: [], knowledge: [], activeHomeId: '' } })],
    ['invalid metadata', JSON.stringify({ schemaVersion: 1, ownerId: 'owner-a', spaceId: 'space-a', portfolio: { home: [], project: [], knowledge: [{ id: 'k', title: 'k', archived: false, updatedAt: 1, unread: 'yes' }], activeHomeId: '' } })],
  ])('quarantines exact %s raw, preserves it, and blocks the next mutation', async (_label, raw) => {
    const storage = createStorage();
    const key = sidebarPortfolioStorageKey('owner-a', 'space-a');
    storage.values.set(key, raw);
    const repository = createSidebarPortfolioRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect(await repository.load()).toEqual({ home: [], project: [], knowledge: [], activeHomeId: '' });
    expect(storage.getItem(key)).toBe(raw);
    expect(storage.getItem(`${key}:quarantine`)).toBe(raw);
    await expect(repository.upsert('home', { id: 'no-overwrite', title: 'no-overwrite' })).rejects.toThrow('recovery');
    expect(storage.getItem(key)).toBe(raw);
  });

  it('blocks writes after a storage read exception and leaves the source untouched', async () => {
    const key = sidebarPortfolioStorageKey('owner-a', 'space-a');
    const raw = 'unreadable-source'; let throwRead = true;
    const storage = { getItem: (name) => { if (name === key && throwRead) { throwRead = false; throw new Error('denied'); } return name === key ? raw : null; }, setItem: () => { throw new Error('must not write'); } };
    const repository = createSidebarPortfolioRepository({ ownerId: 'owner-a', spaceId: 'space-a', storage });
    expect(await repository.load()).toEqual({ home: [], project: [], knowledge: [], activeHomeId: '' });
    await expect(repository.ensure('knowledge', { id: 'blocked', title: 'blocked' })).rejects.toThrow('recovery');
    expect(storage.getItem(key)).toBe(raw);
  });

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
