export const PROJECT_CONVERSATION_SCHEMA_VERSION = 1;
export const PROJECT_CONVERSATION_STORAGE_KEY = 'dots:project-conversations';
export const PROJECT_CONVERSATION_QUARANTINE_KEY = 'dots:project-conversations:quarantine';

function scopedDraftKey(ownerId, spaceId, projectId) {
  const segment = (value) => `${String(value).length}:${value}`;
  return `dots:project-conversation-draft:v1:${segment(ownerId)}:${segment(spaceId)}:${segment(projectId)}`;
}

const roles = new Set(['user', 'assistant']);

function nonEmpty(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

export function normalizeProjectMessage(value) {
  if (!value || typeof value !== 'object' || !roles.has(value.role) || !nonEmpty(value.content)) return null;
  return {
    id: nonEmpty(value.id) ? value.id.trim() : `${value.role}:${value.content.trim()}`,
    role: value.role,
    content: value.content.trim(),
  };
}

function normalizeRecord(value) {
  if (!value || typeof value !== 'object') return null;
  if (!nonEmpty(value.ownerId) || !nonEmpty(value.spaceId) || !nonEmpty(value.projectId) || !Array.isArray(value.messages)) return null;
  const messages = value.messages.map(normalizeProjectMessage);
  if (messages.some((message) => message === null)) return null;
  return { ownerId: value.ownerId.trim(), spaceId: value.spaceId.trim(), projectId: value.projectId.trim(), messages };
}

/** Local-only, owner/space/project bounded persistence. It never makes a network request. */
export function createProjectConversationRepository({ ownerId = 'local-owner', spaceId = 'local-space', projectId = 'demo-project', storage = globalThis.localStorage } = {}) {
  let records = [];
  let loaded;
  let writeBlocked = false;
  let lastError = null;
  const draftKey = scopedDraftKey(ownerId, spaceId, projectId);

  const current = () => records.find((record) => record.ownerId === ownerId && record.spaceId === spaceId && record.projectId === projectId)?.messages ?? [];

  async function quarantine(raw) {
    try {
      if (storage?.getItem(PROJECT_CONVERSATION_QUARANTINE_KEY) == null) storage?.setItem(PROJECT_CONVERSATION_QUARANTINE_KEY, raw);
    } catch {
      // Quarantine is best-effort; the original value is never replaced after a corrupt read.
    }
  }

  async function load() {
    if (loaded) return loaded;
    loaded = Promise.resolve().then(async () => {
      let raw;
      try { raw = storage?.getItem(PROJECT_CONVERSATION_STORAGE_KEY); } catch (error) {
        lastError = error;
        writeBlocked = true;
        return current();
      }
      if (raw == null) return current();
      try {
        const parsed = JSON.parse(raw);
        if (parsed?.schemaVersion !== PROJECT_CONVERSATION_SCHEMA_VERSION || !Array.isArray(parsed.records)) throw new Error('invalid schema');
        const normalized = parsed.records.map(normalizeRecord);
        if (normalized.some((record) => record === null)) throw new Error('invalid record');
        records = normalized;
        lastError = null;
      } catch (error) {
        lastError = error;
        writeBlocked = true;
        await quarantine(raw);
        records = [];
      }
      return current();
    });
    return loaded;
  }

  async function save(messages) {
    await load();
    if (writeBlocked) throw new Error('Project conversation requires recovery before writing');
    if (!Array.isArray(messages)) throw new Error('Project conversation must be an array');
    const normalizedMessages = messages.map(normalizeProjectMessage);
    if (normalizedMessages.some((message) => message === null)) throw new Error('Invalid project conversation message');
    const record = { ownerId, spaceId, projectId, messages: normalizedMessages };
    records = [record, ...records.filter((item) => !(item.ownerId === ownerId && item.spaceId === spaceId && item.projectId === projectId))];
    storage?.setItem(PROJECT_CONVERSATION_STORAGE_KEY, JSON.stringify({ schemaVersion: PROJECT_CONVERSATION_SCHEMA_VERSION, records }));
    loaded = Promise.resolve(normalizedMessages);
    lastError = null;
    return normalizedMessages;
  }

  function retryLoad() {
    loaded = undefined;
    writeBlocked = false;
    lastError = null;
    return load();
  }

  async function loadDraft() {
    try {
      const raw = storage?.getItem(draftKey);
      if (raw == null) return '';
      const parsed = JSON.parse(raw);
      return parsed?.schemaVersion === 1 && typeof parsed.value === 'string' ? parsed.value : '';
    } catch {
      return '';
    }
  }

  async function saveDraft(value) {
    if (typeof value !== 'string') throw new Error('Project draft must be a string');
    storage?.setItem(draftKey, JSON.stringify({ schemaVersion: 1, value }));
    return value;
  }

  return { load, save, loadDraft, saveDraft, retryLoad, getLastError: () => lastError };
}
