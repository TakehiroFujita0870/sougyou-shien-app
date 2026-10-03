import { expect, it } from 'vitest';
import { semanticGraphData, regionGraphData } from './localGraphData.js';

it('keeps semantic assertions and hides internal research and revision records without changing the input', () => {
  const graph = { nodes: [{ id: 'idea', kind: 'idea' }, { id: 'asset', kind: 'asset' }, { id: 'history', kind: 'entity_revision' },
    { id: 'claim', kind: 'claim', label: 'claim' }, { id: 'brief', kind: 'idea_brief_version', label: 'idea brief version' }],
    edges: [{ source: 'idea', target: 'history', label: 'HAS_REVISION' }],
    semantic_edges: [{ id: 'relation', source_id: 'idea', target_id: 'asset', predicate: 'REUSES', status: 'inferred', evidence_ids: ['evidence'] }] };
  const original = JSON.stringify(graph);
  expect(semanticGraphData(graph).edges).toMatchObject([{ source: 'idea', target: 'asset', assertionId: 'relation', label: '再利用する', evidenceIds: ['evidence'] }]);
  expect(semanticGraphData(graph).nodes.map(node => node.id)).toEqual(['idea', 'asset']);
  expect(JSON.stringify(graph)).toBe(original);
});

it('retains the actual root-to-leaf path and membership depth', () => {
  const hits = [{ id: 'idea', kind: 'idea', title: 'Synthetic', depth: 1, matched_facet_id: 'leaf',
    facet_path: [{ facet_id: 'root', label: 'Root', depth: 0 }, { facet_id: 'leaf', label: 'Leaf', depth: 1 }],
    taxonomy_status_path: ['confirmed'], classification_status: 'inferred' }];
  const result = regionGraphData('root', hits, [{ id: 'root', kind: 'facet', label: 'Root' }]);
  expect(result.nodes).toEqual([{ id: 'root', kind: 'facet', label: 'Root', graphDepth: 0 }, { id: 'leaf', kind: 'facet', label: 'Leaf', graphDepth: 1 }, { id: 'idea', kind: 'idea', label: 'Synthetic', graphDepth: 1 }]);
  expect(result.edges).toEqual([{ source: 'root', target: 'leaf', label: '確定' }, { source: 'leaf', target: 'idea', label: '推測' }]);
  expect(regionGraphData('absent', hits, [])).toEqual({ nodes: [], edges: [] });
});

it('renders verified citation edges as a distinct Japanese relationship', () => {
  const graph = {
    nodes: [{ id: 'idea', kind: 'idea', label: '案' }, { id: 'source', kind: 'source', label: '資料', url: 'https://example.test/source' }],
    edges: [{ source: 'idea', target: 'source', label: 'CITES' }], semantic_edges: [],
  };
  expect(semanticGraphData(graph).edges).toEqual([{ source: 'idea', target: 'source', label: '出典（根拠あり）' }]);
});
