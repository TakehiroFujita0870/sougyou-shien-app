import { expect, it } from 'vitest';
import { semanticGraphData, regionGraphData } from './localGraphData.js';
import { COLORS, starRadius, visibleGraphLabelIds } from './localGraphPresentation.js';

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

it('assigns abstraction depth only along unambiguous confirmed Facet taxonomy', () => {
  const graph = {
    nodes: [
      { id: 'root', kind: 'facet', label: '領域' },
      { id: 'middle', kind: 'facet', label: '分野' },
      { id: 'leaf', kind: 'facet', label: '具体分類' },
      { id: 'conflict', kind: 'facet', label: '階層が曖昧' },
      { id: 'inferred', kind: 'facet', label: '推測上の子' },
      { id: 'isolated', kind: 'facet', label: '単独分類' },
      { id: 'idea', kind: 'idea', label: '創業案' },
    ],
    edges: [],
    semantic_edges: [
      { id: 'tax-root-middle', source_id: 'root', target_id: 'middle', predicate: 'CLASSIFIED_AS', status: 'confirmed' },
      { id: 'tax-middle-leaf', source_id: 'middle', target_id: 'leaf', predicate: 'CLASSIFIED_AS', status: 'confirmed' },
      { id: 'tax-root-conflict', source_id: 'root', target_id: 'conflict', predicate: 'CLASSIFIED_AS', status: 'confirmed' },
      { id: 'tax-middle-conflict', source_id: 'middle', target_id: 'conflict', predicate: 'CLASSIFIED_AS', status: 'confirmed' },
      { id: 'tax-middle-inferred', source_id: 'middle', target_id: 'inferred', predicate: 'CLASSIFIED_AS', status: 'inferred' },
      { id: 'idea-classification', source_id: 'idea', target_id: 'leaf', predicate: 'CLASSIFIED_AS', status: 'confirmed' },
    ],
  };

  expect(semanticGraphData(graph).nodes.map(({ id, abstractionDepth }) => [id, abstractionDepth])).toEqual([
    ['root', 0], ['middle', 1], ['leaf', 2], ['conflict', null], ['inferred', null], ['isolated', null], ['idea', null],
  ]);
});

it('distinguishes kinds by larger sizes without inventing Facet hierarchy', () => {
  const unknownFacet = { kind: 'facet', abstractionDepth: null };
  const idea = { kind: 'idea', abstractionDepth: 0 };
  const rootFacet = { kind: 'facet', abstractionDepth: 0 };
  const childFacet = { kind: 'facet', abstractionDepth: 1 };
  expect(starRadius(rootFacet)).toBeGreaterThan(starRadius(childFacet));
  expect(starRadius(unknownFacet)).toBe(11);
  expect(starRadius(idea)).toBe(9);
  expect(starRadius(unknownFacet)).toBeGreaterThan(starRadius(idea));
  expect(starRadius(idea)).toBeGreaterThan(starRadius({ kind: 'asset' }));
  expect(starRadius({ kind: 'asset' })).toBeGreaterThan(starRadius({ kind: 'source' }));
  expect(starRadius({ kind: 'source' })).toBeGreaterThan(5);
});

it('uses distinct pastel stellar colors for main kinds, without green or violet hues', () => {
  expect(new Set(['idea', 'asset', 'source', 'facet'].map(kind => COLORS[kind])).size).toBe(4);
  for (const color of Object.values(COLORS)) {
    expect(color).toMatch(/^#[a-f0-9]{6}$/);
    const [red, green, blue] = [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16));
    expect(Math.min(red, green, blue)).toBeGreaterThanOrEqual(160);
    expect((red >= green && green >= blue) || (blue >= green && green >= red)).toBe(true);
  }
});

it('shows idea and Facet labels at rest, avoids collisions deterministically, and reveals other labels on zoom', () => {
  const nodes = [
    { id: 'facet-root', kind: 'facet', label: '顧客と現場', x: 0, y: 0 },
    { id: 'idea-overlap', kind: 'idea', label: '現場向け支援の構想', x: 1, y: 0 },
    { id: 'idea-clear', kind: 'idea', label: '小さく試す', x: 420, y: 0 },
    { id: 'asset', kind: 'asset', label: '利用者インタビュー', x: 850, y: 0 },
  ];
  const measureText = (label, fontSize) => Array.from(label).length * fontSize;

  const atRest = visibleGraphLabelIds(nodes, 0.9, new Set(), '', measureText);
  expect([...atRest]).toEqual(['facet-root', 'idea-clear']);
  expect([...visibleGraphLabelIds([...nodes].reverse(), 0.9, new Set(), '', measureText)])
    .toEqual([...atRest]);

  const zoomed = visibleGraphLabelIds(nodes, 1.4, new Set(['asset']), '', measureText);
  expect(zoomed.has('asset')).toBe(true);
});
