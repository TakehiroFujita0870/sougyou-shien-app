export const KNOWLEDGE_CONVERSATION_STORAGE_KEY = 'kadode:knowledge-conversation';
export const KNOWLEDGE_CONVERSATION_SCHEMA_VERSION = 1;
const emptyState = { messages: [], entries: [] };
const epoch = new Date(0).toISOString();
const validDate = (value, fallback = epoch) =>
  typeof value === 'string' && Number.isFinite(Date.parse(value)) ? value : fallback;

function normalizeMessage(value) {
  return value && (value.role === 'user' || value.role === 'assistant') && typeof value.content === 'string'
    ? { role: value.role, content: value.content.slice(0, 2000), createdAt: typeof value.createdAt === 'string' && Number.isFinite(Date.parse(value.createdAt)) ? value.createdAt : null }
    : null;
}

function normalizeStrictMessage(value) {
  if (!value || !Object.hasOwn(value, 'createdAt') || (value.createdAt !== null && (typeof value.createdAt !== 'string' || !Number.isFinite(Date.parse(value.createdAt))))) return null;
  if ((value.role !== 'user' && value.role !== 'assistant') || typeof value.content !== 'string' || value.content.length > 2000) return null;
  return { role: value.role, content: value.content, createdAt: value.createdAt };
}

function normalizeEntry(value) {
  if (!value || typeof value.id !== 'string' || typeof value.title !== 'string' || typeof value.content !== 'string') return null;
  const category = ['profile', 'decision', 'conversation', 'note'].includes(value.category) ? value.category : 'note';
  const createdAt = validDate(value.createdAt);
  const sourceType = ['synthetic', 'local', 'unknown'].includes(value.sourceType) ? value.sourceType : 'unknown';
  const confidence = ['high', 'medium', 'unknown'].includes(value.confidence) ? value.confidence : 'unknown';
  return { id: value.id, category, title: value.title.slice(0, 100), content: value.content.slice(0, 4000), createdAt, updatedAt: validDate(value.updatedAt, createdAt), sourceType, projectId: typeof value.projectId === 'string' ? value.projectId.slice(0, 100) : '', evaluationView: typeof value.evaluationView === 'string' ? value.evaluationView.slice(0, 100) : '', confidence, unknowns: Array.isArray(value.unknowns) ? value.unknowns.filter((item) => typeof item === 'string').slice(0, 8).map((item) => item.slice(0, 200)) : [] };
}

function normalizeStrictEntry(value) {
  if (!value || typeof value !== 'object') return null;
  if (typeof value.id !== 'string' || typeof value.title !== 'string' || value.title.length > 100 || typeof value.content !== 'string' || value.content.length > 4000) return null;
  if (!['profile', 'decision', 'conversation', 'note'].includes(value.category)) return null;
  if (typeof value.createdAt !== 'string' || !Number.isFinite(Date.parse(value.createdAt)) || typeof value.updatedAt !== 'string' || !Number.isFinite(Date.parse(value.updatedAt))) return null;
  if (!['synthetic', 'local', 'unknown'].includes(value.sourceType) || typeof value.projectId !== 'string' || value.projectId.length > 100 || typeof value.evaluationView !== 'string' || value.evaluationView.length > 100) return null;
  if (!['high', 'medium', 'unknown'].includes(value.confidence) || !Array.isArray(value.unknowns) || value.unknowns.length > 8 || value.unknowns.some((item) => typeof item !== 'string' || item.length > 200)) return null;
  return { id: value.id, category: value.category, title: value.title, content: value.content, createdAt: value.createdAt, updatedAt: value.updatedAt, sourceType: value.sourceType, projectId: value.projectId, evaluationView: value.evaluationView, confidence: value.confidence, unknowns: value.unknowns };
}

function normalizeEntryForSave(value) {
  if (!value || typeof value !== 'object' || typeof value.id !== 'string' || typeof value.title !== 'string' || typeof value.content !== 'string') return null;
  if (value.title.length > 100 || value.content.length > 4000) return null;
  if (value.category !== undefined && !['profile', 'decision', 'conversation', 'note'].includes(value.category)) return null;
  if (value.createdAt !== undefined && (typeof value.createdAt !== 'string' || !Number.isFinite(Date.parse(value.createdAt)))) return null;
  if (value.updatedAt !== undefined && (typeof value.updatedAt !== 'string' || !Number.isFinite(Date.parse(value.updatedAt)))) return null;
  if (value.sourceType !== undefined && !['synthetic', 'local', 'unknown'].includes(value.sourceType)) return null;
  if (value.projectId !== undefined && (typeof value.projectId !== 'string' || value.projectId.length > 100)) return null;
  if (value.evaluationView !== undefined && (typeof value.evaluationView !== 'string' || value.evaluationView.length > 100)) return null;
  if (value.confidence !== undefined && !['high', 'medium', 'unknown'].includes(value.confidence)) return null;
  if (value.unknowns !== undefined && (!Array.isArray(value.unknowns) || value.unknowns.length > 8 || value.unknowns.some((item) => typeof item !== 'string' || item.length > 200))) return null;
  return normalizeEntry(value);
}

export function knowledgeConversationStorageKey(ownerId, spaceId) {
  return `${KNOWLEDGE_CONVERSATION_STORAGE_KEY}:${scopePart(ownerId)}:${scopePart(spaceId)}:v${KNOWLEDGE_CONVERSATION_SCHEMA_VERSION}`;
}

