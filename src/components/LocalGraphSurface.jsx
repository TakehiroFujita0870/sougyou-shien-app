import { useEffect, useMemo, useRef, useState } from 'react';
import { graphDepthForKind, nextGraphDepth, visibleAtGraphDepth, visibleGraphLink } from './localGraphDepth';
import './LocalGraphSurface.css';
import { semanticGraphData, regionGraphData } from './localGraphData.js';
import { COLORS, relationStatusLabel, initialPosition, shortLabel } from './localGraphPresentation.js';
export { semanticGraphData } from './localGraphData.js';


function GraphCanvas({ client, nodes, edges, depth, onDepthChange, regionHits = [], anchorId = '' }) {
  const container = useRef(null);
  const graphRef = useRef(null);
  const currentDepth = useRef(0);
  const lastWheel = useRef(0);
  const [selected, setSelected] = useState(null);
  const [provenanceRequest, setProvenanceRequest] = useState({ assertionId: '', attempt: 0 });
  const [provenance, setProvenance] = useState(null);
  const [renderError, setRenderError] = useState(false);
  const labelsById = new Map(nodes.map((node) => [node.id, node.label]));
  const semanticEdges = edges.filter((edge) => edge.assertionId);
  const selectedAssertionId = selected?.type === 'semantic-edge' ? selected.assertionId : '';
  currentDepth.current = depth;

  const selectSemanticEdge = (edge) => {
    setSelected({ type: 'semantic-edge', ...edge });
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

  useEffect(() => {
    let active = true;
    let observer;
    let graph;
    let wheelHandler;
    let element;
    const disposeGraph = () => {
      observer?.disconnect();
      observer = undefined;
      if (wheelHandler && element) element.removeEventListener('wheel', wheelHandler, true);
      wheelHandler = undefined;
      let destructorSucceeded = false;
      try {
        if (typeof graph?._destructor === 'function') {
          graph._destructor();
          destructorSucceeded = true;
        }
      } catch (error) {
        console.error('Local graph teardown failed', error);
      }
      if (!destructorSucceeded) {
        try {
          graph?.pauseAnimation?.();
        } catch (error) {
          console.error('Local graph animation cleanup failed', error);
        }
        try {
          graph?.renderer?.()?.dispose?.();
        } catch (error) {
          console.error('Local graph renderer cleanup failed', error);
        }
      }
      graphRef.current = null;
      element?.replaceChildren();
      graph = undefined;
    };
    Promise.all([import('3d-force-graph'), import('three-spritetext')]).then(([{ default: ForceGraph3D }, { default: SpriteText }]) => {
      if (!active || !container.current) return;
      element = container.current;
      const graphNodes = nodes.map((node, index) => {
        const nodeDepth = Number.isInteger(node.graphDepth) ? node.graphDepth : graphDepthForKind(node.kind);
        return { ...node, depth: nodeDepth, fz: -170 * nodeDepth, ...initialPosition(node.id, index) };
      });
      const byId = new Map(graphNodes.map((node) => [node.id, node]));
      const graphLinks = edges.map((edge) => ({ ...edge }));
      const endpoint = (value) => typeof value === 'object' ? value : byId.get(value);
      graph = new ForceGraph3D(element, { controlType: 'orbit' });
      graphRef.current = graph;
      graph
        .width(element.clientWidth)
        .height(element.clientHeight)
        .backgroundColor('#142134')
        .showNavInfo(false)
        .numDimensions(3)
        .graphData({ nodes: graphNodes, links: graphLinks })
        .nodeId('id')
        .nodeLabel((node) => node.label)
        .nodeColor((node) => COLORS[node.kind] ?? '#a8c0e4')
        .nodeVal((node) => node.kind === 'idea' ? 7 : 4)
        .nodeRelSize(4)
        .nodeOpacity(.94)
        .nodeThreeObject((node) => {
          const label = new SpriteText(shortLabel(node.label));
          label.color = '#dce8fa';
          label.textHeight = 7;
          label.position.y = 16;
          return label;
        })
        .nodeThreeObjectExtend(true)
        .nodeVisibility((node) => anchorId
          ? node.id === anchorId || node.depth <= currentDepth.current
          : visibleAtGraphDepth(node.depth, currentDepth.current))
        .linkLabel((link) => link.label)
        .linkColor(() => '#9bb7e5')
        .linkOpacity(.65)
        .linkWidth(1.2)
        .linkDirectionalArrowLength(3)
        .linkVisibility((link) => {
          const source = endpoint(link.source);
          const target = endpoint(link.target);
          return anchorId
            ? Boolean(source && target && (source.id === anchorId || source.depth <= currentDepth.current)
              && (target.id === anchorId || target.depth <= currentDepth.current))
            : visibleGraphLink(source, target, currentDepth.current);
        })
        .enableNodeDrag(true)
        .d3VelocityDecay(.35)
        .warmupTicks(45)
        .cooldownTicks(180)
        .onNodeClick((node) => { setProvenance(null); setProvenanceRequest((previous) => ({ assertionId: '', attempt: previous.attempt + 1 })); setSelected({ type: 'node', id: node.id, kind: node.kind, label: node.label }); })
        .onLinkClick((link) => { if (link.assertionId) selectSemanticEdge(link); else { setSelected(null); setProvenance(null); setProvenanceRequest((previous) => ({ assertionId: '', attempt: previous.attempt + 1 })); } })
        .onBackgroundClick(() => { setSelected(null); setProvenance(null); setProvenanceRequest((previous) => ({ assertionId: '', attempt: previous.attempt + 1 })); });
      graph.d3Force('charge').strength(-35);
      graph.d3Force('link').distance(95);
      graph.cameraPosition({ x: 0, y: 0, z: 430 }, { x: 0, y: 0, z: 0 });
      wheelHandler = (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (Math.abs(event.deltaY) < 2 || Date.now() - lastWheel.current < 260) return;
        lastWheel.current = Date.now();
        onDepthChange((value) => nextGraphDepth(value, event.deltaY));
      };
      element.addEventListener('wheel', wheelHandler, { capture: true, passive: false });
      observer = new ResizeObserver(() => {
        if (!active || !graph) return;
        try {
          graph.width(element.clientWidth).height(element.clientHeight);
        } catch (error) {
          console.error('Local graph resize failed', error);
          setRenderError(true);
          disposeGraph();
        }
      });
      observer.observe(element);
    }).catch((error) => {
      if (!active) return;
      console.error('Local graph rendering failed', error);
      disposeGraph();
      setRenderError(true);
    });
    return () => {
      active = false;
      disposeGraph();
    };
  }, [nodes, edges, onDepthChange]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    graph.nodeVisibility((node) => anchorId
      ? node.id === anchorId || node.depth <= depth
      : visibleAtGraphDepth(node.depth, depth));
    graph.linkVisibility((link) => {
      const source = typeof link.source === 'object' ? link.source : nodes.find((node) => node.id === link.source);
      const target = typeof link.target === 'object' ? link.target : nodes.find((node) => node.id === link.target);
      if (!source || !target) return false;
      if (anchorId) return (source.id === anchorId || (source.depth ?? 0) <= depth)
        && (target.id === anchorId || (target.depth ?? 0) <= depth);
      return visibleGraphLink(
        { depth: source.depth ?? graphDepthForKind(source.kind) },
        { depth: target.depth ?? graphDepthForKind(target.kind) }, depth,
      );
    });
    graph.cameraPosition({ x: 0, y: 0, z: 430 - depth * 170 }, { x: 0, y: 0, z: -depth * 170 }, 520);
  }, [depth, nodes, anchorId]);

  return <div className="local-graph__frame">
    <div ref={container} className="local-graph__canvas" role="img" aria-label={`立体の知識グラフ。${nodes.length}個の点と${edges.length}本のつながり。スクロールで奥の詳細へ進む`} />
    <p className="local-graph__depth" role="status">深度 {depth + 1} / 4 · スクロールで抽象から具体へ</p>
    {renderError && <p role="alert">立体グラフを描画できませんでした。このPCの描画機能を確認してください。</p>}
    {selected?.type === 'node' && <aside className="local-graph__selected"><span>{selected.kind.replaceAll('_', ' ')}</span><strong>{selected.label}</strong></aside>}
    {selected?.type === 'semantic-edge' && <aside className="local-graph__selected" aria-label="意味関係と根拠">
      <span>{relationStatusLabel(selected.status)}{typeof selected.confidence === 'number' ? ` · 確信度 ${Math.round(selected.confidence * 100)}%` : ''}</span>
      <strong>{selected.label}</strong>
      {selected.evidenceIds.length > 0 && <small>根拠ID: {selected.evidenceIds.join('、')}</small>}
      {typeof selected.basedOnBriefId === 'string' && Number.isInteger(selected.basedOnBriefSectionIndex)
        && selected.basedOnBriefSectionIndex >= 0 && selected.basedOnBriefSectionIndex <= 7
        && <small>概要: {selected.basedOnBriefId} · 観点 {selected.basedOnBriefSectionIndex}</small>}
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
          <small>概要 {provenance.section.brief_id} · 第{provenance.section.revision}版 · 観点 {provenance.section.section_index}: {provenance.section.title}</small>
          <p>{provenance.section.content}</p>
        </> : <small>この関係は概要の章に結び付いていません。</small>}
        {provenance.evidence.length > 0 ? provenance.evidence.map((evidence) => <small key={evidence.id}>
          根拠 {evidence.id} · {evidence.polarity} · 確信度 {Math.round(evidence.confidence * 100)}% · {evidence.status}
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
        <small>根拠ID: {hit.evidence_ids.join('、')}</small>
      </article>)}
    </aside>}
  </div>;
}

