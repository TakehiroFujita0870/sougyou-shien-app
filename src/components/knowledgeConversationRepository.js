export const KNOWLEDGE_CONVERSATION_STORAGE_KEY = 'kadode:knowledge-conversation';
const emptyState = { messages: [] };

function normalizeMessage(value) {
  return value && (value.role === 'user' || value.role === 'assistant') && typeof value.content === 'string'
    ? { role: value.role, content: value.content.slice(0, 2000) }
    : null;
}

export function createKnowledgeConversationRepository({ ownerId, spaceId, storage = globalThis.localStorage } = {}) {
  const key = `${KNOWLEDGE_CONVERSATION_STORAGE_KEY}:${ownerId}:${spaceId}`;
  return {
    async load() {
      try {
        const parsed = JSON.parse(storage?.getItem(key) ?? '{}');
        return { messages: Array.isArray(parsed.messages) ? parsed.messages.map(normalizeMessage).filter(Boolean) : [] };
      } catch { return emptyState; }
    },
    async save(value) {
      const next = { messages: Array.isArray(value?.messages) ? value.messages.map(normalizeMessage).filter(Boolean) : [] };
      storage?.setItem(key, JSON.stringify(next));
      return next;
    },
  };
}

export function respondToKnowledge(message, fixture) {
  const asset = fixture?.asset?.name ?? '現在の資料';
  const judgement = fixture?.decision?.judgement ?? '次の判断';
  return `「${asset}」と「${judgement}」を踏まえると、${message.trim()}を確認対象として整理できます。根拠と未確認事項を分けて見ていきましょう。`;
}