export function legacyKnowledgeConversationStorageKey(ownerId, spaceId) {
  return `${KNOWLEDGE_CONVERSATION_STORAGE_KEY}:${ownerId}:${spaceId}`;
}

function scopePart(value) {
  const text = String(value);
  return `${text.length}:${text}`;
}

function normalizeLegacyState(value) {
  if (!value || typeof value !== 'object') return null;
  const messages = Array.isArray(value.messages) ? value.messages.map(normalizeMessage) : [];
  if (messages.some((item) => item === null)) return null;
  return { messages, entries: Array.isArray(value.entries) ? value.entries.map(normalizeEntry).filter(Boolean) : [] };
}

function normalizeStrictState(value, forSave = false) {
  if (!value || typeof value !== 'object' || !Array.isArray(value.messages) || !Array.isArray(value.entries)) return null;
  const messages = value.messages.map(normalizeStrictMessage);
  const entries = value.entries.map(forSave ? normalizeEntryForSave : normalizeStrictEntry);
  if (messages.some((item) => item === null) || entries.some((item) => item === null)) return null;
  return { messages, entries };
}

export function createKnowledgeConversationRepository({ ownerId, spaceId, storage = globalThis.localStorage } = {}) {
  const key = knowledgeConversationStorageKey(ownerId, spaceId);
  const legacyKey = legacyKnowledgeConversationStorageKey(ownerId, spaceId);
  let cachedLoad;
  let writeBlocked = false;
  let lastError = null;

  function quarantine(sourceKey, raw) {
    try {
      const quarantineKey = `${sourceKey}:quarantine`;
      if (storage?.getItem(quarantineKey) == null) storage?.setItem(quarantineKey, raw);
    } catch {
      // Best effort. The exact source raw remains untouched and writes stay blocked.
    }
  }

  function envelope(state) {
    return { schemaVersion: KNOWLEDGE_CONVERSATION_SCHEMA_VERSION, ownerId, spaceId, state };
  }

  async function load() {
    if (cachedLoad) return cachedLoad;
    cachedLoad = Promise.resolve().then(() => {
      let raw;
      try { raw = storage?.getItem(key) ?? null; } catch (error) {
        lastError = error;
        writeBlocked = true;
        return emptyState;
      }
      if (raw == null) {
        try { raw = storage?.getItem(legacyKey) ?? null; } catch (error) {
          lastError = error;
          writeBlocked = true;
          return emptyState;
        }
        if (raw == null) return emptyState;
        try {
          const legacy = normalizeLegacyState(JSON.parse(raw));
          if (!legacy) throw new Error('invalid legacy Knowledge conversation');
          try { storage?.setItem(key, JSON.stringify(envelope(legacy))); } catch { /* the legacy source remains unchanged */ }
          lastError = null;
          return legacy;
        } catch (error) {
          lastError = error;
          writeBlocked = true;
          quarantine(legacyKey, raw);
          return emptyState;
        }
      }
      try {
        const parsed = JSON.parse(raw);
        if (parsed.schemaVersion !== KNOWLEDGE_CONVERSATION_SCHEMA_VERSION || parsed.ownerId !== ownerId || parsed.spaceId !== spaceId) throw new Error('invalid Knowledge conversation envelope');
        const state = normalizeStrictState(parsed.state);
        if (!state) throw new Error('invalid Knowledge conversation state');
        lastError = null;
        return state;
      } catch (error) {
        lastError = error;
        writeBlocked = true;
        quarantine(key, raw);
        return emptyState;
      }
    });
    return cachedLoad;
  }

  async function save(value) {
    await load();
    if (writeBlocked) throw new Error('Knowledge conversation requires recovery before writing');
    const next = normalizeStrictState(value, true);
    if (!next) throw new Error('Invalid Knowledge conversation');
    storage?.setItem(key, JSON.stringify(envelope(next)));
    cachedLoad = Promise.resolve(next);
    lastError = null;
    return next;
  }

  function retryLoad() {
    cachedLoad = undefined;
    writeBlocked = false;
    lastError = null;
    return load();
  }

  return { load, save, retryLoad, getLastError: () => lastError };
}

export function proposeKnowledgeEntry(content) {
  const trimmed = content.trim();
  const category = /(決定|採用|却下|保留)/.test(trimmed) ? 'decision' : /(顧客|経験|強み|プロフィール)/.test(trimmed) ? 'profile' : 'note';
  const label = { profile: 'プロフィール', decision: '意思決定', note: 'メモ' }[category];
  const createdAt = new Date().toISOString();
  return { id: `knowledge:${Date.now()}`, category, title: `${label}: ${trimmed.replace(/\s+/g, ' ').slice(0, 36)}`, content: trimmed, createdAt, updatedAt: createdAt, sourceType: 'local', confidence: 'unknown', unknowns: [] };
}

export function respondToKnowledge(message, fixture) {
  const asset = fixture?.asset?.name ?? '現在の資料';
  const judgement = fixture?.decision?.judgement ?? '次の判断';
  return `「${asset}」と「${judgement}」を踏まえると、${message.trim()}を確認対象として整理できます。根拠と未確認事項を分けて見ていきましょう。`;
}
