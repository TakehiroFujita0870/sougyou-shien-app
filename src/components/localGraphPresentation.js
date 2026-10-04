export const COLORS = {
  // Pastel stellar-temperature palette, used as kind cues rather than measured temperatures.
  idea: '#d4e3ff', asset: '#ffd1a8', source: '#f4f2ee', facet: '#fff1d2',
  person: '#ffd2bb', owner_profile: '#ffe3b8', organization: '#e4edff',
  research_material: '#fff7e8', decision: '#ffdcc2', experiment: '#deebff',
  instruction_artifact: '#fff0d8', report_version: '#f4f2ee',
};
const NODE_KIND_LABELS = {
  idea: 'アイデア', asset: 'アセット', person: '人物', owner_profile: '本人',
  source: '出典', organization: '組織', research_material: '調査資料',
  decision: '判断', experiment: '実験', instruction_artifact: '作業指示', facet: '分類',
};
export function nodeKindLabel(kind) {
  return NODE_KIND_LABELS[kind] ?? '記録';
}
export function relationStatusLabel(status) {
  if (status === 'confirmed') return '確定';
  if (status === 'inferred') return '推測';
  if (status === 'proposed') return '提案';
  return '状態未設定';
}
export function initialPosition(identity, index) {
  let hash = 2166136261;
  for (const character of identity) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  const angle = ((hash >>> 0) / 4294967296) * Math.PI * 2;
  const radius = 18 + (index % 4) * 9;
  return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
}

export function shortLabel(label) {
  const characters = Array.from(label);
  return characters.length > 16 ? `${characters.slice(0, 16).join('')}…` : label;
}

export function starRadius(node) {
  if (node.kind === 'facet') {
    if (!Number.isInteger(node.abstractionDepth) || node.abstractionDepth < 0) return 11;
    return Math.max(11, 16 / Math.sqrt(1 + node.abstractionDepth * 0.8));
  }
  if (node.kind === 'idea') return 9;
  if (node.kind === 'asset' || node.kind === 'owner_profile') return 7;
  if (node.kind === 'person' || node.kind === 'organization') return 8;
  return 5.5;
}

const ALWAYS_LABELLED_KINDS = new Set(['idea', 'facet']);

function graphLabelBounds(node, label, scale, measureText, anchor) {
  if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) return null;
  const fontSize = 12 / scale;
  const measuredWidth = measureText(label, fontSize);
  const width = Number.isFinite(measuredWidth) ? measuredWidth : Array.from(label).length * fontSize * 0.75;
  const gap = starRadius(node) + 5 / scale;
  const boxWidth = Math.max(width, 8 / scale) + 8 / scale;
  const halfHeight = 8 / scale;
  const left = anchor.includes('left') ? node.x - gap - boxWidth
    : anchor.includes('right') ? node.x + gap : node.x - boxWidth / 2;
  const y = anchor.includes('top') ? node.y - gap - halfHeight
    : anchor.includes('bottom') ? node.y + gap + halfHeight : node.y;
  return { left, right: left + boxWidth, top: y - halfHeight, bottom: y + halfHeight,
    x: left + 4 / scale, y, anchor };
}

function gridCells(bounds, size) {
  const cells = [];
  for (let x = Math.floor(bounds.left / size); x <= Math.floor(bounds.right / size); x += 1) {
    for (let y = Math.floor(bounds.top / size); y <= Math.floor(bounds.bottom / size); y += 1) {
      cells.push(x + ',' + y);
    }
  }
  return cells;
}

function overlapsInGrid(bounds, grid, size) {
  for (const cell of gridCells(bounds, size)) {
    for (const other of grid.get(cell) ?? []) {
      if (bounds.left < other.right && bounds.right > other.left
        && bounds.top < other.bottom && bounds.bottom > other.top) return true;
    }
  }
  return false;
}

function addToGrid(bounds, grid, size) {
  for (const cell of gridCells(bounds, size)) {
    const occupants = grid.get(cell);
    if (occupants) occupants.push(bounds);
    else grid.set(cell, [bounds]);
  }
}

export function graphLabelPlacements(nodes, globalScale, priorityIds = new Set(), hoveredId = '', measureText = (label, size) => Array.from(label).length * size * 0.75, viewport, previous = new Map()) {
  const scale = Number.isFinite(globalScale) ? Math.max(globalScale, 0.1) : 1;
  const emphasized = priorityIds instanceof Set ? priorityIds : new Set(priorityIds);
  const allLabelsAtZoom = scale >= 1.25;
  const labelNodes = nodes.filter((node) => ALWAYS_LABELLED_KINDS.has(node.kind)
    || allLabelsAtZoom || emphasized.has(node.id) || node.id === hoveredId);
  const gridSize = 36 / scale;
  const occupied = new Map();

  for (const node of nodes) {
    if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) continue;
    const margin = 2 / scale;
    const radius = starRadius(node) + margin;
    addToGrid({
      left: node.x - radius, right: node.x + radius,
      top: node.y - radius, bottom: node.y + radius,
    }, occupied, gridSize);
  }

  const candidates = labelNodes
    .filter((node) => typeof node.label === 'string' && node.label.length > 0)
    .map((node) => {
      const selected = emphasized.has(node.id);
      const hovered = node.id === hoveredId;
      const priority = selected ? 0 : hovered ? 1 : node.kind === 'facet' ? 2 : node.kind === 'idea' ? 3 : 4;
      return { node, priority };
    })
    .filter(({ node }) => Number.isFinite(node.x) && Number.isFinite(node.y))
    .sort((left, right) => left.priority - right.priority
      || (String(left.node.id) < String(right.node.id) ? -1 : String(left.node.id) > String(right.node.id) ? 1 : 0));

  const placements = new Map();
  for (const { node } of candidates) {
    const preferred = previous.get(node.id)?.anchor;
    const anchors = [...new Set([preferred, 'right', 'left', 'top', 'bottom', 'top-right', 'top-left', 'bottom-right', 'bottom-left'].filter(Boolean))];
    for (const anchor of anchors) {
      const box = graphLabelBounds(node, shortLabel(node.label), scale, measureText, anchor);
      if (viewport && (box.left < viewport.left || box.right > viewport.right
        || box.top < viewport.top || box.bottom > viewport.bottom)) continue;
      if (overlapsInGrid(box, occupied, gridSize)) continue;
      placements.set(node.id, box);
      addToGrid(box, occupied, gridSize);
      break;
    }
  }
  return placements;
}
