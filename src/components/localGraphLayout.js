import { starRadius } from './localGraphPresentation.js';

// Project the settled physical layout once; never refit during user navigation.
export function fitWideGraph(nodes, width, height) {
  if (!nodes.length || width <= 64 || height <= 64
    || !nodes.every(node => Number.isFinite(node.x) && Number.isFinite(node.y))) return null;
  const xs = nodes.map(node => node.x);
  const ys = nodes.map(node => node.y);
  const left = Math.min(...xs), right = Math.max(...xs);
  const top = Math.min(...ys), bottom = Math.max(...ys);
  const spanX = right - left, spanY = bottom - top;
  const centerX = (left + right) / 2, centerY = (top + bottom) / 2;
  // Preserve area and neighborhood order, without exaggerating degenerate lines.
  const stretch = spanX > 0 && spanY > 0
    ? Math.max(0.25, Math.min(4, Math.sqrt((width / height) / (spanX / spanY)))) : 1;
  const positions = nodes.map(node => ({ x: (node.x - centerX) * stretch, y: (node.y - centerY) / stretch }));
  const halo = Math.max(...nodes.map(node => starRadius(node) * 1.8));
  const zoom = Math.min(6, (width - 64) / (spanX * stretch + halo * 2),
    (height - 64) / (spanY / stretch + halo * 2));
  return { positions, zoom };
}
