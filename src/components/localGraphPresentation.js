export const COLORS = {
  idea: '#8dbbff', asset: '#f3bd86', person: '#e4a6c7', owner_profile: '#f5d776',
  source: '#96d7c5', organization: '#b6a4ef', report_version: '#a5b7d8', facet: '#b6a4ef',
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
  if (node.kind !== 'facet' || !Number.isInteger(node.abstractionDepth) || node.abstractionDepth < 0) return 5;
  return Math.max(5.5, 13 / Math.sqrt(1 + node.abstractionDepth * 0.8));
}
