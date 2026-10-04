const VISIBLE_NODE_KINDS = new Set([
  'idea', 'asset', 'person', 'organization', 'owner_profile', 'source',
  'research_material', 'decision', 'experiment', 'instruction_artifact', 'facet',
]);
const INTERNAL_EDGE_LABELS = new Set([
  'SUPERSEDES', 'HAS_REVISION', 'CURRENT_REVISION', 'CURRENT_SOURCE_REVISION',
  'HAS_SOURCE_REVISION', 'HAS_CHUNK', 'EVIDENCE_FROM', 'HAS_AUDIT_EVENT',
]);
const RELATION_LABELS = {
  CITES: '出典（根拠あり）',
  OWNS: '保有する', GOVERNED_BY: '方針に従う', USES_SKILL: 'スキルを使う',
  REUSES: '再利用する', USES: '利用する', SUPPORTS: '支える', ADDRESSES: '課題に応える', DERIVED_FROM: '派生した',
  EVALUATED_BY: '評価された', WORKS_AT: '所属する', HAS_CAPABILITY: '能力を持つ',
  CAN_CONTRIBUTE_TO: '貢献できる', INTRODUCED_BY: '紹介された',
  REQUIRES_CAPABILITY: '能力を要する', CLASSIFIED_AS: '分類される',
  SERVES: '対象とする', COMPETES_WITH: '競合する', DEPENDS_ON: '依存する',
  MERGED_INTO: '統合された', SUPPORTED_BY: '裏付けられる',
  CONTRADICTED_BY: '反証される', BASED_ON: '基づく',
};

function displayRelation(label) {
  if (RELATION_LABELS[label]) return RELATION_LABELS[label];
  return /^[A-Z][A-Z_]+$/.test(label) ? '関係する' : label;
}

export function semanticGraphData(graph) {
  const nodes = (graph.nodes ?? []).filter((node) => VISIBLE_NODE_KINDS.has(node.kind));
  const nodeIds = new Set(nodes.map((node) => node.id));
  const isScaffoldEdge = (edge) => INTERNAL_EDGE_LABELS.has(edge.label)
    || edge.label?.startsWith('ASSERTS_') || edge.label === 'EVIDENCED_BY';
  const edges = (graph.edges ?? []).filter((edge) => nodeIds.has(edge.source)
    && nodeIds.has(edge.target) && !isScaffoldEdge(edge))
    .map((edge) => ({ ...edge, label: displayRelation(edge.label) }));
  for (const assertion of graph.semantic_edges ?? []) {
    if (!assertion?.id || !nodeIds.has(assertion.source_id) || !nodeIds.has(assertion.target_id)
      || typeof assertion.predicate !== 'string' || !assertion.predicate) continue;
    edges.push({
      source: assertion.source_id,
      target: assertion.target_id,
      predicate: assertion.predicate,
      label: displayRelation(assertion.predicate),
      assertionId: assertion.id,
      status: assertion.status,
      confidence: assertion.confidence,
      evidenceIds: Array.isArray(assertion.evidence_ids) ? assertion.evidence_ids : [],
      basedOnBriefId: assertion.based_on_brief_id,
      basedOnBriefSectionIndex: assertion.based_on_brief_section_index,
    });
  }
  const facetIds = new Set(nodes.filter((node) => node.kind === 'facet').map((node) => node.id));
  const facetParents = new Map([...facetIds].map((id) => [id, []]));
  const facetChildren = new Map([...facetIds].map((id) => [id, []]));
  for (const edge of edges) {
    if (edge.predicate !== 'CLASSIFIED_AS' || edge.status !== 'confirmed'
      || !facetIds.has(edge.source) || !facetIds.has(edge.target)) continue;
    facetParents.get(edge.target).push(edge.source);
    facetChildren.get(edge.source).push(edge.target);
  }
  const resolvedFacetDepths = new Map();
  const resolvingFacetIds = new Set();
  const resolveFacetDepth = (id) => {
    if (resolvedFacetDepths.has(id)) return resolvedFacetDepths.get(id);
    if (resolvingFacetIds.has(id)) return null;
    resolvingFacetIds.add(id);
    const parents = facetParents.get(id);
    let depth = null;
    if (parents.length === 0) {
      if (facetChildren.get(id).length > 0) depth = 0;
    } else {
      const parentDepths = parents.map(resolveFacetDepth);
      if (parentDepths.every(Number.isInteger)) {
        const candidates = new Set(parentDepths.map((parentDepth) => parentDepth + 1));
        if (candidates.size === 1) depth = candidates.values().next().value;
      }
    }
    resolvingFacetIds.delete(id);
    resolvedFacetDepths.set(id, depth);
    return depth;
  };
  return {
    nodes: nodes.map((node) => ({
      ...node,
      abstractionDepth: node.kind === 'facet' ? resolveFacetDepth(node.id) : null,
    })),
    edges,
  };
}


export function regionGraphData(facetId, hits, graphNodes) {
  const byId = new Map(graphNodes.map((node) => [node.id, node]));
  const root = byId.get(facetId);
  if (!root) return { nodes: [], edges: [] };
  const nodes = [{ id: root.id, kind: 'facet', label: root.label, graphDepth: 0 }];
  const edges = [];
  const added = new Set([root.id]);
  for (const hit of hits) {
    const path = hit.facet_path;
    if (!Array.isArray(path) || path.length !== hit.depth + 1
      || path[0]?.facet_id !== facetId || path.at(-1)?.facet_id !== hit.matched_facet_id) continue;
    for (let index = 1; index < path.length; index += 1) {
      const current = path[index];
      const previous = path[index - 1];
      if (!added.has(current.facet_id)) {
        nodes.push({ id: current.facet_id, kind: 'facet', label: current.label, graphDepth: current.depth });
        added.add(current.facet_id);
      }
      const edgeStatus = hit.taxonomy_status_path[index - 1];
      if (!edges.some((edge) => edge.source === previous.facet_id && edge.target === current.facet_id)) {
        edges.push({ source: previous.facet_id, target: current.facet_id, label: edgeStatus === 'confirmed' ? '確定' : '推測' });
      }
    }
    if (!added.has(hit.id)) {
      nodes.push({ id: hit.id, kind: hit.kind, label: hit.title, graphDepth: path.at(-1).depth });
      added.add(hit.id);
    }
    edges.push({ source: hit.matched_facet_id, target: hit.id, label: hit.classification_status === 'confirmed' ? '確定' : '推測' });
  }
  return { nodes, edges };
}
