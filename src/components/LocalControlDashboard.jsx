import { useEffect, useRef, useState } from 'react';
import { LocalDeletedRecords } from './LocalDeletedRecords';
import './LocalControlDashboard.css';

const EMPTY_COUNTS = { Idea: 0, Person: 0, Asset: 0, ReportVersion: 0 };
const COUNT_LABELS = { Idea: 'アイデアの記録', Person: '人の記録', Asset: '資産の記録', ReportVersion: '調査レポートの版' };
const KIND_LABELS = { Idea: 'アイデア', Person: '人', Asset: '資産', ReportVersion: '調査レポート' };
const SERVICE_LABELS = { database: '保存先', api: '画面の読み取り', tunnel: 'ChatGPT接続' };
const SERVICE_STATUS_LABELS = { running: '稼働中', stopped: '停止中', starting: '準備中', unavailable: '確認できません' };
const GRAPH_PROCESSING_LABELS = {
  pending: '整理待ち',
  leased: '整理中',
  succeeded: '整理完了',
  failed: '失敗',
  superseded: '新しい版に置換済み',
};
const STATUS_COPY = {
  loading: { label: '状態を確認中', detail: 'Nebulaの稼働状態を読み込んでいます。' },
  running: { label: '稼働中', detail: '保存先と接続が利用できます。' },
  stopped: { label: '停止中', detail: '停止中はChatGPTから保存内容を検索できません。' },
  degraded: { label: '一部利用できません', detail: '下の状態を確認してください。起動操作で再確認できます。' },
  error: { label: '状態を確認できません', detail: 'ローカル操作盤に接続できませんでした。再読み込みしてください。' },
};

function getSafeTitle(record) {
  if (!record || typeof record !== 'object') return '';
  if (record.kind === 'Idea' && typeof record.title === 'string') return record.title;
  if (record.kind === 'Person' && typeof record.name === 'string') return record.name;
  if (record.kind === 'Asset' && typeof record.name === 'string') return record.name;
  if (record.kind === 'ReportVersion') return '調査レポート';
  return '';
}

function getGraphProcessingCounts(processing) {
  if (processing?.status !== 'ready' || !processing.counts || typeof processing.counts !== 'object') return null;
  const entries = Object.entries(GRAPH_PROCESSING_LABELS).map(([state, label]) => [state, label, processing.counts[state]]);
  if (entries.some(([, , count]) => !Number.isSafeInteger(count) || count < 0)) return null;
  return entries;
}

/**
 * Local lifecycle and safe summary dashboard. The caller owns the client and
 * Graph navigation; this component never makes implicit network requests.
 * Client contract: getSnapshot({signal}), start(), stop().
 */
