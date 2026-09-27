const INTERNAL_NODE_KINDS = new Set([
  'relation_assertion', 'entity_revision', 'source_revision', 'content_chunk', 'evidence',
  'audit_event', 'capture_audit', 'report_version',
]);
const INTERNAL_EDGE_LABELS = new Set([
  'SUPERSEDES', 'HAS_REVISION', 'CURRENT_REVISION', 'CURRENT_SOURCE_REVISION',
  'HAS_SOURCE_REVISION', 'HAS_CHUNK', 'EVIDENCE_FROM', 'HAS_AUDIT_EVENT',
]);

export function semanticGraphData(graph) {
  const nodes = (graph.nodes ?? []).filter((node) => !INTERNAL_NODE_KINDS.has(node.kind));
  const nodeIds = new Set(nodes.map((node) => node.id));
  const isScaffoldEdge = (edge) => INTERNAL_EDGE_LABELS.has(edge.label)
    || edge.label?.startsWith('ASSERTS_') || edge.label === 'EVIDENCED_BY';
  const edges = (graph.edges ?? []).filter((edge) => nodeIds.has(edge.source)
    && nodeIds.has(edge.target) && !isScaffoldEdge(edge));
  for (const assertion of graph.semantic_edges ?? []) {
    if (!assertion?.id || !nodeIds.has(assertion.source_id) || !nodeIds.has(assertion.target_id)
      || typeof assertion.predicate !== 'string' || !assertion.predicate) continue;
    edges.push({
      source: assertion.source_id,
      target: assertion.target_id,
      label: assertion.predicate,
      assertionId: assertion.id,
      status: assertion.status,
      confidence: assertion.confidence,
      evidenceIds: Array.isArray(assertion.evidence_ids) ? assertion.evidence_ids : [],
      basedOnBriefId: assertion.based_on_brief_id,
      basedOnBriefSectionIndex: assertion.based_on_brief_section_index,
    });
  }
  return { nodes, edges };
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
