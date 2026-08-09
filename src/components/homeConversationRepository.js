export const HOME_CONVERSATION_STORAGE_KEY = 'kadode:home-conversation';
export const HOME_DRAFT_STORAGE_KEY = 'kadode:home-conversation:draft';
export const EMPTY_HOME_CONVERSATION_STATE = Object.freeze({ messages: [], proposals: [] });

function normalizeHomeConversation(value) {
  return value && Array.isArray(value.messages) && Array.isArray(value.proposals)
    ? { messages: value.messages, proposals: value.proposals }
    : EMPTY_HOME_CONVERSATION_STATE;
}

export function createHomeConversationRepository(storage = globalThis.localStorage) {
  return {
    async load() {
      try {
        return normalizeHomeConversation(JSON.parse(storage?.getItem(HOME_CONVERSATION_STORAGE_KEY) || 'null'));
      } catch {
        return EMPTY_HOME_CONVERSATION_STATE;
      }
    },
    async save(value) {
      const next = normalizeHomeConversation(value);
      storage?.setItem(HOME_CONVERSATION_STORAGE_KEY, JSON.stringify(next));
      return next;
    },
    async loadDraft() {
      try {
        const draft = storage?.getItem(HOME_DRAFT_STORAGE_KEY);
        if (draft != null) return draft.slice(0, 1000);
        const legacy = JSON.parse(storage?.getItem(HOME_CONVERSATION_STORAGE_KEY) || 'null');
        return typeof legacy?.input === 'string' ? legacy.input.slice(0, 1000) : '';
      } catch {
        return '';
      }
    },
    async saveDraft(value) {
      const draft = typeof value === 'string' ? value.slice(0, 1000) : '';
      storage?.setItem(HOME_DRAFT_STORAGE_KEY, draft);
      return draft;
    },
  };
}
