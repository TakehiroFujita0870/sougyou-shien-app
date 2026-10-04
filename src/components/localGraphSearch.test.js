import { expect, it } from 'vitest';
import { searchGraphNodes } from './localGraphSearch.js';

it('searches a 500-node graph and limits keyboard results without losing the total', () => {
  const nodes = Array.from({ length: 500 }, (_, index) => ({ id: `node-${index}`, label: `記録 ${index} 食品店調査` }));
  const startedAt = performance.now();
  const result = searchGraphNodes(nodes, '食品店調査');
  const elapsedMs = performance.now() - startedAt;

  expect(result.total).toBe(500);
  expect(result.results).toHaveLength(12);
  expect(result.results[0].id).toBe('node-0');
  expect(elapsedMs).toBeLessThan(100);
});
