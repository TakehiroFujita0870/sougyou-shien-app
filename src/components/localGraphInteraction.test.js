import { expect, it } from 'vitest';
import { graphHitTarget, isGraphClick } from './localGraphInteraction.js';
import { graphLabelPlacements } from './localGraphPresentation.js';

it('accepts minor pointer jitter but rejects drags including an excursion back to the start', () => {
  for (const distance of [0, 2, 5]) expect(isGraphClick({ maxDistance: distance })).toBe(true);
  expect(isGraphClick({ maxDistance: 5.01 })).toBe(false);
  expect(isGraphClick(null)).toBe(false);
});

it('picks current stars and displayed names independently of the previous hover', () => {
  const nodes = [{ id: 'a', kind: 'idea', x: 0, y: 0 }, { id: 'b', kind: 'asset', x: 100, y: 0 }];
  const labels = new Map([['b', { left: 110, right: 160, top: -8, bottom: 8 }]]);
  expect(graphHitTarget({ x: 100, y: 0 }, nodes, [], labels, 1).node.id).toBe('b');
  expect(graphHitTarget({ x: 140, y: 0 }, nodes, [], labels, 1).node.id).toBe('b');
  expect(graphHitTarget({ x: 40, y: 90 }, nodes, [], labels, 1)).toBeNull();
  expect(graphHitTarget({ x: 50, y: 0 }, nodes, [{ source: nodes[0], target: nodes[1] }], labels, 1).type).toBe('link');
});

it('tries alternative anchors, keeps a viable anchor, and reveals assets on zoom', () => {
  const nodes = [{ id: 'a', kind: 'idea', label: '事業案', x: 0, y: 0 },
    { id: 'b', kind: 'asset', label: '経験', x: 35, y: 0 }];
  const measure = () => 40;
  const labels = graphLabelPlacements(nodes, 1, new Set(), '', measure);
  expect(labels.has('a')).toBe(true);
  expect(labels.get('a').anchor).not.toBe('right');
  expect(labels.has('b')).toBe(false);
  const zoomed = graphLabelPlacements(nodes, 2, new Set(), '', measure, undefined, labels);
  expect(zoomed.get('a').anchor).toBe(labels.get('a').anchor);
  expect(zoomed.has('b')).toBe(true);
});
