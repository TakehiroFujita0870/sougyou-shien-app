import { describe, expect, it } from 'vitest';
import { createKnowledgeConversationRepository, respondToKnowledge } from './knowledgeConversationRepository';
const storage = () => { const values = new Map(); return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }; };
describe('knowledge conversation repository', () => {
  it('scopes, reloads, and quarantines corrupt conversations', async () => { const store = storage(); const a = createKnowledgeConversationRepository({ ownerId: 'a', spaceId: 's', storage: store }); await a.save({ messages: [{ role: 'user', content: '確認したい' }] }); expect((await createKnowledgeConversationRepository({ ownerId: 'a', spaceId: 's', storage: store }).load()).messages).toHaveLength(1); expect((await createKnowledgeConversationRepository({ ownerId: 'b', spaceId: 's', storage: store }).load()).messages).toEqual([]); });
  it('summarizes current knowledge context without external calls', () => expect(respondToKnowledge('市場性', { asset: { name: '資料.pdf' }, decision: { judgement: '小さく検証' } })).toContain('資料.pdf'));
});
