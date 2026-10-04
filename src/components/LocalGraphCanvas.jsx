import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { COLORS, nodeKindLabel, relationStatusLabel, shortLabel, starRadius, visibleGraphLabelIds } from './localGraphPresentation.js';
import { LocalGraphNodeSearch } from './LocalGraphNodeSearch.jsx';
import { safePublicCitationUrl } from '../runtime/publicCitationUrl.js';

const INITIAL_ZOOM = 0.9;
const SEARCH_FOCUS_ZOOM = 1.2;
const EMPTY_GRAPH = { nodes: [], links: [] };

function endpointId(endpoint) {
  return typeof endpoint === 'object' ? endpoint?.id : endpoint;
}

function relationshipText(edge, labelsById) {
  const source = labelsById.get(endpointId(edge.source)) ?? '名称を確認できない記録';
  const target = labelsById.get(endpointId(edge.target)) ?? '名称を確認できない記録';
  return `${source} → ${edge.label} → ${target}`;
}

function evidencePolarityLabel(polarity) {
  if (polarity === 'supports') return '支持';
  if (polarity === 'contradicts') return '反証';
  if (polarity === 'neutral') return '補足';
  return '根拠';
}

function evidenceStatusLabel(status) {
  return status === 'active' ? '有効' : '状態未設定';
}

function drawStar(context, x, y, radius) {
  context.beginPath();
  for (let point = 0; point < 8; point += 1) {
    const angle = -Math.PI / 2 + point * Math.PI / 4;
    const pointRadius = point % 2 === 0 ? radius : radius * 0.3;
    const pointX = x + Math.cos(angle) * pointRadius;
    const pointY = y + Math.sin(angle) * pointRadius;
    if (point === 0) context.moveTo(pointX, pointY);
    else context.lineTo(pointX, pointY);
  }
  context.closePath();
  context.fill();
}

