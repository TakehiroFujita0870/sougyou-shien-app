import { expect, it } from 'vitest';
import { fitWideGraph } from './localGraphLayout.js';

it('spreads a settled square across the available wide viewport and fits its halos', () => {
  const nodes = [{ x: -200, y: -200, kind: 'idea' }, { x: 200, y: 200, kind: 'facet' }];
  const original = structuredClone(nodes);
  const layout = fitWideGraph(nodes, 1026, 664);
  expect(layout.positions[1].x / layout.positions[1].y).toBeCloseTo(1026 / 664);
  expect(layout.zoom).toBeGreaterThan(0.9);
  for (const point of layout.positions) {
    expect(Math.abs(point.x) * layout.zoom + 20 * layout.zoom).toBeLessThan(1026 / 2);
    expect(Math.abs(point.y) * layout.zoom + 20 * layout.zoom).toBeLessThan(664 / 2);
  }
  expect(nodes).toEqual(original);
});

it('handles a single point, a line, and empty or unfinished data without non-finite coordinates', () => {
  for (const nodes of [[{ x: 10, y: 10 }], [{ x: 0, y: 1 }, { x: 100, y: 1 }]]) {
    const layout = fitWideGraph(nodes, 1026, 664);
    expect(layout.zoom).toBeGreaterThan(0);
    expect(layout.zoom).toBeLessThanOrEqual(6);
    expect(layout.positions.every(point => Number.isFinite(point.x) && Number.isFinite(point.y))).toBe(true);
  }
  expect(fitWideGraph([], 1026, 664)).toBeNull();
  expect(fitWideGraph([{ x: NaN, y: 0 }], 1026, 664)).toBeNull();
  expect(fitWideGraph([{ x: 0, y: 0 }], 0, 0)).toBeNull();
});
