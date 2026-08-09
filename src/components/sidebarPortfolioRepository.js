export const SIDEBAR_PORTFOLIO_KEY = 'kadode:sidebar-portfolio';
export function createSidebarPortfolioRepository({ ownerId = 'local-owner', spaceId = 'local-space', storage = globalThis.localStorage } = {}) {
  const key = `${SIDEBAR_PORTFOLIO_KEY}:${ownerId}:${spaceId}`;
  const empty = { home: [], project: [], knowledge: [], activeHomeId: '' };
  const types = new Set(Object.keys(empty));
  // The all-items dialog is intentionally bounded to the newest 100 local records per surface.
  const normalizeEntries = (entries) => (Array.isArray(entries) ? entries : [])
    .filter((entry) => entry && typeof entry.id === 'string' && typeof entry.title === 'string')
    .slice(0, 100)
    .map((entry) => ({ ...entry, archived: Boolean(entry.archived), updatedAt: Number(entry.updatedAt) || 0 }));
  const normalize = (value) => ({
    home: normalizeEntries(value?.home),
    project: normalizeEntries(value?.project),
    knowledge: normalizeEntries(value?.knowledge),
    activeHomeId: typeof value?.activeHomeId === 'string' ? value.activeHomeId : '',
  });
  async function load() {
    try { return normalize(JSON.parse(storage.getItem(key) || '{}')); } catch { return { ...empty }; }
  }
  let mutationQueue = Promise.resolve();
  function commit(mutator) {
    const operation = mutationQueue.then(async () => {
      const current = await load();
      const next = normalize(mutator(current));
      storage.setItem(key, JSON.stringify(next));
      return next;
    });
    mutationQueue = operation.catch(() => undefined);
    return operation;
  }
  async function save(value) {
    return commit(() => value);
  }
  async function upsert(type, entry) {
    if (!types.has(type)) throw new Error('Unknown portfolio type');
    return commit((current) => {
      const existing = current[type].find((item) => item.id === entry.id);
      const nextEntry = { ...existing, ...entry, archived: false, updatedAt: Number(entry.updatedAt) || Date.now() };
      return { ...current, [type]: [nextEntry, ...current[type].filter((item) => item.id !== entry.id)] };
    });
  }
  async function ensure(type, entry) {
    if (!types.has(type)) throw new Error('Unknown portfolio type');
    return commit((current) => {
      const existing = current[type].find((item) => item.id === entry.id);
      const nextEntry = { ...existing, ...entry, archived: existing?.archived ?? false, updatedAt: Number(entry.updatedAt) || Date.now() };
      return { ...current, [type]: [nextEntry, ...current[type].filter((item) => item.id !== entry.id)] };
    });
  }
  async function upsertAndActivateHome(entry) {
    return commit((current) => {
      const existing = current.home.find((item) => item.id === entry.id);
      const nextEntry = { ...existing, ...entry, archived: false, updatedAt: Number(entry.updatedAt) || Date.now() };
      return { ...current, activeHomeId: entry.id, home: [nextEntry, ...current.home.filter((item) => item.id !== entry.id)] };
    });
  }
  async function setActiveHome(id) {
    return commit((current) => ({ ...current, activeHomeId: current.home.some((item) => item.id === id) ? id : '' }));
  }
  async function archive(type, id) {
    if (!types.has(type)) throw new Error('Unknown portfolio type');
    return commit((current) => ({ ...current, [type]: current[type].map((item) => item.id === id ? { ...item, archived: true, archivedAt: Date.now() } : item) }));
  }
  async function restore(type, id) {
    if (type !== 'home' && type !== 'project') throw new Error('Unsupported restore type');
    return commit((current) => {
      const item = current[type].find((entry) => entry.id === id);
      if (!item?.snapshot) throw new Error('Archived snapshot is unavailable');
      const restored = { ...item, archived: false, archivedAt: undefined, updatedAt: Date.now() };
      return {
        ...current,
        activeHomeId: type === 'home' ? id : current.activeHomeId,
        [type]: [restored, ...current[type].filter((entry) => entry.id !== id)],
      };
    });
  }
  async function markRead(type, id) {
    if (!types.has(type)) throw new Error('Unknown portfolio type');
    return commit((current) => ({ ...current, [type]: current[type].map((item) => item.id === id ? { ...item, unread: false } : item) }));
  }
  return { load, save, upsert, ensure, upsertAndActivateHome, setActiveHome, archive, restore, markRead };
}
