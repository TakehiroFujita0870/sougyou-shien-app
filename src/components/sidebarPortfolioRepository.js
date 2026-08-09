export const SIDEBAR_PORTFOLIO_KEY = 'kadode:sidebar-portfolio';
export function createSidebarPortfolioRepository({ ownerId = 'local-owner', spaceId = 'local-space', storage = globalThis.localStorage } = {}) {
  const key = `${SIDEBAR_PORTFOLIO_KEY}:${ownerId}:${spaceId}`;
  const empty = { home: [], project: [], knowledge: [] };
  const normalize = (value) => ({ ...empty, ...value, home: Array.isArray(value?.home) ? value.home.slice(0, 100) : [], project: Array.isArray(value?.project) ? value.project.slice(0, 100) : [], knowledge: Array.isArray(value?.knowledge) ? value.knowledge.slice(0, 100) : [] });
  return { async load() { try { return normalize(JSON.parse(storage.getItem(key) || '{}')); } catch { return empty; } }, async save(value) { const next = normalize(value); storage.setItem(key, JSON.stringify(next)); return next; }, async upsert(type, entry) { const current = await this.load(); const next = { ...current, [type]: [{ ...entry, archived: false }, ...current[type].filter((item) => item.id !== entry.id)] }; return this.save(next); } };
}
