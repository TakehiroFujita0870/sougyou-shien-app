import { useEffect, useMemo, useState } from 'react';
import { LocalGraphCanvas as GraphCanvas } from './LocalGraphCanvas';
import './LocalGraphSurface.css';
import { semanticGraphData } from './localGraphData.js';
export { semanticGraphData } from './localGraphData.js';



export function LocalGraphSurface({ client, onOpenServices }) {
  const [graph, setGraph] = useState({ status: 'loading', nodes: [], edges: [], truncated: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve().then(() => client.getGraph({ signal: controller.signal }))
      .then((result) => { if (!controller.signal.aborted) setGraph(result); })
      .catch(() => { if (!controller.signal.aborted) setGraph({ status: 'failed', nodes: [], edges: [], truncated: false }); });
    return () => controller.abort();
  }, [client, attempt]);
  const semanticGraph = useMemo(() => semanticGraphData(graph), [graph]);
  return <main className="local-graph" aria-labelledby="local-graph-heading">
    <h1 id="local-graph-heading" className="sr-only">グラフ</h1>
    {graph.status === 'loading' && <p role="status">グラフを読み込んでいます。</p>}
    {graph.status === 'failed' && <p role="alert">グラフを読み込めませんでした。<button type="button" onClick={() => setAttempt((value) => value + 1)}>再試行</button></p>}
    {graph.status === 'stopped' && <p role="status">Dots.は停止中です。<button type="button" onClick={onOpenServices}>サービス管理を開く</button></p>}
    {graph.status === 'empty' && <p role="status">まだ表示できる記録はありません。</p>}
    {graph.status === 'ready' && <>
      <GraphCanvas client={client} nodes={semanticGraph.nodes} edges={semanticGraph.edges} />
      {graph.truncated && <p className="local-graph__limit">表示件数の上限に達しました。全体ではなく一部を表示しています。</p>}
    </>}
  </main>;
}