export function LocalGraphCanvas({ client, nodes, edges, regionHits = [] }) {
  const container = useRef(null);
  const graphRef = useRef(null);
  const [graphReady, setGraphReady] = useState(false);
  const attachGraph = useCallback((graph) => {
    graphRef.current = graph;
    if (!graph) return;
    // Configure before the library's deferred warmup, not after visible motion.
    graph.d3Force('charge')?.strength(-18).distanceMax(160);
    graph.d3Force('link')?.distance(30);
    // A fixed initial scale also disables the library's node-count auto-zoom.
    graph.zoom(INITIAL_ZOOM, 0);
    setGraphReady(true);
  }, []);
  const [selected, setSelected] = useState(null);
  const [hoveredId, setHoveredId] = useState('');
  const [Graph2D, setGraph2D] = useState(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const visibleLabelIds = useRef(new Set());
  const [provenanceRequest, setProvenanceRequest] = useState({ assertionId: '', attempt: 0 });
  const [provenance, setProvenance] = useState(null);
  const [renderError, setRenderError] = useState(false);
  const graphData = useMemo(() => ({
    nodes: nodes.map((node) => ({ ...node })),
    links: edges.map((edge) => ({ ...edge })),
  }), [nodes, edges]);
  const labelsById = new Map(nodes.map((node) => [node.id, node.label]));
  const semanticEdges = edges.filter((edge) => edge.assertionId);
  const selectedAssertionId = selected?.type === 'semantic-edge' ? selected.assertionId : '';
  const selectedNodeIds = new Set();
  if (selected?.type === 'node') selectedNodeIds.add(selected.id);
  if (selected?.type === 'semantic-edge') {
    selectedNodeIds.add(endpointId(selected.source));
    selectedNodeIds.add(endpointId(selected.target));
  }
  if (selected?.type === 'node') {
    for (const edge of edges) {
      if (endpointId(edge.source) === selected.id) selectedNodeIds.add(endpointId(edge.target));
      if (endpointId(edge.target) === selected.id) selectedNodeIds.add(endpointId(edge.source));
    }
  }
  const selectedNodeRelations = selected?.type === 'node'
    ? semanticEdges.filter((edge) => endpointId(edge.source) === selected.id || endpointId(edge.target) === selected.id)
    : [];
  useEffect(() => {
    let active = true;
    import('react-force-graph-2d').then(({ default: ForceGraph2D }) => {
      if (active) setGraph2D(() => ForceGraph2D);
    }).catch((error) => {
      if (!active) return;
      console.error('Local graph rendering failed', error);
      setRenderError(true);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const element = container.current;
    if (!element) return undefined;
    const updateSize = () => {
      const bounds = element.getBoundingClientRect();
      const width = element.clientWidth || bounds.width || 0;
      const height = element.clientHeight || bounds.height || 0;
      setDimensions((previous) => previous.width === width && previous.height === height
        ? previous : { width, height });
    };
    updateSize();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const selectSemanticEdge = (edge) => {
    setSelected({ ...edge, source: endpointId(edge.source), target: endpointId(edge.target), type: 'semantic-edge' });
    setProvenance(null);
    setProvenanceRequest((previous) => ({ assertionId: '', attempt: previous.attempt + 1 }));
  };

  const selectNode = (node) => {
    const url = node.kind === 'source' ? safePublicCitationUrl(node.url) : null;
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
      return;
    }
    setProvenance(null);
    setProvenanceRequest((previous) => ({ assertionId: '', attempt: previous.attempt + 1 }));
    setSelected({ type: 'node', id: node.id, kind: node.kind, label: node.label });
  };

  const focusNode = (node) => {
    const graphNode = graphData.nodes.find((candidate) => candidate.id === node.id);
    const graph = graphRef.current;
    if (graph && Number.isFinite(graphNode?.x) && Number.isFinite(graphNode?.y)) {
      graph.centerAt(graphNode.x, graphNode.y, 450);
      const zoom = graph.zoom();
      if (Number.isFinite(zoom) && zoom < SEARCH_FOCUS_ZOOM) graph.zoom(SEARCH_FOCUS_ZOOM, 450);
    }
    selectNode(node);
  };

  const clearSelection = () => {
    setSelected(null);
    setProvenance(null);
    setProvenanceRequest((previous) => ({ assertionId: '', attempt: previous.attempt + 1 }));
  };

  useEffect(() => {
    if (!selectedAssertionId || provenanceRequest.assertionId !== selectedAssertionId) return undefined;
    const controller = new AbortController();
    let active = true;
    setProvenance({ status: 'loading', assertion_id: selectedAssertionId });
    Promise.resolve().then(() => {
      if (typeof client?.getSemanticEdgeProvenance !== 'function') throw new Error('Provenance is unavailable');
      return client.getSemanticEdgeProvenance(selectedAssertionId, { signal: controller.signal });
    }).then((result) => {
      if (!active) return;
      if (result?.status === 'ready' && result.assertion_id === selectedAssertionId) {
        setProvenance(result);
      } else if (result?.status === 'stopped') {
        setProvenance({ status: 'stopped', assertion_id: selectedAssertionId });
      } else {
        setProvenance({ status: 'failed', assertion_id: selectedAssertionId });
      }
    }).catch((error) => {
      if (active && error?.name !== 'AbortError') setProvenance({ status: 'failed', assertion_id: selectedAssertionId });
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [client, selectedAssertionId, provenanceRequest.assertionId, provenanceRequest.attempt]);

  const prepareFrame = (context, globalScale) => {
    const scale = Math.max(globalScale, 0.1);
    context.save();
    context.font = `500 ${12 / scale}px system-ui, sans-serif`;
    visibleLabelIds.current = visibleGraphLabelIds(
      graphData.nodes, scale, selectedNodeIds, hoveredId,
      (label) => context.measureText(label).width,
    );
    context.restore();
  };

  const renderNode = (node, context, globalScale) => {
    const radius = starRadius(node);
    const selectedOrRelated = selectedNodeIds.has(node.id);
    const isSelected = selected?.type === 'node' && selected.id === node.id;
    const scale = Math.max(globalScale, 0.1);
    context.save();
    context.globalAlpha = selected && !selectedOrRelated ? 0.2 : 0.68;
    context.fillStyle = COLORS[node.kind] ?? '#c4d4ed';
    context.shadowColor = context.fillStyle;
    context.shadowBlur = isSelected ? radius * 2.2 : Math.max(4, radius * 1.15);
    drawStar(context, node.x, node.y, radius);
    context.shadowBlur = 0;
    context.globalAlpha = selected && !selectedOrRelated ? 0.62 : 0.98;
    context.fillStyle = '#fff';
    context.beginPath();
    context.arc(node.x, node.y, Math.max(1.5, radius * 0.31), 0, Math.PI * 2);
    context.fill();
    if (isSelected) {
      context.strokeStyle = '#f7fbff';
      context.lineWidth = 1.5 / scale;
      context.beginPath();
      context.arc(node.x, node.y, radius + 2.5 / scale, 0, Math.PI * 2);
      context.stroke();
    }
    if (visibleLabelIds.current.has(node.id)) {
      context.globalAlpha = 1;
      context.font = `500 ${12 / scale}px system-ui, sans-serif`;
      context.textBaseline = 'middle';
      context.fillStyle = '#f4f7ff';
      context.shadowColor = '#02050a';
      context.shadowBlur = 4 / scale;
      context.fillText(shortLabel(node.label), node.x + radius + 5 / scale, node.y);
    }
    context.restore();
  };

  const isHighlightedLink = (link) => {
    if (!selected) return false;
    if (selected.type === 'semantic-edge') return link.assertionId === selected.assertionId;
    return endpointId(link.source) === selected.id || endpointId(link.target) === selected.id;
  };
  const paintPointerArea = (node, color, context) => {
    context.fillStyle = color;
    context.beginPath();
    context.arc(node.x, node.y, starRadius(node) + 4, 0, Math.PI * 2);
    context.fill();
  };
  return <div className="local-graph__frame">
    <div ref={container} className="local-graph__canvas" role="img" aria-label={`平面の知識グラフ。${nodes.length}個の点と${edges.length}本のつながり。ドラッグで移動し、スクロールで拡大縮小できます。`}>
      {Graph2D && <Graph2D
        ref={attachGraph}
        graphData={graphReady ? graphData : EMPTY_GRAPH}
        width={dimensions.width || 800}
        height={dimensions.height || 500}
        backgroundColor="rgba(0,0,0,0)"
        nodeId="id"
        nodeLabel={(node) => node.label}
        nodeColor={(node) => COLORS[node.kind] ?? '#c4d4ed'}
        nodeVal={(node) => starRadius(node) ** 2}
        nodeRelSize={1}
        nodeCanvasObjectMode={() => 'replace'}
        nodeCanvasObject={renderNode}
        nodePointerAreaPaint={paintPointerArea}
        onRenderFramePre={prepareFrame}
        linkLabel={(link) => link.label}
        linkColor={(link) => isHighlightedLink(link) ? 'rgba(222, 236, 255, 0.94)' : selected ? 'rgba(155, 179, 220, 0.025)' : 'rgba(155, 179, 220, 0.22)'}
        linkWidth={(link) => isHighlightedLink(link) ? 2.2 : selected ? 0.45 : 0.7}
        enableNodeDrag
        enableZoomInteraction
        enablePanInteraction
        enablePointerInteraction
        autoPauseRedraw
        d3VelocityDecay={0.42}
        warmupTicks={120}
        cooldownTicks={100}
        onNodeClick={selectNode}
        onNodeHover={(node) => setHoveredId(node?.id ?? '')}
        onLinkClick={(link) => link.assertionId ? selectSemanticEdge(link) : clearSelection()}
        onBackgroundClick={clearSelection}
      />}
    </div>
    <LocalGraphNodeSearch nodes={nodes} onSelect={focusNode} />
    {renderError && <p role="alert">平面グラフを表示できませんでした。画面を再読み込みしてください。</p>}
    {selected?.type === 'node' && <aside className="local-graph__selected" aria-label="選択した記録">
      <span>{nodeKindLabel(selected.kind)}</span><strong>{selected.label}</strong>
      {selectedNodeRelations.length > 0 && <section className="local-graph__selected-relations" aria-label="関連する意味関係">
        <strong>関連する意味関係</strong>
        {selectedNodeRelations.map((edge) => <button key={edge.assertionId} type="button"
          onClick={() => selectSemanticEdge(edge)}>{relationshipText(edge, labelsById)}</button>)}
      </section>}
    </aside>}
    {selected?.type === 'semantic-edge' && <aside className="local-graph__selected" aria-label="意味関係と根拠">
      <span>{relationStatusLabel(selected.status)}{typeof selected.confidence === 'number' ? ` · 確信度 ${Math.round(selected.confidence * 100)}%` : ''}</span>
      <strong>{relationshipText(selected, labelsById)}</strong>
      {selected.evidenceIds.length > 0 && <small>根拠 {selected.evidenceIds.length}件</small>}
      {typeof selected.basedOnBriefId === 'string' && Number.isInteger(selected.basedOnBriefSectionIndex)
        && selected.basedOnBriefSectionIndex >= 0 && selected.basedOnBriefSectionIndex <= 7
        && <small>概要の第{selected.basedOnBriefSectionIndex + 1}観点</small>}
      <button type="button" disabled={provenance?.assertion_id === selected.assertionId && provenance.status === 'loading'}
        onClick={() => setProvenanceRequest((previous) => ({ assertionId: selected.assertionId, attempt: previous.attempt + 1 }))}>
        {provenance?.assertion_id === selected.assertionId && provenance.status === 'loading' ? '根拠を確認中…' : '根拠を確認'}
      </button>
      {provenance?.assertion_id === selected.assertionId && provenance.status === 'loading'
        && <small role="status">根拠を確認中です。</small>}
      {provenance?.assertion_id === selected.assertionId && provenance.status === 'stopped'
        && <small role="status">Dots.は停止中のため根拠を確認できません。</small>}
      {provenance?.assertion_id === selected.assertionId && provenance.status === 'failed'
        && <small role="alert">根拠を確認できませんでした。関係が更新された可能性があります。</small>}
      {provenance?.assertion_id === selected.assertionId && provenance.status === 'ready' && <section aria-label="確認済みの根拠">
        {provenance.section ? <>
          <small>概要 第{provenance.section.revision}版 · 第{provenance.section.section_index + 1}観点: {provenance.section.title}</small>
          <p>{provenance.section.content}</p>
        </> : <small>この関係は概要の章に結び付いていません。</small>}
        {provenance.evidence.length > 0 ? provenance.evidence.map((evidence) => <small key={evidence.id}>
          {evidencePolarityLabel(evidence.polarity)} · 確信度 {Math.round(evidence.confidence * 100)}% · {evidenceStatusLabel(evidence.status)}
        </small>) : <small>共有可能な根拠の詳細はありません。</small>}
      </section>}
    </aside>}
    {semanticEdges.length > 0 && <aside className="local-graph__evidence" aria-label="意味関係">
      <article>{semanticEdges.slice(0, 8).map((edge) => <button key={edge.assertionId} type="button"
        onClick={() => selectSemanticEdge(edge)}>
        {labelsById.get(edge.source)} → {edge.label} → {labelsById.get(edge.target)}
      </button>)}</article>
    </aside>}
    {regionHits.length > 0 && <aside className="local-graph__evidence" aria-label="分類領域の記録と根拠">
      {regionHits.map((hit) => <article key={JSON.stringify([hit.id, hit.matched_facet_id])}>
        <strong>{hit.title}</strong>
        <span>{hit.classification_status === 'confirmed' ? '確定' : '推測'} · {hit.kind === 'idea' ? '案' : '資産'} · 深度 {hit.depth}</span>
        <span>{hit.facet_path.map((item) => item.label).join(' → ')}</span>
        {hit.taxonomy_status_path.length > 0 && <span>親子関係: {hit.taxonomy_status_path.map((status) => status === 'confirmed' ? '確定' : '推測').join(' · ')}</span>}
        <small>根拠 {hit.evidence_ids.length}件</small>
      </article>)}
    </aside>}
  </div>;
}
