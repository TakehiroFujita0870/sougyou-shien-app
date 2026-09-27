import { useEffect, useMemo, useState } from 'react';
import { LocalGraphCanvas as GraphCanvas } from './LocalGraphCanvas';
import './LocalGraphSurface.css';
import { semanticGraphData, regionGraphData } from './localGraphData.js';
export { semanticGraphData } from './localGraphData.js';



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
