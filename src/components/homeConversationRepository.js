export const HOME_CONVERSATION_SCHEMA_VERSION = 1;
export const HOME_CONVERSATION_STORAGE_KEY = 'kadode:home-conversation';
export const HOME_DRAFT_STORAGE_KEY = 'kadode:home-conversation:draft';
export const EMPTY_HOME_CONVERSATION_STATE = Object.freeze({ messages: [], proposals: [] });

const CANONICAL_OWNER_ID = 'local-owner';
const CANONICAL_SPACE_ID = 'local-space';
const roles = new Set(['user', 'assistant']);
const proposalStatuses = new Set(['pending', 'adopted', 'held', 'rejected']);

export function homeConversationStorageKey(ownerId, spaceId) {
  return `${HOME_CONVERSATION_STORAGE_KEY}:${scopePart(ownerId)}:${scopePart(spaceId)}:v${HOME_CONVERSATION_SCHEMA_VERSION}`;
}

export function homeDraftStorageKey(ownerId, spaceId) {
  return `${HOME_DRAFT_STORAGE_KEY}:${scopePart(ownerId)}:${scopePart(spaceId)}:v${HOME_CONVERSATION_SCHEMA_VERSION}`;
}

function scopePart(value) {
  const text = String(value);
  return `${text.length}:${text}`;
}

function isNonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function normalizeMessage(value) {
  if (!value || typeof value !== 'object' || !roles.has(value.role) || !isNonEmptyString(value.content)) return null;
  return { role: value.role, content: value.content };
}

function normalizeProposal(value) {
  if (!value || typeof value !== 'object' || !isNonEmptyString(value.id) || !proposalStatuses.has(value.status)) return null;
  if (!['title', 'fact', 'inference', 'reason', 'action'].every((key) => typeof value[key] === 'string')) return null;
  if (typeof value.confirmed !== 'boolean') return null;
  if (value.rejectionReason !== undefined && typeof value.rejectionReason !== 'string') return null;
  return {
    id: value.id,
    title: value.title,
    fact: value.fact,
    inference: value.inference,
    reason: value.reason,
    action: value.action,
    confirmed: value.confirmed,
    status: value.status,
    ...(value.rejectionReason === undefined ? {} : { rejectionReason: value.rejectionReason }),
  };
}

function normalizeConversation(value) {
  if (!value || typeof value !== 'object' || !Array.isArray(value.messages) || !Array.isArray(value.proposals)) return null;
  const messages = value.messages.map(normalizeMessage);
  const proposals = value.proposals.map(normalizeProposal);
  if (messages.some((entry) => entry === null) || proposals.some((entry) => entry === null)) return null;
  return { messages, proposals };
}

function isCanonicalScope(ownerId, spaceId) {
  return ownerId === CANONICAL_OWNER_ID && spaceId === CANONICAL_SPACE_ID;
}

