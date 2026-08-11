export const KNOWLEDGE_SCHEMA_VERSION = 2;
export const KNOWLEDGE_STORAGE_KEY = 'kadode:knowledge-metadata';
export const KNOWLEDGE_QUARANTINE_KEY = 'kadode:knowledge-metadata:quarantine';
export const KNOWLEDGE_SCOPED_STORAGE_KEY = 'kadode:knowledge-metadata-scoped';

const STATES = new Set(['metadata_only', 'processing', 'searchable', 'failed', 'deleted']);
const PROCESSING_STATES = new Set(['pending', 'ready']);
const SOURCE_TYPES = new Set(['local', 'synthetic', 'unknown']);
const CONFIDENCE_LEVELS = new Set(['high', 'medium', 'unknown']);

function scopePart(value) {
  const text = String(value);
  return `${text.length}:${text}`;
}

export function knowledgeMetadataStorageKey(ownerId, spaceId) {
  return `${KNOWLEDGE_SCOPED_STORAGE_KEY}:${scopePart(ownerId)}:${scopePart(spaceId)}:v${KNOWLEDGE_SCHEMA_VERSION}`;
}

function nonEmpty(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function validTimestamp(value) {
  return typeof value === 'string' && Number.isFinite(Date.parse(value));
}

function normalizeLegacyDocument(value) {
  if (!value || !nonEmpty(value.id) || !nonEmpty(value.ownerId) || !nonEmpty(value.spaceId) || !nonEmpty(value.name)) return null;
  const state = value.state === undefined ? 'processing' : (STATES.has(value.state) ? value.state : null);
  if (!state || (state === 'deleted' && !validTimestamp(value.deletedAt))) return null;
  if (value.version !== undefined && (!Number.isInteger(value.version) || value.version < 1)) return null;
  if (value.mediaType !== undefined && value.mediaType !== null && typeof value.mediaType !== 'string') return null;
  if (value.sizeBytes !== undefined && value.sizeBytes !== null && (!Number.isSafeInteger(value.sizeBytes) || value.sizeBytes < 0)) return null;
  if (value.lastModified !== undefined && value.lastModified !== null && (!Number.isSafeInteger(value.lastModified) || value.lastModified < 0)) return null;
  if (value.sourceType !== undefined && !SOURCE_TYPES.has(value.sourceType)) return null;
  if (value.confidence !== undefined && !CONFIDENCE_LEVELS.has(value.confidence)) return null;
  if (value.createdAt !== undefined && value.createdAt !== null && !validTimestamp(value.createdAt)) return null;
  if (value.updatedAt !== undefined && value.updatedAt !== null && !validTimestamp(value.updatedAt)) return null;
  if (value.projectId !== undefined && typeof value.projectId !== 'string') return null;
  if (value.evaluationView !== undefined && typeof value.evaluationView !== 'string') return null;
  if (value.extractedTextState !== undefined && !PROCESSING_STATES.has(value.extractedTextState)) return null;
  if (value.indexState !== undefined && !PROCESSING_STATES.has(value.indexState)) return null;
  if (state !== 'deleted' && value.deletedAt !== undefined && value.deletedAt !== null) return null;
  return {
    id: value.id.trim(), ownerId: value.ownerId.trim(), spaceId: value.spaceId.trim(), name: value.name.trim(),
    version: Number.isInteger(value.version) && value.version > 0 ? value.version : 1,
    state,
    mediaType: typeof value.mediaType === 'string' ? value.mediaType : null,
    sizeBytes: Number.isSafeInteger(value.sizeBytes) ? value.sizeBytes : null,
    lastModified: Number.isSafeInteger(value.lastModified) ? value.lastModified : null,
    extractedTextState: PROCESSING_STATES.has(value.extractedTextState) ? value.extractedTextState : 'pending',
    indexState: PROCESSING_STATES.has(value.indexState) ? value.indexState : 'pending',
    deletedAt: state === 'deleted' ? value.deletedAt : null,
    sourceType: SOURCE_TYPES.has(value.sourceType) ? value.sourceType : 'local',
    confidence: CONFIDENCE_LEVELS.has(value.confidence) ? value.confidence : 'unknown',
    createdAt: validTimestamp(value.createdAt) ? value.createdAt : null,
    updatedAt: validTimestamp(value.updatedAt) ? value.updatedAt : null,
    projectId: typeof value.projectId === 'string' ? value.projectId : '',
    evaluationView: typeof value.evaluationView === 'string' ? value.evaluationView : '',
  };
}

function normalizeCurrentDocument(value) {
  if (!value || typeof value !== 'object') return null;
  const required = ['id', 'ownerId', 'spaceId', 'name', 'version', 'state', 'mediaType', 'sizeBytes', 'lastModified', 'extractedTextState', 'indexState', 'deletedAt', 'sourceType', 'confidence', 'createdAt', 'updatedAt', 'projectId', 'evaluationView'];
  if (!required.every((field) => Object.hasOwn(value, field))) return null;
  const normalized = normalizeLegacyDocument(value);
  if (!normalized) return null;
  if (!Number.isInteger(value.version) || value.version < 1) return null;
  if (!PROCESSING_STATES.has(value.extractedTextState) || !PROCESSING_STATES.has(value.indexState)) return null;
  if (value.state !== 'deleted' && value.deletedAt !== null) return null;
  return normalized;
}

function normalizeNewDocument(value) {
  return normalizeLegacyDocument({ state: 'processing', ...value });
}

export function createKnowledgeMetadataRepository({ ownerId, spaceId, storage = globalThis.localStorage } = {}) {
  const scopedKey = knowledgeMetadataStorageKey(ownerId, spaceId);
  let documents = [];
  let loadPromise;
  let lastError = null;
  let writeBlocked = false;

  const list = () => documents.filter((document) => document.ownerId === ownerId && document.spaceId === spaceId && document.state !== 'deleted');
  const find = (id) => documents.find((document) => document.id === id && document.ownerId === ownerId && document.spaceId === spaceId) ?? null;
  const writeDocuments = (nextDocuments) => storage?.setItem(scopedKey, JSON.stringify({ schemaVersion: KNOWLEDGE_SCHEMA_VERSION, ownerId, spaceId, documents: nextDocuments }));

  function quarantine(key, raw) {
    try {
      const quarantineKey = key === KNOWLEDGE_STORAGE_KEY ? KNOWLEDGE_QUARANTINE_KEY : `${key}:quarantine`;
      if (storage?.getItem(quarantineKey) == null) storage?.setItem(quarantineKey, raw);
    } catch {
      // Best effort only. The source remains untouched and writes stay blocked.
    }
  }

  async function load() {
    if (loadPromise) return loadPromise;
    loadPromise = Promise.resolve().then(() => {
      let raw;
      try { raw = storage?.getItem(scopedKey) ?? null; } catch (error) {
        lastError = error;
        writeBlocked = true;
        return list();
      }
      if (raw != null) {
        try {
          const parsed = JSON.parse(raw);
          if (parsed?.schemaVersion !== KNOWLEDGE_SCHEMA_VERSION || parsed.ownerId !== ownerId || parsed.spaceId !== spaceId || !Array.isArray(parsed.documents)) throw new Error('Invalid Knowledge metadata envelope');
          const normalized = parsed.documents.map(normalizeCurrentDocument);
          if (normalized.some((document) => document === null || document.ownerId !== ownerId || document.spaceId !== spaceId)) throw new Error('Invalid Knowledge metadata record');
          documents = normalized;
          lastError = null;
        } catch (error) {
          lastError = error;
          writeBlocked = true;
          documents = [];
          quarantine(scopedKey, raw);
        }
        return list();
      }
      let legacyRaw;
      try { legacyRaw = storage?.getItem(KNOWLEDGE_STORAGE_KEY) ?? null; } catch (error) {
        lastError = error;
        writeBlocked = true;
        return list();
      }
      if (legacyRaw == null) { lastError = null; return list(); }
      try {
        const parsed = JSON.parse(legacyRaw);
        if ((parsed?.schemaVersion !== 1 && parsed?.schemaVersion !== undefined) || !Array.isArray(parsed.documents)) throw new Error('Unsupported legacy Knowledge metadata schema');
        const normalized = parsed.documents.map(normalizeLegacyDocument);
        if (normalized.some((document) => document === null)) throw new Error('Invalid legacy Knowledge metadata record');
        documents = normalized.filter((document) => document.ownerId === ownerId && document.spaceId === spaceId);
        try { writeDocuments(documents); } catch { /* original legacy raw remains authoritative until a scoped write succeeds */ }
        lastError = null;
      } catch (error) {
        lastError = error;
        writeBlocked = true;
        documents = [];
        quarantine(KNOWLEDGE_STORAGE_KEY, legacyRaw);
      }
      return list();
    });
    return loadPromise;
  }

  async function add(metadata) {
    await load();
    if (writeBlocked) throw new Error('Knowledge metadata requires recovery before writing');
    const document = normalizeNewDocument({ ...metadata, ownerId, spaceId });
    if (!document) throw new Error('Invalid metadata');
    const nextDocuments = [...documents.filter((item) => item.id !== document.id || item.ownerId !== ownerId || item.spaceId !== spaceId), document];
    try {
      writeDocuments(nextDocuments);
      documents = nextDocuments;
      loadPromise = Promise.resolve(list());
      lastError = null;
      return document;
    } catch (error) {
      lastError = error;
      throw error;
    }
  }

  async function remove(id, fallbackMetadata) {
    await load();
    if (writeBlocked) throw new Error('Knowledge metadata requires recovery before writing');
    const current = find(id) ?? normalizeNewDocument({ ...fallbackMetadata, id, ownerId, spaceId });
    if (!current) return null;
    const deleted = { ...current, state: 'deleted', deletedAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
    const nextDocuments = [...documents.filter((item) => item.id !== id || item.ownerId !== ownerId || item.spaceId !== spaceId), deleted];
    try {
      writeDocuments(nextDocuments);
      documents = nextDocuments;
      loadPromise = Promise.resolve(list());
      lastError = null;
      return deleted;
    } catch (error) {
      lastError = error;
      throw error;
    }
  }

  function retryLoad() {
    loadPromise = undefined;
    writeBlocked = false;
    lastError = null;
    return load();
  }

  return { load, list, find, add, delete: remove, retryLoad, getLastError: () => lastError };
}
