import { useMemo, useState } from 'react';
import { nodeKindLabel } from './localGraphPresentation.js';
import { searchGraphNodes } from './localGraphSearch.js';

export function LocalGraphNodeSearch({ nodes, onSelect }) {
  const [query, setQuery] = useState('');
  const { results, total } = useMemo(() => searchGraphNodes(nodes, query), [nodes, query]);
  const resultLabel = total > 12
    ? `${total}件見つかりました。先頭12件を表示しています。`
    : total > 0 ? `${total}件見つかりました。` : '一致する記録はありません。';

  return <aside className="local-graph__node-search" aria-label="グラフ内の記録">
    <label>記録を探す<input type="search" aria-label="グラフ内の記録を検索" value={query}
      onChange={(event) => setQuery(event.target.value)} placeholder="名前を入力" /></label>
    {query.trim() && <>
      <p role="status">{resultLabel}</p>
      <div className="local-graph__node-results">{results.map((node) => <button key={node.id} type="button"
        className="local-graph__node-result" onClick={() => onSelect(node)}>
        <span>{nodeKindLabel(node.kind)}</span>{node.label}
      </button>)}</div>
    </>}
  </aside>;
}