/** Local-only, owner/space bounded persistence. It never makes a network request. */
export function createHomeConversationRepository(options = {}) {
  const { ownerId = CANONICAL_OWNER_ID, spaceId = CANONICAL_SPACE_ID, storage = globalThis.localStorage } = typeof options?.getItem === 'function'
    ? { storage: options }
    : options;
  const conversationKey = homeConversationStorageKey(ownerId, spaceId);
  const draftKey = homeDraftStorageKey(ownerId, spaceId);
  let conversationLoaded;
  let draftLoaded;
  let legacyLoaded;
  let conversationWriteBlocked = false;
  let draftWriteBlocked = false;

  function read(key) {
    try { return { ok: true, value: storage?.getItem(key) ?? null }; } catch { return { ok: false, value: null }; }
  }

  function quarantine(key, raw) {
    try {
      const quarantineKey = `${key}:quarantine`;
      if (storage?.getItem(quarantineKey) == null) storage?.setItem(quarantineKey, raw);
    } catch {
      // Best effort only. The source value remains untouched and writes stay blocked.
    }
  }

  function conversationEnvelope(conversation) {
    return { schemaVersion: HOME_CONVERSATION_SCHEMA_VERSION, ownerId, spaceId, conversation };
  }

  function draftEnvelope(draft) {
    return { schemaVersion: HOME_CONVERSATION_SCHEMA_VERSION, ownerId, spaceId, draft };
  }

  function parseConversationEnvelope(raw) {
    const parsed = JSON.parse(raw);
    if (parsed?.schemaVersion !== HOME_CONVERSATION_SCHEMA_VERSION || parsed.ownerId !== ownerId || parsed.spaceId !== spaceId) return null;
    return normalizeConversation(parsed.conversation);
  }

  function loadLegacy() {
    if (legacyLoaded) return legacyLoaded;
    legacyLoaded = (() => {
      const result = read(HOME_CONVERSATION_STORAGE_KEY);
      if (!result.ok) {
        conversationWriteBlocked = true;
        draftWriteBlocked = true;
        return { present: false, conversation: EMPTY_HOME_CONVERSATION_STATE, draft: '' };
      }
      if (result.value == null) return { present: false, conversation: EMPTY_HOME_CONVERSATION_STATE, draft: '' };
      try {
        const parsed = JSON.parse(result.value);
        const conversation = normalizeConversation(parsed);
        if (!conversation || (parsed.input !== undefined && typeof parsed.input !== 'string')) throw new Error('invalid legacy Home state');
        return { present: true, conversation, draft: typeof parsed.input === 'string' ? parsed.input.slice(0, 1000) : '' };
      } catch {
        conversationWriteBlocked = true;
        draftWriteBlocked = true;
        quarantine(HOME_CONVERSATION_STORAGE_KEY, result.value);
        return { present: true, conversation: EMPTY_HOME_CONVERSATION_STATE, draft: '' };
      }
    })();
    return legacyLoaded;
  }

  async function load() {
    if (conversationLoaded) return conversationLoaded;
    conversationLoaded = Promise.resolve().then(() => {
      const scoped = read(conversationKey);
      if (!scoped.ok) {
        conversationWriteBlocked = true;
        return EMPTY_HOME_CONVERSATION_STATE;
      }
      if (scoped.value != null) {
        try {
          const conversation = parseConversationEnvelope(scoped.value);
          if (!conversation) throw new Error('invalid scoped conversation');
          return conversation;
        } catch {
          conversationWriteBlocked = true;
          quarantine(conversationKey, scoped.value);
          return EMPTY_HOME_CONVERSATION_STATE;
        }
      }
      if (!isCanonicalScope(ownerId, spaceId)) return EMPTY_HOME_CONVERSATION_STATE;
      const legacy = loadLegacy();
      if (!legacy.present || conversationWriteBlocked) return EMPTY_HOME_CONVERSATION_STATE;
      try { storage?.setItem(conversationKey, JSON.stringify(conversationEnvelope(legacy.conversation))); } catch { /* legacy remains the source for the next load */ }
      return legacy.conversation;
    });
    return conversationLoaded;
  }

  async function save(value) {
    await load();
    if (conversationWriteBlocked) throw new Error('Home conversation requires recovery before writing');
    const next = normalizeConversation(value);
    if (!next) throw new Error('Invalid Home conversation');
    storage?.setItem(conversationKey, JSON.stringify(conversationEnvelope(next)));
    conversationLoaded = Promise.resolve(next);
    return next;
  }

  async function loadDraft() {
    if (draftLoaded) return draftLoaded;
    draftLoaded = Promise.resolve().then(() => {
      const scoped = read(draftKey);
      if (!scoped.ok) {
        draftWriteBlocked = true;
        return '';
      }
      if (scoped.value != null) {
        try {
          const parsed = JSON.parse(scoped.value);
          if (parsed?.schemaVersion !== HOME_CONVERSATION_SCHEMA_VERSION || parsed.ownerId !== ownerId || parsed.spaceId !== spaceId || typeof parsed.draft !== 'string' || parsed.draft.length > 1000) throw new Error('invalid scoped draft');
          return parsed.draft;
        } catch {
          draftWriteBlocked = true;
          quarantine(draftKey, scoped.value);
          return '';
        }
      }
      if (!isCanonicalScope(ownerId, spaceId)) return '';
      const legacy = loadLegacy();
      if (draftWriteBlocked) return '';
      const legacyDraft = read(HOME_DRAFT_STORAGE_KEY);
      if (!legacyDraft.ok) {
        draftWriteBlocked = true;
        return '';
      }
      if (legacyDraft.value != null) {
        const draft = legacyDraft.value.slice(0, 1000);
        try { storage?.setItem(draftKey, JSON.stringify(draftEnvelope(draft))); } catch { /* legacy remains the source for the next load */ }
        return draft;
      }
      if (!legacy.present || draftWriteBlocked) return '';
      try { storage?.setItem(draftKey, JSON.stringify(draftEnvelope(legacy.draft))); } catch { /* legacy remains the source for the next load */ }
      return legacy.draft;
    });
    return draftLoaded;
  }

  async function saveDraft(value) {
    await loadDraft();
    if (draftWriteBlocked) throw new Error('Home draft requires recovery before writing');
    const draft = typeof value === 'string' ? value.slice(0, 1000) : '';
    storage?.setItem(draftKey, JSON.stringify(draftEnvelope(draft)));
    draftLoaded = Promise.resolve(draft);
    return draft;
  }

  return { load, save, loadDraft, saveDraft };
}
