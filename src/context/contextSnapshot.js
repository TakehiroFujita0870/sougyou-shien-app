export const CONTEXT_SNAPSHOT_VERSION = 1;

const SURFACE_NAMES = new Set(['Home', 'Project', 'Knowledge']);
const SOURCE_KINDS = new Set(['fact', 'inference']);
const SELECTED_ENTITY_NAMES = ['project', 'asset', 'decision'];

function isVisibleToOwner(value, ownerId) {
  return value?.ownerId === ownerId
    && value.permission === 'read'
    && value.deleted !== true
    && value.hidden !== true;
}

function hasRequiredEntityFields(value) {
  return typeof value?.id === 'string'
    && typeof value?.displayName === 'string'
    && typeof value?.locator === 'string' && value.locator.length > 0
    && typeof value?.revision === 'string' && value.revision.length > 0;
}

function allowSelectedEntity(value, ownerId) {
  if (!isVisibleToOwner(value, ownerId) || !hasRequiredEntityFields(value)) return null;
  return {
    id: value.id,
    displayName: value.displayName,
    locator: value.locator,
    revision: value.revision,
  };
}

function allowSource(value, ownerId) {
  if (!isVisibleToOwner(value, ownerId) || !SOURCE_KINDS.has(value?.kind)) return null;
  if (typeof value.entityId !== 'string' || typeof value.locator !== 'string' || value.locator.length === 0) return null;
  if (typeof value.revision !== 'string' || value.revision.length === 0) return null;
  return { kind: value.kind, entityId: value.entityId, locator: value.locator, revision: value.revision };
}

function compareById(left, right) {
  return left.id.localeCompare(right.id);
}

export function createLocalContextSnapshot({ ownerId, surface, selected = {}, selection = [], dirtyChanges = [], sources = [] } = {}) {
  if (typeof ownerId !== 'string' || !SURFACE_NAMES.has(surface?.name)) {
    throw new Error('有効なownerとsurfaceが必要です。');
  }

  const allowedSelected = Object.fromEntries(
    SELECTED_ENTITY_NAMES
      .map((name) => [name, allowSelectedEntity(selected[name], ownerId)])
      .filter(([, value]) => value !== null),
  );
  const allowedDirtyChanges = dirtyChanges
    .filter((change) => change?.explicit === true && change.target !== 'profile')
    .filter((change) => typeof change.id === 'string' && typeof change.label === 'string' && typeof change.value === 'string')
    .map(({ id, label, value }) => ({ id, label, value }))
    .sort(compareById);
  const allowedSources = sources
    .map((source) => allowSource(source, ownerId))
    .filter((source) => source !== null)
    .sort((left, right) => `${left.entityId}:${left.kind}`.localeCompare(`${right.entityId}:${right.kind}`));

  return {
    version: CONTEXT_SNAPSHOT_VERSION,
    surface: {
      name: surface.name,
      ...(typeof surface.route === 'string' ? { route: surface.route } : {}),
      ...(typeof surface.view === 'string' ? { view: surface.view } : {}),
      ...(typeof surface.subview === 'string' ? { subview: surface.subview } : {}),
    },
    selected: allowedSelected,
    selection: [...new Set(selection.filter((id) => typeof id === 'string'))].sort(),
    dirtyChanges: allowedDirtyChanges,
    sources: allowedSources,
  };
}
