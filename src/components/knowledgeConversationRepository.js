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

export function knowledgeConversationStorageKey(ownerId, spaceId) {
  return `${KNOWLEDGE_CONVERSATION_STORAGE_KEY}:${ownerId}:${spaceId}`;
}

function normalizeLegacyState(value) {
  if (!value || typeof value !== 'object') return null;
  const messages = Array.isArray(value.messages) ? value.messages.map(normalizeMessage) : [];
  if (messages.some((item) => item === null)) return null;
  return { messages, entries: Array.isArray(value.entries) ? value.entries.map(normalizeEntry).filter(Boolean) : [] };
}

function normalizeStrictState(value) {
  if (!value || typeof value !== 'object' || !Array.isArray(value.messages) || !Array.isArray(value.entries)) return null;
  const messages = value.messages.map(normalizeStrictMessage);
  if (messages.some((item) => item === null)) return null;
  return { messages, entries: value.entries.map(normalizeEntry).filter(Boolean) };
}

export function createKnowledgeConversationRepository({ ownerId, spaceId, storage = globalThis.localStorage } = {}) {
  const key = knowledgeConversationStorageKey(ownerId, spaceId);
  let cachedLoad;
  let writeBlocked = false;

  function quarantine(raw) {
    try {
      const quarantineKey = `${key}:quarantine`;
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
      try { raw = storage?.getItem(key) ?? null; } catch {
        writeBlocked = true;
        return emptyState;
      }
      if (raw == null) return emptyState;
      try {
        const parsed = JSON.parse(raw);
        if (parsed?.schemaVersion === undefined) {
          const legacy = normalizeLegacyState(parsed);
          if (!legacy) throw new Error('invalid legacy Knowledge conversation');
          try { storage?.setItem(key, JSON.stringify(envelope(legacy))); } catch { /* the legacy raw remains available */ }
          return legacy;
        }
        if (parsed.schemaVersion !== KNOWLEDGE_CONVERSATION_SCHEMA_VERSION || parsed.ownerId !== ownerId || parsed.spaceId !== spaceId) throw new Error('invalid Knowledge conversation envelope');
        const state = normalizeStrictState(parsed.state);
        if (!state) throw new Error('invalid Knowledge conversation state');
        return state;
      } catch {
        writeBlocked = true;
        quarantine(raw);
        return emptyState;
      }
    });
    return cachedLoad;
  }

  async function save(value) {
    await load();
    if (writeBlocked) throw new Error('Knowledge conversation requires recovery before writing');
    const next = normalizeStrictState(value);
    if (!next) throw new Error('Invalid Knowledge conversation');
    storage?.setItem(key, JSON.stringify(envelope(next)));
    cachedLoad = Promise.resolve(next);
    return next;
  }

  return { load, save };
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
