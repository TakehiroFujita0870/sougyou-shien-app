import { useState } from 'react';

const SOURCE_OPTIONS = [
  { id: 'web', label: 'Web', detail: '公開情報' },
  { id: 'patent', label: 'JPO', detail: '特許公開' },
  { id: 'document', label: 'ファイル', detail: '登録資料' },
  { id: 'decision', label: '過去判断', detail: '判断記憶' },
];

const EVIDENCE = {
  web: { source_type: 'web', locator: 'https://example.test/maintenance-market', excerpt: '設備保全の記録漏れが復旧時間を長くしている。' },
  patent: { source_type: 'patent', locator: 'JP2023-123456A', excerpt: '設備状態を記録し、保全時期を通知する技術が公開されている。' },
  document: { source_type: 'document', locator: 'document:brief-1#page=3', excerpt: 'ヒアリングでは、紙の引継ぎノートが検索できないと確認された。' },
  decision: { source_type: 'decision', locator: 'decision:dec-42', excerpt: '初期顧客は停止損失を把握する小規模工場を優先する。' },
};

export function createLocalResearchRepository({ sourceStatus = {} } = {}) {
  return {
    run: async (query, selectedSources) => ({
      id: 'local-run-1',
      status: Object.values(sourceStatus).some((status) => status !== 'completed') ? 'partial' : 'completed',
      query,
      selected_sources: selectedSources,
      source_status: Object.fromEntries(selectedSources.map((source) => [source, sourceStatus[source] || 'completed'])),
      evidence: selectedSources.filter((source) => (sourceStatus[source] || 'completed') === 'completed').map((source) => EVIDENCE[source]),
      inference: `「${query}」では、取得できた根拠から現場の記録検索を先に検証する仮説です。`,
    }),
  };
}

function statusLabel(status) {
  if (status === 'completed') return '完了';
  if (status.startsWith('timeout')) return '時間切れ';
  if (status.startsWith('limit')) return '利用上限';
  return '未実行';
}

function locatorLabel(locator) {
  if (locator.startsWith('http')) return 'URL';
  if (locator.startsWith('JP')) return '特許公開番号';
  if (locator.startsWith('document:')) return 'ファイルページ';
  return '意思決定 ID';
}

export function ResearchWorkspace({ repository = createLocalResearchRepository() }) {
  const [query, setQuery] = useState('設備保全の記録を検索可能にする価値');
  const [selectedSources, setSelectedSources] = useState(SOURCE_OPTIONS.map((source) => source.id));
  const [run, setRun] = useState(null);
  const [error, setError] = useState('');
  const [running, setRunning] = useState(false);

  const toggleSource = (source) => setSelectedSources((current) => current.includes(source) ? current.filter((item) => item !== source) : [...current, source]);
  async function execute() {
    if (!query.trim()) return setError('調べたい論点を入力してください。');
    if (!selectedSources.length) return setError('少なくとも1つの調査先を選んでください。');
    setError(''); setRunning(true);
    try { setRun(await repository.run(query.trim(), selectedSources)); } catch { setError('ローカル調査を開始できませんでした。もう一度試してください。'); }
    finally { setRunning(false); }
  }
  async function retryFailedSources() {
    const failedSources = run.selected_sources.filter((source) => run.source_status[source] !== 'completed');
    setRunning(true);
    try {
      const retry = await repository.run(query.trim(), failedSources);
      const source_status = { ...run.source_status, ...retry.source_status };
      const evidence = [...run.evidence, ...retry.evidence.filter((item) => !run.evidence.some((saved) => saved.locator === item.locator))];
      setRun({ ...run, status: Object.values(source_status).every((status) => status === 'completed') ? 'completed' : 'partial', source_status, evidence });
    } catch { setError('失敗したソースを再試行できませんでした。'); }
    finally { setRunning(false); }
  }

  return <section className="w-full max-w-5xl rounded-3xl border border-stone-200 bg-white p-5 shadow-sm sm:p-8" aria-labelledby="research-heading">
    <p className="text-xs font-bold tracking-[0.16em] text-emerald-700">横断調査</p>
    <h2 id="research-heading" className="mt-2 text-2xl font-bold sm:text-3xl">反証のために、根拠を集める</h2>
    <p className="mt-2 text-sm leading-6 text-stone-600">ローカルの fake 結果だけを表示します。外部サービスへ送信しません。</p>
    <label className="mt-6 block text-sm font-bold">調べたい論点<textarea value={query} onChange={(event) => setQuery(event.target.value)} rows={3} className="mt-2 w-full rounded-2xl border border-stone-300 p-3 font-normal outline-none focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100" /></label>
    <fieldset className="mt-5"><legend className="text-sm font-bold">調査先</legend><div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{SOURCE_OPTIONS.map((source) => <label key={source.id} className="flex cursor-pointer items-start gap-3 rounded-2xl border border-stone-200 p-3"><input type="checkbox" checked={selectedSources.includes(source.id)} onChange={() => toggleSource(source.id)} className="mt-1 size-4 accent-emerald-800" /><span><strong className="block text-sm">{source.label}</strong><span className="text-xs text-stone-600">{source.detail}</span></span></label>)}</div></fieldset>
    {error && <p role="alert" className="mt-3 text-sm font-bold text-red-700">{error}</p>}
    <button type="button" onClick={execute} disabled={running} className="mt-6 rounded-full bg-emerald-800 px-5 py-3 font-bold text-white disabled:bg-stone-400">{running ? '調査中…' : 'ローカル調査を実行'}</button>
    {run && <div className="mt-8 border-t border-stone-200 pt-6"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-xl font-bold">調査結果</h3><span className="rounded-full bg-emerald-50 px-3 py-1 text-sm font-bold text-emerald-800">{run.status === 'partial' ? '一部取得' : '取得完了'}</span></div>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2" aria-label="ソース別進行">{run.selected_sources.map((source) => <li key={source} className="rounded-2xl border border-stone-200 p-4"><strong>{SOURCE_OPTIONS.find((item) => item.id === source)?.label}</strong><p className="mt-1 text-sm text-stone-700">{statusLabel(run.source_status[source])}</p>{run.source_status[source] !== 'completed' && <p className="mt-2 text-xs text-red-700">{run.source_status[source]}</p>}</li>)}</ul>
      {run.status === 'partial' && <button type="button" onClick={retryFailedSources} disabled={running} className="mt-4 rounded-full border border-emerald-800 px-4 py-2 text-sm font-bold text-emerald-900 disabled:border-stone-300 disabled:text-stone-400">失敗したソースを再試行</button>}
      <div className="mt-6 grid gap-5 lg:grid-cols-[1.2fr_.8fr]"><div><h4 className="font-bold">確認できた事実</h4><ul className="mt-3 grid gap-3">{run.evidence.map((item) => <li key={item.locator} className="rounded-2xl bg-stone-50 p-4"><p className="text-xs font-bold text-emerald-800">{locatorLabel(item.locator)} · {item.source_type}</p><p className="mt-1 break-all text-sm font-medium">{item.locator}</p><p className="mt-2 text-sm leading-6 text-stone-700">{item.excerpt}</p></li>)}</ul></div><aside className="rounded-2xl border border-amber-200 bg-amber-50 p-4"><p className="text-xs font-bold tracking-wide text-amber-900">AI推論</p><p className="mt-2 text-sm leading-6 text-stone-800">{run.inference}</p><p className="mt-3 text-xs text-stone-600">これは根拠そのものではありません。左の locator を確認してください。</p></aside></div>
    </div>}
  </section>;
}
