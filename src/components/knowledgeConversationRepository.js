export const KNOWLEDGE_CONVERSATION_STORAGE_KEY = 'kadode:knowledge-conversation';
const emptyState = { messages: [], entries: [] };

function normalizeMessage(value) {
  return value && (value.role === 'user' || value.role === 'assistant') && typeof value.content === 'string'
    ? { role: value.role, content: value.content.slice(0, 2000), createdAt: typeof value.createdAt === 'string' ? value.createdAt : null }
    : null;
}

function normalizeEntry(value) {
  if (!value || typeof value.id !== 'string' || typeof value.title !== 'string' || typeof value.content !== 'string') return null;
  const category = ['profile', 'decision', 'conversation', 'note'].includes(value.category) ? value.category : 'note';
  const createdAt = typeof value.createdAt === 'string' ? value.createdAt : new Date(0).toISOString();
  const sourceType = ['synthetic', 'local', 'unknown'].includes(value.sourceType) ? value.sourceType : 'unknown';
  const confidence = ['high', 'medium', 'unknown'].includes(value.confidence) ? value.confidence : 'unknown';
  return { id: value.id, category, title: value.title.slice(0, 100), content: value.content.slice(0, 4000), createdAt, updatedAt: typeof value.updatedAt === 'string' ? value.updatedAt : createdAt, sourceType, projectId: typeof value.projectId === 'string' ? value.projectId.slice(0, 100) : '', evaluationView: typeof value.evaluationView === 'string' ? value.evaluationView.slice(0, 100) : '', confidence, unknowns: Array.isArray(value.unknowns) ? value.unknowns.filter((item) => typeof item === 'string').slice(0, 8).map((item) => item.slice(0, 200)) : ['未確認'] };
}

export function createKnowledgeConversationRepository({ ownerId, spaceId, storage = globalThis.localStorage } = {}) {
  const key = `${KNOWLEDGE_CONVERSATION_STORAGE_KEY}:${ownerId}:${spaceId}`;
  return {
    async load() {
      try {
        const parsed = JSON.parse(storage?.getItem(key) ?? '{}');
        return { messages: Array.isArray(parsed.messages) ? parsed.messages.map(normalizeMessage).filter(Boolean) : [], entries: Array.isArray(parsed.entries) ? parsed.entries.map(normalizeEntry).filter(Boolean) : [] };
      } catch { return emptyState; }
    },
    async save(value) {
      const next = { messages: Array.isArray(value?.messages) ? value.messages.map(normalizeMessage).filter(Boolean) : [], entries: Array.isArray(value?.entries) ? value.entries.map(normalizeEntry).filter(Boolean) : [] };
      storage?.setItem(key, JSON.stringify(next));
      return next;
    },
  };
}

export function proposeKnowledgeEntry(content) {
  const trimmed = content.trim();
  const category = /(決定|採用|却下|保留)/.test(trimmed) ? 'decision' : /(顧客|経験|強み|プロフィール)/.test(trimmed) ? 'profile' : 'note';
  const label = { profile: 'プロフィール', decision: '意思決定', note: 'メモ' }[category];
  const createdAt = new Date().toISOString();
  return { id: `knowledge:${Date.now()}`, category, title: `${label}: ${trimmed.replace(/\s+/g, ' ').slice(0, 36)}`, content: trimmed, createdAt, updatedAt: createdAt, sourceType: 'local', confidence: 'unknown', unknowns: ['未確認'] };
}

export function respondToKnowledge(message, fixture) {
  const asset = fixture?.asset?.name ?? '現在の資料';
  const judgement = fixture?.decision?.judgement ?? '次の判断';
  return `「${asset}」と「${judgement}」を踏まえると、${message.trim()}を確認対象として整理できます。根拠と未確認事項を分けて見ていきましょう。`;
}
