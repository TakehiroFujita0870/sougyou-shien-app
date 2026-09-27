import { describe, expect, it } from 'vitest';
import { createLocalDashboardClient } from './localDashboardClient';

const edge = { id: 'assertion-1', source_id: 'idea-1', target_id: 'asset-1', predicate: 'REUSES', status: 'inferred', confidence: 0.8, evidence_ids: ['evidence-1'], based_on_brief_id: 'brief-1', based_on_brief_section_index: 5 };
const graph = { status: 'ready', nodes: [{ id: 'idea-1', kind: 'idea', label: '合成案' }, { id: 'asset-1', kind: 'asset', label: '合成経験' }], edges: [], semantic_edges: [edge], truncated: false };
function client(payload) {
  return createLocalDashboardClient({ location: { origin: 'http://localhost:8765', hostname: 'localhost' }, fetchImpl: async () => ({ ok: true, json: async () => payload }) });
}
describe('local semantic graph transport', () => {
  it('retains only the semantic edge contract through the real client', async () => {
    const result = await client({ ...graph, semantic_edges: [{ ...edge, payload_json: 'PRIVATE', source_text: 'PRIVATE' }] }).getGraph();
    expect(result.semantic_edges).toEqual([edge]);
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
  });
  it.each([{ target_id: 'missing' }, { confidence: 2 }, { based_on_brief_section_index: 8 }, { evidence_ids: [''] }, { status: 'rejected' }])('rejects invalid semantic edges: %j', async (change) => {
    await expect(client({ ...graph, semantic_edges: [{ ...edge, ...change }] }).getGraph()).rejects.toThrow();
  });
});
