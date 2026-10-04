import { starRadius } from './localGraphPresentation.js';

export function isGraphClick(press) {
  return Boolean(press && press.maxDistance <= 5);
}

export function graphHitTarget(point, nodes, links, labels, scale) {
  if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return null;
  const zoom = Math.max(scale || 1, 0.1);
  let closest = null;
  let distance = Infinity;
  for (const node of nodes) {
    const current = Math.hypot(point.x - node.x, point.y - node.y);
    if (current <= starRadius(node) + 5 / zoom && current < distance) {
      closest = node;
      distance = current;
    }
  }
  if (closest) return { type: 'node', node: closest };
  for (const node of nodes) {
    const box = labels.get(node.id);
    if (box && point.x >= box.left && point.x <= box.right && point.y >= box.top && point.y <= box.bottom) {
      return { type: 'node', node };
    }
  }
  const byId = new Map(nodes.map(node => [node.id, node]));
  for (const link of links) {
    const source = typeof link.source === 'object' ? link.source : byId.get(link.source);
    const target = typeof link.target === 'object' ? link.target : byId.get(link.target);
    if (!source || !target) continue;
    const dx = target.x - source.x, dy = target.y - source.y;
    const length = dx * dx + dy * dy;
    if (!Number.isFinite(length) || !length) continue;
    const t = Math.max(0, Math.min(1, ((point.x - source.x) * dx + (point.y - source.y) * dy) / length));
    const current = Math.hypot(point.x - source.x - t * dx, point.y - source.y - t * dy);
    if (current <= 4 / zoom && current < distance) { closest = link; distance = current; }
  }
  return closest ? { type: 'link', link: closest } : null;
}