export function LocalGraphSurface({ client, onOpenServices }) {
  const [graph, setGraph] = useState({ status: 'loading', nodes: [], edges: [], truncated: false });
  const [facetId, setFacetId] = useState('');
  const [depth, setDepth] = useState(0);
  const [region, setRegion] = useState({ status: 'empty', hits: [] });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve().then(() => client.getGraph({ signal: controller.signal }))
      .then((result) => { if (!controller.signal.aborted) setGraph(result); })
      .catch(() => { if (!controller.signal.aborted) setGraph({ status: 'failed', nodes: [], edges: [], truncated: false }); });
    return () => controller.abort();
  }, [client, attempt]);
  const facets = graph.nodes.filter((node) => node.kind === 'facet');
  useEffect(() => {
    if (facets.length === 0) {
      setFacetId('');
      setRegion({ status: 'empty', hits: [] });
      return;
    }
    if (facetId && !facets.some((facet) => facet.id === facetId)) {
      setFacetId('');
      setDepth(0);
    }
  }, [graph.nodes, facetId]);
  useEffect(() => {
    if (!facetId || graph.status !== 'ready') return undefined;
    const controller = new AbortController();
    setRegion({ status: 'loading', hits: [] });
    Promise.resolve().then(() => client.getFacetRegion(facetId, depth, { signal: controller.signal }))
      .then((result) => { if (!controller.signal.aborted) setRegion(result); })
      .catch(() => { if (!controller.signal.aborted) setRegion({ status: 'failed', hits: [] }); });
    return () => controller.abort();
  }, [client, facetId, depth, graph.status]);
  const selectedFacet = facets.find((facet) => facet.id === facetId);
  const matchingRegion = region.facet_id === facetId && region.depth === depth;
  const regionGraph = useMemo(() => facetId && region.status !== 'failed' && region.status !== 'stopped'
    ? regionGraphData(facetId, matchingRegion ? region.hits : [], graph.nodes)
    : null, [facetId, graph.nodes, matchingRegion, region.hits, region.status]);
  const semanticGraph = useMemo(() => semanticGraphData(graph), [graph]);
  const visibleNodes = regionGraph?.nodes ?? semanticGraph.nodes;
  const visibleEdges = regionGraph?.edges ?? semanticGraph.edges;
  return <main className="local-graph" aria-labelledby="local-graph-heading">
    <h1 id="local-graph-heading" className="sr-only">グラフ</h1>
    {graph.status === 'loading' && <p role="status">グラフを読み込んでいます。</p>}
    {graph.status === 'failed' && <p role="alert">グラフを読み込めませんでした。<button type="button" onClick={() => setAttempt((value) => value + 1)}>再試行</button></p>}
    {graph.status === 'stopped' && <p role="status">Dots.は停止中です。<button type="button" onClick={onOpenServices}>サービス管理を開く</button></p>}
    {graph.status === 'empty' && <p role="status">まだ表示できる記録はありません。</p>}
    {graph.status === 'ready' && <>
      {facets.length > 0 && <div className="local-graph__region-controls">
        <label>分類から探す <select value={facetId} onChange={(event) => { setFacetId(event.target.value); setDepth(0); }}>
          <option value="">全体の意味グラフ</option>
          {facets.map((facet) => <option key={facet.id} value={facet.id}>{facet.label}</option>)}
        </select></label>
        <span>{selectedFacet ? `${selectedFacet.label}から具体記録へ` : ''}</span>
      </div>}
      {facetId && region.status === 'loading' && <p className="local-graph__region-status" role="status">分類内の記録を読み込んでいます…</p>}
      {facetId && region.status === 'empty' && matchingRegion && <p className="local-graph__region-status" role="status">この深度に根拠付きの記録はありません。提案は結果に含めません。</p>}
      {facetId && region.status === 'stopped' && matchingRegion && <p className="local-graph__region-status" role="status">データベースが停止しています。</p>}
      {facetId && region.status === 'failed' && <p className="local-graph__region-status" role="alert">分類内の記録を読めませんでした。従来のグラフを表示します。</p>}
      <GraphCanvas key={facetId || 'all'} client={client} nodes={visibleNodes} edges={visibleEdges} depth={depth} onDepthChange={setDepth} anchorId={regionGraph ? facetId : ''} regionHits={facetId && region.status === 'ready' && matchingRegion ? region.hits : []} />
      {graph.truncated && <p className="local-graph__limit">表示件数の上限に達しました。全体ではなく一部を表示しています。</p>}
    </>}
  </main>;
}