export function LocalControlDashboard({ client, onOpenGraph, serviceOnly = false }) {
  const [state, setState] = useState('loading');
  const [snapshot, setSnapshot] = useState(null);
  const [pending, setPending] = useState(false);
  const [confirmation, setConfirmation] = useState(null);
  const [notice, setNotice] = useState('');
  const confirmButtonRef = useRef(null);
  const actionButtonRef = useRef(null);
  const confirmationWasOpen = useRef(false);

  async function refresh(signal) {
    const reader = serviceOnly && typeof client?.getServiceSnapshot === 'function' ? client.getServiceSnapshot : client?.getSnapshot;
    if (typeof reader !== 'function') {
      setState('error');
      setSnapshot(null);
      return;
    }
    setState('loading');
    try {
      const result = await reader({ signal });
      if (signal?.aborted) return;
      if (!result || !['running', 'stopped', 'degraded'].includes(result.state) || !result.counts || !Array.isArray(result.latest)) throw new Error('Invalid snapshot');
      if (Object.keys(EMPTY_COUNTS).some((kind) => !Number.isSafeInteger(result.counts[kind]) || result.counts[kind] < 0)) throw new Error('Invalid counts');
      setSnapshot(result);
      setState(result.state);
    } catch {
      if (signal?.aborted) return;
      setSnapshot(null);
      setState('error');
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [client, serviceOnly]);

  useEffect(() => {
    if (!confirmation) {
      if (confirmationWasOpen.current) actionButtonRef.current?.focus();
      confirmationWasOpen.current = false;
      return undefined;
    }
    confirmationWasOpen.current = true;
    confirmButtonRef.current?.focus();
    const closeOnEscape = (event) => {
      if (event.key === 'Escape' && !pending) setConfirmation(null);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [confirmation, pending]);

  async function confirmAction() {
    const action = confirmation;
    if (!action || pending) return;
    setPending(true);
    setNotice('');
    try {
      if (typeof client?.[action] !== 'function') throw new Error('Action unavailable');
      await client[action]();
      setConfirmation(null);
      setNotice(action === 'stop' ? 'Nebulaを停止しました。' : 'Nebulaを起動しました。');
      await refresh();
    } catch {
      setNotice('操作を完了できませんでした。状態を確認して、もう一度お試しください。');
    } finally {
      setPending(false);
    }
  }

  const status = STATUS_COPY[state];
  const records = Array.isArray(snapshot?.latest) ? snapshot.latest : [];
  const latest = records.map((record) => ({ record, title: getSafeTitle(record) })).filter(({ title }) => title).slice(0, 5);
  const graphProcessingCounts = getGraphProcessingCounts(snapshot?.processing);
  const action = state === 'running' ? 'stop' : 'start';

  return (
    <main className="mx-auto grid w-full max-w-5xl gap-6 px-4 pb-6 pt-0 sm:px-6" aria-labelledby="local-control-heading">
      <header className="grid gap-2">
        <h1 id="local-control-heading" className="sr-only">サービス管理</h1>
        <section className="grid gap-3 py-3 sm:grid-cols-[1fr_auto] sm:items-center" aria-labelledby="runtime-heading">
          <div>
            <h2 id="runtime-heading" className="text-base font-semibold">稼働状態</h2>
            <p className="mt-1" role={state === 'error' ? 'alert' : undefined} aria-live="polite" data-dashboard-state={state}>
              <span className="font-medium">{status.label}</span>
              <span className="block text-sm text-[var(--color-text-muted)]">{status.detail}</span>
            </p>
          </div>
          <button ref={actionButtonRef} type="button" disabled={pending || state === 'loading' || state === 'error'} onClick={() => setConfirmation(action)} className={`min-h-11 rounded-xl border border-[var(--color-border-subtle)] px-4 py-2 font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)] disabled:cursor-not-allowed disabled:opacity-50 ${action === 'stop' ? 'local-control__stop-button' : ''}`}>
            {pending ? '処理中…' : action === 'stop' ? 'Nebulaを停止' : 'Nebulaを起動'}
          </button>
        </section>
        {snapshot?.services && <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3" aria-label="サービスごとの状態">
          {Object.entries(SERVICE_LABELS).map(([name, label]) => <div key={name} data-service={name} className="flex items-center justify-between gap-3 border-b border-[var(--color-border-subtle)] px-2 py-2 text-sm">
            <dt>{label}</dt><dd className="flex items-center gap-2 font-medium">{['running', 'stopped'].includes(snapshot.services[name]) && <span aria-hidden="true" className={`local-control__lamp local-control__lamp--${snapshot.services[name]}`} />}{SERVICE_STATUS_LABELS[snapshot.services[name]] ?? '確認できません'}</dd>
          </div>)}
        </dl>}
      </header>

      {serviceOnly && <section className="border-t border-[var(--color-border-subtle)] pt-4" aria-label="削除済みの記録を管理">
        <LocalDeletedRecords client={client} />
      </section>}

      {serviceOnly && <section className="grid gap-3 border-t border-[var(--color-border-subtle)] pt-4" aria-labelledby="graph-processing-heading">
        <h2 id="graph-processing-heading" className="text-base font-semibold">グラフ整理</h2>
        {graphProcessingCounts ? <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5" aria-label="整理状況別の件数">
          {graphProcessingCounts.map(([stateName, label, count]) => <div key={stateName} className="rounded-xl border border-[var(--color-border-subtle)] px-3 py-3">
            <dt className="text-sm text-[var(--color-text-muted)]">{label}</dt>
            <dd className="mt-1 text-xl font-semibold tabular-nums">{count}</dd>
          </div>)}
        </dl> : <div className="flex flex-wrap items-center justify-between gap-3">
          <p role="status" className="text-sm text-[var(--color-text-muted)]">保存先が止まっているか、整理状況を確認できません。</p>
          <button type="button" disabled={state === 'loading' || pending} onClick={() => { void refresh(); }} className="min-h-10 rounded-xl border border-[var(--color-border-subtle)] px-3 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)] disabled:opacity-50">状態を再確認</button>
        </div>}
      </section>}

      {(state === 'stopped' || state === 'degraded') && <p className="rounded-xl border border-dashed border-[var(--color-border-subtle)] p-4 text-sm text-[var(--color-text-muted)]">保存先と接続が稼働すると、件数と最近の記録を表示できます。</p>}

      {!serviceOnly && state === 'running' && <>
        <section aria-labelledby="counts-heading" className="grid gap-3">
          <h2 id="counts-heading" className="text-lg font-semibold">保存内容</h2>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {Object.entries(EMPTY_COUNTS).map(([kind, fallback]) => (
              <div key={kind} className="rounded-2xl border border-[var(--color-border-subtle)] bg-[var(--color-surface)] p-4">
                <dt className="text-sm text-[var(--color-text-muted)]">{COUNT_LABELS[kind]}</dt>
                <dd className="mt-2 text-2xl font-semibold tabular-nums">{Number.isSafeInteger(snapshot?.counts?.[kind]) && snapshot.counts[kind] >= 0 ? snapshot.counts[kind] : fallback}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section aria-labelledby="latest-heading" className="grid gap-3">
          <h2 id="latest-heading" className="text-lg font-semibold">最近更新された記録</h2>
          {latest.length ? <ul className="grid gap-2" aria-label="最近更新された安全な題名">
            {latest.map(({ record, title }, index) => <li key={record.id ?? `${record.kind}-${index}`} className="flex min-h-12 items-center justify-between gap-3 rounded-xl border border-[var(--color-border-subtle)] px-4 py-3">
              <span className="min-w-0 break-words font-medium">{title}</span>
              <span className="shrink-0 text-xs text-[var(--color-text-muted)]">{KIND_LABELS[record.kind]}</span>
            </li>)}
          </ul> : <p className="rounded-xl border border-dashed border-[var(--color-border-subtle)] p-4 text-sm text-[var(--color-text-muted)]">表示できる記録はありません。</p>}
        </section>
      </>}

      {!serviceOnly && <section className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-[var(--color-muted)] p-4" aria-label="Graphへの移動">
        <div><h2 className="font-semibold">保存した情報を詳しく見る</h2><p className="text-sm text-[var(--color-text-muted)]">Graphで記録とつながりを確認できます。</p></div>
        <button type="button" onClick={onOpenGraph} className="min-h-11 rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-4 py-2 font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)]">Graphを開く</button>
      </section>}

      <p role="status" aria-live="polite" className="min-h-5 text-sm">{notice}</p>

      {confirmation && <div className="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget && !pending) setConfirmation(null); }}>
        <section role="alertdialog" aria-modal="true" aria-labelledby="control-confirm-heading" aria-describedby="control-confirm-description" className="grid w-full max-w-md gap-4 rounded-2xl border border-[var(--color-border-subtle)] bg-[var(--color-surface)] p-5 shadow-2xl">
          <h2 id="control-confirm-heading" className="text-lg font-semibold">{confirmation === 'stop' ? 'Nebulaを停止しますか？' : 'Nebulaを起動しますか？'}</h2>
          <p id="control-confirm-description" className="text-sm leading-6 text-[var(--color-text-muted)]">{confirmation === 'stop' ? 'ChatGPT接続、通常API、保存先の順に停止します。操作盤と保存データは残ります。停止中はChatGPTから検索できません。' : '既存の保存先を起動し、準備できた後に通常APIと承認済み接続を起動します。保存データは削除されません。'}</p>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" disabled={pending} onClick={() => setConfirmation(null)} className="min-h-11 rounded-xl border border-[var(--color-border-subtle)] px-4 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)] disabled:opacity-50">キャンセル</button>
            <button ref={confirmButtonRef} type="button" disabled={pending} onClick={() => { void confirmAction(); }} className={`local-control-confirm-button min-h-11 rounded-xl bg-[var(--color-primary)] px-4 py-2 font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)] disabled:opacity-50 ${confirmation === 'stop' ? 'local-control__stop-button' : ''}`}>{pending ? '処理中…' : confirmation === 'stop' ? '停止する' : '起動する'}</button>
          </div>
        </section>
      </div>}
    </main>
  );
}

export default LocalControlDashboard;
