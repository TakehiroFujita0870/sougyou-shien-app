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

function isArray(value) {
  return Array.isArray(value) ? value : [];
}

function allowDirtyState(value, selectedEntityIds) {
  if (!value || value.explicit !== true || value.dirty !== true) return null;
  if (typeof value.entityId !== 'string' || !selectedEntityIds.has(value.entityId)) return null;
  return { entityId: value.entityId, dirty: true };
}

function compareSources(left, right) {
  return `${left.entityId}:${left.kind}:${left.locator}:${left.revision}`
    .localeCompare(`${right.entityId}:${right.kind}:${right.locator}:${right.revision}`);
}

export function createLocalContextSnapshot({ ownerId, surface, selected = {}, selection = [], dirtyState = [], sources = [] } = {}) {
  if (typeof ownerId !== 'string' || !SURFACE_NAMES.has(surface?.name)) {
    throw new Error('有効なownerとsurfaceが必要です。');
  }

  const allowedSelected = Object.fromEntries(
    SELECTED_ENTITY_NAMES
      .map((name) => [name, allowSelectedEntity(selected[name], ownerId)])
      .filter(([, value]) => value !== null),
  );
  const selectedEntityIds = new Set(Object.values(allowedSelected).map((entity) => entity.id));
  const allowedSources = isArray(sources)
    .map((source) => allowSource(source, ownerId))
    .filter((source) => source !== null)
    .sort(compareSources);
  const selectableEntityIds = new Set([
    ...selectedEntityIds,
    ...allowedSources.map((source) => source.entityId),
  ]);
  const allowedDirtyState = isArray(dirtyState)
    .map((state) => allowDirtyState(state, selectedEntityIds))
    .filter((state) => state !== null)
    .sort((left, right) => left.entityId.localeCompare(right.entityId))
    .filter((state, index, values) => index === 0 || values[index - 1].entityId !== state.entityId);

  return {
    version: CONTEXT_SNAPSHOT_VERSION,
    surface: {
      name: surface.name,
      ...(typeof surface.route === 'string' ? { route: surface.route } : {}),
      ...(typeof surface.view === 'string' ? { view: surface.view } : {}),
      ...(typeof surface.subview === 'string' ? { subview: surface.subview } : {}),
    },
    selected: allowedSelected,
    selection: [...new Set(isArray(selection).filter((id) => selectableEntityIds.has(id)))].sort(),
    dirtyState: allowedDirtyState,
    sources: allowedSources,
  };
}
