export const ADOPTED_PROJECT_SCHEMA_VERSION = 1;
export const ADOPTED_PROJECT_STORAGE_KEY = 'dots:adopted-projects';

function scopePart(value) {
  const text = String(value);
  return `${text.length}:${text}`;
}

export function adoptedProjectStorageKey(ownerId, spaceId) {
  return `${ADOPTED_PROJECT_STORAGE_KEY}:${scopePart(ownerId)}:${scopePart(spaceId)}:v${ADOPTED_PROJECT_SCHEMA_VERSION}`;
}

function isNonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

export function normalizeAdoptedProject(value) {
  if (!value || typeof value !== 'object') return null;
  if (!isNonEmptyString(value.id) || !isNonEmptyString(value.ownerId) || !isNonEmptyString(value.spaceId)) return null;
  if (!isNonEmptyString(value.title) || !isNonEmptyString(value.fact) || !isNonEmptyString(value.inference)) return null;
  if (value.status !== 'adopted') return null;
  if (value.reason !== undefined && typeof value.reason !== 'string') return null;
  return {
    id: value.id,
    ownerId: value.ownerId,
    spaceId: value.spaceId,
    title: value.title.trim(),
    fact: value.fact.trim(),
    inference: value.inference.trim(),
    reason: typeof value.reason === 'string' ? value.reason.trim() : '',
    status: 'adopted',
  };
}

function parseProjects(value, strict = false) {
  if (!Array.isArray(value)) return null;
  const normalized = value.map((project) => strict && !Object.hasOwn(project ?? {}, 'reason') ? null : normalizeAdoptedProject(project));
  return normalized.some((project) => project === null) ? null : normalized;
}

export function createAdoptedProjectRepository({ ownerId = 'local-owner', spaceId = 'local-space', storage = globalThis.localStorage } = {}) {
  const scopedKey = adoptedProjectStorageKey(ownerId, spaceId);
  let records = [];
  let loadPromise;
  let writeBlocked = false;
  let lastError = null;

  const list = () => [...records];
  const current = () => records.at(0) ?? null;
  const envelope = (projects) => ({ schemaVersion: ADOPTED_PROJECT_SCHEMA_VERSION, ownerId, spaceId, projects });

  function quarantine(sourceKey, raw) {
    try {
      const quarantineKey = `${sourceKey}:quarantine`;
      if (storage?.getItem(quarantineKey) == null) storage?.setItem(quarantineKey, raw);
    } catch {
      // Best effort only. The source raw remains authoritative and writes stay blocked.
    }
  }

  function fail(sourceKey, raw, error) {
    records = [];
    writeBlocked = true;
    lastError = error instanceof Error ? error : new Error('Invalid adopted projects');
    if (raw != null) quarantine(sourceKey, raw);
    return null;
  }

  function parseScoped(raw) {
    const parsed = JSON.parse(raw);
    if (parsed?.schemaVersion !== ADOPTED_PROJECT_SCHEMA_VERSION || parsed.ownerId !== ownerId || parsed.spaceId !== spaceId) {
      throw new Error('Invalid scoped adopted project envelope');
    }
    const projects = parseProjects(parsed.projects, true);
    if (!projects || projects.some((project) => project.ownerId !== ownerId || project.spaceId !== spaceId)) {
      throw new Error('Invalid scoped adopted project records');
    }
    return projects;
  }

  function parseLegacy(raw) {
    const parsed = JSON.parse(raw);
    if (parsed?.schemaVersion !== ADOPTED_PROJECT_SCHEMA_VERSION) throw new Error('Invalid legacy adopted project envelope');
    const projects = parseProjects(parsed.projects);
    if (!projects) throw new Error('Invalid legacy adopted project records');
    return projects.filter((project) => project.ownerId === ownerId && project.spaceId === spaceId);
  }

  async function load() {
    if (loadPromise) return loadPromise;
    loadPromise = Promise.resolve().then(() => {
      let raw;
      try {
        raw = storage?.getItem(scopedKey) ?? null;
      } catch (error) {
        return fail(scopedKey, null, error);
      }
      if (raw != null) {
        try {
          records = parseScoped(raw);
          writeBlocked = false;
          lastError = null;
          return current();
        } catch (error) {
          return fail(scopedKey, raw, error);
        }
      }

      let legacyRaw;
      try {
        legacyRaw = storage?.getItem(ADOPTED_PROJECT_STORAGE_KEY) ?? null;
      } catch (error) {
        return fail(ADOPTED_PROJECT_STORAGE_KEY, null, error);
      }
      if (legacyRaw == null) {
        records = [];
        writeBlocked = false;
        lastError = null;
        return null;
      }
      try {
        records = parseLegacy(legacyRaw);
        writeBlocked = false;
        lastError = null;
        try { storage?.setItem(scopedKey, JSON.stringify(envelope(records))); } catch { /* legacy remains unchanged */ }
        return current();
      } catch (error) {
        return fail(ADOPTED_PROJECT_STORAGE_KEY, legacyRaw, error);
      }
    });
    return loadPromise;
  }

  function persist(next) {
    storage?.setItem(scopedKey, JSON.stringify(envelope(next)));
    records = next;
    loadPromise = Promise.resolve(current());
    lastError = null;
  }

  async function saveAdopted(candidate) {
    await load();
    if (writeBlocked) throw new Error('Stored adopted projects require recovery before writing');
    const project = normalizeAdoptedProject({
      id: candidate?.id,
      ownerId,
      spaceId,
      title: candidate?.title,
      fact: candidate?.fact,
      inference: candidate?.inference,
      reason: candidate?.reason,
      status: 'adopted',
    });
    if (!project) throw new Error('Invalid adopted project');
    persist([project, ...records.filter((record) => record.id !== project.id)]);
    return project;
  }

  async function clearAdopted() {
    await load();
    if (writeBlocked) throw new Error('Stored adopted projects require recovery before writing');
    persist([]);
    return null;
  }

  async function selectCurrent(id) {
    await load();
    if (writeBlocked) throw new Error('Stored adopted projects require recovery before writing');
    const selected = records.find((record) => record.id === id);
    if (!selected) return null;
    persist([selected, ...records.filter((record) => record !== selected)]);
    return selected;
  }

  function retryLoad() {
    loadPromise = undefined;
    writeBlocked = false;
    lastError = null;
    return load();
  }

  return { load, list, current, saveAdopted, clearAdopted, selectCurrent, retryLoad, getLastError: () => lastError };
}
