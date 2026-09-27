export const MAX_GRAPH_DEPTH = 3;

const DEPTH_ZERO = new Set(['idea', 'asset', 'person', 'organization', 'owner_profile', 'facet']);
const DEPTH_ONE = new Set(['source', 'research_campaign', 'report_version', 'instruction_artifact', 'experiment', 'decision']);
const DEPTH_THREE = new Set(['content_chunk', 'evidence', 'research_material']);

export function graphDepthForKind(kind) {
  if (DEPTH_ZERO.has(kind)) return 0;
  if (DEPTH_ONE.has(kind)) return 1;
  if (DEPTH_THREE.has(kind)) return 3;
  return 2;
}

export function nextGraphDepth(current, deltaY) {
  return Math.max(0, Math.min(MAX_GRAPH_DEPTH, current + Math.sign(deltaY)));
}

export function visibleAtGraphDepth(nodeDepth, viewedDepth) {
  return nodeDepth <= viewedDepth && nodeDepth >= Math.max(0, viewedDepth - 1);
}

export function visibleGraphLink(source, target, viewedDepth) {
  return Boolean(source && target && visibleAtGraphDepth(source.depth, viewedDepth) && visibleAtGraphDepth(target.depth, viewedDepth));
}
