export const SIDEBAR_PORTFOLIO_KEY = 'dots:sidebar-portfolio';
export const SIDEBAR_PORTFOLIO_SCHEMA_VERSION = 1;

const EMPTY_PORTFOLIO = Object.freeze({ home: [], project: [], knowledge: [], activeHomeId: '' });
const PORTFOLIO_TYPES = new Set(['home', 'project', 'knowledge']);

const scopePart = (value) => { const text = String(value); return `${text.length}:${text}`; };
export const sidebarPortfolioStorageKey = (ownerId, spaceId) => `${SIDEBAR_PORTFOLIO_KEY}:${scopePart(ownerId)}:${scopePart(spaceId)}:v${SIDEBAR_PORTFOLIO_SCHEMA_VERSION}`;
export const legacySidebarPortfolioStorageKey = (ownerId, spaceId) => `${SIDEBAR_PORTFOLIO_KEY}:${ownerId}:${spaceId}`;

function validEntry(value, strict) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || typeof value.id !== 'string' || !value.id || typeof value.title !== 'string' || !value.title) return null;
  if (strict && (typeof value.archived !== 'boolean' || !Number.isFinite(value.updatedAt))) return null;
  if (value.archived !== undefined && typeof value.archived !== 'boolean') return null;
  if (value.updatedAt !== undefined && !Number.isFinite(Number(value.updatedAt))) return null;
  if (value.archivedAt !== undefined && !Number.isFinite(value.archivedAt)) return null;
  if (value.unread !== undefined && typeof value.unread !== 'boolean') return null;
  if (value.snapshot !== undefined && (!value.snapshot || typeof value.snapshot !== 'object' || Array.isArray(value.snapshot))) return null;
  return { ...value, archived: value.archived ?? false, updatedAt: Number(value.updatedAt) || 0 };
}

function normalizePortfolio(value, strict = false) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  if (strict && (!Array.isArray(value.home) || !Array.isArray(value.project) || !Array.isArray(value.knowledge) || typeof value.activeHomeId !== 'string')) return null;
  const result = { activeHomeId: typeof value.activeHomeId === 'string' ? value.activeHomeId : '' };
  for (const type of PORTFOLIO_TYPES) {
    const source = value[type] ?? [];
    if (!Array.isArray(source)) return null;
    const entries = source.slice(0, 100).map((entry) => validEntry(entry, strict));
    if (entries.some((entry) => entry === null)) return null;
    result[type] = entries;
  }
  return result;
}

export function createSidebarPortfolioRepository({ ownerId = 'local-owner', spaceId = 'local-space', storage = globalThis.localStorage } = {}) {
  const key = sidebarPortfolioStorageKey(ownerId, spaceId);
  const legacyKey = legacySidebarPortfolioStorageKey(ownerId, spaceId);
  let cachedLoad;
  let writeBlocked = false;
  let mutationQueue = Promise.resolve();

  const envelope = (portfolio) => ({ schemaVersion: SIDEBAR_PORTFOLIO_SCHEMA_VERSION, ownerId, spaceId, portfolio });
  const empty = () => ({ ...EMPTY_PORTFOLIO });
  function quarantine(sourceKey, raw) { try { const quarantineKey = `${sourceKey}:quarantine`; if (storage?.getItem(quarantineKey) == null) storage?.setItem(quarantineKey, raw); } catch { /* source raw remains untouched */ } }

  async function load() {
    if (cachedLoad) return cachedLoad;
    cachedLoad = Promise.resolve().then(() => {
      let raw;
      try { raw = storage?.getItem(key) ?? null; } catch { writeBlocked = true; return empty(); }
      if (raw != null) {
        try {
          const parsed = JSON.parse(raw);
          if (parsed?.schemaVersion !== SIDEBAR_PORTFOLIO_SCHEMA_VERSION || parsed.ownerId !== ownerId || parsed.spaceId !== spaceId) throw new Error('invalid portfolio envelope');
          const portfolio = normalizePortfolio(parsed.portfolio, true);
          if (!portfolio) throw new Error('invalid portfolio');
          return portfolio;
        } catch { writeBlocked = true; quarantine(key, raw); return empty(); }
      }
      try { raw = storage?.getItem(legacyKey) ?? null; } catch { writeBlocked = true; return empty(); }
      if (raw == null) return empty();
      try {
        const portfolio = normalizePortfolio(JSON.parse(raw));
        if (!portfolio) throw new Error('invalid legacy portfolio');
        try { storage?.setItem(key, JSON.stringify(envelope(portfolio))); } catch { /* legacy remains authoritative */ }
        return portfolio;
      } catch { writeBlocked = true; quarantine(legacyKey, raw); return empty(); }
    });
    return cachedLoad;
  }

  function commit(mutator) {
    const operation = mutationQueue.then(async () => {
      const current = await load();
      if (writeBlocked) throw new Error('Sidebar portfolio requires recovery before writing');
      const next = normalizePortfolio(mutator(current));
      if (!next) throw new Error('Invalid sidebar portfolio');
      storage?.setItem(key, JSON.stringify(envelope(next)));
      cachedLoad = Promise.resolve(next);
      return next;
    });
    mutationQueue = operation.catch(() => undefined);
    return operation;
  }
  const assertType = (type) => { if (!PORTFOLIO_TYPES.has(type)) throw new Error('Unknown portfolio type'); };
  const save = (value) => commit(() => value);
  const upsert = (type, entry) => { assertType(type); return commit((current) => { const existing = current[type].find((item) => item.id === entry.id); const nextEntry = { ...existing, ...entry, archived: false, updatedAt: Number(entry.updatedAt) || Date.now() }; return { ...current, [type]: [nextEntry, ...current[type].filter((item) => item.id !== entry.id)] }; }); };
  const ensure = (type, entry) => { assertType(type); return commit((current) => { const existing = current[type].find((item) => item.id === entry.id); const nextEntry = { ...existing, ...entry, archived: existing?.archived ?? false, updatedAt: Number(entry.updatedAt) || Date.now() }; return { ...current, [type]: [nextEntry, ...current[type].filter((item) => item.id !== entry.id)] }; }); };
  const upsertAndActivateHome = (entry) => commit((current) => { const existing = current.home.find((item) => item.id === entry.id); const nextEntry = { ...existing, ...entry, archived: false, updatedAt: Number(entry.updatedAt) || Date.now() }; return { ...current, activeHomeId: entry.id, home: [nextEntry, ...current.home.filter((item) => item.id !== entry.id)] }; });
  const setActiveHome = (id) => commit((current) => ({ ...current, activeHomeId: current.home.some((item) => item.id === id) ? id : '' }));
  const archive = (type, id) => { assertType(type); return commit((current) => ({ ...current, [type]: current[type].map((item) => item.id === id ? { ...item, archived: true, archivedAt: Date.now() } : item) })); };
  const restore = (type, id) => { if (type !== 'home' && type !== 'project') throw new Error('Unsupported restore type'); return commit((current) => { const item = current[type].find((entry) => entry.id === id); if (!item?.snapshot) throw new Error('Archived snapshot is unavailable'); const restored = { ...item, archived: false, archivedAt: undefined, updatedAt: Date.now() }; return { ...current, activeHomeId: type === 'home' ? id : current.activeHomeId, [type]: [restored, ...current[type].filter((entry) => entry.id !== id)] }; }); };
  const markRead = (type, id) => { assertType(type); return commit((current) => ({ ...current, [type]: current[type].map((item) => item.id === id ? { ...item, unread: false } : item) })); };
  return { load, save, upsert, ensure, upsertAndActivateHome, setActiveHome, archive, restore, markRead };
}
