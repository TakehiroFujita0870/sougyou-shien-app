export const SIDEBAR_PORTFOLIO_KEY = 'kadode:sidebar-portfolio';
export function createSidebarPortfolioRepository({ ownerId = 'local-owner', spaceId = 'local-space', storage = globalThis.localStorage } = {}) {
  const key = `${SIDEBAR_PORTFOLIO_KEY}:${ownerId}:${spaceId}`;
  const empty = { home: [], project: [], knowledge: [] };
  const types = new Set(Object.keys(empty));
  const normalizeEntries = (entries) => (Array.isArray(entries) ? entries : [])
    .filter((entry) => entry && typeof entry.id === 'string' && typeof entry.title === 'string')
    .slice(0, 100)
    .map((entry) => ({ ...entry, archived: Boolean(entry.archived), updatedAt: Number(entry.updatedAt) || 0 }));
  const normalize = (value) => ({
    home: normalizeEntries(value?.home),
    project: normalizeEntries(value?.project),
    knowledge: normalizeEntries(value?.knowledge),
  });
  async function load() {
    try { return normalize(JSON.parse(storage.getItem(key) || '{}')); } catch { return { ...empty }; }
  }
  async function save(value) {
    const next = normalize(value);
    storage.setItem(key, JSON.stringify(next));
    return next;
  }
  async function upsert(type, entry) {
    if (!types.has(type)) throw new Error('Unknown portfolio type');
    const current = await load();
    const existing = current[type].find((item) => item.id === entry.id);
    const nextEntry = { ...existing, ...entry, archived: false, updatedAt: Number(entry.updatedAt) || Date.now() };
    return save({ ...current, [type]: [nextEntry, ...current[type].filter((item) => item.id !== entry.id)] });
  }
  async function archive(type, id) {
    if (!types.has(type)) throw new Error('Unknown portfolio type');
    const current = await load();
    return save({ ...current, [type]: current[type].map((item) => item.id === id ? { ...item, archived: true, archivedAt: Date.now() } : item) });
  }
  return { load, save, upsert, archive };
}
