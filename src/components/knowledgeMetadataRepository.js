export const KNOWLEDGE_SCHEMA_VERSION = 1;
export const KNOWLEDGE_STORAGE_KEY = 'kadode:knowledge-metadata';

const STATES = new Set(['processing', 'searchable', 'failed', 'deleted']);

function normalizeDocument(value) {
  if (!value || typeof value.id !== 'string' || typeof value.ownerId !== 'string' || typeof value.spaceId !== 'string' || typeof value.name !== 'string') return null;
  const state = STATES.has(value.state) ? value.state : 'processing';
  return { id: value.id, ownerId: value.ownerId, spaceId: value.spaceId, name: value.name, version: Number.isInteger(value.version) && value.version > 0 ? value.version : 1, state, extractedTextState: value.extractedTextState === 'ready' ? 'ready' : 'pending', indexState: value.indexState === 'ready' ? 'ready' : 'pending', deletedAt: state === 'deleted' && typeof value.deletedAt === 'string' ? value.deletedAt : null };
}

export function createKnowledgeMetadataRepository({ ownerId, spaceId, storage = globalThis.localStorage } = {}) {
  let documents = [];
  let loadPromise;
  const writeDocuments = (nextDocuments) => storage?.setItem(KNOWLEDGE_STORAGE_KEY, JSON.stringify({ schemaVersion: KNOWLEDGE_SCHEMA_VERSION, documents: nextDocuments }));
  async function load() {
    if (loadPromise) return loadPromise;
    loadPromise = Promise.resolve().then(() => { try { const parsed = JSON.parse(storage?.getItem(KNOWLEDGE_STORAGE_KEY) ?? '{"documents":[]}'); const next = Array.isArray(parsed.documents) ? parsed.documents.map(normalizeDocument).filter(Boolean) : []; documents = next; } catch { /* quarantine corrupt records and retain safe empty state */ } return list(); });
    return loadPromise;
  }
  const list = () => documents.filter((document) => document.ownerId === ownerId && document.spaceId === spaceId && document.state !== 'deleted');
  async function add(metadata) { const document = normalizeDocument({ ...metadata, ownerId, spaceId }); if (!document) throw new Error('Invalid metadata'); const nextDocuments = [...documents.filter((item) => item.id !== document.id), document]; writeDocuments(nextDocuments); documents = nextDocuments; return document; }
  async function remove(id) { const current = documents.find((item) => item.id === id && item.ownerId === ownerId && item.spaceId === spaceId); if (!current) return null; const deleted = { ...current, state: 'deleted', deletedAt: new Date().toISOString() }; const nextDocuments = documents.map((item) => item.id === id ? deleted : item); writeDocuments(nextDocuments); documents = nextDocuments; return deleted; }
  return { load, list, add, delete: remove };
}
