export const ADOPTED_PROJECT_SCHEMA_VERSION = 1;
export const ADOPTED_PROJECT_STORAGE_KEY = 'kadode:adopted-projects';

function isNonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

export function normalizeAdoptedProject(value) {
  if (!value || typeof value !== 'object') return null;
  if (!isNonEmptyString(value.id) || !isNonEmptyString(value.ownerId) || !isNonEmptyString(value.spaceId)) return null;
  if (!isNonEmptyString(value.title) || !isNonEmptyString(value.fact) || !isNonEmptyString(value.inference)) return null;
  if (value.status !== 'adopted') return null;
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

export function createAdoptedProjectRepository({ ownerId = 'local-owner', spaceId = 'local-space', storage = globalThis.localStorage } = {}) {
  let records = [];
  let loadPromise;

  const list = () => records.filter((record) => record.ownerId === ownerId && record.spaceId === spaceId);
  const current = () => list().at(0) ?? null;

  async function load() {
    if (loadPromise) return loadPromise;
    loadPromise = Promise.resolve().then(() => {
      try {
        const parsed = JSON.parse(storage?.getItem(ADOPTED_PROJECT_STORAGE_KEY) ?? '{"projects":[]}');
        records = Array.isArray(parsed.projects) ? parsed.projects.map(normalizeAdoptedProject).filter(Boolean) : [];
      } catch {
        // A corrupted value must never trigger a replacement write during hydration.
        records = [];
      }
      return current();
    });
    return loadPromise;
  }

  async function saveAdopted(candidate) {
    await load();
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
    const next = [project, ...records.filter((record) => record.id !== project.id)];
    storage?.setItem(ADOPTED_PROJECT_STORAGE_KEY, JSON.stringify({ schemaVersion: ADOPTED_PROJECT_SCHEMA_VERSION, projects: next }));
    records = next;
    return project;
  }

  return { load, list, current, saveAdopted };
}
